"""경상북도 시·군 식별 — 시군 소관 민원의 "다음 행동"을 구체화하기 위한 것.

## 왜 필요한가

가로등·주민등록·쓰레기 수거는 도청이 아니라 시·군이 한다. 여기까지는
concepts.py 가 판단한다. 하지만 상담원에게 "시군 소관입니다"라고만 말하면
어르신에게는 아무 도움이 안 된다. **어느 시군인지**까지 짚어야 다음 행동이 된다.

    "안동시청 민원실로 안내하세요"   ← 이게 다음 행동이다
    "시군 소관입니다"                ← 이건 아직 아니다

## 전화번호를 넣지 않은 이유

각 시·군 민원실 직통번호는 일부러 비워 뒀다.

1. 계약서 3절 — 가짜 전화번호를 만들지 않는다. 확인 못 한 번호를 자신 있게
   안내하는 것은 대표번호로 넘기는 것보다 나쁘다.
2. 번호는 바뀐다. 검증·갱신 책임이 없는 번호를 코드에 박으면 부채가 된다.
3. 경상북도청 대표번호 1522-0120 이 시·군 연결을 대신해 준다. 한 단계 더
   거치지만 틀리지 않는다.

나중에 실제 번호를 확인해 채우면 ``phone`` 만 넣으면 그대로 쓰인다.
그때도 출처와 확인 날짜를 함께 남길 것.

## 군위군

군위군은 2023년 7월 1일 대구광역시로 편입되어 **경상북도 관할이 아니다.**
옛 자료(도청 홈페이지 시군 링크 페이지 포함)에는 아직 남아 있을 수 있어,
따로 감지해서 대구광역시로 안내한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tokenizer import normalize

PROVINCE_MAIN_PHONE = "1522-0120"
PROVINCE_PHONE_LABEL = "경상북도청 대표번호(시·군 연결 요청 가능)"


@dataclass(frozen=True)
class Region:
    name: str          # 공식 명칭 (예: "안동시")
    stem: str          # 접미사 없는 형태 (예: "안동")
    phone: str = ""    # 민원실 직통번호. 확인된 값이 없으면 비워 둔다.


# 경상북도 10시 12군 (2023년 군위군 대구 편입 이후 기준)
REGIONS: tuple[Region, ...] = (
    Region("포항시", "포항"),
    Region("경주시", "경주"),
    Region("김천시", "김천"),
    Region("안동시", "안동"),
    Region("구미시", "구미"),
    Region("영주시", "영주"),
    Region("영천시", "영천"),
    Region("상주시", "상주"),
    Region("문경시", "문경"),
    Region("경산시", "경산"),
    Region("의성군", "의성"),
    Region("청송군", "청송"),
    Region("영양군", "영양"),
    Region("영덕군", "영덕"),
    Region("청도군", "청도"),
    Region("고령군", "고령"),
    Region("성주군", "성주"),
    Region("칠곡군", "칠곡"),
    Region("예천군", "예천"),
    Region("봉화군", "봉화"),
    Region("울진군", "울진"),
    Region("울릉군", "울릉"),
)

REGION_COUNT = len(REGIONS)

# 경북에서 빠진 시군 — 옛 자료에 남아 있어 오안내를 막으려고 따로 둔다.
TRANSFERRED = {
    "군위": (
        "군위군",
        "군위군은 2023년 7월 1일 대구광역시로 편입되어 경상북도 관할이 아닙니다. "
        "대구광역시 군위군청으로 안내하세요.",
    ),
}

# 지명이 일상어와 겹치는 곳들. 이런 곳은 "시/군" 접미사가 있어야 인정한다.
#   영양군 vs "영양 상태",  고령군 vs "고령자",  상주시 vs "상주(喪主)",
#   성주군 vs "성주",  구미시 vs "구미(口味)",  의성군 vs "의성(擬聲)"
_AMBIGUOUS = {"영양", "고령", "상주", "성주", "구미", "의성", "봉화", "청도"}

# 흔히 쓰는 다른 이름
_ALIASES: dict[str, str] = {
    "울릉도": "울릉군",
    "독도": "울릉군",
}

# 접미사가 붙으면("안동시에") 뒤에 조사가 와도 인정한다.
# 접미사 없이 지명만 쓰면("안동 사는데") 뒤에 다른 한글이 붙지 않아야 한다
# — "안동네", "고령자", "영양가" 같은 오탐을 막는 장치다.
_SUFFIX = r"(?:시청|군청|시|군|읍|면)"
_NOT_HANGUL = r"(?![가-힣])"


def _region_pattern(stem: str) -> re.Pattern:
    if stem in _AMBIGUOUS:
        return re.compile(rf"{stem}{_SUFFIX}")          # 접미사 필수
    return re.compile(rf"{stem}(?:{_SUFFIX}|{_NOT_HANGUL})")


_PATTERNS = tuple((r, _region_pattern(r.stem)) for r in REGIONS)
_BY_NAME = {r.name: r for r in REGIONS}
_ALIAS_RE = tuple(
    (re.compile(rf"{a}{_NOT_HANGUL}"), _BY_NAME[n]) for a, n in _ALIASES.items()
)


def detect(text: str) -> Region | None:
    """민원 문장에서 경상북도 시·군을 찾는다. 없으면 None."""
    if not text:
        return None
    norm = normalize(text)
    if not norm:
        return None
    for pattern, region in _ALIAS_RE:
        if pattern.search(norm):
            return region
    for region, pattern in _PATTERNS:
        if pattern.search(norm):
            return region
    return None


def detect_transferred(text: str) -> tuple[str, str] | None:
    """경북에서 빠져나간 시군(군위)을 언급했는지."""
    if not text:
        return None
    norm = normalize(text)
    for stem, payload in TRANSFERRED.items():
        if stem in norm:
            return payload
    return None


def municipal_next_action(text: str) -> dict[str, str]:
    """시군 소관 민원의 '다음 행동'을 만든다. 전화번호를 지어내지 않는다."""
    moved = detect_transferred(text)
    if moved is not None:
        name, note = moved
        return {
            "type": "other_jurisdiction",
            "region": name,
            "instruction": note,
            "phone": "",
            "phone_label": "",
        }

    region = detect(text)
    if region is None:
        return {
            "type": "municipal_office",
            "region": "",
            "instruction": (
                "민원인이 어느 시·군에 사는지 먼저 확인한 뒤, 해당 시·군청 민원실로 "
                f"안내하세요. 시·군 번호를 모르면 경상북도청 대표번호 {PROVINCE_MAIN_PHONE} "
                "에서 연결을 요청할 수 있습니다."
            ),
            "phone": PROVINCE_MAIN_PHONE,
            "phone_label": PROVINCE_PHONE_LABEL,
        }

    phone = region.phone or PROVINCE_MAIN_PHONE
    label = f"{region.name} 민원실" if region.phone else PROVINCE_PHONE_LABEL
    tail = (
        ""
        if region.phone
        else f" 직통번호가 없으면 경상북도청 대표번호 {PROVINCE_MAIN_PHONE} 에서 연결을 요청하세요."
    )
    return {
        "type": "municipal_office",
        "region": region.name,
        "instruction": f"{region.name}청 민원실로 안내하세요.{tail}",
        "phone": phone,
        "phone_label": label,
    }
