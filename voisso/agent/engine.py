"""대화 엔진 — Claude 기반과 규칙 기반 두 가지.

`ClaudeEngine` 이 본체다. 하지만 **ANTHROPIC_API_KEY 가 없어도 전체 흐름이
동작해야 한다**는 것이 이 프로젝트의 타협 불가 조건이라, 같은 인터페이스를
구현한 `RuleEngine` 을 항상 곁에 둔다. 키가 없으면 처음부터 규칙 엔진으로
가고, 통화 중 API 호출이 실패하면 그 턴만 규칙 엔진이 받아낸다.
통화가 API 오류로 끊기는 것이 가장 나쁜 실패다.
"""

from __future__ import annotations

import json
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any

from . import prompts
from .slots import SLOT_ORDER, Slots, extract_slots

log = logging.getLogger("voisso.agent.engine")

# 실시간 통화다. 응답 지연이 곧 사용성이라 대화 턴은 Sonnet 을 쓴다.
DEFAULT_TURN_MODEL = "claude-sonnet-5"
# 요약은 통화가 끝난 뒤 한 번만 도는 배치성 작업이고, 담당 공무원이 읽는
# 결과물이라 품질을 우선한다.
DEFAULT_SUMMARY_MODEL = "claude-opus-5"


@dataclass
class TurnDecision:
    """한 턴의 결정."""

    reply: str
    slots: dict[str, str] = field(default_factory=dict)
    ready_to_close: bool = False
    engine: str = "rule"
    error: str | None = None


class RuleEngine:
    """키 없이 도는 규칙 기반 엔진.

    슬롯을 정규식으로 뽑고, 아직 빈 슬롯 중 하나를 골라 정해진 문장으로 묻는다.
    Claude 만큼 유연하진 않지만 '어르신 말을 받아주고 하나만 묻는다'는
    대화 원칙은 템플릿 수준에서 그대로 지킨다.
    """

    name = "rule"

    # 어르신이 한 말을 먼저 받아주는 맞장구. 매 턴 하나를 고른다.
    ACKS = (
        "아이고, 그러셨구나예.",
        "네, 말씀 잘 들었습니다.",
        "아이고, 얼마나 불편하셨겠습니까.",
        "예, 알겠습니다.",
    )

    # 슬롯별 질문. 인덱스는 몇 번째로 묻는지(0-based).
    QUESTIONS = {
        "what": (
            "어떤 일로 전화 주셨는지 편하게 말씀해 주세요.",
            "어떤 일이 있었는지 한 번만 더 말씀해 주시겠어요?",
        ),
        "where": (
            "그게 어디쯤인가요? 시·군이랑 동네 이름까지 말씀해 주세요.",
            "동네 이름이 어떻게 되는지 한 번만 더 알려 주시겠어요?",
        ),
        "when": (
            "언제부터 그랬는지 기억나세요?",
            "대략 언제쯤부터였는지만 알려 주시겠어요?",
        ),
        "contact": (
            "연락받으실 전화번호 좀 알려 주시겠어요?",
            "전화번호를 한 번만 더 불러 주시겠어요?",
        ),
    }

    CLOSING = (
        "네, 말씀하신 내용 잘 접수해 두겠습니다. "
        "담당하는 곳으로 전달해서 연락이 가도록 하겠습니다. 전화 주셔서 고맙습니다."
    )

    # 요약 폴백에서 쓰는 분류표. 키워드가 겹치면 위에 있는 것이 이긴다.
    #   (분류명, 발화에서 찾을 키워드, 부서 검색에 넘길 행정 용어)
    # 세 번째 값이 중요하다. 어르신의 말("물이 안 빠지고 고이가꼬")을 그대로
    # 부서 검색에 넣으면 사무분장 문서와 어휘가 안 맞아 엉뚱한 과가 잡힌다.
    # 같은 뜻의 행정 용어로 바꿔서 넘긴다. 짧을수록 좋다 — 단어를 늘리면
    # 점수는 흩어지고 evidence 로 엉뚱한 사무분장 줄이 뽑힌다.
    CATEGORY_RULES = (
        (
            "도로·하수 유지관리",
            ("배수", "하수", "물이 안", "물 안", "고이", "침수", "빗물", "역류", "맨홀", "하수구", "도랑"),
            "하수도 정비 배수시설",
        ),
        (
            "도로·하수 유지관리",
            ("도로", "포장", "아스팔트", "패인", "구멍", "인도", "보도블록"),
            "도로건설 도로관리 포장",
        ),
        ("상수도", ("수돗물", "상수도", "단수", "수도관", "녹물"), "상수도 급수 수질"),
        (
            "생활폐기물·환경",
            ("쓰레기", "폐기물", "분리수거", "악취", "냄새", "소각"),
            "생활폐기물 청소 재활용",
        ),
        (
            "안전·시설물",
            ("가로등", "신호등", "cctv", "위험", "무너", "붕괴", "축대", "옹벽"),
            "시설물 안전점검 재난예방",
        ),
        (
            "농정·농업기반",
            ("농로", "수리시설", "저수지", "농업", "밭", "논", "경작"),
            "농업기반 수리시설 농로",
        ),
        ("대중교통", ("버스", "노선", "정류장", "택시", "교통편"), "대중교통 버스노선"),
        (
            "복지·보건",
            ("복지", "요양", "돌봄", "보건소", "기초연금", "장애"),
            "노인복지 돌봄",
        ),
        (
            "산림·재해",
            ("산사태", "산불", "임도", "벌목", "태풍", "호우"),
            "산림재해 산사태 사방사업",
        ),
    )

    @property
    def available(self) -> bool:
        return True

    def respond(self, transcript: list[dict[str, Any]], slots: Slots) -> TurnDecision:
        last_caller = _last_caller_text(transcript)

        found = extract_slots(last_caller, slots) if last_caller else {}
        merged = {name: slots.get(name) for name in SLOT_ORDER}
        merged.update(found)

        # 지금 이 턴에 뭘 물을지 정하려면 방금 채운 값까지 반영해야 한다.
        preview = Slots(**{k: merged.get(k, "") for k in SLOT_ORDER})
        preview.ask_counts = dict(slots.ask_counts)
        preview.given_up = set(slots.given_up)

        target = preview.next_slot()
        if target is None:
            return TurnDecision(
                reply=self.CLOSING, slots=merged, ready_to_close=True, engine=self.name
            )

        asked = slots.ask_counts.get(target, 0)
        options = self.QUESTIONS[target]
        question = options[min(asked, len(options) - 1)]

        # 첫 인사 직후(=아직 아무것도 못 들은 상태)에는 맞장구가 어색하다.
        if last_caller:
            ack = random.choice(self.ACKS)
            reply = f"{ack} {question}"
        else:
            reply = question

        return TurnDecision(reply=reply, slots=merged, ready_to_close=False, engine=self.name)

    def summarize(self, transcript: list[dict[str, Any]], slots: Slots) -> dict[str, str]:
        what = slots.get("what")
        where = slots.get("where")
        when = slots.get("when")

        haystack = " ".join(
            entry.get("standard", "") for entry in transcript if entry.get("role") == "caller"
        ).lower()
        category = "기타 민원"
        routing_terms = ""
        for label, keywords, terms in self.CATEGORY_RULES:
            if any(kw in haystack for kw in keywords):
                category, routing_terms = label, terms
                break

        parts = [p for p in (where, what) if p]
        summary = ", ".join(parts) if parts else "통화 내용 확인 필요"
        if when:
            summary = f"{summary} ({when}부터)" if not when.endswith("부터") else f"{summary} ({when})"

        return {
            "summary": summary[:200],
            "category": category,
            # 지명은 부서 검색에 방해가 되므로 빼고, 행정 용어로 바꿔서 넘긴다.
            # 분류가 안 잡히면(기타 민원) 어쩔 수 없이 원문을 쓴다.
            "routing_query": (routing_terms or what)[:200],
        }


class ClaudeEngine:
    """Claude 기반 엔진. 실패 시 호출자가 RuleEngine 으로 넘긴다."""

    name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        turn_model: str | None = None,
        summary_model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or ""
        self.turn_model = turn_model or os.getenv("VOISSO_AGENT_MODEL") or DEFAULT_TURN_MODEL
        self.summary_model = (
            summary_model or os.getenv("VOISSO_SUMMARY_MODEL") or DEFAULT_SUMMARY_MODEL
        )
        self._client: Any | None = None
        # output_config.effort 를 서버가 거부하면 한 번만 배우고 이후엔 안 보낸다.
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

    def _create_json(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        max_tokens: int,
        thinking: dict[str, Any] | None,
        effort: str | None,
    ) -> dict[str, Any]:
        """구조화 출력으로 한 번 호출하고 JSON 을 파싱해 돌려준다."""
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
            # effort 를 못 받는 조합이면 그것만 빼고 한 번 더 시도한다.
            if "effort" not in output_config:
                raise
            log.warning("output_config.effort 거부됨 — 이후 호출에서는 생략합니다.")
            self._send_effort = False
            output_config.pop("effort")
            response = client.messages.create(**kwargs)

        text = "".join(block.text for block in response.content if block.type == "text")
        # 구조화 출력이라 정상 경로에서는 그대로 JSON 이다.
        return json.loads(text)

    def respond(self, transcript: list[dict[str, Any]], slots: Slots) -> TurnDecision:
        messages = _build_messages(transcript)
        if not messages:
            # 아직 어르신 발화가 없다 — 물어볼 것도 없다.
            return TurnDecision(reply=prompts.opening_line(), engine=self.name)

        # 현재 슬롯 상태를 마지막 사용자 메시지에 붙여 준다. Sonnet 5 는
        # 대화 중간 system 메시지를 지원하지 않으므로 이 방식이 맞다.
        note = prompts.build_state_note(slots)
        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{note}"

        data = self._create_json(
            model=self.turn_model,
            system=prompts.SYSTEM_PROMPT,
            messages=messages,
            schema=prompts.TURN_SCHEMA,
            max_tokens=1024,
            # 실시간 통화라 지연을 줄인다. 슬롯 채우기는 추론이 깊게 필요한 일이 아니다.
            thinking={"type": "disabled"},
            effort="low",
        )

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
            engine=self.name,
        )

    def summarize(self, transcript: list[dict[str, Any]], slots: Slots) -> dict[str, str]:
        conversation = _render_transcript(transcript)
        state = "\n".join(f"- {k}: {v}" for k, v in slots.for_card().items())
        content = f"[통화 기록]\n{conversation}\n\n[접수된 슬롯]\n{state}"

        data = self._create_json(
            model=self.summary_model,
            system=prompts.SUMMARY_PROMPT,
            messages=[{"role": "user", "content": content}],
            schema=prompts.SUMMARY_SCHEMA,
            max_tokens=4000,
            # 담당 공무원이 읽는 결과물이다. Opus 5 는 사고가 기본으로 켜져 있고,
            # 끄면 오히려 품질이 떨어지므로 그대로 둔다.
            thinking=None,
            effort=None,
        )
        return {
            "summary": str(data.get("summary") or "").strip(),
            "category": str(data.get("category") or "").strip(),
            "routing_query": str(data.get("routing_query") or "").strip(),
        }


# --------------------------------------------------------------------------
# 헬퍼
# --------------------------------------------------------------------------


def _build_messages(transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
    """통화 기록을 Messages API 형식으로 바꾼다.

    Messages API 는 user 로 시작해야 하는데 우리 통화는 상담원 인사로 시작한다.
    그래서 어르신의 첫 발화 이전 턴은 잘라낸다.
    """
    messages: list[dict[str, str]] = []
    for entry in transcript:
        role = entry.get("role")
        text = (entry.get("standard") or entry.get("dialect") or "").strip()
        if not text:
            continue
        if role == "caller":
            messages.append({"role": "user", "content": text})
        elif role == "agent":
            if not messages:
                continue  # 어르신 발화 전의 인사말은 버린다
            messages.append({"role": "assistant", "content": text})

    # 마지막이 assistant 면 모델에게 넘길 새 입력이 없다는 뜻이다.
    while messages and messages[-1]["role"] == "assistant":
        messages.pop()
    return messages


def _last_caller_text(transcript: list[dict[str, Any]]) -> str:
    for entry in reversed(transcript):
        if entry.get("role") == "caller":
            return (entry.get("standard") or entry.get("dialect") or "").strip()
    return ""


def _render_transcript(transcript: list[dict[str, Any]]) -> str:
    lines = []
    for entry in transcript:
        who = "어르신" if entry.get("role") == "caller" else "상담원"
        text = (entry.get("standard") or entry.get("dialect") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


_claude_engine: ClaudeEngine | None = None
_rule_engine = RuleEngine()


def get_engines() -> tuple[ClaudeEngine | None, RuleEngine]:
    """(주 엔진, 폴백 엔진). 주 엔진은 키가 없으면 None."""
    global _claude_engine
    candidate = ClaudeEngine()
    if candidate.available:
        if _claude_engine is None or _claude_engine.api_key != candidate.api_key:
            _claude_engine = candidate
        return _claude_engine, _rule_engine
    _claude_engine = None
    return None, _rule_engine


def engine_status() -> dict[str, Any]:
    claude, _ = get_engines()
    return {
        "primary": "claude" if claude else "rule",
        "claude_available": claude is not None,
        "turn_model": claude.turn_model if claude else None,
        "summary_model": claude.summary_model if claude else None,
        "fallback": "rule",
    }
