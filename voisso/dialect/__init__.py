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
    convert,
    entries,
    explain,
    load_lexicon,
    restricted_entries,
    rules,
    source_counts,
)
from .llm import refine

__all__ = [
    "normalize",
    "to_dialect",
    "lexicon_size",
    "rule_count",
    "explain",
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
