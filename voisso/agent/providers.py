"""대화 LLM 프로바이더 — OpenAI / Anthropic.

두 경로를 **나란히** 둔다. 지금은 OPENAI_API_KEY 하나로 STT(Whisper)와 대화를
같이 쓰지만, Anthropic 키가 생기면 `VOISSO_AGENT_PROVIDER=anthropic` 한 줄로
전환된다. 어느 쪽이든 실패하면 규칙 엔진이 받는다(engine.RuleEngine).

의존성은 늘리지 않는다. OpenAI 는 SDK 없이 `voisso/voice/_http.py` 의
urllib 유틸로 `/v1/chat/completions` 를 직접 호출한다. Anthropic 은 이미
설치된 anthropic SDK 를 쓴다.

두 프로바이더 모두 **구조화 출력**을 쓴다. 통화 한 턴에서 우리가 원하는 것은
"할 말 + 갱신된 슬롯 + 종료 여부" 세 가지이고, 자유 텍스트를 파싱하는 것보다
스키마를 강제하는 쪽이 훨씬 안정적이다.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..voice._http import HTTPError, post_json, post_sse_lines
from . import prompts
from .slots import SLOT_ORDER, Slots
from .usage import PROCESS_TOTAL, Usage

log = logging.getLogger("voisso.agent.providers")

# --- OpenAI ---------------------------------------------------------------
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# 실시간 통화라 **지연이 곧 사용성**이다. 어르신이 말을 마치고 응답이 올 때까지
# 2~3초가 넘어가면 통화로 안 느껴진다.
#
# 처음에는 가장 싼 등급(gpt-5.6-luna)을 기본으로 뒀는데, 재보니 **더 비싼
# terra 가 더 빨랐다.** 같은 프롬프트로 3회씩 측정한 첫 토큰까지 시간(TTFT):
#   gpt-5.6-luna  : 1226ms (1180 / 1226 / 1354)   전체 1718ms
#   gpt-5.6-terra :  772ms ( 772 /  790 /  756)   전체 1399ms
# 값싼 등급이 항상 빠르지는 않다 — 큰 모델이 더 좋은 하드웨어에 배치되면
# 지연은 오히려 줄어든다. 턴당 토큰이 얼마 안 되므로(입력 ~1K, 출력 ~150)
# terra 를 써도 통화 한 건이 2센트 안쪽이다. 지연을 사는 값으로 싸다.
DEFAULT_OPENAI_TURN_MODEL = "gpt-5.6-terra"
# 요약은 통화가 끝난 뒤 한 번만 돌고, 그 문장이 담당 공무원 대시보드에 그대로
# 뜨는 산출물이라 품질을 우선한다. 지연은 중요하지 않다.
DEFAULT_OPENAI_SUMMARY_MODEL = "gpt-5.6-terra"

# --- Anthropic ------------------------------------------------------------
DEFAULT_ANTHROPIC_TURN_MODEL = "claude-sonnet-5"
DEFAULT_ANTHROPIC_SUMMARY_MODEL = "claude-opus-5"


class LLMProvider:
    """대화 프로바이더 인터페이스."""

    name = "base"

    def __init__(self) -> None:
        self.turn_model = ""
        self.summary_model = ""
        # 키가 '있다'와 '통한다'는 다르다. 마지막 실패를 기억해 상태 조회에
        # 실어 보낸다 — 무효한 키를 두고 "LLM 으로 동작 중"이라고 표시하면
        # 실제로는 매 턴 규칙 엔진으로 떨어지는데 화면만 멀쩡해 보인다.
        self.last_error: str | None = None

    @property
    def available(self) -> bool:  # pragma: no cover - 인터페이스
        return False

    def respond(self, transcript, slots, usage=None):  # pragma: no cover
        raise NotImplementedError

    def summarize(self, transcript, slots, usage=None) -> dict[str, str]:  # pragma: no cover
        raise NotImplementedError

    def _record(self, model: str, raw_usage: dict[str, Any] | None, usage: Usage | None) -> None:
        """응답의 usage 를 세션 원장과 프로세스 누적에 함께 기록한다."""
        if usage is not None:
            usage.add_llm(model, raw_usage)
        PROCESS_TOTAL.add_llm(model, raw_usage)


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions. SDK 없이 REST 직접 호출."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        turn_model: str | None = None,
        summary_model: str | None = None,
    ) -> None:
        super().__init__()
        # STT 와 같은 키를 재사용한다. 새 환경변수를 만들지 않는다.
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self.turn_model = (
            turn_model or os.getenv("VOISSO_AGENT_MODEL") or DEFAULT_OPENAI_TURN_MODEL
        )
        self.summary_model = (
            summary_model or os.getenv("VOISSO_SUMMARY_MODEL") or DEFAULT_OPENAI_SUMMARY_MODEL
        )
        # 일부 모델은 max_tokens 대신 max_completion_tokens 만 받는다.
        # 400 을 한 번 맞으면 학습해서 이후로는 바꿔 보낸다.
        self._token_field = "max_completion_tokens"

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int,
        usage: Usage | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            self._token_field: max_tokens,
        }

        try:
            raw, _ = post_json(
                OPENAI_CHAT_URL,
                payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=45.0,
            )
        except HTTPError as exc:
            # 토큰 파라미터 이름이 안 맞으면 한 번만 바꿔 재시도한다.
            body = exc.body.decode("utf-8", "replace")
            if exc.status == 400 and "max_completion_tokens" in body and "max_tokens" in body:
                other = "max_tokens" if self._token_field == "max_completion_tokens" else "max_completion_tokens"
                log.info("토큰 파라미터를 %s 로 바꿔 재시도합니다.", other)
                payload.pop(self._token_field, None)
                self._token_field = other
                payload[other] = max_tokens
                raw, _ = post_json(
                    OPENAI_CHAT_URL,
                    payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=45.0,
                )
            else:
                raise

        body = json.loads(raw.decode("utf-8"))
        self._record(model, body.get("usage"), usage)
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if message.get("refusal"):
            raise RuntimeError(f"모델이 응답을 거부했습니다: {message['refusal']}")
        content = message.get("content") or ""
        if not content.strip():
            raise RuntimeError(f"빈 응답 (finish_reason={choice.get('finish_reason')})")
        self.last_error = None
        return json.loads(content)

    def respond(self, transcript, slots, usage: Usage | None = None):
        from .engine import TurnDecision, build_messages

        messages = build_messages(transcript, slots)
        if not messages:
            return TurnDecision(reply=prompts.opening_line(), engine=self.name)

        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{prompts.build_state_note(slots)}"
        data = self._call(
            model=self.turn_model,
            system=prompts.SYSTEM_PROMPT,
            messages=messages,
            schema=prompts.TURN_SCHEMA,
            schema_name="voisso_turn",
            max_tokens=1200,
            usage=usage,
        )
        return _decision_from(data, slots, self.name)

    def respond_stream(self, transcript, slots, usage: Usage | None = None):
        """토큰이 오는 대로 **완성된 문장부터** 내보낸다.

        `("sentence", 문장)` 을 여러 번, 마지막에 `("final", TurnDecision)`.
        첫 문장을 일찍 얻는 것이 목적이다 — 그 사이에 TTS 를 시작하면
        LLM 시간과 합성 시간이 겹쳐져 첫 소리가 훨씬 빨리 난다.
        """
        from .engine import TurnDecision, build_messages
        from .streaming import ReplySentenceExtractor

        messages = build_messages(transcript, slots)
        if not messages:
            yield ("final", TurnDecision(reply=prompts.opening_line(), engine=self.name))
            return

        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{prompts.build_state_note(slots)}"
        payload: dict[str, Any] = {
            "model": self.turn_model,
            "messages": [{"role": "system", "content": prompts.SYSTEM_PROMPT}, *messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "voisso_turn", "strict": True, "schema": prompts.TURN_SCHEMA},
            },
            self._token_field: 1200,
            "stream": True,
            # 스트리밍은 기본적으로 usage 를 안 준다. 명시해야 마지막 청크에 실린다.
            "stream_options": {"include_usage": True},
        }

        extractor = ReplySentenceExtractor()
        raw = ""
        for event in post_sse_lines(
            OPENAI_CHAT_URL,
            payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=45.0,
        ):
            if event.get("usage"):
                self._record(self.turn_model, event["usage"], usage)
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = (choices[0].get("delta") or {}).get("content") or ""
            if not delta:
                continue
            raw += delta
            for sentence in extractor.feed(delta):
                yield ("sentence", sentence)

        for sentence in extractor.finish():
            yield ("sentence", sentence)

        self.last_error = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"스트리밍 JSON 파싱 실패: {exc}") from exc
        yield ("final", _decision_from(data, slots, self.name))

    def summarize(self, transcript, slots, usage: Usage | None = None) -> dict[str, str]:
        data = self._call(
            model=self.summary_model,
            system=prompts.SUMMARY_PROMPT,
            messages=[{"role": "user", "content": _summary_input(transcript, slots)}],
            schema=prompts.SUMMARY_SCHEMA,
            schema_name="voisso_summary",
            max_tokens=1200,
            usage=usage,
        )
        return _summary_from(data)


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API. 이미 설치된 SDK 를 쓴다."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        turn_model: str | None = None,
        summary_model: str | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or ""
        self.turn_model = (
            turn_model or os.getenv("VOISSO_AGENT_MODEL") or DEFAULT_ANTHROPIC_TURN_MODEL
        )
        self.summary_model = (
            summary_model or os.getenv("VOISSO_SUMMARY_MODEL") or DEFAULT_ANTHROPIC_SUMMARY_MODEL
        )
        self._client: Any | None = None
        self._send_effort = True

    @property
    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            # 통화 중이다. SDK 기본 10분 타임아웃은 너무 길다.
            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=30.0, max_retries=1)
        return self._client

    def _call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        max_tokens: int,
        thinking: dict[str, Any] | None,
        effort: str | None,
        usage: Usage | None = None,
    ) -> dict[str, Any]:
        import anthropic

        client = self._get_client()
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if effort and self._send_effort:
            output_config["effort"] = effort

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "output_config": output_config,
        }
        if thinking is not None:
            kwargs["thinking"] = thinking

        try:
            response = client.messages.create(**kwargs)
        except anthropic.BadRequestError:
            if "effort" not in output_config:
                raise
            log.warning("output_config.effort 거부됨 — 이후 호출에서는 생략합니다.")
            self._send_effort = False
            output_config.pop("effort")
            response = client.messages.create(**kwargs)

        raw_usage = getattr(response, "usage", None)
        self._record(
            model,
            raw_usage.model_dump() if hasattr(raw_usage, "model_dump") else None,
            usage,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        self.last_error = None
        return json.loads(text)

    def respond(self, transcript, slots, usage: Usage | None = None):
        from .engine import TurnDecision, build_messages

        messages = build_messages(transcript, slots)
        if not messages:
            return TurnDecision(reply=prompts.opening_line(), engine=self.name)

        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{prompts.build_state_note(slots)}"
        data = self._call(
            model=self.turn_model,
            usage=usage,
            system=prompts.SYSTEM_PROMPT,
            messages=messages,
            schema=prompts.TURN_SCHEMA,
            max_tokens=1024,
            # 실시간 통화라 지연을 줄인다. 슬롯 채우기는 깊은 추론이 아니다.
            thinking={"type": "disabled"},
            effort="low",
        )
        return _decision_from(data, slots, self.name)

    def summarize(self, transcript, slots, usage: Usage | None = None) -> dict[str, str]:
        data = self._call(
            model=self.summary_model,
            usage=usage,
            system=prompts.SUMMARY_PROMPT,
            messages=[{"role": "user", "content": _summary_input(transcript, slots)}],
            schema=prompts.SUMMARY_SCHEMA,
            max_tokens=4000,
            # 담당 공무원이 읽는 결과물이다. Opus 5 는 사고가 기본으로 켜져 있고
            # 끄면 오히려 품질이 떨어지므로 그대로 둔다.
            thinking=None,
            effort=None,
        )
        return _summary_from(data)


# --------------------------------------------------------------------------
# 두 프로바이더가 공유하는 변환
# --------------------------------------------------------------------------


def _decision_from(data: dict[str, Any], slots: Slots, engine_name: str):
    from .engine import TurnDecision

    raw_slots = data.get("slots") or {}
    merged = {name: str(raw_slots.get(name) or "").strip() for name in SLOT_ORDER}
    # 모델이 이전에 알아낸 값을 빠뜨렸으면 우리가 가진 값을 지킨다.
    for name in SLOT_ORDER:
        if not merged[name]:
            merged[name] = slots.get(name)

    return TurnDecision(
        reply=str(data.get("reply") or "").strip() or prompts.opening_line(),
        slots=merged,
        ready_to_close=bool(data.get("ready_to_close")),
        engine=engine_name,
        answered_question=bool(data.get("answered_question")),
        caller_unclear=bool(data.get("caller_unclear")),
        landmark=str(raw_slots.get("landmark") or "").strip(),
        caller_finished=bool(data.get("caller_finished")),
        note=str(data.get("note") or "").strip(),
    )


def _summary_from(data: dict[str, Any]) -> dict[str, str]:
    return {
        "summary": str(data.get("summary") or "").strip(),
        "category": str(data.get("category") or "").strip(),
        "routing_query": str(data.get("routing_query") or "").strip(),
    }


def _summary_input(transcript: list[dict[str, Any]], slots: Slots) -> str:
    from .engine import render_transcript

    state = "\n".join(f"- {k}: {v}" for k, v in slots.for_card().items())
    return f"[통화 기록]\n{render_transcript(transcript)}\n\n[접수된 슬롯]\n{state}"


def explain_error(exc: Exception) -> str:
    """호출 실패를 담당자가 바로 고칠 수 있는 문장으로."""
    text = str(exc)
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    lowered = text.lower()
    if status == 401 or "authentication" in lowered or "invalid api key" in lowered or "invalid x-api-key" in lowered:
        key = "OPENAI_API_KEY" if "openai" in lowered or "sk-proj" in lowered else "API 키"
        return f"{key} 가 거부되었습니다(401). 키가 올바른지 확인하세요."
    if status == 429 or "rate limit" in lowered or "quota" in lowered:
        return "LLM 사용 한도에 걸렸습니다(429). 잠시 후 다시 시도하세요."
    if status and int(status) >= 500:
        return f"LLM 서버 오류({status}). 잠시 후 다시 시도하세요."
    return text[:200]
