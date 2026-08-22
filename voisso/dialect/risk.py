# -*- coding: utf-8 -*-
"""긴급도 판정용 위험 신호 탐지 (계약서 5-A).

**안전 직결 모듈이다.** 어르신이 위험을 알리는 표현을 놓치면 응급 상황이 "보통"으로
접수되고 뒤에 묻힌다. 그래서 설계 원칙이 하나다.

    놓치는 것이 과잉 탐지보다 훨씬 나쁘다. 애매하면 위험 쪽으로 분류한다.
    담당자가 등급을 내리는 건 쉽지만, 묻힌 응급은 되돌릴 수 없다.

**이 모듈은 등급을 제안할 뿐 결정하지 않는다.** 계약서 5-A의 판정 주체는 P6이다.
여기서 하는 일은 (1) 어떤 위험 표현이 나왔는지, (2) 왜 위험한지, (3) 등급을 올릴
근거가 있는지를 **증거와 함께** 돌려주는 것이다. 라우팅의 ``evidence`` 와 같은 원칙이다.
담당자가 "왜 응급인가"를 납득하지 못하면 그 표시는 무시된다.

사투리와 표준어를 **둘 다** 본다. ``normalize()`` 를 거치기 전이든 후든 걸린다.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

RISK_PATH = Path(__file__).parent / "risk_signals.json"

#: 높은 쪽이 위험하다. 계약서 5-A 의 4단계 중 이 모듈은 위 두 개만 제안한다.
LEVEL_ORDER = {"보통": 0, "중요": 1, "응급": 2}

#: 실제로 악화가 진행 중임을 뜻하는 신호. 이것만 단독으로 등급을 올릴 수 있다.
#: "자꾸"(continuing)는 뺐다 — "물이 자꾸 고인다"는 만성 불편이지 급성 위험이 아니다.
#: 그걸 응급으로 올리면 진짜 응급이 묻힌다. 늑대소년이 되면 표시 자체가 무시된다.
_PROGRESSION = {"progression", "increasing"}
#: 사람이 관련됐다는 신호. **상황 신호와 겹칠 때만** 등급을 올린다.
_PERSON = {"person-at-risk", "immediacy"}
#: 실제 사고 상황을 뜻하는 분류. "혼자 계신다"만으로는 응급이 아니다.
_HAZARD_CATEGORIES = {"침수·물", "붕괴·구조", "화재·가스", "고립·부상"}


@lru_cache(maxsize=1)
def load_risk_signals() -> dict[str, Any]:
    try:
        with RISK_PATH.open(encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        log.exception("위험 신호 사전을 읽지 못했다 — 탐지를 건너뛴다")
        return {"signals": [], "escalators": [], "ambiguous": [], "admin_context": []}


def _hits(patterns: list[str], *texts: str) -> str | None:
    """패턴 중 하나라도 걸리면 그 패턴을 돌려준다. 부분 문자열 매칭이다."""
    for pattern in patterns:
        for text in texts:
            if pattern and pattern in text:
                return pattern
    return None


def detect_risk(text: str, *, standard: str | None = None) -> dict[str, Any]:
    """위험 신호를 찾아 **근거와 함께** 돌려준다.

    Args:
        text: 어르신 발화 원문(사투리 그대로도 된다).
        standard: :func:`~voisso.dialect.normalize` 를 거친 표준어. 주면 둘 다 본다.
            생략하면 내부에서 정규화한다.

    Returns:
        딕셔너리::

            {
              "level": "응급" | "중요" | "보통",   # 제안 등급. 결정은 P6 이 한다
              "reason": "판정 근거 한 문장",       # 계약서 5-A 의 urgency.reason 에 그대로 쓸 수 있다
              "signals": ["침수 진행 중", ...],    # urgency.signals 에 그대로
              "safety_referral": {"number": "119", "label": "소방·구조"} | None,
              "matched": [ {...상세...} ],         # 어떤 표현이 왜 걸렸는지
              "escalators": [ {...} ],             # 등급을 올린 근거
              "ambiguous": [ {...} ],              # 일상 강조일 수 있다는 단서
              "admin_context": bool,               # 행정 문의 맥락으로 보이는가
            }

    이 함수는 **예외를 던지지 않는다.** 실패하면 ``level="보통"`` 과 빈 근거를 돌려준다.
    안전 판정이 통화를 끊게 두지 않는다.
    """
    empty = {
        "level": "보통", "reason": "위험 신호 없음", "signals": [],
        "safety_referral": None, "matched": [], "escalators": [],
        "ambiguous": [], "admin_context": False,
    }
    if not text or not text.strip():
        return empty

    try:
        if standard is None:
            from .core import convert
            standard = convert(text, "to_standard")
        data = load_risk_signals()

        matched: list[dict[str, Any]] = []
        for signal in data.get("signals", []):
            hit = _hits(signal.get("patterns", []), text, standard)
            if hit:
                matched.append({
                    "id": signal["id"], "category": signal["category"],
                    "level": signal["level"], "standard": signal["standard"],
                    "why": signal["why"], "referral": signal.get("referral"),
                    "matched_text": hit,
                })

        escalators: list[dict[str, str]] = []
        for esc in data.get("escalators", []):
            hit = _hits(esc.get("patterns", []), text, standard)
            if hit:
                escalators.append({"id": esc["id"], "label": esc["label"], "matched_text": hit})

        ambiguous: list[dict[str, str]] = []
        for amb in data.get("ambiguous", []):
            hit = _hits(amb.get("patterns", []), text, standard)
            if hit:
                ambiguous.append({
                    "label": amb["label"], "matched_text": hit,
                    "why": amb["why"], "disambiguate": amb["disambiguate"],
                })

        admin = bool(_hits(data.get("admin_context", []), text, standard))
        return _decide(matched, escalators, ambiguous, admin)
    except Exception:  # noqa: BLE001 - 안전 판정이 통화를 끊게 두지 않는다
        log.exception("위험 신호 탐지 실패 — 보통으로 돌려준다")
        return empty


def _decide(matched, escalators, ambiguous, admin) -> dict[str, Any]:
    """등급과 근거 문장을 만든다. 올리는 쪽으로만 움직인다."""
    if not matched:
        reason = "위험 신호 없음"
        if ambiguous:
            reason = (f"'{ambiguous[0]['matched_text']}' 가 나왔지만 구체적 위험 표현이 없다 — "
                      "일상 강조로 보인다")
        return {
            "level": "보통", "reason": reason, "signals": [], "safety_referral": None,
            "matched": [], "escalators": escalators, "ambiguous": ambiguous,
            "admin_context": admin,
        }

    base = max(matched, key=lambda m: LEVEL_ORDER[m["level"]])
    level = base["level"]

    # 실제 사고 상황을 뜻하는 신호. "혼자 계신다"는 그 자체로 사고가 아니다.
    situation = [m for m in matched
                 if m["category"] in _HAZARD_CATEGORIES and m["id"] != "alone-elderly"]
    progression = [e for e in escalators if e["id"] in _PROGRESSION]
    person = [e for e in escalators if e["id"] in _PERSON]
    alone = [m for m in matched if m["id"] == "alone-elderly"]

    # 중요 → 응급 상승 조건. 올리는 쪽으로만 움직이되 근거를 요구한다.
    #   ① 악화가 진행 중이다 ("점점 심해진다", "번지고 있다")
    #   ② 사람이 관련된 상황 신호가 있다 (고령 1인 + 실제 사고)
    # "자꾸 고인다"(만성)는 여기에 걸리지 않는다 — 그건 중요다.
    raised, escalating = False, []
    if level == "중요":
        if progression:
            level, raised, escalating = "응급", True, progression
        elif situation and (person or alone):
            level, raised, escalating = "응급", True, (person or [])
            if alone:
                escalating = escalating + [{"id": "alone-elderly", "label": "고령 1인 거주",
                                            "matched_text": alone[0]["matched_text"]}]

    referral = next((m["referral"] for m in matched
                     if m["referral"] and LEVEL_ORDER[m["level"]] >= LEVEL_ORDER[base["level"]]),
                    None)
    if level == "응급" and referral is None:
        referral = next((m["referral"] for m in matched if m["referral"]), None)

    categories = list(dict.fromkeys(m["category"] for m in matched))
    quoted = ", ".join(f"'{m['matched_text']}'" for m in matched[:3])
    reason = f"{'·'.join(categories)} 위험 표현({quoted})이 나왔다. {base['why']}"
    if raised:
        labels = ", ".join(dict.fromkeys(e["label"] for e in escalating))
        reason += f" 여기에 {labels} 신호가 겹쳐 등급을 올렸다."
    if ambiguous and level == "응급":
        reason += " (일상 강조 표현도 함께 있으나 구체적 위험 표현이 우선한다.)"

    return {
        "level": level,
        "reason": reason,
        "signals": [m["standard"] for m in matched],
        "safety_referral": ({"number": referral, "label": "소방·구조" if referral == "119" else "신고"}
                            if level == "응급" and referral else None),
        "matched": matched,
        "escalators": escalators,
        "ambiguous": ambiguous,
        "admin_context": admin,
    }
