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


def detect_risk(text: str, *, standard: str | None = None,
                history: list[str] | None = None) -> dict[str, Any]:
    """위험 신호를 찾아 **근거와 함께** 돌려준다.

    Args:
        text: 어르신 발화 원문(사투리 그대로도 된다).
        standard: :func:`~voisso.dialect.normalize` 를 거친 표준어. 주면 둘 다 본다.
            생략하면 내부에서 정규화한다.
        history: **이전 턴들의 어르신 발화.** 주면 재촉 반복을 함께 본다.
            "빨리와요!!!" 를 세 번 되풀이하는 상황은 단발 문장만 봐서는 절대 잡히지 않는다.

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

        # 위험 표현은 **통화 전체**에서 찾는다. 어르신이 1턴에 "물이 차올라예" 라 하고
        # 이후 "빨리와요"만 되풀이하면, 현재 문장만 봐서는 위험이 사라진 것처럼 보인다.
        # 실사용 결함이 정확히 이 지점이었다.
        from .core import convert as _convert
        pairs: list[tuple[str, str]] = [(t, _convert(t, "to_standard"))
                                        for t in (history or []) if t and t.strip()]
        pairs.append((text, standard))
        flat: list[str] = [part for pair in pairs for part in pair]

        matched: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for signal in data.get("signals", []):
            hit = _hits(signal.get("patterns", []), *flat)
            if hit and signal["id"] not in seen_ids:
                seen_ids.add(signal["id"])
                matched.append({
                    "id": signal["id"], "category": signal["category"],
                    "level": signal["level"], "standard": signal["standard"],
                    "why": signal["why"], "referral": signal.get("referral"),
                    "matched_text": hit,
                })

        escalators: list[dict[str, str]] = []
        for esc in data.get("escalators", []):
            hit = _hits(esc.get("patterns", []), *flat)
            if hit:
                escalators.append({"id": esc["id"], "label": esc["label"], "matched_text": hit})

        ambiguous: list[dict[str, str]] = []
        for amb in data.get("ambiguous", []):
            hit = _hits(amb.get("patterns", []), *flat)
            if hit:
                ambiguous.append({
                    "label": amb["label"], "matched_text": hit,
                    "why": amb["why"], "disambiguate": amb["disambiguate"],
                })

        admin = bool(_hits(data.get("admin_context", []), *flat))
        pressure = detect_pressure(list(history or []) + [text])
        # 시제는 **가장 최근 발화**로 본다. 앞 턴이 과거여도 지금 진행 중일 수 있다.
        tense = detect_tense(text)
        return _decide(matched, escalators, ambiguous, admin, pressure, tense)
    except Exception:  # noqa: BLE001 - 안전 판정이 통화를 끊게 두지 않는다
        log.exception("위험 신호 탐지 실패 — 보통으로 돌려준다")
        return empty


def _decide(matched, escalators, ambiguous, admin, pressure=None, tense=None) -> dict[str, Any]:
    """등급과 근거 문장을 만든다. 올리는 쪽으로만 움직인다."""
    pressure = pressure or {"escalate": False, "signals": [], "reason": "", "strength": None}
    tense = tense or {"verdict": "불명", "progress": [], "past": [], "past_ending": []}

    if not matched:
        # 상황 신호가 없어도 다급함이 반복되면 그냥 두면 안 된다.
        # 다만 무엇이 위험한지 모르므로 응급까지는 올리지 않는다 — 119 안내는 근거가 필요하다.
        if pressure["escalate"]:
            return {
                "level": "중요",
                "reason": f"구체적 위험 표현은 없지만 다급함이 반복된다. {pressure['reason']}",
                "signals": pressure["signals"], "safety_referral": None,
                "matched": [], "escalators": escalators, "ambiguous": ambiguous,
                "admin_context": admin, "pressure": pressure, "tense": tense,
            }
        reason = "위험 신호 없음"
        if ambiguous:
            reason = (f"'{ambiguous[0]['matched_text']}' 가 나왔지만 구체적 위험 표현이 없다 — "
                      "일상 강조로 보인다")
        return {
            "level": "보통", "reason": reason, "signals": [], "safety_referral": None,
            "matched": [], "escalators": escalators, "ambiguous": ambiguous,
            "admin_context": admin, "pressure": pressure, "tense": tense,
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
        elif pressure["escalate"]:
            # 상황 신호 + 다급함 반복. 실사용 결함이 정확히 이 조합이었다.
            level, raised = "응급", True
            escalating = [{"id": "pressure", "label": "다급함 반복",
                           "matched_text": (pressure["matched"] or [{}])[0].get("matched_text", "")}]
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
    # 과거 신고를 응급으로 두면 진짜 응급이 묻힌다. 다만 내리는 조건은 아주 좁게 잡는다.
    lowered = False
    if (level == "응급" and tense["verdict"] == "과거" and not pressure["escalate"]
            and matched and all(m["id"] in _TENSE_DOWNGRADABLE for m in matched)):
        level, lowered = "중요", True

    if ambiguous and level == "응급":
        reason += " (일상 강조 표현도 함께 있으나 구체적 위험 표현이 우선한다.)"
    if pressure["escalate"] and pressure.get("signals"):
        reason += f" {pressure['reason']}"
    if lowered:
        reason += (f" 다만 과거 표현({', '.join(tense['past'])})과 과거 서술어가 함께 있어 "
                   "이미 지나간 일로 보고 한 단계 내렸다. 진행 중이면 다시 올려야 한다.")
    elif tense["verdict"] == "진행" and level == "응급":
        reason += f" 진행 중 신호({', '.join(tense['progress'])})가 있다."

    return {
        "level": level,
        "reason": reason,
        "signals": [m["standard"] for m in matched] + list(pressure.get("signals") or []),
        "safety_referral": ({"number": referral, "label": "소방·구조" if referral == "119" else "신고"}
                            if level == "응급" and referral else None),
        "matched": matched,
        "escalators": escalators,
        "ambiguous": ambiguous,
        "admin_context": admin,
        "pressure": pressure,
        "tense": tense,
    }

# --------------------------------------------------------------------------- #
# 재촉·다급함 (반복이 신호다)
# --------------------------------------------------------------------------- #

_STRENGTH_ORDER = {"약": 0, "중": 1, "강": 2}


def pressure_data() -> dict[str, Any]:
    """재촉 표현 사전 (표현·가산신호·임계값)."""
    return load_risk_signals().get("pressure", {})


@lru_cache(maxsize=1)
def _intensity_patterns() -> list[tuple[str, str, Any]]:
    import re
    out = []
    for item in pressure_data().get("intensity", []):
        try:
            out.append((item["id"], item["label"], re.compile(item["regex"])))
        except Exception:  # noqa: BLE001 - 사전 오타가 통화를 죽이지 않는다
            log.warning("재촉 가산 신호 정규식 오류: %s", item.get("id"))
    return out


def detect_pressure(turns: str | list[str]) -> dict[str, Any]:
    """어르신의 재촉·다급함을 센다. **반복이 신호다.**

    실사용 결함에서 나온 기능이다. 집에 물이 차오르는 민원인이 "빨리와요!!!" 를 세 번
    반복했는데 시스템이 긴급도를 올리지 못했다. 단발 문장만 보면 이걸 잡을 수 없다.

    강도 설계가 핵심이다. "큰일이라예"는 경북에서 아주 흔한 일상 강조라 1회로 올리면
    오탐이 쏟아지고, **오탐이 쏟아지면 진짜 응급이 묻힌다.** 그래서 표현마다 단독 강도를
    두고 반복 횟수로 판정한다.

    Args:
        turns: 어르신 발화 하나 또는 **여러 턴의 목록**. 목록을 주어야 반복을 센다.

    Returns:
        딕셔너리::

            {
              "escalate": True,             # 긴급도를 올려야 하는가
              "strength": "강"|"중"|"약",   # 관측된 최고 단독 강도
              "count": 3,                   # 재촉 표현이 나온 횟수(턴 기준)
              "distinct": 1,                # 서로 다른 표현 수
              "repeated_turns": 3,          # 거의 같은 말을 되풀이한 턴 수
              "intensity": [...],           # 느낌표 반복 등 가산 신호
              "reason": "...",              # urgency.reason 에 이어 붙일 수 있다
              "signals": ["재촉 3회 반복"], # urgency.signals 에 그대로
              "matched": [...]              # 어느 턴에서 무엇이 걸렸는지
            }

    예외를 던지지 않는다. 실패하면 ``escalate=False`` 를 돌려준다.
    """
    empty = {"escalate": False, "strength": None, "count": 0, "distinct": 0,
             "repeated_turns": 0, "intensity": [], "reason": "재촉 표현 없음",
             "signals": [], "matched": []}
    if not turns:
        return empty
    texts = [turns] if isinstance(turns, str) else [t for t in turns if t and t.strip()]
    if not texts:
        return empty

    try:
        data = pressure_data()
        expressions = data.get("expressions", [])
        thresholds = data.get("thresholds", {"강": 1, "중": 2, "약": 3})

        matched: list[dict[str, Any]] = []
        for index, text in enumerate(texts):
            # 정규화 전후를 둘 다 본다. 사투리 그대로 들어와도 걸려야 한다.
            from .core import convert
            standard = convert(text, "to_standard")
            for expr in expressions:
                hit = _hits(expr.get("patterns", []), text, standard)
                if hit:
                    matched.append({
                        "turn": index, "id": expr["id"], "strength": expr["strength"],
                        "standard": expr["standard"], "note": expr["note"],
                        "matched_text": hit, "text": text,
                    })

        intensity = []
        for iid, label, pattern in _intensity_patterns():
            for index, text in enumerate(texts):
                if pattern.search(text):
                    intensity.append({"id": iid, "label": label, "turn": index})
                    break

        # 거의 같은 말을 되풀이했는가. 공백·문장부호를 지우고 비교한다.
        import re
        stripped = [re.sub(r"[\s!?.…~ㅠㅜ]+", "", t) for t in texts]
        repeated = sum(1 for i, a in enumerate(stripped)
                       if a and any(a == b for j, b in enumerate(stripped) if j != i))

        return _decide_pressure(matched, intensity, repeated, thresholds, len(texts))
    except Exception:  # noqa: BLE001 - 안전 판정이 통화를 끊게 두지 않는다
        log.exception("재촉 탐지 실패")
        return empty


def _decide_pressure(matched, intensity, repeated, thresholds, turn_count) -> dict[str, Any]:
    if not matched:
        return {"escalate": False, "strength": None, "count": 0, "distinct": 0,
                "repeated_turns": repeated, "intensity": intensity,
                "reason": "재촉 표현 없음", "signals": [], "matched": []}

    strongest = max(matched, key=lambda m: _STRENGTH_ORDER[m["strength"]])["strength"]
    turns_with = len({m["turn"] for m in matched})
    distinct = len({m["id"] for m in matched})

    # 가산 신호는 횟수 1회분으로 친다. 느낌표 반복과 되풀이는 목소리가 높아졌다는 뜻이다.
    effective = turns_with + (1 if intensity else 0) + (1 if repeated >= 2 else 0)
    needed = thresholds.get(strongest, 2)
    escalate = effective >= needed

    parts = [f"재촉 표현이 {turns_with}개 턴에서 나왔다"]
    if distinct > 1:
        parts.append(f"서로 다른 표현 {distinct}가지")
    if repeated >= 2:
        parts.append(f"같은 말을 {repeated}번 되풀이했다")
    if intensity:
        parts.append(", ".join(dict.fromkeys(i["label"] for i in intensity)))
    quoted = ", ".join(f"'{m['matched_text']}'" for m in matched[:3])
    reason = (f"{'. '.join(parts)}({quoted}). "
              f"단독 강도 '{strongest}' 기준 {needed}회에서 올린다 — "
              f"환산 {effective}회로 {'넘었다' if escalate else '아직 못 넘었다'}.")

    signals = []
    if escalate:
        signals.append(f"다급함 반복 {turns_with}회")
        if repeated >= 2:
            signals.append("같은 말 되풀이")
        if intensity:
            signals.append(intensity[0]["label"])

    return {
        "escalate": escalate, "strength": strongest, "count": turns_with,
        "distinct": distinct, "repeated_turns": repeated, "intensity": intensity,
        "reason": reason, "signals": signals, "matched": matched,
    }

# --------------------------------------------------------------------------- #
# 진행 여부 (과거 신고 vs 지금 위험)
# --------------------------------------------------------------------------- #

#: 시제로 등급을 내려도 되는 신호. 침수 계열만이다.
#: 불·가스·붕괴·부상은 과거형이어도 현장이 그대로일 수 있어 내리지 않는다.
_TENSE_DOWNGRADABLE = {"flood-ingress", "flood-filling", "flood-submerged",
                       "flood-overflow", "flood-washed-away"}


def detect_tense(text: str) -> dict[str, Any]:
    """진행 중인지 지나간 일인지 가르는 수식어를 찾는다.

    같은 "물이 들어온다" 라도 "어제 들어왔어예"(과거 피해 신고)와 "지금 들어와요"
    (지금 사람이 위험함)는 등급이 달라야 한다.

    Returns:
        ``{"progress": [...], "past": [...], "past_ending": [...], "verdict": "진행"|"과거"|"불명"}``

    ``"과거"`` 는 **과거 수식어와 과거 서술어가 함께 있고 진행 수식어가 없을 때만** 나온다.
    "어제부터 물이 들어옵니더" 는 어제가 붙어도 서술어가 현재형이라 ``"진행"`` 이 아닌
    ``"불명"`` 으로 두고 등급을 내리지 않는다. 내리는 판단은 보수적이어야 한다.
    """
    data = load_risk_signals().get("tense", {})
    found = {key: [p for p in data.get(key, []) if p and p in (text or "")]
             for key in ("progress", "past", "past_ending")}
    if found["progress"]:
        verdict = "진행"
    elif found["past"] and found["past_ending"]:
        verdict = "과거"
    else:
        verdict = "불명"
    return {**found, "verdict": verdict}

# --------------------------------------------------------------------------- #
# 119 연결 확인 — 긍정 / 부정 / 애매
# --------------------------------------------------------------------------- #

import re as _re

#: 문장부호·군말을 털어 낸다. 다급하면 "예!!" "어..." 처럼 들어온다.
_CLEAN = _re.compile(r'''[\s.,!?…~"'’”·ㅣㅜ]+''')


def consent_data() -> dict[str, Any]:
    """119 연결 확인용 응답 사전."""
    return load_risk_signals().get("consent", {})


def consent_prompts() -> dict[str, list[str]]:
    """119 연결 확인에 쓸 문장(표준어). :func:`~voisso.dialect.to_dialect` 를 태워 쓴다."""
    return load_risk_signals().get("consent_prompts", {})


def _short_match(cleaned: str, candidates: list[str]) -> str | None:
    """발화 **전체**가 짧은 응답과 같은가. 반복형("예예", "어어")도 인정한다.

    부분 문자열로 찾으면 안 된다. "예"가 "괜찮아예"(부정)에도 들어 있기 때문이다.
    """
    if not cleaned:
        return None
    for candidate in candidates:
        if cleaned == candidate:
            return candidate
        # "예예", "어어어" 처럼 되풀이한 경우
        if len(candidate) == 1 and cleaned == candidate * len(cleaned):
            return candidate
        if len(cleaned) <= len(candidate) * 3 and cleaned == candidate * (len(cleaned) // len(candidate)):
            return candidate
    return None


def detect_consent(text: str, *, standard: str | None = None) -> dict[str, Any]:
    """119 연결 물음에 대한 대답을 가른다. **애매를 부정으로 처리하지 않는다.**

    응급 시 AI 가 "119 불러 드릴까예?" 라고 묻고 어르신이 답한다. 다급하면 대답이
    아주 짧다 — "어", "야", "예". 이걸 놓치면 연결이 안 된다.

    Args:
        text: 어르신 대답 원문. 빈 문자열이면 **무응답**으로 본다.
        standard: 정규화한 표준어. 생략하면 내부에서 정규화한다.

    Returns:
        딕셔너리::

            {
              "verdict": "긍정" | "부정" | "애매",
              "confidence": "높음" | "낮음",
              "matched": {"positive": [...], "negative": [...], "unclear": [...]},
              "reason": "판정 근거",
              "next": "connect" | "stop" | "reask",   # P6 이 탈 경로
            }

    판정 규칙

    - 긍정만 걸리면 ``긍정``, 부정만 걸리면 ``부정``.
    - **둘 다 걸리면 애매다.** "아니 빨리 해 주이소" 처럼 부정어가 군말로 앞에 붙는
      경우가 실제로 흔하다. 단정하지 않고 한 번 더 묻는다.
    - 아무것도 안 걸리면 애매다. 동문서답·침묵 포함.
    - **애매를 부정으로 처리하면 위험하다.** 반드시 ``next="reask"`` 로 보낸다.
    """
    empty_reason = "무응답 — 대답이 없다"
    try:
        raw = text or ""
        if not raw.strip():
            return {"verdict": "애매", "confidence": "낮음",
                    "matched": {"positive": [], "negative": [], "unclear": []},
                    "reason": empty_reason, "next": "reask"}

        if standard is None:
            from .core import convert
            standard = convert(raw, "to_standard")
        data = consent_data()
        cleaned_raw = _CLEAN.sub("", raw)
        cleaned_std = _CLEAN.sub("", standard)

        positive: list[str] = []
        negative: list[str] = []
        unclear: list[str] = []

        # ⓪ "못 들었다"는 말은 긍정보다 먼저 본다.
        #    "다시 말해 주이소" 는 '해 주이소'를 품고 있어 그냥 두면 긍정으로 잡힌다.
        #    못 들었다는 말이 119 연결을 트리거하면 위험하다.
        for pattern in data.get("unclear_priority", []):
            if pattern and (pattern in raw or pattern in standard):
                return {"verdict": "애매", "confidence": "낮음",
                        "matched": {"positive": [], "negative": [], "unclear": [pattern]},
                        "reason": f"못 알아들으셨다는 표현({pattern!r})이다. 다시 여쭤본다.",
                        "next": "reask"}

        # ① 한 글자·짧은 응답 — 발화 전체가 같을 때만
        for cleaned in (cleaned_raw, cleaned_std):
            hit = _short_match(cleaned, data.get("positive_short", []))
            if hit and hit not in positive:
                positive.append(hit)
            hit = _short_match(cleaned, data.get("negative_short", []))
            if hit and hit not in negative:
                negative.append(hit)

        # ② 긴 표현 — 부분 문자열
        for key, bucket in (("positive_phrase", positive), ("negative_phrase", negative),
                            ("unclear_phrase", unclear)):
            for pattern in data.get(key, []):
                if pattern and (pattern in raw or pattern in standard) and pattern not in bucket:
                    bucket.append(pattern)

        matched = {"positive": positive, "negative": negative, "unclear": unclear}

        if positive and negative:
            return {"verdict": "애매", "confidence": "낮음", "matched": matched,
                    "reason": f"긍정({positive[0]!r})과 부정({negative[0]!r})이 함께 나왔다. "
                              "단정하지 않고 한 번 더 묻는다.",
                    "next": "reask"}
        if positive:
            return {"verdict": "긍정", "confidence": "높음", "matched": matched,
                    "reason": f"긍정 응답({', '.join(repr(p) for p in positive[:2])})", "next": "connect"}
        if negative:
            return {"verdict": "부정", "confidence": "높음", "matched": matched,
                    "reason": f"부정 응답({', '.join(repr(n) for n in negative[:2])})", "next": "stop"}
        if unclear:
            return {"verdict": "애매", "confidence": "낮음", "matched": matched,
                    "reason": f"판단을 미루는 표현({unclear[0]!r})이다. 한 번 더 묻는다.",
                    "next": "reask"}
        return {"verdict": "애매", "confidence": "낮음", "matched": matched,
                "reason": "긍정도 부정도 아니다(동문서답으로 보인다). 한 번 더 묻는다.",
                "next": "reask"}
    except Exception:  # noqa: BLE001 - 안전 판정이 통화를 끊게 두지 않는다
        log.exception("119 연결 확인 판정 실패 — 한 번 더 묻는 쪽으로 돌려준다")
        return {"verdict": "애매", "confidence": "낮음",
                "matched": {"positive": [], "negative": [], "unclear": []},
                "reason": "판정에 실패했다. 한 번 더 묻는다.", "next": "reask"}
