"""Voisso HTTP API — 계약서 5절.

    POST /api/call/start                  -> {"session_id"}
    POST /api/call/turn                   -> {"reply_text","reply_dialect","audio_b64","done","slots"}
    POST /api/call/end                    -> {"complaint": <민원카드>}
    GET  /api/complaints                  -> {"complaints": [...]}
    GET  /api/complaints/{id}             -> {"complaint": ...}

정적 파일: /call -> web/call/, /dashboard -> web/dashboard/
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Any

from pydantic import BaseModel, Field

from voisso.agent import agent_status
from voisso.agent.session import MAX_SESSION_TOKENS, MAX_TURNS
from voisso.agent.callback import (
    ROLE_AGENT,
    STATUS_ANSWERED,
    STATUS_PENDING,
    Callback,
    answer_from_facts,
)
from voisso.agent.callback import VALID_ROLES as CALLBACK_ROLES
from voisso.agent.callback import empty_status as callback_empty_status
from voisso.agent.callback import STATUS_CLOSED
from voisso.agent.handoff import (
    HANDOFF_NOTICE,
    VALID_ROLES,
    Handoff,
    empty_status,
)
from voisso.agent.urgency import revise as revise_urgency_block
from voisso.agent.usage import PROCESS_TOTAL
from voisso.voice import SpeechContext, get_tts_provider, stt_status, tts_status
from voisso.voice import stream as tts_stream
from voisso.voice.vocabulary import vocabulary_status

import os

from . import config
from .store import CallbackStore, ComplaintStore, HandoffStore, SessionStore

# .env 는 다른 것을 읽기 전에 먼저 반영해야 한다.
config.load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
)
log = logging.getLogger("voisso.server")

app = FastAPI(
    title="Voisso API",
    description="경북 어르신 사투리 민원 접수 — 음성 파이프라인 + 대화 오케스트레이션",
    version="0.1.0",
)

# P7(통화 UI)/P8(대시보드)이 별도 포트에서 붙는다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    # allow_origins=["*"] 와 credentials 를 같이 켜면 브라우저가 거부한다.
    allow_credentials="*" not in config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = SessionStore()
complaints = ComplaintStore(config.COMPLAINTS_DIR)
handoffs = HandoffStore(config.HANDOFFS_DIR)
callbacks = CallbackStore(config.CALLBACKS_DIR)


# --------------------------------------------------------------------------
# 요청 스키마
# --------------------------------------------------------------------------


class StartRequest(BaseModel):
    """통화 시작. 본문은 없어도 된다."""

    caller_hint: str | None = Field(default=None, description="선택 — 발신 지역 등 힌트")


class TurnRequest(BaseModel):
    session_id: str
    text: str | None = None
    audio_b64: str | None = None
    # 브라우저 음성인식(Web Speech)의 maxAlternatives 후보들.
    # 문자열 배열이거나 [{"transcript": ..., "confidence": ...}] 형태.
    # 없으면 기존처럼 text 만 쓴다(하위호환).
    alternatives: list[Any] | None = None
    # False 면 TTS 를 건너뛰고 텍스트만 돌려준다. 클라이언트가
    # /api/tts/stream 으로 따로 받아 재생할 때 쓴다.
    want_audio: bool = True
    # 브라우저 음성인식으로 텍스트를 만들어 보낼 때 그 출처를 밝힌다.
    # 응답 caller_turn.stt_provider 로 그대로 돌아간다.
    stt_provider: str | None = None


class EndRequest(BaseModel):
    session_id: str


class TurnStreamRequest(TurnRequest):
    """스트리밍 턴 요청. 필드는 `/api/call/turn` 과 같다."""


class HandoffStartRequest(BaseModel):
    officer_name: str = Field(default="", description="담당자 이름 — 마스킹해서만 저장한다")
    department: str = Field(default="", description="담당 부서")


class HandoffMessageRequest(BaseModel):
    role: str = Field(description="officer | caller")
    text: str


class UrgencyReviseRequest(BaseModel):
    level: str = Field(description="응급 | 중요 | 보통 | 낮음")
    reason: str = Field(default="", description="담당자가 조정한 이유")


class CallbackScheduleRequest(BaseModel):
    briefing: str = Field(description="담당자가 표준어로 쓴 진행 상황")
    officer_name: str = Field(default="", description="담당자 이름 — 마스킹해서만 저장한다")
    department: str = Field(default="", description="담당 부서")


class CallbackMessageRequest(BaseModel):
    role: str = Field(description="caller | agent")
    text: str


class SpeakRequest(BaseModel):
    """TTS 스트리밍 요청. 텍스트는 이미 사투리로 변환된 상태를 가정한다."""

    text: str
    previous_text: str | None = Field(
        default=None, description="선택 — 감정 추론용 앞 문맥(어르신이 방금 한 말)"
    )


# --------------------------------------------------------------------------
# 통화 API
# --------------------------------------------------------------------------


def runtime_status() -> dict:
    """지금 무엇이 켜져 있고 무엇이 꺼져 있는지 한눈에.

    키가 없어도 데모가 너무 잘 돌아서 "키가 없다"는 사실 자체가 안 보였다.
    개발 중에 "왜 응답이 밋밋하지?" 를 즉시 알 수 있어야 한다.
    """
    stt = stt_status()
    tts = tts_status()
    agent = agent_status()
    engine = agent["engine"]

    missing_keys: list[str] = []
    if not engine["llm_available"]:
        # 어느 쪽 키든 하나만 있으면 된다.
        missing_keys.append("OPENAI_API_KEY 또는 ANTHROPIC_API_KEY")
    if not stt.get("audio_in"):
        # 명시적으로 꺼 둔 경우는 키 문제가 아니다.
        if "none" not in str(os.getenv("VOISSO_STT_PROVIDER") or "").lower():
            missing_keys.append("OPENAI_API_KEY")

    if engine.get("llm_error"):
        engine_label = f"규칙 기반 폴백 · {engine['llm_error']}"
        if "401" in engine["llm_error"]:
            missing_keys.append(f"{engine['provider']} 키(무효)")
    elif engine["llm_available"]:
        engine_label = f"{engine['provider']} 대화 ({engine['turn_model']})"
    else:
        engine_label = "규칙 기반 폴백 · LLM 키 없음"

    stt_error = stt.get("last_error")
    if stt_error:
        # 키가 있어도 통하지 않으면 '켜짐'이라고 말하면 안 된다.
        stt_label = f"음성 인식 실패 · {stt_error}"
        if "401" in stt_error and "OPENAI_API_KEY" not in missing_keys:
            missing_keys.append("OPENAI_API_KEY(무효)")
    elif stt.get("audio_in"):
        stt_label = f"음성 인식 켜짐 ({stt.get('model')})"
    else:
        stt_label = "음성 인식 꺼짐 · 텍스트 입력만"

    tts_error = tts.get("last_error")
    if tts_error:
        tts_label = f"음성 출력 실패 · {tts_error}"
        missing_keys.append(f"{tts['provider']} 크레딧/키 점검")
    elif tts["provider"] == "none":
        tts_label = "음성 출력 꺼짐 · 텍스트만"
    else:
        tts_label = f"음성 출력 ({tts['provider']})"

    integrations = agent["integrations"]
    return {
        "engine": engine["primary"],
        "engine_label": engine_label,
        "engine_provider": engine["provider"],
        "turn_model": engine["turn_model"],
        "summary_model": engine["summary_model"],
        "stt": stt.get("provider"),
        "stt_label": stt_label,
        "tts": tts["provider"],
        "tts_label": tts_label,
        "dialect": integrations["dialect"],
        "routing": integrations["routing"],
        # 하나라도 폴백으로 돌고 있으면 true. P7 이 배지를 띄우는 기준.
        "degraded": bool(missing_keys) or not integrations["routing"],
        "missing_keys": missing_keys,
    }


@app.post("/api/call/start")
def call_start(payload: StartRequest | None = None) -> dict:
    """통화를 연다.

    계약상 필수 응답은 `session_id` 하나다. 첫 인사(`reply_text` 등)와
    `status` 는 **추가 필드**다. P7 이 왕복을 한 번 아끼고, 지금 어떤 엔진·
    프로바이더로 돌고 있는지 화면에 표시할 수 있게 얹은 것이다.
    쓰지 않아도 되고, 무시해도 계약은 지켜진다.
    """
    session = sessions.create()
    greeting = session.greet()
    log.info("통화 시작 session=%s", session.id)
    return {
        "session_id": session.id,
        "reply_text": greeting["reply_text"],
        "reply_dialect": greeting["reply_dialect"],
        "caller_turn": None,
        "audio_b64": greeting["audio_b64"],
        "audio_mime": greeting.get("audio_mime"),
        "done": False,
        "slots": greeting["slots"],
        "urgency": greeting.get("urgency"),
        "status": runtime_status(),
    }


@app.post("/api/call/turn")
def call_turn(payload: TurnRequest) -> dict:
    """어르신의 한 마디를 받아 응답한다. text 또는 audio_b64 중 하나."""
    session = sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다. 통화를 다시 시작해 주세요.")

    # 핸드오프가 열렸으면 AI 는 말하지 않는다. 담당자를 연기하면 안 된다.
    silenced = _handoff_notice(session)
    if silenced is not None:
        return silenced

    has_alternatives = bool(payload.alternatives)
    if (
        not (payload.text or "").strip()
        and not (payload.audio_b64 or "").strip()
        and not has_alternatives
    ):
        # 빈 입력은 오류로 보지 않고 첫 인사로 처리한다.
        return session.greet()

    return session.turn(
        text=payload.text,
        audio_b64=payload.audio_b64,
        alternatives=payload.alternatives,
        want_audio=payload.want_audio,
        stt_provider=payload.stt_provider,
    )


@app.post("/api/call/turn/stream")
def call_turn_stream(payload: TurnStreamRequest):
    """턴을 NDJSON 으로 흘려보낸다 (계약 외 추가 엔드포인트).

    계약서의 `/api/call/turn` 은 LLM 과 TTS 가 **다 끝나야** 응답이 나가므로
    첫 소리까지 두 시간이 그대로 더해진다. 여기서는 LLM 이 첫 문장을 뱉는
    즉시 합성을 시작해 시간이 겹쳐진다.

    응답: `application/x-ndjson` — 한 줄에 JSON 객체 하나.

        {"type":"heard","dialect":"…","standard":"…"}
        {"type":"sentence","index":0,"standard":"…","dialect":"…"}
        {"type":"audio_start","index":0,"mime":"audio/wav",
         "sample_rate":32000,"bits":16,"channels":1}
        {"type":"audio_chunk","index":0,"seq":0,"b64":"…"}   ← 첫 청크에 WAV 헤더
        {"type":"audio_chunk","index":0,"seq":1,"b64":"…"}   ← 이후는 raw PCM
        {"type":"audio_end","index":0,"chunks":49}
        {"type":"sentence","index":1,…}                       ← 다음 문장 반복
        {"type":"final","reply_text":…,"reply_dialect":…,"slots":{…},"done":false,"meta":{…}}

    클라이언트는 `audio_chunk` 를 **seq 순서대로 이어 붙여** 재생하면 된다.
    `final` 의 `slots`/`done` 은 `/api/call/turn` 과 같은 값이다.
    """
    session = sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다. 통화를 다시 시작해 주세요.")

    silenced = _handoff_notice(session)
    if silenced is not None:
        return StreamingResponse(
            iter([json.dumps({"type": "final", **silenced}, ensure_ascii=False) + "\n"]),
            media_type="application/x-ndjson",
        )

    def emit():
        try:
            for event in session.turn_stream(
                text=payload.text,
                audio_b64=payload.audio_b64,
                alternatives=payload.alternatives,
                stt_provider=payload.stt_provider,
            ):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:  # 스트림 도중 죽어도 클라이언트가 알 수 있게
            log.exception("스트리밍 턴 실패")
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        emit(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/call/end")
def call_end(payload: EndRequest) -> dict:
    """통화를 닫고 민원카드를 만들어 저장한다."""
    session = sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    if session.closed and session.complaint_id:
        # 중복 호출 — 같은 카드를 다시 만들지 않고 저장된 것을 돌려준다.
        existing = complaints.get(session.complaint_id)
        if existing is not None:
            return {"complaint": existing}

    complaint_id = complaints.next_id()
    complaint = session.end(complaint_id)
    complaints.save(complaint)
    sessions.drop(session.id)

    log.info(
        "민원 접수 id=%s 부서=%s (요약 %.0fms / 라우팅 %.0fms)",
        complaint["id"],
        complaint["assigned"]["full_name"],
        session.end_timings.get("summary_ms", 0.0),
        session.end_timings.get("routing_ms", 0.0),
    )
    # `complaint` 는 계약서 5절 스키마 그대로다. `meta` 는 추가 필드.
    # 사용량은 민원 데이터가 아니므로 카드에 넣지 않고 meta 로만 보낸다.
    # `complaint` 는 계약서 5절 스키마 그대로. `meta` 는 추가 필드.
    return {
        "complaint": complaint,
        "meta": {
            "timings": session.end_timings,
            "usage": session.usage.as_dict(),
            # 통화 화면이 무엇을 기다려야 하는지. 확인 단계 없이 바로 대기로 넘어간다.
            "next_step": {
                "action": "handoff_wait",
                "complaint_id": complaint["id"],
                "poll": f"/api/handoff/{complaint['id']}",
                "also_poll": f"/api/callback/{complaint['id']}",
                "waiting_for": "담당자가 민원을 확인하고 통화를 잇는 것",
                "message": "담당자에게 전달했습니더. 담당자가 확인하면 이 화면으로 알려드릴게예.",
                # 처리 시간은 담당 부서가 정한다. 우리가 약속하지 않는다.
                "eta": None,
            },
        },
    }


# --------------------------------------------------------------------------
# 민원카드 조회 (P8 대시보드)
# --------------------------------------------------------------------------


@app.get("/api/complaints")
def list_complaints() -> dict:
    # `handoffs` 는 추가 필드다. 대시보드가 목록에서 연결 상태를 바로 보도록
    # {민원번호: "open"|"closed"} 를 함께 준다. 계약의 `complaints` 는 그대로다.
    return {
        "complaints": complaints.list_all(),
        "handoffs": handoffs.statuses(),
        "callbacks": callbacks.statuses(),
    }


@app.get("/api/complaints/{complaint_id}")
def get_complaint(complaint_id: str) -> dict:
    complaint = complaints.get(complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail=f"민원카드 {complaint_id} 를 찾을 수 없습니다.")
    return {"complaint": complaint}


# --------------------------------------------------------------------------
# 운영 편의 (계약 외 추가 엔드포인트)
# --------------------------------------------------------------------------


@app.post("/api/tts/stream")
def tts_stream_endpoint(payload: SpeakRequest):
    """음성을 청크 단위로 흘려보낸다 (계약 외 추가 엔드포인트).

    계약서의 `/api/call/turn` 은 `audio_b64` 로 통짜 오디오를 주는데,
    통화 데모에서는 첫 음성까지의 지연이 체감을 좌우한다. 그래서 P7 이
    원하면 이 경로로 바꿔 붙일 수 있게 열어 둔다.

    **TTS API 키는 이 서버 안에서만 쓰인다.** 브라우저는 이 엔드포인트만
    호출하고 키를 볼 일이 없다.
    """
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 가 비어 있습니다.")

    provider = get_tts_provider()
    if not getattr(provider, "supports_streaming", False):
        raise HTTPException(
            status_code=503,
            detail=f"현재 TTS 프로바이더('{provider.name}')는 스트리밍을 지원하지 않습니다.",
        )

    context = SpeechContext(previous_text=payload.previous_text or "")
    return StreamingResponse(
        tts_stream(text, context=context),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


def _handoff_notice(session) -> dict | None:
    """이 통화에 열린 핸드오프가 있으면 AI 대신 안내를 돌려준다.

    **AI 가 담당자를 연기하면 안 된다.** 접수까지가 AI 의 역할이고, 그 뒤로는
    사람이 책임진다. 누가 말하는지 헷갈리는 순간 신뢰가 무너진다.
    """
    complaint_id = getattr(session, "complaint_id", None)
    if not complaint_id:
        return None
    handoff = handoffs.get(complaint_id)
    if handoff is None or not handoff.is_open:
        return None

    from voisso.agent import integrations

    return {
        "session_id": session.id,
        "reply_text": HANDOFF_NOTICE,
        "reply_dialect": integrations.to_dialect(HANDOFF_NOTICE),
        "caller_turn": None,
        "audio_b64": None,
        "audio_mime": None,
        "done": True,
        "slots": session.slots.as_dict(),
        "urgency": session.urgency.as_dict(),
        "meta": {"engine": "handoff", "handoff": handoff.as_dict()["status"]},
    }


@app.post("/api/handoff/{complaint_id}/start")
def handoff_start(complaint_id: str, payload: HandoffStartRequest) -> dict:
    """담당자가 민원을 이어받는다. 민원카드가 있어야만 시작된다."""
    if complaints.get(complaint_id) is None:
        raise HTTPException(
            status_code=400, detail=f"민원카드 {complaint_id} 가 없습니다. 접수 후에 연결할 수 있습니다."
        )

    existing = handoffs.get(complaint_id)
    if existing is not None and existing.is_open:
        # 중복 시작 — 이미 열린 채널을 그대로 돌려준다.
        return {
            "channel_id": existing.channel_id,
            "status": existing.status,
            "started_at": existing.started_at,
        }

    handoff = Handoff.open(complaint_id, payload.officer_name, payload.department)
    handoffs.save(handoff)
    log.info(
        "핸드오프 시작 민원=%s 부서=%s 담당자=%s",
        complaint_id,
        handoff.officer_department or "-",
        handoff.officer_name_masked or "-",
    )
    return {
        "channel_id": handoff.channel_id,
        "status": handoff.status,
        "started_at": handoff.started_at,
    }


@app.post("/api/handoff/{complaint_id}/message")
def handoff_message(complaint_id: str, payload: HandoffMessageRequest) -> dict:
    """메시지를 남긴다. 저장 시 양방향 통역이 걸린다."""
    if payload.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400, detail=f"role 은 {' | '.join(VALID_ROLES)} 중 하나여야 합니다."
        )
    if not (payload.text or "").strip():
        raise HTTPException(status_code=400, detail="text 가 비어 있습니다.")

    # 읽기→추가→쓰기를 락 안에서 한 번에 한다. 동시 요청에 메시지가
    # 유실되거나 재전송이 중복으로 남는 것을 막는다.
    state: dict = {}

    def append(handoff):
        if not handoff.is_open:
            state["error"] = "이미 종료된 상담입니다."
            return None
        message = handoff.add_message(payload.role, payload.text)
        state["message"] = message
        return message

    handoff, _ = handoffs.mutate(complaint_id, append)
    if handoff is None:
        raise HTTPException(status_code=400, detail="아직 담당자 연결이 시작되지 않았습니다.")
    if "error" in state:
        raise HTTPException(status_code=400, detail=state["error"])
    return {"ok": True, "message": state["message"].as_dict()}


@app.get("/api/handoff/{complaint_id}")
def handoff_status(complaint_id: str) -> dict:
    """통화 화면과 대시보드가 함께 폴링하는 엔드포인트."""
    handoff = handoffs.get(complaint_id)
    if handoff is None:
        return empty_status(complaint_id)
    return handoff.as_dict()


@app.post("/api/handoff/{complaint_id}/close")
def handoff_close(complaint_id: str) -> dict:
    handoff = handoffs.get(complaint_id)
    if handoff is None:
        raise HTTPException(status_code=400, detail="아직 담당자 연결이 시작되지 않았습니다.")
    if handoff.is_open:
        handoff.close()
        handoffs.save(handoff)
        log.info("핸드오프 종료 민원=%s (메시지 %d건)", complaint_id, len(handoff.messages))
    return {"status": handoff.status}


@app.post("/api/complaints/{complaint_id}/urgency")
def revise_urgency(complaint_id: str, payload: UrgencyReviseRequest) -> dict:
    """담당자가 긴급도를 조정한다 (계약 외 추가 엔드포인트).

    **AI 판정은 제안이고 최종 판단은 사람이 한다.** 원래 판정과 근거는
    `urgency.history` 에 남아 나중에 대조할 수 있다.
    """
    complaint = complaints.get(complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail=f"민원카드 {complaint_id} 를 찾을 수 없습니다.")

    try:
        revised = revise_urgency_block(complaint.get("urgency") or {}, payload.level, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    complaint["urgency"] = revised
    complaints.save(complaint)
    log.info("긴급도 조정 민원=%s -> %s", complaint_id, revised["level"])
    return {"complaint_id": complaint_id, "urgency": revised}


@app.post("/api/callback/{complaint_id}/schedule")
def callback_schedule(complaint_id: str, payload: CallbackScheduleRequest) -> dict:
    """담당자가 진행 상황을 쓰고 '안내 전화 걸기' 를 누른다.

    브리핑은 **AI 가 생성하지 않는다.** 담당자가 쓴 표준어를 `to_dialect()` 로
    변환만 한다. 생성이 아니라 번역이라 없는 사실이 끼어들 수 없다.
    """
    if complaints.get(complaint_id) is None:
        raise HTTPException(status_code=400, detail=f"민원카드 {complaint_id} 가 없습니다.")
    if not (payload.briefing or "").strip():
        raise HTTPException(status_code=400, detail="briefing 이 비어 있습니다.")

    callback = Callback.schedule(
        complaint_id, payload.briefing, payload.officer_name, payload.department
    )
    callbacks.save(callback)
    log.info("안내 전화 예약 민원=%s 부서=%s", complaint_id, callback.officer_department or "-")
    return {"callback_id": callback.callback_id, "status": callback.status}


@app.get("/api/callback/{complaint_id}")
def callback_status(complaint_id: str) -> dict:
    """통화 화면이 폴링한다. status=pending 이면 수신 화면을 띄운다."""
    callback = callbacks.get(complaint_id)
    if callback is None:
        return callback_empty_status(complaint_id)
    return callback.as_dict()


@app.post("/api/callback/{complaint_id}/answer")
def callback_answer(complaint_id: str) -> dict:
    """어르신이 전화를 받았다. 브리핑이 첫 발화로 남는다."""
    callback = callbacks.get(complaint_id)
    if callback is None:
        raise HTTPException(status_code=400, detail="예약된 안내 전화가 없습니다.")
    if callback.status == STATUS_PENDING:
        callback.answer()
        callbacks.save(callback)
        log.info("안내 전화 수신 민원=%s", complaint_id)
    return callback.as_dict()


@app.post("/api/callback/{complaint_id}/message")
def callback_message(complaint_id: str, payload: CallbackMessageRequest) -> dict:
    """어르신의 추가 문의를 받아 적는다.

    **AI 는 답하지 않는다.** 접수번호·담당 부서처럼 이미 확정된 사실만
    민원카드에서 꺼내 답하고, 나머지는 담당자에게 넘긴다.
    """
    if payload.role not in CALLBACK_ROLES:
        raise HTTPException(
            status_code=400, detail=f"role 은 {' | '.join(CALLBACK_ROLES)} 중 하나여야 합니다."
        )
    if not (payload.text or "").strip():
        raise HTTPException(status_code=400, detail="text 가 비어 있습니다.")

    card = complaints.get(complaint_id)
    state: dict = {}

    def append(cb):
        if cb.status not in (STATUS_PENDING, STATUS_ANSWERED):
            state["error"] = "이미 종료된 안내 전화입니다."
            return None
        state["message"] = cb.add_message(payload.role, payload.text)
        if payload.role != ROLE_AGENT:
            # 확정된 사실이 아니면 DEFER_REPLY 가 돌아온다. 지어내지 않는다.
            state["reply"] = cb.add_message(ROLE_AGENT, answer_from_facts(payload.text, card))
        return True

    callback, _ = callbacks.mutate(complaint_id, append)
    if callback is None:
        raise HTTPException(status_code=400, detail="예약된 안내 전화가 없습니다.")
    if "error" in state:
        raise HTTPException(status_code=400, detail=state["error"])
    reply = state["reply"].as_dict() if "reply" in state else None
    return {"ok": True, "message": state["message"].as_dict(), "reply": reply}


@app.post("/api/callback/{complaint_id}/close")
def callback_close(complaint_id: str) -> dict:
    """안내 전화를 끝낸다. 어르신의 추가 문의는 민원카드에 쌓인다."""
    callback = callbacks.get(complaint_id)
    if callback is None:
        raise HTTPException(status_code=400, detail="예약된 안내 전화가 없습니다.")

    if callback.status != STATUS_CLOSED:
        callback.close()
        callbacks.save(callback)
        _append_callback_notes(complaint_id, callback)
        log.info(
            "안내 전화 종료 민원=%s (추가 문의 %d건)", complaint_id, len(callback.caller_questions)
        )
    return {"status": callback.status}


def _append_callback_notes(complaint_id: str, callback) -> None:
    """어르신의 추가 문의를 민원카드 notes 로 옮긴다.

    담당자가 다음에 그 카드를 열었을 때 무엇을 물어봤는지 보여야 한다.
    """
    questions = callback.caller_questions
    if not questions:
        return
    complaint = complaints.get(complaint_id)
    if complaint is None:
        return

    notes = list(complaint.get("notes") or [])
    known = {n.get("text") for n in notes}
    added = 0
    for message in questions:
        text = f"[안내 전화 문의] {message.standard}".strip()
        if text in known:
            continue
        notes.append({"text": text, "at": message.at, "source": "callback"})
        known.add(text)
        added += 1
    if added:
        complaint["notes"] = notes
        complaints.save(complaint)


@app.get("/api/usage")
def usage_total() -> dict:
    """서버가 뜬 뒤 누적 API 사용량 (계약 외 추가 엔드포인트).

    `api.usage.read` 스코프가 없으면 OpenAI 대시보드 말고는 조회 수단이 없다.
    그래서 응답의 usage 를 우리가 직접 세어 여기로 노출한다.
    리허설 스크립트(P3)는 실행 전후로 이걸 찍어 차이를 내면 된다.
    """
    return {
        "usage": PROCESS_TOTAL.as_dict(),
        "one_line": PROCESS_TOTAL.one_line(),
        "limits": {"max_turns": MAX_TURNS, "max_session_tokens": MAX_SESSION_TOKENS},
    }


@app.get("/api/health")
def health() -> dict:
    """지금 어떤 조합으로 돌고 있는지. 데모 전에 한 번 찍어보면 좋다."""
    return {
        "status": "ok",
        "runtime": runtime_status(),
        "vocabulary": vocabulary_status(),
        "stt": stt_status(),
        "tts": tts_status(),
        "agent": agent_status(),
        # 서버가 뜬 뒤 누적 사용량. 리허설 스크립트가 이 값을 읽어 집계한다.
        "usage_total": PROCESS_TOTAL.as_dict(),
        "limits": {
            "max_turns": MAX_TURNS,
            "max_session_tokens": MAX_SESSION_TOKENS,
        },
        "active_sessions": sessions.active_count(),
        "complaint_count": complaints.count(),
        "data_dir": str(config.DATA_DIR),
    }


# --------------------------------------------------------------------------
# 정적 파일 — web/call, web/dashboard
# --------------------------------------------------------------------------


# 브라우저가 되묻지도 않고 캐시를 쓰는 것을 막는 조합.
# no-store 만으로 충분한 브라우저가 대부분이지만, 오래된 브라우저와
# 중간 프록시까지 고려해 셋을 함께 보낸다.
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


class NoCacheStaticFiles(StaticFiles):
    """정적 파일에 캐시 방지 헤더를 붙여 서빙한다.

    StaticFiles 는 기본적으로 Cache-Control 을 보내지 않는다. 그러면
    브라우저가 휴리스틱 캐싱을 적용해 **재검증 요청조차 보내지 않고**
    옛 파일을 쓴다. 시연 직전 수정이 반영되지 않는 사고의 원인이다.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE_HEADERS)
        # 조건부 요청으로 304 가 나가면 브라우저는 캐시본을 쓴다.
        # 검증자를 지워 항상 본문을 받도록 한다.
        for header in ("etag", "last-modified"):
            if header in response.headers:
                del response.headers[header]
        return response


_PLACEHOLDER = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Voisso — {title}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:34rem;margin:4rem auto;padding:0 1.5rem;
line-height:1.7;color:#222}}code{{background:#f2f2f2;padding:.15em .4em;border-radius:4px}}</style>
</head><body><h1>Voisso — {title}</h1>
<p>아직 <code>{path}</code> 가 없습니다. 담당 모듈이 파일을 추가하면
서버를 다시 시작할 때 이 경로에 자동으로 붙습니다.</p>
<p>API 는 이미 동작합니다 — <a href="/api/health">/api/health</a>,
<a href="/docs">/docs</a></p></body></html>"""


def _mount_static(url_path: str, directory, title: str) -> None:
    """디렉터리가 있으면 정적 서빙, 없으면 안내 페이지를 붙인다.

    P7/P8 이 아직 파일을 안 만들었을 수 있다. 그때 StaticFiles 를 그냥
    마운트하면 서버가 아예 안 뜬다. 데모 서버가 남의 진도 때문에
    죽는 일은 없어야 한다.
    """
    if directory.is_dir():
        factory = NoCacheStaticFiles if config.NO_CACHE_STATIC else StaticFiles
        app.mount(url_path, factory(directory=str(directory), html=True), name=title)
        log.info(
            "정적 파일 마운트 %s -> %s (캐시 %s)",
            url_path,
            directory,
            "차단" if config.NO_CACHE_STATIC else "허용",
        )
        return

    rel = directory.relative_to(config.ROOT_DIR)
    log.warning("%s 없음 — %s 는 안내 페이지로 대체합니다.", rel, url_path)

    async def placeholder() -> HTMLResponse:
        return HTMLResponse(
            _PLACEHOLDER.format(title=title, path=rel),
            headers=NO_CACHE_HEADERS if config.NO_CACHE_STATIC else None,
        )

    app.get(url_path, include_in_schema=False)(placeholder)


_mount_static("/call", config.CALL_UI_DIR, "통화 화면")
_mount_static("/dashboard", config.DASHBOARD_DIR, "담당자 대시보드")
_mount_static("/demo", config.DEMO_DIR, "발표용 분할 화면")


@app.on_event("startup")
def log_runtime_banner() -> None:
    """기동할 때 지금 무엇으로 도는지 찍는다.

    ANTHROPIC_API_KEY 를 넣고 재시작하면 engine 이 rule -> claude 로 바뀌는 것이
    로그 첫 줄에서 바로 보여야 한다. 안 그러면 키를 넣고도 왜 응답이 밋밋한지
    한참 헤매게 된다.
    """
    status = runtime_status()
    log.info("─" * 58)
    log.info("  대화 엔진 : %-8s  %s", status["engine"].upper(), status["engine_label"])
    log.info("  음성 인식 : %-8s  %s", status["stt"], status["stt_label"])
    log.info("  음성 출력 : %-8s  %s", status["tts"], status["tts_label"])
    log.info(
        "  옆 모듈   : 방언 %s / 라우팅 %s",
        "O" if status["dialect"] else "X",
        "O" if status["routing"] else "X",
    )
    log.info(
        "  정적 캐시 : %s",
        "차단 (수정 즉시 반영)" if config.NO_CACHE_STATIC else "허용 (VOISSO_NO_CACHE=0)",
    )
    if status["missing_keys"]:
        log.warning("  빠진 키   : %s — 폴백으로 동작합니다.", ", ".join(status["missing_keys"]))
    else:
        log.info("  모든 기능이 켜져 있습니다.")
    log.info("─" * 58)


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/call")
