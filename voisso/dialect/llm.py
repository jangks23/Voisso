"""선택적 LLM 다듬기 — 규칙 변환 결과의 자연스러움만 손본다.

**기본은 꺼져 있다.** 켜려면 두 조건이 모두 필요하다.

    export ANTHROPIC_API_KEY=sk-ant-...
    export VOISSO_DIALECT_LLM=1

기본 OFF인 이유는 두 가지다.

1. **지연** — 전화 통화는 턴당 지연이 즉시 체감된다. 규칙 변환은 수 ms, LLM은 초 단위다.
2. **재현성** — 호출마다 결과가 달라지면 왕복 테스트가 불안정해지고,
   담당자에게 전달되는 민원 카드의 문장도 매번 달라진다.

그래서 LLM은 **0→1이 아니라 1→1.2** 역할만 한다. 규칙 변환을 먼저 돌리고,
그 결과를 넘겨 어색한 부분만 다듬게 한다. 실패·타임아웃·패키지 없음은
전부 규칙 결과로 조용히 폴백한다. 이 레이어가 통화를 끊게 두지 않는다.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache

from .core import explain

log = logging.getLogger(__name__)

#: 다듬기용 모델. 환경변수로 덮어쓸 수 있다.
DEFAULT_MODEL = "claude-opus-5"
#: 전화 통화용이라 짧게 잡는다. 넘기면 규칙 결과를 그대로 쓴다.
TIMEOUT_SECONDS = 6.0
MAX_TOKENS = 1024

_SYSTEM = """\
너는 경상북도청 민원 전화 시스템의 한국어 문장 교정기다.
이미 규칙 기반으로 변환된 문장을 받아서, **어색한 부분만** 자연스럽게 다듬는다.

지켜야 할 것:
- 의미를 바꾸지 마라. 정보를 더하거나 빼지 마라.
- 부서명, 숫자, 전화번호, 사람 이름, 주소는 **한 글자도 바꾸지 마라.**
- 화계를 유지하라. 정중한 존댓말이 들어오면 정중한 존댓말로 나가야 한다.
- 상대는 경북 지역 어르신이다. 과장된 사투리나 희화화된 말투를 쓰지 마라.
  목표는 '정중한 경북 말투'지, 코미디 프로그램의 사투리가 아니다.
- 바꿀 곳이 없으면 입력을 그대로 돌려줘라.

출력은 **교정된 문장 한 줄만** 써라. 설명, 따옴표, 앞뒤 말을 붙이지 마라.\
"""

_DIRECTION_HINT = {
    "to_standard": "경북 사투리를 표준어로 옮긴 결과다. 표준어로서 자연스러운지 봐라.",
    "to_dialect": "표준어를 경북 사투리로 옮긴 결과다. 경북 어르신이 들어서 자연스러운지 봐라.",
}


def enabled(use_llm: bool | None = None) -> bool:
    """LLM 경로를 쓸지 판단한다. 명시 인자 > 환경변수 순."""
    if use_llm is False:
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    if use_llm is True:
        return True
    return os.environ.get("VOISSO_DIALECT_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _client():
    """anthropic 클라이언트. 패키지가 없으면 None (규칙 경로로 폴백)."""
    try:
        import anthropic
    except ImportError:
        log.info("anthropic 패키지가 없다 — 방언 변환은 규칙 경로로만 동작한다")
        return None
    try:
        return anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=0)
    except Exception:  # noqa: BLE001
        log.exception("anthropic 클라이언트 생성 실패 — 규칙 경로로 폴백")
        return None


def _few_shot(source: str, direction: str) -> str:
    """이 문장에 실제로 적용된 사전 항목만 발췌한다.

    사전 300여 항목을 매번 통째로 넣으면 토큰 낭비다. 걸린 것만 최대 20개 넣는다.
    """
    hits = explain(source, direction)[:20]
    if not hits:
        return ""
    lines = [f"- {h['from']} → {h['to']}" + (f"  ({h['desc']})" if h["desc"] else "") for h in hits]
    return "\n\n이 문장에 적용된 사전 항목이다. 참고만 하고, 이미 반영돼 있으면 그대로 둬라.\n" + "\n".join(lines)


_DIGITS = re.compile(r"\d+")


def _safe(rule_result: str, candidate: str) -> bool:
    """LLM 결과를 채택해도 되는지. 하나라도 어긋나면 규칙 결과를 쓴다."""
    if not candidate or "\n" in candidate.strip():
        return False
    # 길이가 크게 흔들리면 문장을 새로 쓴 것이다.
    if not (0.5 * len(rule_result) <= len(candidate) <= 2.0 * len(rule_result) + 20):
        return False
    # 숫자(전화번호·번지수)는 한 글자도 사라지면 안 된다.
    return _DIGITS.findall(rule_result) == _DIGITS.findall(candidate)


@lru_cache(maxsize=512)
def _call(source: str, rule_result: str, direction: str, model: str) -> str:
    client = _client()
    if client is None:
        return rule_result

    import anthropic

    prompt = (
        f"{_DIRECTION_HINT.get(direction, '')}\n\n"
        f"원문: {source}\n"
        f"규칙 변환 결과: {rule_result}"
        f"{_few_shot(source, direction)}"
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM,
            output_config={"effort": "low"},  # 통화 지연을 줄인다
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as exc:
        log.warning("방언 LLM 다듬기 API 오류(%s) — 규칙 결과 사용", exc.status_code)
        return rule_result
    except anthropic.APIConnectionError:
        log.warning("방언 LLM 다듬기 연결 실패/타임아웃 — 규칙 결과 사용")
        return rule_result
    except Exception:  # noqa: BLE001 - 어떤 이유로도 통화를 끊지 않는다
        log.exception("방언 LLM 다듬기 실패 — 규칙 결과 사용")
        return rule_result

    if getattr(response, "stop_reason", None) == "refusal":
        log.warning("방언 LLM 다듬기가 거부됨 — 규칙 결과 사용")
        return rule_result

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not _safe(rule_result, text):
        log.info("방언 LLM 결과가 검증을 통과하지 못했다 — 규칙 결과 사용")
        return rule_result
    return text


def refine(source: str, rule_result: str, direction: str, *, use_llm: bool | None = None) -> str:
    """규칙 변환 결과를 LLM으로 다듬는다. 꺼져 있거나 실패하면 그대로 돌려준다.

    Args:
        source: 변환 전 원문.
        rule_result: 규칙 기반 변환 결과. **폴백 값이기도 하다.**
        direction: ``"to_standard"`` 또는 ``"to_dialect"``.
        use_llm: ``None`` 이면 환경변수를 따른다.
    """
    if not rule_result or not rule_result.strip():
        return rule_result
    if not enabled(use_llm):
        return rule_result
    model = os.environ.get("VOISSO_DIALECT_LLM_MODEL", DEFAULT_MODEL)
    return _call(source, rule_result, direction, model)
