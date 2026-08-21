"""통화 세션 오케스트레이션.

한 턴의 흐름:

    음성 -> STT -> normalize(사투리→표준어) -> 대화 엔진 -> 슬롯 갱신
         -> to_dialect(표준어→사투리) -> TTS -> 응답

통화가 끝나면 요약 + 부서 라우팅을 거쳐 민원카드를 만든다.
어느 단계가 없어도(키가 없어도, 옆 모듈이 아직 없어도) 흐름 자체는 끊기지 않는다.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ..voice import SpeechContext, synthesize, transcribe
from . import integrations, prompts
from .complaint import build_complaint
from .engine import get_engines
from .slots import SLOT_ORDER, Slots

log = logging.getLogger("voisso.agent.session")

# 어르신이 말을 못 알아듣고 빙빙 도는 경우를 대비한 상한.
# 이 턴 수를 넘으면 있는 정보로 접수하고 마무리한다.
MAX_TURNS = 24


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
        }

    # -- 통화 --------------------------------------------------------------
    def greet(self) -> dict[str, Any]:
        """첫 인사. 통화 시작 직후 한 번만 부른다."""
        if self.transcript:
            return self._last_agent_response()
        return self._say(prompts.opening_line(), done=False)

    def turn(self, text: str | None = None, audio_b64: str | None = None) -> dict[str, Any]:
        """어르신의 한 마디를 받아 응답을 만든다.

        text 와 audio_b64 가 모두 비어 있으면 첫 인사를 돌려준다
        (P7 이 start 직후 곧바로 turn 을 호출해도 자연스럽게 동작하도록).
        """
        if self.closed:
            return self._last_agent_response(done=True)

        caller_dialect = (text or "").strip()
        stt_error: str | None = None

        if not caller_dialect and audio_b64:
            result = transcribe(audio_b64)
            caller_dialect = result.text.strip()
            stt_error = result.error
            if not caller_dialect:
                # 음성을 못 알아들었다. 통화를 끊지 말고 되물어본다.
                self.last_error = stt_error
                return self._say(
                    "죄송합니다, 잘 안 들렸어요. 한 번만 더 말씀해 주시겠어요?",
                    done=False,
                    stt_error=stt_error,
                )

        if not caller_dialect:
            return self.greet()

        # 사투리 -> 표준어. P5 미탑재면 원문 그대로 통과한다.
        caller_standard = integrations.normalize(caller_dialect)
        self.transcript.append(
            {"role": "caller", "dialect": caller_dialect, "standard": caller_standard}
        )
        self.turn_count += 1

        decision = self._decide()
        self.slots.merge(decision.slots)
        self.engine_used = decision.engine

        done = bool(decision.ready_to_close) or self.slots.is_complete()
        if self.turn_count >= MAX_TURNS:
            done = True

        if not done:
            # 이번 응답이 어떤 슬롯을 물었는지 기록해 둔다.
            # 같은 것을 세 번 묻지 않기 위한 카운터다.
            pending = self.slots.next_slot()
            if pending:
                self.slots.record_ask(pending)
                # 포기 처리로 남은 슬롯이 없어졌다면 이제 마무리해도 된다.
                done = self.slots.is_complete()

        return self._say(decision.reply, done=done, stt_error=stt_error)

    def end(self, complaint_id: str) -> dict[str, Any]:
        """통화를 닫고 민원카드를 만든다."""
        duration = self.duration_sec
        self.closed = True
        self.complaint_id = complaint_id

        summary_data = self._summarize()
        card = build_complaint(
            complaint_id=complaint_id,
            created_at=self.created_at,
            duration_sec=duration,
            transcript=self.transcript,
            slots=self.slots,
            summary=summary_data.get("summary", ""),
            category=summary_data.get("category", ""),
            routing_query=summary_data.get("routing_query", ""),
        )
        return card

    # -- 내부 --------------------------------------------------------------
    def _decide(self):
        """Claude 로 한 턴 결정. 실패하면 그 턴만 규칙 엔진이 받는다."""
        claude, rule = get_engines()
        if claude is not None:
            try:
                return claude.respond(self.transcript, self.slots)
            except Exception as exc:
                log.warning("Claude 턴 실패 — 규칙 엔진으로 대체합니다: %s", exc)
                self.last_error = f"claude_turn: {exc}"
        return rule.respond(self.transcript, self.slots)

    def _summarize(self) -> dict[str, str]:
        claude, rule = get_engines()
        if claude is not None:
            try:
                data = claude.summarize(self.transcript, self.slots)
                if data.get("summary"):
                    return data
                log.warning("요약이 비어 규칙 기반 요약으로 대체합니다.")
            except Exception as exc:
                log.warning("Claude 요약 실패 — 규칙 기반 요약으로 대체합니다: %s", exc)
                self.last_error = f"claude_summary: {exc}"
        return rule.summarize(self.transcript, self.slots)

    def _say(
        self, reply_standard: str, *, done: bool, stt_error: str | None = None
    ) -> dict[str, Any]:
        """상담원 발화를 사투리로 바꾸고 음성으로 만들어 기록한다."""
        reply_dialect = integrations.to_dialect(reply_standard)
        # 어르신이 방금 한 말을 앞 문맥으로 넘긴다. TTS 가 문맥에서 감정을
        # 추론하므로("아이고, 그러셨구나예"를 밝게 읽으면 이상하다) 실제로
        # 톤이 달라진다.
        speech = synthesize(
            reply_dialect,
            context=SpeechContext(previous_text=_last_caller_utterance(self.transcript)),
        )

        self.transcript.append(
            {"role": "agent", "standard": reply_standard, "dialect": reply_dialect}
        )

        return {
            "session_id": self.id,
            "reply_text": reply_standard,
            "reply_dialect": reply_dialect,
            "audio_b64": speech.audio_b64,
            "done": bool(done),
            "slots": self.slots.as_dict(),
            # 아래는 계약 외 진단 필드다. 소비자는 무시해도 된다.
            "meta": {
                "engine": self.engine_used,
                "tts": speech.provider,
                "tts_error": speech.error,
                "stt_error": stt_error,
                "turn": self.turn_count,
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
                    "audio_b64": None,
                    "done": self.closed if done is None else done,
                    "slots": self.slots.as_dict(),
                    "meta": {"engine": self.engine_used, "replayed": True},
                }
        return self._say(prompts.opening_line(), done=False)


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
