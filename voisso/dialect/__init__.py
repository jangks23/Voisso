"""Voisso 경북 방언 레이어 — 사투리 ↔ 표준어 양방향 변환.

경북 어르신이 사투리로 말해도 시스템이 알아듣고, 시스템도 사투리로 답하게 만드는
레이어다. 표준어만 아는 ARS가 어르신에게 벽이 되는 문제를 푼다.

정직성 고지
-----------
**우리는 방언 음향 모델을 학습시키지 않았다.** 48시간 해커톤에서 음향 모델
파인튜닝은 불가능하고, 시도하지도 않았다. 이 레이어가 하는 일은 두 가지뿐이다.

1. 출처가 기록된 어휘·어미 사전(``lexicon.json``) 기반 **결정론적 문자열 변환**
2. ``VOISSO_DIALECT_LLM=1`` 일 때만 켜지는 **선택적** LLM 다듬기 (``llm.py``)

사전에는 AI Hub 방언 코퍼스(dataSetSn=119)에서 온 항목이 **하나도 없다.**
이용정책 제5항이 승인 없는 제3자 제공을 금지하므로 공개 저장소에 올릴 수 없다.
자세한 근거는 ``SOURCES.md`` 와 ``docs/DATA_LICENSE.md`` §1 참조.

계약 인터페이스 (docs/CONTRACT.md §4)
-------------------------------------
    normalize(text: str) -> str     # 사투리 → 표준어 (STT 결과 교정)
    to_dialect(text: str) -> str    # 표준어 → 경북 사투리 (TTS 입력)
    lexicon_size() -> int

사용 예::

    >>> from voisso.dialect import normalize, to_dialect
    >>> to_dialect("접수해 드리겠습니다.")
    '접수해 드리겠습니더.'
    >>> normalize("물이 안 빠져가 큰일이라예")
    '물이 안 빠져서 큰일이에요'
"""

from __future__ import annotations

from .core import (
    LEXICON_PATH,
    STRENGTHS,
    LexiconError,
    admin_plain,
    callback_data,
    convert,
    cues,
    digit_names,
    entries,
    expand_noun_final,
    for_tts,
    explain,
    load_lexicon,
    noun_final,
    number_speech,
    restricted_entries,
    rules,
    short_form_limits,
    short_form_table,
    soften,
    source_counts,
)
from .llm import refine
from .risk import (
    RISK_PATH,
    consent_prompts,
    detect_consent,
    detect_pressure,
    detect_risk,
    detect_tense,
    load_risk_signals,
    pressure_data,
)

__all__ = [
    "normalize",
    "to_dialect",
    "lexicon_size",
    "rule_count",
    "explain",
    "closing_cues",
    "detect_risk",
    "detect_consent",
    "detect_pressure",
    "emergency_lines",
    "short_forms",
    "line",
    "detect_tense",
    "pressure_data",
    "load_risk_signals",
    "officer_to_dialect",
    "briefing_to_dialect",
    "callback_question",
    "deflection_line",
    "expand_noun_final",
    "for_tts",
    "number_speech",
    "soften",
    "admin_plain",
    "source_counts",
    "restricted_entries",
    "load_lexicon",
    "entries",
    "rules",
    "convert",
    "refine",
    "LexiconError",
    "LEXICON_PATH",
    "RISK_PATH",
    "STRENGTHS",
]


def normalize(text: str, *, use_llm: bool | None = None) -> str:
    """사투리 → 표준어. STT가 잘못 받아적은 방언 어휘를 교정한다.

    라우팅·요약이 표준어를 전제로 하므로 **재현율 우선**이다. 조금 과하게
    잡아도 다운스트림에는 이득이다.

    Args:
        text: STT가 받아적은 원문.
        use_llm: ``None`` 이면 환경변수(``VOISSO_DIALECT_LLM``)를 따른다.
            ``True`` 여도 키가 없거나 호출이 실패하면 규칙 결과를 그대로 쓴다.

    Returns:
        표준어 문장. 변환에 실패하면 입력을 그대로 돌려준다.
    """
    result = convert(text, "to_standard")
    return refine(text, result, "to_standard", use_llm=use_llm)


def to_dialect(text: str, *, use_llm: bool | None = None, strength: str = "polite") -> str:
    """표준어 → 경북 사투리. TTS에 넣기 전 단계다.

    어미 변환("~합니다"→"~합니더", "~할게요"→"~할게예")이 체감 차이의 대부분이다.
    과하게 바꾸면 희화화되므로 **정밀도 우선**으로, 어휘는 역변환 화이트리스트만
    건드린다. 어르신 대상 공공 서비스라 목표 화계는 '정중한 경북 말투'다.

    Args:
        text: 표준어 응답 문장.
        use_llm: ``None`` 이면 환경변수를 따른다.
        strength: ``"light"``(종결어미만) / ``"polite"``(기본) /
            ``"strong"``(데모용, 어휘까지). 계약 시그니처 ``to_dialect(text)`` 는
            ``"polite"`` 로 동작한다.

    Returns:
        경북 말투 문장. 변환에 실패하면 입력을 그대로 돌려준다.
    """
    result = convert(text, "to_dialect", strength=strength)
    return refine(text, result, "to_dialect", use_llm=use_llm)


def lexicon_size() -> int:
    """사전에 실린 어휘 대응쌍 개수. 어미 규칙 수는 :func:`rule_count` 로 따로 센다."""
    try:
        return len(entries())
    except LexiconError:
        return 0


def rule_count() -> int:
    """어미·문법 변환 규칙 개수."""
    try:
        return len(rules())
    except LexiconError:
        return 0


def closing_cues() -> dict[str, list[str]]:
    """통화 마무리 신호 목록 — P6 의 종료 판정용.

    슬롯이 다 찬 뒤 "더 하실 말씀 있으신교?" 를 물었을 때, 어르신의 대답이
    종료인지 계속인지 가르는 표현들이다. 어르신이 "없다"를 말하는 방식은
    아주 다양해서(없어예 / 됐어예 / 괘안타 / 그기 다라예 / 끝이라예 …)
    이걸 못 알아들으면 통화가 끝나지 않는다.

    Returns:
        ``{"closing_negative": [...], "closing_positive": [...]}``
        사투리형과 표준어형이 함께 들어 있다. :func:`normalize` 전후 어느 쪽에
        매칭해도 걸리도록 한 것이다.

    사용 예::

        cues = closing_cues()
        said = normalize(caller_text)
        if any(c in said or c in caller_text for c in cues["closing_positive"]):
            ...  # 계속 듣는다 (긍정을 먼저 본다 — 놓치면 민원을 잃는다)
        elif any(c in said or c in caller_text for c in cues["closing_negative"]):
            ...  # 담당자 연결로 넘어간다
    """
    try:
        return {k: list(v) for k, v in cues().items()}
    except LexiconError:
        return {"closing_negative": [], "closing_positive": []}


def officer_to_dialect(text: str) -> str:
    """담당자가 쓴 표준어를 어르신이 들을 경북 말투로. **핸드오프·콜백 브리핑 공용.**

    계약서 5-B(담당자 핸드오프)·5-C(진행 안내 콜백)에서 부르는 단 하나의 함수다.
    두 가지를 한 번에 처리한다.

    1. :func:`soften` — 공문체 낱말을 쉬운 말로 ("회신"→"연락", "이첩"→"넘겨")
    2. :func:`to_dialect` 의 ``strength="light"`` — **종결어미만** 바꾼다

    ``strength="light"`` 인 이유가 핵심이다. 기본값 ``"polite"`` 는 어휘까지 역변환해서
    "최대한 **퍼뜩** 처리하겠습니더", "**마이** 불편하셨겠습니더" 같은 결과를 만든다.
    AI 가 제 목소리로 말할 때는 정겹지만, **공무원의 공식 답변으로는 희화화된다.**
    담당자의 낱말은 그대로 두고 말끝만 경북으로 바꾸는 편이 정중하고 안전하다.

    변환하지 않는 것이 어색하게 변환하는 것보다 낫다.

    Args:
        text: 담당자가 입력한 표준어 문장.

    Returns:
        어르신에게 보여 줄 경북 말투 문장.
        계약서 5-B에 따라 원문(``standard``)과 이 결과(``dialect``)를 **둘 다** 저장하라.

    사용 예::

        >>> officer_to_dialect("해당 건은 검토 후 회신드리겠습니다.")
        '말씀하신 건은 살펴보고 연락드리겠습니더.'
        >>> officer_to_dialect("많이 불편하셨겠습니다. 최대한 빨리 처리하겠습니다.")
        '많이 불편하셨겠습니더. 최대한 빨리 처리하겠습니더.'
    """
    return to_dialect(soften(text), strength="light")


def briefing_to_dialect(text: str) -> str:
    """담당자가 쓴 진행 상황을 **AI 가 읽어 줄** 경북 말투로. (계약서 5-C)

    핸드오프(:func:`officer_to_dialect`)와 한 단계 다르다. 브리핑은 **소리 내어 읽는다.**
    공문은 "현장 확인 완료." 처럼 명사로 끝나는데, 이걸 그대로 읽으면 전화가 아니라
    공문 낭독이 된다. 그래서 문장 종결형으로 먼저 편다.

    1. :func:`expand_noun_final` — "확인 완료." → "확인 다 했습니다."
    2. :func:`soften` — "준설"→"바닥 흙 파내는 작업", "착공"→"공사 시작"
    3. :func:`to_dialect` ``strength="light"`` — 종결어미만 경북으로

    **이 함수는 내용을 만들지 않는다.** 담당자가 쓴 말을 바꿔 말할 뿐, 처리 결과·일정·
    가능 여부를 생성하지 않는다 (계약서 5-C 절대 규칙). 브리핑에 없는 답은 여기서도 안 나온다.

    호출한 쪽은 원문(``standard``)과 이 결과(``dialect``)를 **둘 다** 저장해야 한다.
    담당자가 "내가 쓴 대로 전달됐는가" 를 확인할 수 있어야 하기 때문이다.

    사용 예::

        >>> briefing_to_dialect("현장 확인 완료. 이번 주 내 배수관 준설 예정입니다.")
        '현장 확인 다 했습니더. 이번 주 내 배수관 바닥 흙 파내는 작업 예정입니더.'
    """
    return to_dialect(soften(expand_noun_final(text)), strength="light")


def callback_question(text: str) -> dict[str, object]:
    """어르신의 추가 질문을 AI 가 답해도 되는지 가른다. (계약서 5-C 절대 규칙)

    **AI 는 담당자가 쓴 내용만 전달한다.** 브리핑에 없는 답을 지어내면 그것은
    행정 약속이 된다. 그래서 질문을 두 갈래로 나눈다.

    - ``"relay"``      — 새 정보를 요구한다. **AI 가 답하면 안 된다.** 받아 적어 넘긴다.
    - ``"answerable"`` — 이미 확정된 사실 확인(접수번호·부서명). 답해도 된다.

    **애매하면 ``"relay"`` 다.** 지어내는 것보다 넘기는 편이 언제나 낫다.

    Returns:
        ``{"verdict": "relay"|"answerable", "matched": [...], "reason": "...",
           "suggested_reply": "..."}``
        ``suggested_reply`` 는 ``relay`` 일 때만 채워진다 (사투리 변환까지 마친 문장).

    사용 예::

        >>> callback_question("그라믄 언제 됩니꺼?")["verdict"]
        'relay'
        >>> callback_question("접수번호가 몇 번이라예?")["verdict"]
        'answerable'
    """
    try:
        data = callback_data()
        standard = normalize(text or "")
        def hits(key: str) -> list[str]:
            return [p for p in data.get(key, []) if p and (p in (text or "") or p in standard)]

        relay, answer = hits("must_relay"), hits("answerable")
        # 새 정보 요구가 하나라도 있으면 넘긴다. 확인 질문과 겹쳐도 마찬가지다.
        if relay:
            return {
                "verdict": "relay",
                "matched": relay,
                "reason": f"새 정보를 요구하는 표현({', '.join(repr(m) for m in relay[:3])})이 있다. "
                          "브리핑에 없는 답을 지어내면 행정 약속이 된다.",
                "suggested_reply": deflection_line(),
            }
        if answer:
            return {
                "verdict": "answerable",
                "matched": answer,
                "reason": "이미 확정된 사실 확인이라 답해도 된다.",
                "suggested_reply": "",
            }
        return {
            "verdict": "relay",
            "matched": [],
            "reason": "확정된 사실 확인으로 보이지 않는다. 애매하면 넘기는 쪽이 안전하다.",
            "suggested_reply": deflection_line(),
        }
    except LexiconError:
        return {"verdict": "relay", "matched": [], "reason": "사전을 읽지 못했다 — 안전 쪽으로 넘긴다",
                "suggested_reply": ""}


def deflection_line(index: int = 0) -> str:
    """브리핑에 없는 것을 물었을 때 쓸 문장 (사투리 변환까지 마친 것).

    계약서 5-C: "모르는 것은 '담당자에게 여쭤보고 다시 연락드릴게예' 로 넘긴다."
    """
    try:
        lines = callback_data().get("deflection", [])
        if not lines:
            return "담당자에게 여쭤보고 다시 연락드릴게예."
        return briefing_to_dialect(lines[index % len(lines)])
    except LexiconError:
        return "담당자에게 여쭤보고 다시 연락드릴게예."


def emergency_lines() -> dict[str, list[str]]:
    """119 연결 확인 흐름에서 쓸 문장들 — **사투리 변환까지 마친 것**.

    다급한 사람에게는 짧게 말해야 한다. 긴 문장은 안 들린다.

    Returns:
        ``{"ask": [...], "reask": [...], "confirmed": [...], "declined": [...], "button": [...]}``

    사용 예::

        lines = emergency_lines()
        say(lines["ask"][0])                       # "119 불러 드릴까예?"
        verdict = detect_consent(caller_text)
        if verdict["next"] == "connect":
            say(lines["confirmed"][0])
        elif verdict["next"] == "reask":
            say(lines["reask"][0])                 # 애매하면 한 번 더 묻는다
        else:
            say(lines["declined"][0])
    """
    try:
        return {key: [to_dialect(line) for line in lines]
                for key, lines in consent_prompts().items()}
    except Exception:  # noqa: BLE001
        return {"ask": ["119 불러 드릴까예?"], "reask": ["119 부를까예? 예 아니요로 말씀해 주이소."],
                "confirmed": ["지금 바로 연결하겠습니더. 끊지 마이소."],
                "declined": ["알겠습니더. 위험하시믄 바로 119 누르이소."],
                "button": ["화면에 뜬 큰 단추 한 번만 눌러 주이소."]}


def short_forms() -> dict[str, dict[str, str]]:
    """자막용 문구 모음 — **사투리 변환까지 마친 것**.

    P7 이 어르신 화면을 자막 오버레이로 바꿨다. **자막은 길면 안 읽힌다.**
    상황마다 짧은 판과 보통 판을 두고 부르는 쪽이 고른다.

    Returns:
        ``{용도: {"short": "...", "normal": "...", "standard_short": "...",
                  "standard_normal": "...", "category": "..."}}``

    사용 예::

        forms = short_forms()
        subtitle = forms["ask_where"]["short"]     # '어데신지 말씀해 주이소.'
        spoken   = forms["ask_where"]["normal"]    # '어느 마을이신지 말씀해 주이소.'
    """
    try:
        out: dict[str, dict[str, str]] = {}
        for item in short_form_table():
            out[item["id"]] = {
                "category": item["category"],
                "short": to_dialect(item["short"]),
                "normal": to_dialect(item["normal"]),
                "standard_short": item["short"],
                "standard_normal": item["normal"],
            }
        return out
    except LexiconError:
        return {}


def line(intent: str, style: str = "short") -> str:
    """자막 문구 하나를 꺼낸다. 없으면 빈 문자열.

    Args:
        intent: ``short_forms()`` 의 키 (``"ask_where"``, ``"ask_119"`` …).
        style: ``"short"`` (자막용) 또는 ``"normal"`` (음성·여유 있을 때).
    """
    return short_forms().get(intent, {}).get(style, "")
