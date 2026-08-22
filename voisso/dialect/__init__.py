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
    convert,
    cues,
    entries,
    explain,
    load_lexicon,
    restricted_entries,
    rules,
    soften,
    source_counts,
)
from .llm import refine

__all__ = [
    "normalize",
    "to_dialect",
    "lexicon_size",
    "rule_count",
    "explain",
    "closing_cues",
    "officer_to_dialect",
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
