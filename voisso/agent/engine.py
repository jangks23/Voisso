"""대화 엔진 — LLM 프로바이더 선택과 규칙 기반 폴백.

실제 LLM 호출은 `providers.py` 가 한다(OpenAI / Anthropic). 이 파일은
**무엇을 쓸지 고르는 일**과, 아무것도 쓸 수 없을 때를 위한 `RuleEngine` 을 맡는다.

**어떤 키도 없이 전체 흐름이 동작해야 한다**는 것이 이 프로젝트의 타협 불가
조건이라, 규칙 엔진을 항상 곁에 둔다. 키가 없으면 처음부터 규칙 엔진으로 가고,
통화 중 API 호출이 실패하면(401/429/5xx/타임아웃) 그 턴만 규칙 엔진이 받아낸다.
통화가 API 오류로 끊기는 것이 가장 나쁜 실패다.

환경변수
--------
VOISSO_AGENT_PROVIDER  openai | anthropic | rule (기본 auto: 키 있는 것을 자동 선택)
VOISSO_AGENT_MODEL     대화 턴 모델
VOISSO_SUMMARY_MODEL   요약 모델
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from . import prompts
from .slots import SLOT_ORDER, Slots, extract_slots, is_meaningless

log = logging.getLogger("voisso.agent.engine")

# 프로바이더별 기본 모델은 providers.py 가 정한다.


@dataclass
class TurnDecision:
    """한 턴의 결정."""

    reply: str
    slots: dict[str, str] = field(default_factory=dict)
    ready_to_close: bool = False
    engine: str = "rule"
    error: str | None = None
    # 어르신이 되물어서 그 질문에 먼저 답한 턴인지. 규칙 엔진은 항상 False.
    answered_question: bool = False
    # 이번 발화에 알아들을 내용이 없었는지(잡음·혼잣말·오인식).
    caller_unclear: bool = False
    # 어르신이 말한 지형지물. where 와 별개로 담는다.
    landmark: str = ""
    # 어르신이 더 할 말이 없다고 했는지.
    caller_finished: bool = False
    # 슬롯에 안 맞지만 담당자가 알아야 할 추가 정보.
    note: str = ""


class RuleEngine:
    """키 없이 도는 규칙 기반 엔진.

    슬롯을 정규식으로 뽑고, 아직 빈 슬롯 중 하나를 골라 정해진 문장으로 묻는다.
    Claude 만큼 유연하진 않지만 '어르신 말을 받아주고 하나만 묻는다'는
    대화 원칙은 템플릿 수준에서 그대로 지킨다.
    """

    name = "rule"

    # 어르신이 한 말을 먼저 받아주는 맞장구.
    #
    # **매 턴 반드시 하나가 붙는다.** 어르신 대상 공공 서비스에서 사무적인
    # 응답은 그 자체로 실패다. 예전에는 random 으로 골랐는데 "예, 알겠습니다."
    # 같은 건조한 문구가 걸리면 공감이 사라졌고, 무작위라 재현도 안 됐다.
    # 지금은 턴 번호로 순환시켜 공감 표현이 빠지는 경우가 없게 하고,
    # 연속으로 같은 말이 나오지도 않게 한다.
    ACKS = (
        "아이고, 그러셨구나예.",
        "아이고, 얼마나 불편하셨겠습니까.",
        "예, 그러셨군요. 많이 답답하셨겠습니다.",
        "아이고, 고생이 많으십니다.",
    )

    # 마무리 인사에도 공감을 먼저 둔다.
    CLOSING_ACK = "고생 많으셨습니다."

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

    # 통화를 마치는 인사. **질문으로 끝내지 않는 유일한 예외** 중 하나다.
    CLOSING = "접수해 두겠습니다. 담당하는 곳으로 전달하겠습니다."

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

        # 몇 번째 응답인지 — 맞장구를 순환시키는 기준.
        turn_index = sum(1 for e in transcript if e.get("role") == "caller")

        unclear = bool(last_caller) and is_meaningless(last_caller)

        target = preview.next_slot()
        if target is None:
            reply = f"{self.CLOSING_ACK} {self.CLOSING}" if last_caller else self.CLOSING
            return TurnDecision(
                reply=reply, slots=merged, ready_to_close=True, engine=self.name
            )

        asked = slots.ask_counts.get(target, 0)
        options = self.QUESTIONS[target]
        question = options[min(asked, len(options) - 1)]

        # 첫 인사 직후(=아직 아무것도 못 들은 상태)에는 맞장구가 어색하다.
        if last_caller:
            ack = self.ACKS[(turn_index - 1) % len(self.ACKS)]
            reply = f"{ack} {question}"
        else:
            reply = question

        return TurnDecision(
            reply=reply,
            slots=merged,
            ready_to_close=False,
            engine=self.name,
            caller_unclear=unclear,
        )

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


# --------------------------------------------------------------------------
# 헬퍼
# --------------------------------------------------------------------------


# 매 턴 전체 이력을 보내면 통화가 길어질수록 입력 토큰이 제곱으로 는다.
# 슬롯 상태는 별도 메모(build_state_note)로 매번 전달되므로 오래된 발화는
# 대부분 중복이다. 다만 **최근 몇 턴은 반드시 남겨야 한다** — 되묻기(B)와
# 정정(C) 처리가 직전 문맥에 의존하기 때문이다.
DEFAULT_MAX_EXCHANGES = 3


def _max_exchanges() -> int:
    raw = os.getenv("VOISSO_MAX_HISTORY_EXCHANGES")
    if not raw:
        return DEFAULT_MAX_EXCHANGES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_EXCHANGES


def build_messages(
    transcript: list[dict[str, Any]], slots: Any = None
) -> list[dict[str, str]]:
    """통화 기록을 Messages API 형식으로 바꾼다.

    Messages API 는 user 로 시작해야 하는데 우리 통화는 상담원 인사로 시작한다.
    그래서 어르신의 첫 발화 이전 턴은 잘라낸다.

    이력이 길면 **최근 교환만 남긴다.** 잘린 앞부분의 사실관계는 슬롯 메모로
    이미 전달되므로 정보가 사라지지는 않는다.
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

    # 최근 교환만 남긴다. user 로 시작하도록 경계를 맞춘다.
    limit = _max_exchanges() * 2
    if len(messages) > limit:
        trimmed = messages[-limit:]
        while trimmed and trimmed[0]["role"] != "user":
            trimmed.pop(0)
        messages = trimmed or messages[-1:]
    return messages


def _last_caller_text(transcript: list[dict[str, Any]]) -> str:
    for entry in reversed(transcript):
        if entry.get("role") == "caller":
            return (entry.get("standard") or entry.get("dialect") or "").strip()
    return ""


def render_transcript(transcript: list[dict[str, Any]]) -> str:
    lines = []
    for entry in transcript:
        who = "어르신" if entry.get("role") == "caller" else "상담원"
        text = (entry.get("standard") or entry.get("dialect") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


_llm_provider: Any | None = None
_llm_key: tuple[str, str] | None = None
_rule_engine = RuleEngine()


def _select_provider():
    """VOISSO_AGENT_PROVIDER 에 따라 LLM 프로바이더를 고른다.

    기본은 auto — **키가 있는 것을 자동으로 쓴다.** 둘 다 없으면 None 이고
    호출자는 규칙 엔진으로 간다. 어떤 경우에도 예외를 던지지 않는다.
    """
    from .providers import AnthropicProvider, OpenAIProvider

    choice = (os.getenv("VOISSO_AGENT_PROVIDER") or "auto").strip().lower()

    if choice == "rule":
        return None
    if choice == "openai":
        candidate = OpenAIProvider()
        return candidate if candidate.available else None
    if choice == "anthropic":
        candidate = AnthropicProvider()
        return candidate if candidate.available else None

    # auto — OpenAI 를 먼저 본다. STT 와 키를 공유하므로 이미 있을 확률이 높다.
    for factory in (OpenAIProvider, AnthropicProvider):
        candidate = factory()
        if candidate.available:
            return candidate
    return None


def get_engines() -> tuple[Any | None, RuleEngine]:
    """(LLM 프로바이더, 폴백 규칙 엔진). LLM 은 쓸 수 없으면 None."""
    global _llm_provider, _llm_key

    choice = (os.getenv("VOISSO_AGENT_PROVIDER") or "auto").strip().lower()
    # 키가 바뀌면 프로바이더를 다시 만든다(재시작 없이 반영되도록).
    key = (
        choice,
        f"{bool(os.getenv('OPENAI_API_KEY'))}{bool(os.getenv('ANTHROPIC_API_KEY'))}"
        f"{os.getenv('VOISSO_AGENT_MODEL') or ''}",
    )
    if _llm_provider is not None and _llm_key == key:
        return _llm_provider, _rule_engine

    provider = _select_provider()
    _llm_provider, _llm_key = provider, key
    if provider is not None:
        log.info("대화 프로바이더: %s (%s)", provider.name, provider.turn_model)
    return provider, _rule_engine


def engine_status() -> dict[str, Any]:
    llm, _ = get_engines()
    error = llm.last_error if llm else None
    return {
        # 키가 있어도 호출이 실패하고 있으면 실질 엔진은 rule 이다.
        "primary": llm.name if (llm and not error) else "rule",
        "provider": llm.name if llm else None,
        "llm_available": llm is not None,
        "llm_error": error,
        # 이전 이름 호환 — 대시보드/헬스체크가 쓰고 있다.
        "claude_available": bool(llm and llm.name == "anthropic"),
        "claude_error": error if (llm and llm.name == "anthropic") else None,
        "turn_model": llm.turn_model if llm else None,
        "summary_model": llm.summary_model if llm else None,
        "fallback": "rule",
    }
