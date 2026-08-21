"""Voisso HTTP API — 계약서 5절.

    POST /api/call/start                  -> {"session_id"}
    POST /api/call/turn                   -> {"reply_text","reply_dialect","audio_b64","done","slots"}
    POST /api/call/end                    -> {"complaint": <민원카드>}
    GET  /api/complaints                  -> {"complaints": [...]}
    GET  /api/complaints/{id}             -> {"complaint": ...}

정적 파일: /call -> web/call/, /dashboard -> web/dashboard/
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from voisso.agent import agent_status
from voisso.voice import SpeechContext, get_tts_provider, stt_status, tts_status
from voisso.voice import stream as tts_stream

from . import config
from .store import ComplaintStore, SessionStore

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


class EndRequest(BaseModel):
    session_id: str


class SpeakRequest(BaseModel):
    """TTS 스트리밍 요청. 텍스트는 이미 사투리로 변환된 상태를 가정한다."""

    text: str
    previous_text: str | None = Field(
        default=None, description="선택 — 감정 추론용 앞 문맥(어르신이 방금 한 말)"
    )


# --------------------------------------------------------------------------
# 통화 API
# --------------------------------------------------------------------------


@app.post("/api/call/start")
def call_start(payload: StartRequest | None = None) -> dict:
    """통화를 연다.

    계약상 필수 응답은 `session_id` 하나다. 첫 인사(`reply_text` 등)를 함께
    돌려주는 것은 **추가 필드**로, P7 이 왕복을 한 번 아끼도록 얹은 것이다.
    쓰지 않아도 되고, 무시해도 계약은 지켜진다.
    """
    session = sessions.create()
    greeting = session.greet()
    log.info("통화 시작 session=%s", session.id)
    return {
        "session_id": session.id,
        "reply_text": greeting["reply_text"],
        "reply_dialect": greeting["reply_dialect"],
        "audio_b64": greeting["audio_b64"],
        "done": False,
        "slots": greeting["slots"],
    }


@app.post("/api/call/turn")
def call_turn(payload: TurnRequest) -> dict:
    """어르신의 한 마디를 받아 응답한다. text 또는 audio_b64 중 하나."""
    session = sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다. 통화를 다시 시작해 주세요.")

    if not (payload.text or "").strip() and not (payload.audio_b64 or "").strip():
        # 빈 입력은 오류로 보지 않고 첫 인사로 처리한다.
        return session.greet()

    return session.turn(text=payload.text, audio_b64=payload.audio_b64)


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
        "민원 접수 id=%s 부서=%s",
        complaint["id"],
        complaint["assigned"]["full_name"],
    )
    return {"complaint": complaint}


# --------------------------------------------------------------------------
# 민원카드 조회 (P8 대시보드)
# --------------------------------------------------------------------------


@app.get("/api/complaints")
def list_complaints() -> dict:
    return {"complaints": complaints.list_all()}


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


@app.get("/api/health")
def health() -> dict:
    """지금 어떤 조합으로 돌고 있는지. 데모 전에 한 번 찍어보면 좋다."""
    return {
        "status": "ok",
        "stt": stt_status(),
        "tts": tts_status(),
        "agent": agent_status(),
        "active_sessions": sessions.active_count(),
        "complaint_count": complaints.count(),
        "data_dir": str(config.DATA_DIR),
    }


# --------------------------------------------------------------------------
# 정적 파일 — web/call, web/dashboard
# --------------------------------------------------------------------------


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
        app.mount(url_path, StaticFiles(directory=str(directory), html=True), name=title)
        log.info("정적 파일 마운트 %s -> %s", url_path, directory)
        return

    rel = directory.relative_to(config.ROOT_DIR)
    log.warning("%s 없음 — %s 는 안내 페이지로 대체합니다.", rel, url_path)

    async def placeholder() -> HTMLResponse:
        return HTMLResponse(_PLACEHOLDER.format(title=title, path=rel))

    app.get(url_path, include_in_schema=False)(placeholder)


_mount_static("/call", config.CALL_UI_DIR, "통화 화면")
_mount_static("/dashboard", config.DASHBOARD_DIR, "담당자 대시보드")


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/call")
