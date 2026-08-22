"""통화 세션 오케스트레이션.

한 턴의 흐름:

    음성 -> STT -> normalize(사투리→표준어) -> 대화 엔진 -> 슬롯 갱신
         -> to_dialect(표준어→사투리) -> TTS -> 응답

통화가 끝나면 요약 + 부서 라우팅을 거쳐 민원카드를 만든다.
어느 단계가 없어도(키가 없어도, 옆 모듈이 아직 없어도) 흐름 자체는 끊기지 않는다.
"""

from __future__ import annotations

import logging
import base64
import os
import re
import time
import uuid
from contextlib import contextmanager
from difflib import SequenceMatcher
from datetime import datetime, timezone
from typing import Any

from ..voice import SpeechContext, synthesize, transcribe
from ..voice.tts import TTSResult, get_tts_provider
from ..voice.vocabulary import score_transcript
from . import integrations, prompts
from .complaint import build_complaint
from .engine import get_engines
from .slots import (
    SLOT_ORDER,
    Slots,
    extract_contact,
    extract_location,
    is_meaningless,
    looks_finished,
)
from .urgency import Urgency, assess, confirm_intent, has_pressure
from .usage import PROCESS_TOTAL, Usage

log = logging.getLogger("voisso.agent.session")

# 어르신이 말을 못 알아듣고 빙빙 도는 경우를 대비한 상한.
# 이 턴 수를 넘으면 있는 정보로 접수하고 마무리한다.
MAX_TURNS = int(os.getenv("VOISSO_MAX_TURNS") or 24)

# 세션 하나가 쓸 수 있는 대화 토큰 상한. 폭주로 과금이 나는 것을 막는
# 안전장치다. 넘으면 통화를 끊지 않고 **정리 단계로 넘겨** 접수는 마친다.
MAX_SESSION_TOKENS = int(os.getenv("VOISSO_MAX_SESSION_TOKENS") or 60000)

# 슬롯이 다 찬 뒤 "더 하실 말씀 있으신가요?" 를 몇 번까지 반복할지.
# 어르신이 계속 말씀하시면 계속 받되, 무한 루프는 막는다.
MAX_WRAPUP_ROUNDS = int(os.getenv("VOISSO_MAX_WRAPUP_ROUNDS") or 4)

# 마무리 안내. **처리 결과도, 걸리는 시간도 약속하지 않는다.**
# 대신 "무엇을 기다리는지"와 "전화를 붙들고 있지 않아도 된다"를 알려 준다.
# 어르신이 언제 끝나는지 몰라 전화기를 든 채 기다리는 것이 가장 나쁜 상태다.
# 자막으로 한두 줄에 들어가야 한다. "전화를 끊고 계셔도 된다"는 정보는
# 다음 턴(대기 안내)에서 next_step 으로 전달되므로 여기서 뺀다.
HANDOFF_CLOSING = "접수했습니다. 담당자가 확인하면 이 화면으로 알려 드리겠습니다."
WRAPUP_QUESTION = "더 얘기하실 사항 있으실까요?"

# 정보를 더 받아야 하는 턴인데 선언으로 끝났을 때 붙이는 질문.
# 프롬프트로 지시해도 모델은 가끔 선언으로 끝낸다. 후처리로 확실히 막는다.
NUDGE_QUESTION = "혹시 더 말씀해 주실 수 있을까요?"

# ── 응급 모드 문구 ──────────────────────────────────────────────────────
# 응급에서는 **질문이 아니라 상태**로 답한다. 물이 차오르는 사람에게
# "더 하실 말씀 있으신가예?" 를 되묻는 것은 대화 실패가 아니라 안전 실패다.
# 그래서 "항상 질문으로 끝내라" 규칙을 응급 경로에는 적용하지 않는다.
# 재촉이 반복될 때 **같은 문장을 되풀이하면 시스템이 고장 난 것처럼 들린다.**
# 뜻은 같고 표현만 바꾼 것들을 돌려 쓴다. 셋 다 "무엇이 되어 있는지 + 지금 뭘 하면
# 되는지"를 담고, 처리 결과는 약속하지 않는다.
# 응급 접수 확정 한 줄. **119 는 여기서 말하지 않는다** —
# 첫 안내에서 이미 말했고, 화면에 버튼이 고정돼 있다.
# 다급한 사람에게 긴 문장은 들리지 않는다. 짧게 끝낸다.
EMERGENCY_CONFIRM = "접수됐습니다. 담당자에게 바로 넘겼습니다."

# ── 119 연결 제안 ────────────────────────────────────────────────────────
# **통보가 아니라 질문이다.** 예전에는 "위험하시면 먼저 119에 전화해 주이소"
# 라고 통보했고, 어르신이 직접 걸어야 했다. 이제는 우리가 걸어 드리겠다고 묻는다.
# 어르신은 버튼보다 말이 편하다 — 이 프로젝트의 전제 그 자체다.
SAFETY_OFFER = "많이 위험해 보입니다. {number}에 연결해 드릴까요?"
SAFETY_OFFER_AGAIN = "{number}에 연결해 드릴까요? 예, 아니오만요."

# 브라우저는 사용자 조작 없이 tel: 을 실행하지 못한다. 말로 "네" 한 것은
# 브라우저 입장에서 조작이 아니다. 그래서 확정 뒤에도 화면 버튼이 필요하다.
# **실제 전화망 연동(H3)에서는 이 제약이 사라지고 바로 전환된다.**
SAFETY_CONFIRMED = "예, {number} 연결합니다. 화면 단추를 눌러 주세요."
SAFETY_DECLINED = "예, 위험해지시면 말씀해 주세요."
# 두 번 물어도 불분명하면 더 묻지 않는다. 공포를 주면 안 된다.
SAFETY_FALLBACK = "위험하시면 화면의 {number} 단추를 눌러 주세요."

# 한 통화에 연결 질문은 최대 이만큼. 계속 물으면 공포를 준다.
MAX_SAFETY_OFFERS = 2

# ── 자막 길이 제한 ──────────────────────────────────────────────────────
# 어르신 화면은 말풍선 목록이 아니라 **자막 오버레이**다. TV 자막처럼 한두 줄만
# 크게 뜬다. 길면 읽히지 않는다.
MAX_REPLY_CHARS = int(os.getenv("VOISSO_MAX_REPLY_CHARS") or 50)
# 다급한 상황일수록 더 짧게. 긴 문장은 들리지도 읽히지도 않는다.
MAX_REPLY_CHARS_URGENT = int(os.getenv("VOISSO_MAX_REPLY_CHARS_URGENT") or 30)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# 접수가 끝난 뒤에도 어르신이 말을 이어갈 때의 대답.
#
# **고정 문구를 돌려쓰지 않는다.** 방금 하신 말을 짧게 되짚는다 —
# 반복이 사라지고, 어르신도 자기 말이 전달되고 있다는 걸 안다.
# 되짚을 거리가 없을 때만 아래 폴백을 쓰고, 직전에 쓴 것은 다시 쓰지 않는다.
POST_INTAKE_ACKS = (
    "예, 같이 전하겠습니다.",
    "적어 뒀습니다.",
    "예, 그것도 적었습니다.",
    "말씀 담아 뒀습니다.",
    "예, 담당자에게 전하겠습니다.",
    "그 내용도 적어 뒀습니다.",
    "예, 알겠습니다. 적었습니다.",
    "담당자에게 같이 넘기겠습니다.",
)

# 다급한 분께는 더 짧게. 긴 문장은 들리지 않는다.
POST_INTAKE_ACKS_URGENT = (
    "적어 뒀습니다.",
    "예, 전하겠습니다.",
    "같이 넘기겠습니다.",
    "예, 적었습니다.",
)

# 재촉을 되짚는 말. "빨리와요" 가 반복돼도 문장은 달라진다.
# 감사·마무리 인사. 민원 내용이 아니므로 받아 적었다고 답하면 어색하다.
_COURTESY_RE = re.compile(r"고맙|감사|수고하|애쓰|잘\s*부탁")

PRESSURE_ACKS = (
    "빨리 와 달라고 하신 것도 전하겠습니다.",
    "급하신 상황이라고 같이 적었습니다.",
    "서둘러 달라고 전하겠습니다.",
    "급하다고 담당자에게 강조하겠습니다.",
)
# 위치는 출동에 필요하다. 응급에서 유일하게 계속 묻는 항목이고, 한 번에 하나만 묻는다.
# 상태 문장과 붙여 쓰므로 여기서 "접수"를 또 말하지 않는다.
# 두 번 묻게 되므로 표현을 바꿔 둔다. 같은 문장이 연달아 나오면 고장처럼 들린다.
EMERGENCY_ASK_WHERE = (
    "어디신지만 알려 주시겠어요?",
    "동네 이름만 말씀해 주시겠어요?",
)
# 슬롯별로 더 자연스러운 되물음.
SLOT_NUDGE = {
    "what": "어떤 일 때문에 불편하신지 말씀해 주시겠어요?",
    "where": "어느 시·군, 어느 동네인지 여쭤봐도 될까요?",
    "when": "언제부터 그랬는지 기억나세요?",
    "contact": "연락받으실 전화번호를 알려 주시겠어요?",
}

# 이 이상 비슷하면 같은 메모로 본다. 표현만 바꾼 재작성을 걸러낸다.
NOTE_SIMILARITY = 0.6


@contextmanager
def _timed(bucket: dict[str, float], key: str):
    """구간 소요시간을 ms 로 기록한다.

    실시간 통화에서 지연은 곧 품질이다. 어느 구간이 병목인지 추측하지 않고
    숫자로 보려고 매 턴 재서 응답 meta 에 실어 보낸다.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        bucket[key] = round((time.perf_counter() - start) * 1000, 1)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ConversationSession:
    """메모리에 사는 통화 한 건."""

    def __init__(self, session_id: str | None = None) -> None:
        self.id = session_id or uuid.uuid4().hex
        self.created_at = _utc_now_iso()
        self._started_at = time.monotonic()
        self.slots = Slots()
        self.transcript: list[dict[str, Any]] = []
        self.closed = False
        self.complaint_id: str | None = None
        self.turn_count = 0
        # 진단용 — 어떤 엔진/프로바이더가 실제로 쓰였는지 대시보드에서 볼 수 있게.
        self.engine_used: str | None = None
        self.last_error: str | None = None
        self.last_rescoring: dict[str, Any] | None = None
        self.end_timings: dict[str, float] = {}
        # 알아들을 수 없는 발화가 연속으로 몇 번 왔는지.
        self.unclear_streak = 0
        # 슬롯이 다 찬 뒤 "더 하실 말씀?" 을 몇 번 물었는지.
        self.wrapup_rounds = 0
        # 재촉이 나온 발화 수. 턴을 넘긴 반복만 센다.
        self.pressure_turns = 0
        # 접수가 확정됐는가. 확정 뒤에는 대화를 끌지 않고 담당자에게 넘긴다.
        self.intake_closed = False
        # 접수 확정 뒤에 들어온 발화 수. 폴백 문구를 고르는 데 쓴다.
        self.post_intake_turns = 0
        # 길이 때문에 줄이기 전의 원문. 시연 화면이 전체를 보여줄 수 있게 남긴다.
        self.last_reply_full = ""
        # 이미 쓴 대답들. 통화 전체에서 같은 말을 두 번 하지 않기 위해 기억한다.
        # (직전 것만 기억하면 한 칸 건너뛴 중복이 그대로 남는다)
        self.used_acks: set[str] = set()
        # 재강조로 안전 안내를 다시 붙인 적이 있는지. 매 턴 되풀이하지 않는다.
        self.reemphasized_once = False
        # 119 연결 제안 상태.
        self.safety_offers = 0          # 몇 번 물었는가 (최대 MAX_SAFETY_OFFERS)
        self.safety_pending = False     # 대답을 기다리는 중인가
        self.safety_confirmed = False   # 연결하겠다고 하셨는가
        self.safety_declined = False    # 거절하셨는가
        # 응급 접수 확정 문구를 이미 말했는가. 매 턴 붙이면 반복된다.
        self.emergency_status_said = False
        # 모델이 직전 턴에 한 말. 위험 인지 여부를 보는 데 쓴다.
        # (우리가 앞에 붙이는 안전 안내는 제외한 **모델 원문**이다)
        self.last_llm_reply = ""
        # 슬롯에 안 맞는 추가 정보. 민원카드 notes 로 나간다.
        self.notes: list[dict[str, Any]] = []
        # 긴급도는 통화 전체를 누적해서 판정한다. 뒤늦게 나오는 말이 더 위험할 수 있다.
        self.urgency = Urgency()
        # 안전 안내를 이미 했는가. 같은 안내를 매 턴 반복하지 않는다.
        self.safety_announced = False
        self.usage = Usage()
        self.budget_exceeded = False

    # -- 조회 --------------------------------------------------------------
    @property
    def duration_sec(self) -> int:
        return int(round(time.monotonic() - self._started_at))

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "created_at": self.created_at,
            "duration_sec": self.duration_sec,
            "turn_count": self.turn_count,
            "closed": self.closed,
            "complaint_id": self.complaint_id,
            "engine": self.engine_used,
            "slots": self.slots.as_dict(),
            "notes": list(self.notes),
            "urgency": self.urgency.as_dict(),
            "wrapup_rounds": self.wrapup_rounds,
            "usage": self.usage.as_dict(),
            "budget_exceeded": self.budget_exceeded,
        }

    # -- 통화 --------------------------------------------------------------
    def greet(self) -> dict[str, Any]:
        """첫 인사. 통화 시작 직후 한 번만 부른다."""
        if self.transcript:
            return self._last_agent_response()
        return self._say(prompts.opening_line(), done=False)

    def turn(
        self,
        text: str | None = None,
        audio_b64: str | None = None,
        alternatives: list[Any] | None = None,
        want_audio: bool = True,
        stt_provider: str | None = None,
    ) -> dict[str, Any]:
        """어르신의 한 마디를 받아 응답을 만든다.

        text 와 audio_b64 가 모두 비어 있으면 첫 인사를 돌려준다
        (P7 이 start 직후 곧바로 turn 을 호출해도 자연스럽게 동작하도록).

        `alternatives` 가 오면 브라우저 음성인식의 후보들로 보고 재점수화한다.
        기존 `text` 만 보내는 호출은 그대로 동작한다(하위호환).

        `want_audio=False` 면 TTS 를 건너뛰고 텍스트만 돌려준다. 클라이언트가
        `/api/tts/stream` 으로 따로 받아 재생하는 경우에 쓴다 — 합성 시간이
        턴의 임계 경로에서 빠져 응답이 1.5초쯤 빨라진다.
        """
        if self.closed:
            return self._last_agent_response(done=True)

        turn_started = time.perf_counter()
        timings: dict[str, float] = {}
        caller_dialect = (text or "").strip()
        stt_error: str | None = None
        rescored: dict[str, Any] | None = None
        # 어르신 발화가 어디서 왔는지. 화면에 그대로 보여주기 위해 끝까지 들고 간다.
        source = "text"
        stt_raw: str | None = caller_dialect or None
        provider_name: str | None = stt_provider

        if alternatives:
            picked, rescored = pick_best_alternative(alternatives, fallback=caller_dialect)
            if picked:
                caller_dialect = picked
                stt_raw = picked
                source = "stt"
                provider_name = stt_provider or "web"

        if not caller_dialect and audio_b64:
            with _timed(timings, "stt_ms"):
                result = transcribe(audio_b64)
            self._record_stt(result)
            caller_dialect = result.text.strip()
            stt_error = result.error
            source = "stt"
            stt_raw = caller_dialect or None
            provider_name = result.provider or provider_name
            if not caller_dialect:
                # 음성을 못 알아들었다. 통화를 끊지 말고 되물어본다.
                self.last_error = stt_error
                return self._say(
                    "죄송합니다, 잘 안 들렸어요. 한 번만 더 말씀해 주시겠어요?",
                    done=False,
                    stt_error=stt_error,
                    timings=timings,
                    started=turn_started,
                    want_audio=want_audio,
                )

        if not caller_dialect:
            return self.greet()

        # 사투리 -> 표준어. P5 미탑재면 원문 그대로 통과한다.
        with _timed(timings, "normalize_ms"):
            caller_standard = integrations.normalize(caller_dialect)
        self.transcript.append(
            {"role": "caller", "dialect": caller_dialect, "standard": caller_standard}
        )
        self.turn_count += 1
        if has_pressure(caller_dialect) or has_pressure(caller_standard):
            self.pressure_turns += 1

        self.last_rescoring = rescored
        caller_turn = self.build_caller_turn(
            caller_dialect, caller_standard, source, stt_raw, provider_name
        )

        # 접수가 확정된 뒤다. **같은 안내를 되풀이하지 않는다.**
        # 어르신 말은 버리지 않고 담당자에게 전할 메모로 쌓는다.
        if self.intake_closed:
            self.add_note(caller_standard, source="caller_after_intake")
            # 말로는 되풀이하지 않지만 **긴급도는 계속 갱신한다.**
            # 재촉이 이어지면 P7 이 화면의 119 버튼을 계속 강조해야 한다.
            self._update_urgency()
            ack = self._post_intake_ack(caller_standard)
            self.post_intake_turns += 1
            return self._say(
                ack,
                done=True,
                stt_error=stt_error,
                rescored=rescored,
                timings=timings,
                started=turn_started,
                want_audio=want_audio,
                caller_turn=caller_turn,
            )

        with _timed(timings, "llm_ms"):
            decision = self._decide()
        reply = self._apply_decision(decision)

        # **긴급도를 먼저 판정한다.** 종료 판단이 이 결과에 달려 있다.
        # (예전에는 순서가 반대라 응급 분기가 한 턴 낡은 값을 봤다.)
        notice = self._update_urgency()

        done, reply = self._resolve_done(decision, caller_standard)
        emergency = self.urgency.is_emergency

        # 안전 안내는 응답 맨 앞에 붙인다. 접수보다 먼저다.
        if notice:
            reply = f"{notice} {reply}".strip()
            # 첫 안내 턴에는 통화를 끝내지 않는다. 다만 **재강조는 다르다** —
            # 이미 안내한 상황에서 재촉이 반복되는 것이라, 접수 확정을 미루면
            # 안 된다. 카드를 만들어 담당자에게 넘기는 편이 낫다.
            if not self.urgency.reemphasize:
                done = False

        # 아직 받을 정보가 남았으면 질문으로 끝낸다.
        # **응급은 예외다** — 재촉에는 질문이 아니라 상태로 답해야 한다.
        reply = self._ensure_question(
            reply, done=done, safety=bool(notice) or emergency
        )

        # 응급에서는 위치만 묻고 그 기록은 _emergency_reply 가 이미 했다.
        if not done and not emergency:
            # 이번 응답이 어떤 슬롯을 물었는지 기록해 둔다.
            # 같은 것을 세 번 묻지 않기 위한 카운터다.
            pending = self.slots.next_slot()
            if pending:
                self.slots.record_ask(pending)
                # 포기 처리로 남은 슬롯이 없어졌다면 이제 마무리해도 된다.
                done = self.slots.is_complete()

        if done:
            # 이 턴으로 접수가 확정됐다. 다음 발화부터는 담당자에게 넘긴다.
            self.intake_closed = True

        return self._say(
            reply,
            done=done,
            stt_error=stt_error,
            rescored=rescored,
            timings=timings,
            started=turn_started,
            want_audio=want_audio,
            caller_turn=caller_turn,
        )

    def turn_stream(
        self,
        text: str | None = None,
        audio_b64: str | None = None,
        alternatives: list[Any] | None = None,
        stt_provider: str | None = None,
    ):
        """턴을 **문장 단위로 흘려보낸다.** 첫 소리를 최대한 빨리 내는 경로.

        일괄 경로(`turn`)는 LLM 이 끝나야 TTS 를 시작하므로 첫 소리까지
        `LLM + TTS` 가 그대로 더해진다. 여기서는 LLM 이 첫 문장을 뱉는 즉시
        합성을 시작해 두 시간이 겹쳐진다.

        내보내는 이벤트(dict):
          {"type": "heard",    "dialect", "standard"}         어르신 발화를 받아썼다
          {"type": "sentence", "index", "standard", "dialect"} 응답 문장 하나
          {"type": "audio",    "index", "mime", "audio_b64"}   그 문장의 음성
          {"type": "final",    "reply_text", "reply_dialect", "slots", "done", "meta"}
          {"type": "error",    "message"}

        어느 단계가 실패해도 일괄 경로로 폴백해 `final` 은 반드시 나간다.
        """
        if self.closed:
            yield {"type": "final", **self._last_agent_response(done=True)}
            return

        turn_started = time.perf_counter()
        timings: dict[str, float] = {}
        caller_dialect = (text or "").strip()
        stt_error: str | None = None
        rescored: dict[str, Any] | None = None
        # 어르신 발화가 어디서 왔는지. 화면에 그대로 보여주기 위해 끝까지 들고 간다.
        source = "text"
        stt_raw: str | None = caller_dialect or None
        provider_name: str | None = stt_provider

        if alternatives:
            picked, rescored = pick_best_alternative(alternatives, fallback=caller_dialect)
            if picked:
                caller_dialect = picked
                stt_raw = picked
                source = "stt"
                provider_name = stt_provider or "web"

        if not caller_dialect and audio_b64:
            with _timed(timings, "stt_ms"):
                result = transcribe(audio_b64)
            self._record_stt(result)
            caller_dialect = result.text.strip()
            stt_error = result.error
            source = "stt"
            stt_raw = caller_dialect or None
            provider_name = result.provider or provider_name
            if not caller_dialect:
                self.last_error = stt_error
                yield {
                    "type": "final",
                    **self._say(
                        "죄송합니다, 잘 안 들렸어요. 한 번만 더 말씀해 주시겠어요?",
                        done=False,
                        stt_error=stt_error,
                        timings=timings,
                        started=turn_started,
                    ),
                }
                return

        if not caller_dialect:
            yield {"type": "final", **self.greet()}
            return

        with _timed(timings, "normalize_ms"):
            caller_standard = integrations.normalize(caller_dialect)
        self.transcript.append(
            {"role": "caller", "dialect": caller_dialect, "standard": caller_standard}
        )
        self.turn_count += 1
        if has_pressure(caller_dialect) or has_pressure(caller_standard):
            self.pressure_turns += 1
        self.last_rescoring = rescored
        caller_turn = self.build_caller_turn(
            caller_dialect, caller_standard, source, stt_raw, provider_name
        )


        yield {"type": "heard", "caller_turn": caller_turn, **caller_turn}

        # 접수 확정 뒤에는 LLM 을 부르지 않고 짧게 받아 적기만 한다.
        if self.intake_closed:
            self.add_note(caller_standard, source="caller_after_intake")
            # 말로는 되풀이하지 않지만 **긴급도는 계속 갱신한다.**
            # 재촉이 이어지면 P7 이 화면의 119 버튼을 계속 강조해야 한다.
            self._update_urgency()
            ack = self._post_intake_ack(caller_standard)
            self.post_intake_turns += 1
            dialect = integrations.to_dialect(ack)
            self.transcript.append({"role": "agent", "standard": ack, "dialect": dialect})
            yield {
                "type": "final",
                "session_id": self.id,
                "reply_text": ack,
                "reply_dialect": dialect,
                "caller_turn": caller_turn,
                "audio_b64": None,
                "audio_mime": None,
                "done": True,
                "slots": self.slots.as_dict(),
                "urgency": self.urgency.as_dict(),
                "meta": {"engine": "post_intake", "turn": self.turn_count},
            }
            return

        llm, rule = get_engines()
        streamer = getattr(llm, "respond_stream", None) if llm is not None else None

        decision = None
        spoken: list[str] = []
        index = 0
        previous = _last_caller_utterance(self.transcript)

        if streamer is not None:
            try:
                for kind, payload in streamer(self.transcript, self.slots, usage=self.usage):
                    if kind == "sentence":
                        for event in self._speak_sentence(payload, index, previous, timings):
                            yield event
                        spoken.append(payload)
                        index += 1
                    elif kind == "final":
                        decision = payload
                timings["llm_ms"] = round((time.perf_counter() - turn_started) * 1000, 1)
            except Exception as exc:
                from .providers import explain_error

                log.warning("%s 스트리밍 실패 — 일괄 경로로 폴백합니다: %s", llm.name, exc)
                self.last_error = f"{llm.name}_stream: {exc}"
                llm.last_error = explain_error(exc)
                decision, spoken = None, []

        if decision is None:
            # 스트리밍을 못 썼거나 실패했다. 일괄 경로로 결정을 만든다.
            with _timed(timings, "llm_ms"):
                decision = self._decide()
            if not spoken:
                for sentence in _split_sentences(decision.reply):
                    for event in self._speak_sentence(sentence, index, previous, timings):
                        yield event
                    spoken.append(sentence)
                    index += 1

        self._apply_decision(decision)
        notice = self._update_urgency()
        done, _ = self._resolve_done(decision, caller_standard)
        if notice and not self.urgency.reemphasize:
            done = False
        if done:
            self.intake_closed = True
        if not done and not self.urgency.is_emergency:
            pending = self.slots.next_slot()
            if pending:
                self.slots.record_ask(pending)
                done = self.slots.is_complete()

        # 실제로 말한 문장을 이어 붙인 것이 이번 턴의 응답이다.
        reply_standard = " ".join(spoken).strip() or decision.reply
        reply_dialect = " ".join(
            integrations.to_dialect(sentence) for sentence in spoken
        ).strip() or integrations.to_dialect(reply_standard)

        self.transcript.append(
            {"role": "agent", "standard": reply_standard, "dialect": reply_dialect}
        )
        timings["total_ms"] = round((time.perf_counter() - turn_started) * 1000, 1)

        yield {
            "type": "final",
            "session_id": self.id,
            "reply_text": reply_standard,
            "reply_dialect": reply_dialect,
            "caller_turn": caller_turn,
            "audio_b64": None,  # 문장별 audio 이벤트로 이미 보냈다
            "audio_mime": None,
            "done": bool(done),
            "slots": self.slots.as_dict(),
            "urgency": self._urgency_payload(),
            "meta": {
                "engine": self.engine_used,
                "streamed": streamer is not None and bool(spoken),
                "sentences": len(spoken),
                "stt_error": stt_error,
                "turn": self.turn_count,
                "rescored": rescored,
                # 자막용으로 줄이기 전의 원문. 줄이지 않았으면 빈 값이다.
                "reply_full": self.last_reply_full,
                "timings": timings,
            },
        }

    def _speak_sentence(
        self, sentence: str, index: int, previous: str, timings: dict[str, float]
    ):
        """문장 하나를 사투리로 바꿔 합성하고 **청크 단위로** 내보낸다.

        통짜 합성을 기다리면 그 시간이 그대로 '첫 소리까지'에 더해진다.
        스트리밍 합성은 첫 청크가 훨씬 빨리 오므로 그것부터 흘려보낸다.

        프로바이더가 스트리밍을 못 하면(none/elevenlabs) 통짜 결과를
        청크 하나로 감싸 내보낸다 — **이벤트 모양은 항상 같다.**
        """
        dialect = integrations.to_dialect(sentence)
        yield {
            "type": "sentence",
            "index": index,
            "standard": sentence,
            "dialect": dialect,
        }

        provider = get_tts_provider()
        if provider.name == "none":
            return

        started = time.perf_counter()
        first_at: float | None = None
        sent = 0

        yield {
            "type": "audio_start",
            "index": index,
            # 스트리밍 WAV 는 32kHz 16bit mono PCM 이고 헤더는 첫 청크에만 있다.
            "mime": "audio/wav",
            "sample_rate": 32000,
            "bits": 16,
            "channels": 1,
        }

        try:
            if getattr(provider, "supports_streaming", False):
                for chunk in provider.stream(
                    dialect, context=SpeechContext(previous_text=previous)
                ):
                    if not chunk:
                        continue
                    if first_at is None:
                        first_at = time.perf_counter()
                    yield {
                        "type": "audio_chunk",
                        "index": index,
                        "seq": sent,
                        "b64": base64.b64encode(chunk).decode("ascii"),
                    }
                    sent += 1
            else:
                speech = synthesize(dialect, context=SpeechContext(previous_text=previous))
                self._record_tts(dialect, speech.provider)
                if speech.audio_b64:
                    first_at = time.perf_counter()
                    yield {"type": "audio_chunk", "index": index, "seq": 0, "b64": speech.audio_b64}
                    sent = 1
        except Exception as exc:
            # 합성이 깨져도 통화는 계속된다. 텍스트는 이미 나갔다.
            log.warning("문장 %d 합성 실패: %s", index, exc)

        elapsed = round((time.perf_counter() - started) * 1000, 1)
        # 실패한 합성은 과금되지 않으므로 사용량에도 세지 않는다.
        if sent:
            self._record_tts(dialect, provider.name)
        if first_at is not None:
            # '첫 소리까지'를 좌우하는 것은 전체 합성이 아니라 첫 청크다.
            timings.setdefault(
                "tts_first_chunk_ms", round((first_at - started) * 1000, 1)
            )
        timings["tts_ms"] = round(timings.get("tts_ms", 0.0) + elapsed, 1)
        yield {"type": "audio_end", "index": index, "chunks": sent}

    def end(self, complaint_id: str) -> dict[str, Any]:
        """통화를 닫고 민원카드를 만든다."""
        duration = self.duration_sec
        self.closed = True
        self.complaint_id = complaint_id

        # 원장은 여기서 초기화하지 않는다. 통화 내내 쌓아 온 값에
        # 요약 호출을 더해야 '이 통화가 쓴 총량'이 된다.
        self.end_timings = {}
        with _timed(self.end_timings, "summary_ms"):
            summary_data = self._summarize()
        with _timed(self.end_timings, "routing_ms"):
            card = build_complaint(
                complaint_id=complaint_id,
                created_at=self.created_at,
                duration_sec=duration,
                transcript=self.transcript,
                slots=self.slots,
                summary=summary_data.get("summary", ""),
                category=summary_data.get("category", ""),
                routing_query=summary_data.get("routing_query", ""),
                notes=self.notes,
                urgency=self.urgency.as_dict(),
            )
        log.info("통화 %s 사용량 — %s", self.id, self.usage.one_line())
        self.end_timings["total_ms"] = round(
            sum(self.end_timings.get(k, 0.0) for k in ("summary_ms", "routing_ms")), 1
        )
        return card

    # -- 내부 --------------------------------------------------------------
    # 같은 안내를 계속 반복하지 않기 위한 문턱. 이 횟수를 넘으면 말투를 바꾼다.
    UNCLEAR_GUIDANCE_AFTER = 2

    @staticmethod
    def build_caller_turn(
        dialect: str,
        standard: str,
        source: str,
        stt_raw: str | None,
        stt_provider: str | None,
    ) -> dict[str, Any]:
        """어르신 발화를 화면에 그대로 보여주기 위한 블록.

        **세 값이 같아도 셋 다 채운다.** 프론트가 분기하지 않게 하려는 것이다.
        예전에는 이 정보를 응답에 안 실어서, STT 가 멀쩡히 돌았는데도 화면에는
        "(음성 발화)" 만 떴다. 방언 정규화가 일하는 것을 보여줄 수 없었다.
        """
        return {
            "dialect": dialect or "",
            "standard": standard or dialect or "",
            "source": source,
            "stt_raw": stt_raw,
            "stt_provider": stt_provider,
        }

    def _urgency_payload(self) -> dict[str, Any]:
        """응답에 실을 긴급도. **연결 확정 여부를 함께 담는다.**

        브라우저는 사용자 조작 없이 tel: 을 실행하지 못한다. 말로 "네" 하신 것은
        브라우저 입장에서 조작이 아니므로, P7 이 이 값을 보고 큰 버튼을 띄운다.
        실제 전화망 연동(H3)에서는 이 제약이 사라지고 바로 전환된다.
        """
        payload = self.urgency.as_dict()
        referral = payload.get("safety_referral")
        if referral:
            referral = dict(referral)
            referral["confirmed"] = self.safety_confirmed
            referral["declined"] = self.safety_declined
            referral["asked"] = self.safety_offers
            payload["safety_referral"] = referral
        return payload

    def _caller_text(self) -> str:
        """어르신이 한 말 전체. 긴급도는 누적 판정한다."""
        return " ".join(
            e.get("standard") or e.get("dialect") or ""
            for e in self.transcript
            if e.get("role") == "caller"
        )

    def _emergency_reply(self, caller_text: str) -> tuple[bool, str]:
        """응급 모드의 응답을 정한다. `(종료 여부, 할 말)`.

        계약서 5-A: 응급으로 판정되면 대화 모드가 바뀐다.
        - 슬롯 채우기 중단. 연락처·시점을 더 묻지 않는다.
        - **위치만 예외** — 출동에 필요하다. 한 번에 하나만 묻는다.
        - **마무리 질문을 하지 않는다.** 접수를 즉시 확정하고 넘긴다.
        - 재촉에는 질문이 아니라 **지금 무엇이 되어 있는지**로 답한다.
        """
        number = (self.urgency.safety_referral or {}).get("number", "119")

        # 1) 연결 여부를 물어 놓고 대답을 기다리는 중이다.
        if self.safety_pending:
            answer = confirm_intent(caller_text)
            if answer == "yes":
                self.safety_pending = False
                self.safety_confirmed = True
                log.warning("119 연결 확정 session=%s 번호=%s", self.id, number)
                return False, SAFETY_CONFIRMED.format(number=number)
            if answer == "no":
                self.safety_pending = False
                self.safety_declined = True
                return False, SAFETY_DECLINED
            # 불분명하다. **부정으로 단정하지 않는다.** 한 번 더 짧게 묻는다.
            if self.safety_offers < MAX_SAFETY_OFFERS:
                self.safety_offers += 1
                return False, SAFETY_OFFER_AGAIN.format(number=number)
            # 두 번 물어도 불분명하면 화면 버튼 안내로 넘어간다.
            self.safety_pending = False
            return False, SAFETY_FALLBACK.format(number=number)

        # 2) 아직 안 물어봤거나, 거절 뒤 상황이 나빠졌다.
        if self._should_offer_safety():
            self.safety_offers += 1
            self.safety_pending = True
            return False, SAFETY_OFFER.format(number=number)

        status = EMERGENCY_CONFIRM

        if self.turn_count >= MAX_TURNS or self._check_budget():
            return True, status

        # 위치를 아직 못 받았고 두 번 넘게 묻지 않았으면 그것만 묻는다.
        if not self.slots.is_filled("where") and "where" not in self.slots.given_up:
            asked = self.slots.ask_counts.get("where", 0)
            question = EMERGENCY_ASK_WHERE[min(asked, len(EMERGENCY_ASK_WHERE) - 1)]
            self.slots.record_ask("where")
            if has_pressure(caller_text):
                # 재촉 중이다. 상태를 먼저 알리고 위치만 덧붙인다.
                # 상태는 한 번만 붙인다 — 매번 붙이면 같은 문장이 반복된다.
                if not self.emergency_status_said:
                    self.emergency_status_said = True
                    return False, f"{status} {question}"
            return False, question

        # 더 물을 것이 없다. 마무리 질문 루프에 들어가지 않고 즉시 확정한다.
        return True, status

    def _should_offer_safety(self) -> bool:
        """지금 119 연결을 물어봐야 하는가.

        처음 응급으로 판정됐을 때 한 번 묻는다. 거절하셨으면 **강요하지 않는다** —
        다만 상황이 더 나빠지는 신호(재촉 반복)가 오면 한 번 더 물어도 된다.
        어느 경우든 한 통화에 두 번을 넘지 않는다. 계속 물으면 공포를 준다.
        """
        if self.safety_confirmed or self.safety_offers >= MAX_SAFETY_OFFERS:
            return False
        if not self.safety_declined:
            return True
        # 거절 뒤에도 재촉이 이어지면 상황이 악화되고 있다는 뜻이다.
        return self.urgency.reemphasize

    def _update_urgency(self) -> str:
        """긴급도를 다시 판정하고, 필요하면 안전 안내 문구를 돌려준다.

        **이 안내는 슬롯 채우기보다 우선한다.** 위치·연락처를 다 못 받았어도
        먼저 안내한다. 사람이 위험한 상황을 접수만 하고 끝내는 것이
        이 시스템의 가장 큰 위험이기 때문이다.
        """
        previous = self.urgency
        self.urgency = assess(
            self._caller_text(),
            pressure_turns=self.pressure_turns,
            # 모델이 위험을 인지했는지 본다. 규칙이 못 잡은 위험을
            # 모델이 알아채는 경우가 있다(안전 쪽으로만 올린다).
            llm_reply=self.last_llm_reply,
        )
        # 이력은 이어 간다.
        self.urgency.history = list(previous.history)

        # 이미 응급인데 또 재촉이 오면 안내를 다시 강조한다.
        # **다만 한 번만** 다시 읽어 준다 — 매 턴 같은 안내를 되풀이하면
        # 고장 난 것처럼 들린다. 이후로는 reemphasize 플래그로 P7 이
        # 화면의 119 버튼을 계속 강조한다.
        if self.urgency.reemphasize and not self.reemphasized_once:
            self.reemphasized_once = True
            self.safety_announced = False

        if self.urgency.is_emergency and not self.safety_announced:
            self.safety_announced = True
            log.warning(
                "응급 판정 session=%s 신호=%s 안내=%s",
                self.id,
                ", ".join(self.urgency.signals),
                (self.urgency.safety_referral or {}).get("number"),
            )
        # 안내 문구는 _emergency_reply 가 **질문 형태로** 만든다.
        # 여기서 통보성 문장을 앞에 붙이지 않는다.
        return ""

    def _apply_decision(self, decision) -> str:
        """결정을 슬롯에 반영하고, 실제로 할 말을 정한다.

        못 알아들은 발화는 슬롯에 넣지 않는다. 다만 **되묻기만 반복하면
        어르신이 지친다.** 두 번 넘게 이어지면 재촉이 아니라 안심시키는
        말로 바꾼다.
        """
        self.engine_used = decision.engine
        self.last_llm_reply = decision.reply or ""

        if decision.caller_unclear:
            self.unclear_streak += 1
        else:
            self.unclear_streak = 0
            self.slots.merge(decision.slots)

        # 랜드마크는 못 알아들은 턴이 아니면 항상 살린다.
        if not decision.caller_unclear and decision.landmark:
            self.slots.add_landmark(decision.landmark)

        if not decision.caller_unclear and decision.note:
            self.add_note(decision.note)

        if self.unclear_streak >= self.UNCLEAR_GUIDANCE_AFTER:
            return "괜찮습니다, 천천히 말씀하셔도 됩니다. 어떤 일이신가요?"
        return decision.reply

    def add_note(self, text: str, source: str = "caller") -> None:
        """슬롯에 안 맞는 추가 정보를 쌓는다.

        "아침에만 그래예", "옆집도 같이 그래예" 같은 말이 담당자에게는
        슬롯보다 유용할 때가 많다. 버리지 않는다.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return

        # 모델이 매 턴 '지금까지의 메모'를 표현만 바꿔 다시 보내는 일이 잦다
        # ("옆집도 함께 그렇군요" / "옆집도 같은 증상이 있다고 함" / …).
        # 포함 관계로는 안 걸리므로 유사도까지 본다.
        for existing in list(self.notes):
            if cleaned == existing["text"] or cleaned in existing["text"]:
                return
            if existing["text"] in cleaned:
                self.notes.remove(existing)  # 새 메모가 더 자세하다
                continue
            if SequenceMatcher(None, existing["text"], cleaned).ratio() >= NOTE_SIMILARITY:
                return  # 같은 내용을 다시 쓴 것

        self.notes.append({"text": cleaned, "at": _utc_now_iso(), "source": source})

    def _resolve_done(self, decision, caller_text: str) -> tuple[bool, str]:
        """마무리 단계를 처리하고 `(종료 여부, 할 말)` 을 돌려준다.

        슬롯 네 개가 찼다고 바로 끊지 않는다. **"더 하실 말씀 있으신가요?" 를
        반드시 한 번은 묻는다.** 어르신은 중요한 것을 나중에 말한다.
        """
        reply = decision.reply

        # 응급이면 대화 모드가 다르다. 마무리 질문 루프에 들어가지 않는다.
        if self.urgency.is_emergency:
            return self._emergency_reply(caller_text)

        if self.turn_count >= MAX_TURNS or self._check_budget():
            return True, HANDOFF_CLOSING
        if decision.caller_unclear:
            # 못 알아들은 턴으로 통화를 끝내지 않는다.
            return False, reply
        if not self.slots.is_complete():
            return False, reply

        finished = bool(decision.caller_finished) or looks_finished(caller_text)
        if finished or self.wrapup_rounds >= MAX_WRAPUP_ROUNDS:
            return True, HANDOFF_CLOSING

        # 아직 마무리 확인을 안 했거나, 어르신이 계속 말씀하시는 중이다.
        self.wrapup_rounds += 1
        if not decision.ready_to_close and reply:
            # 모델이 이미 마무리 질문을 하고 있으면 그대로 둔다.
            if "말씀" in reply and "?" in reply:
                return False, reply
        return False, WRAPUP_QUESTION

    @staticmethod
    def _ends_with_question(text: str) -> bool:
        """마지막 문장이 물음표로 끝나는가."""
        cleaned = (text or "").strip().rstrip(" \"'\u2019\u201d)]\u300b\u300d")
        return cleaned.endswith(("?", "？"))

    def _ensure_question(self, reply: str, done: bool, safety: bool) -> str:
        """정보를 더 받아야 하는 턴은 **반드시 질문으로 끝낸다.**

        선언으로 끝나면 어르신은 자기 차례인지 모르고 침묵한다.
        모델이 규칙을 어길 때를 대비한 후처리다.

        예외는 둘. 안전 안내(지시라서 선언이 맞다)와 통화 종료 인사.
        """
        text = (reply or "").strip()
        if done or safety or self._ends_with_question(text):
            return text

        pending = self.slots.next_slot()
        question = SLOT_NUDGE.get(pending or "", NUDGE_QUESTION)
        if not text:
            return question
        return f"{text} {question}"

    def _post_intake_ack(self, caller_standard: str) -> str:
        """접수 확정 뒤의 대답을 만든다.

        **방금 하신 말을 되짚는 것이 기본이다.** 고정 문구를 돌려쓰면
        여덟 턴에 같은 문장이 두 번 나오고, 어르신은 시스템이 고장 났다고
        느낀다. 되짚을 거리가 없을 때만 폴백을 쓰고, 그때도 직전 문구는
        다시 쓰지 않는다.
        """
        text = (caller_standard or "").strip()
        urgent = self.urgency.is_emergency
        candidates: list[str] = []

        # 인사·마무리 표현은 "적어 뒀습니다" 로 받으면 어색하다. 인사로 받는다.
        # (감사 인사는 P5 의 종료 신호 목록에 없어서 여기서 따로 본다)
        if looks_finished(text) or _COURTESY_RE.search(text):
            for phrase in (
                "예, 전화 주셔서 고맙습니다.",
                "예, 담당자가 곧 연락드릴 겁니다.",
                "예, 편히 계세요.",
                "예, 들어가세요.",
            ):
                if phrase not in self.used_acks:
                    self.used_acks.add(phrase)
                    return phrase

        # 1) 무엇을 받아 적었는지 되짚는다.
        contact = extract_contact(text)
        if contact:
            candidates.append("연락처 받았습니다.")

        location = extract_location(text)
        if location:
            candidates.append(f"{location}이라고 적었습니다.")

        if has_pressure(text):
            candidates.append(
                PRESSURE_ACKS[self.post_intake_turns % len(PRESSURE_ACKS)]
            )

        if not candidates and text and not is_meaningless(text):
            # 하신 말을 그대로 짧게 인용한다. 지어내지 않으니 틀릴 일이 없다.
            quoted = text.rstrip(" .!?\u2026")
            if len(quoted) > 22:
                quoted = quoted[:22] + "…"
            candidates.append(f"'{quoted}' 적어 뒀습니다.")

        # 2) 폴백 — 직전과 다른 것을 고른다.
        pool = POST_INTAKE_ACKS_URGENT if urgent else POST_INTAKE_ACKS
        for offset in range(len(pool)):
            candidates.append(pool[(self.post_intake_turns + offset) % len(pool)])

        for candidate in candidates:
            if candidate not in self.used_acks:
                self.used_acks.add(candidate)
                return candidate
        # 준비한 문구를 다 썼다. 통화가 그만큼 길어졌다는 뜻이다.
        return candidates[0]

    def _fit_length(self, reply: str, urgent: bool) -> str:
        """자막에 들어가도록 응답을 줄인다.

        **빠뜨리는 게 아니라 줄이는 것이다.** 문장 단위로 자르고, 질문이 있으면
        질문을 반드시 남긴다 — 질문이 사라지면 어르신이 자기 차례인지 모른다.
        잘라낸 원문은 `meta.reply_full` 로 함께 보내 시연 화면에서 볼 수 있다.
        """
        text = (reply or "").strip()
        limit = MAX_REPLY_CHARS_URGENT if urgent else MAX_REPLY_CHARS
        if len(text) <= limit:
            return text

        sentences = [x.strip() for x in _SENTENCE_SPLIT.split(text) if x.strip()]
        question = next(
            (x for x in reversed(sentences) if x.rstrip().endswith(("?", "？"))), ""
        )

        kept: list[str] = []
        used = 0
        for sentence in sentences:
            if sentence == question:
                continue
            cost = len(sentence) + (1 if kept else 0)
            reserve = len(question) + 1 if question else 0
            if used + cost + reserve > limit:
                break
            kept.append(sentence)
            used += cost
        if question:
            kept.append(question)

        shortened = " ".join(kept).strip()
        if not shortened:
            # 문장 하나가 통째로 상한을 넘는다. 질문이라도 살린다.
            shortened = question or sentences[0]

        log.info(
            "자막 길이 초과 %d자 -> %d자 (상한 %d) | 원문: %s",
            len(text),
            len(shortened),
            limit,
            text[:80],
        )
        self.last_reply_full = text
        return shortened

    def _record_stt(self, result) -> None:
        if result.provider == "none":
            return
        self.usage.add_stt(result.model or result.provider, result.duration_sec, result.usage)
        PROCESS_TOTAL.add_stt(result.model or result.provider, result.duration_sec, result.usage)

    def _record_tts(self, text: str, provider: str) -> None:
        if provider in ("none", "skipped"):
            return
        self.usage.add_tts(provider, len(text or ""))
        PROCESS_TOTAL.add_tts(provider, len(text or ""))

    def _check_budget(self) -> bool:
        """토큰 상한을 넘었으면 True. 넘는 순간 한 번만 로그를 남긴다."""
        if self.budget_exceeded:
            return True
        if self.usage.total_tokens >= MAX_SESSION_TOKENS:
            self.budget_exceeded = True
            log.warning(
                "세션 %s 토큰 상한 초과 (%d >= %d) — 정리 단계로 넘깁니다.",
                self.id,
                self.usage.total_tokens,
                MAX_SESSION_TOKENS,
            )
        return self.budget_exceeded

    def _decide(self):
        """LLM 으로 한 턴 결정. 실패하면 그 턴만 규칙 엔진이 받는다."""
        llm, rule = get_engines()
        if llm is not None:
            try:
                return llm.respond(self.transcript, self.slots, usage=self.usage)
            except Exception as exc:
                from .providers import explain_error

                log.warning("%s 턴 실패 — 규칙 엔진으로 대체합니다: %s", llm.name, exc)
                self.last_error = f"{llm.name}_turn: {exc}"
                llm.last_error = explain_error(exc)
        return rule.respond(self.transcript, self.slots)

    def _summarize(self) -> dict[str, str]:
        llm, rule = get_engines()
        if llm is not None:
            try:
                data = llm.summarize(self.transcript, self.slots, usage=self.usage)
                if data.get("summary"):
                    return data
                log.warning("요약이 비어 규칙 기반 요약으로 대체합니다.")
            except Exception as exc:
                from .providers import explain_error

                log.warning("%s 요약 실패 — 규칙 기반 요약으로 대체합니다: %s", llm.name, exc)
                self.last_error = f"{llm.name}_summary: {exc}"
                llm.last_error = explain_error(exc)
        return rule.summarize(self.transcript, self.slots)

    def _say(
        self,
        reply_standard: str,
        *,
        done: bool,
        stt_error: str | None = None,
        rescored: dict[str, Any] | None = None,
        timings: dict[str, float] | None = None,
        started: float | None = None,
        want_audio: bool = True,
        caller_turn: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """상담원 발화를 사투리로 바꾸고 음성으로 만들어 기록한다."""
        timings = timings if timings is not None else {}
        self.last_reply_full = ""
        reply_standard = self._fit_length(reply_standard, self.urgency.is_emergency)
        with _timed(timings, "dialect_ms"):
            reply_dialect = integrations.to_dialect(reply_standard)
        # 어르신이 방금 한 말을 앞 문맥으로 넘긴다. TTS 가 문맥에서 감정을
        # 추론하므로("아이고, 그러셨구나예"를 밝게 읽으면 이상하다) 실제로
        # 톤이 달라진다.
        if want_audio:
            with _timed(timings, "tts_ms"):
                speech = synthesize(
                    reply_dialect,
                    context=SpeechContext(previous_text=_last_caller_utterance(self.transcript)),
                )
        else:
            speech = TTSResult(text=reply_dialect, provider="skipped")
        if speech.audio_b64:
            self._record_tts(reply_dialect, speech.provider)
        if started is not None:
            timings["total_ms"] = round((time.perf_counter() - started) * 1000, 1)

        self.transcript.append(
            {"role": "agent", "standard": reply_standard, "dialect": reply_dialect}
        )

        return {
            "session_id": self.id,
            "reply_text": reply_standard,
            "reply_dialect": reply_dialect,
            # 계약서 5절 — 서버가 무엇을 받아썼는지. 화면에 그대로 보여준다.
            "caller_turn": caller_turn,
            "audio_b64": speech.audio_b64,
            "audio_mime": speech.mime,
            "done": bool(done),
            "slots": self.slots.as_dict(),
            # **통화 중에** 긴급도를 알려 준다. 카드(end)에만 있으면 늦다 —
            # 통화가 끝난 뒤 119 버튼이 떠봐야 소용이 없다.
            "urgency": self._urgency_payload(),
            # 아래는 계약 외 진단 필드다. 소비자는 무시해도 된다.
            "meta": {
                "engine": self.engine_used,
                "tts": speech.provider,
                "tts_error": speech.error,
                "stt_error": stt_error,
                "turn": self.turn_count,
                "rescored": rescored,
                # 자막용으로 줄이기 전의 원문. 줄이지 않았으면 빈 값이다.
                "reply_full": self.last_reply_full,
                "timings": timings,
            },
        }

    def _last_agent_response(self, done: bool | None = None) -> dict[str, Any]:
        """이미 한 말을 다시 돌려준다(중복 호출 방어)."""
        for entry in reversed(self.transcript):
            if entry.get("role") == "agent":
                return {
                    "session_id": self.id,
                    "reply_text": entry.get("standard", ""),
                    "reply_dialect": entry.get("dialect", ""),
                    "caller_turn": None,
                    "audio_b64": None,
                    "audio_mime": None,
                    "done": self.closed if done is None else done,
                    "slots": self.slots.as_dict(),
                    "urgency": self._urgency_payload(),
                    "meta": {"engine": self.engine_used, "replayed": True},
                }
        return self._say(prompts.opening_line(), done=False)


def pick_best_alternative(
    alternatives: list[Any], fallback: str = ""
) -> tuple[str, dict[str, Any]]:
    """음성인식 후보 중 '경북 어르신의 민원 발화'에 가장 가까운 것을 고른다.

    브라우저 Web Speech 는 표준어에 맞춰져 있어 1순위 후보가 사투리를
    표준어로 바꿔 놓는 일이 잦다("옥동입니더" -> "옥동입니다"). 방언 어미·
    경북 지명·민원 용어로 점수를 매기면 원래 발화에 가까운 후보가 올라온다.

    후보는 문자열이거나 `{"transcript": ..., "confidence": ...}` 형태를
    받는다(Web Speech 결과를 그대로 넘겨도 되게).
    """
    parsed: list[tuple[str, float]] = []
    for item in alternatives:
        if isinstance(item, str):
            transcript, confidence = item, 0.0
        elif isinstance(item, dict):
            transcript = str(item.get("transcript") or item.get("text") or "")
            try:
                confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
        else:
            continue
        transcript = transcript.strip()
        if transcript:
            parsed.append((transcript, confidence))

    if not parsed:
        return fallback, {"used": False, "reason": "후보 없음"}

    scored = []
    for index, (transcript, confidence) in enumerate(parsed):
        # 인식기 신뢰도는 동점일 때만 갈음하는 보조 지표로 쓴다.
        # 순위가 뒤인 후보를 근거 없이 끌어올리지 않도록 순서도 살짝 반영한다.
        total = score_transcript(transcript) + confidence * 0.5 - index * 0.01
        scored.append({"transcript": transcript, "score": round(total, 3), "rank": index})

    best = max(scored, key=lambda c: c["score"])
    return best["transcript"], {
        "used": True,
        "picked": best["transcript"],
        "picked_rank": best["rank"],
        "changed": best["rank"] != 0,
        "candidates": scored,
    }


def _split_sentences(text: str) -> list[str]:
    """일괄 경로에서도 문장 단위로 합성하기 위해 나눈다."""
    import re

    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text or "") if p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def _last_caller_utterance(transcript: list[dict[str, Any]]) -> str:
    for entry in reversed(transcript):
        if entry.get("role") == "caller":
            return entry.get("dialect") or entry.get("standard") or ""
    return ""


def agent_status() -> dict[str, Any]:
    """헬스체크용 — 지금 어떤 조합으로 도는지 한눈에."""
    from .engine import engine_status

    return {
        "engine": engine_status(),
        "integrations": integrations.integration_status(),
        "slots": list(SLOT_ORDER),
        "max_turns": MAX_TURNS,
    }
