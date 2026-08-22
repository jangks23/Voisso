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

## ``url`` 은 왜 넣었나

경상북도청 **시군민원실** 안내 페이지(``page.do?mnu_uid=6666``)에는 22개 시군의
민원 안내 페이지 링크가 있다. **전화번호는 없다** — 그 페이지의 번호 5개는 전부
도청 자체 번호(054-880-xxxx)다.

그래서 번호는 포기하고 링크만 가져왔다. 한 페이지에서 22개가 전부 나오고,
값이 URL 이라 사람이 눈으로 검증할 수 있다. 담당자가 "안동시 민원 안내" 를
바로 열어 볼 수 있으면 대표번호만 알려 주는 것보다 낫다.

번호를 원한다면 22개 시군 홈페이지를 각각 크롤해야 하는데(구조가 전부 다르다),
검증·갱신 책임을 질 수 없는 번호를 코드에 박는 것은 대표번호 안내보다 나쁘다.
수집일: 2026-08-23, 출처: https://www.gb.go.kr/Main/page.do?mnu_uid=6666

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
    url: str = ""      # 시군 민원 안내 페이지 (경북도청 시군민원실 목록에서 수집)


# 경상북도 10시 12군 (2023년 군위군 대구 편입 이후 기준)
REGIONS: tuple[Region, ...] = (
    Region("포항시", "포항", url="https://www.pohang.go.kr/portal/contents.do?mid=0105020000"),
    Region("경주시", "경주", url="https://www.gyeongju.go.kr/open_content/ko/page.do?mnu_uid=198&"),
    Region("김천시", "김천", url="https://www.gc.go.kr/portal/contents.do?mId=1202070800"),
    Region("안동시", "안동", url="https://www.andong.go.kr/portal/contents.do?mId=0101000000"),
    Region("구미시", "구미", url="https://www.gumi.go.kr/portal/contents.do?mid=0101010000"),
    Region("영주시", "영주", url="https://www.yeongju.go.kr/open_content/main/page.do?mnu_uid=3669&"),
    Region("영천시", "영천", url="https://www.yc.go.kr/portal/contents.do?mId=0101000000"),
    Region("상주시", "상주", url="https://www.sangju.go.kr/civil/page/16370/11000.tc"),
    Region("문경시", "문경", url="https://www.gbmg.go.kr/portal/contents.do?mId=0101010000"),
    Region("경산시", "경산", url="https://www.gbgs.go.kr/open_content/ko/page.do?mnu_uid=2104&"),
    Region("의성군", "의성", url="https://www.usc.go.kr/ko/page.do?mnu_uid=141&"),
    Region("청송군", "청송", url="https://www.cs.go.kr/minwon/00002609/00003135.web"),
    Region("영양군", "영양", url="https://www.yyg.go.kr/www/civil_complaint/center_guide"),
    Region("영덕군", "영덕", url="https://www.yd.go.kr/?p=551"),
    Region("청도군", "청도", url="https://www.cheongdo.go.kr/portal/contents.do?mid=0101000000"),
    Region("고령군", "고령", url="http://www.goryeong.go.kr/kor/contents.do?IDX=62"),
    Region("성주군", "성주", url="https://sj.go.kr/page.do?mnu_uid=1064&"),
    Region("칠곡군", "칠곡", url="https://www.chilgok.go.kr/portal/contents.do?mId=0104020000"),
    Region("예천군", "예천", url="https://www.ycg.kr/open.content/ko/e.application/civil.information/position/"),
    Region("봉화군", "봉화", url="https://www.bonghwa.go.kr/open.content/ko/electron.popular/guidance/guidance/"),
    Region("울진군", "울진", url="http://www.uljin.go.kr/index.uljin?menuCd=DOM_000000101001000000"),
    Region("울릉군", "울릉", url="https://ulleung.go.kr/ko/page.do?mnu_uid=1911&"),
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


# 검색어에서 걸러낼 지명 조각. 부서 사무분장에는 지명이 없다.
_PLACE_TOKENS: frozenset[str] = frozenset(
    [r.name for r in REGIONS]
    + [r.stem for r in REGIONS]
    + [r.stem + suffix for r in REGIONS for suffix in ("시청", "군청", "시내", "읍", "면")]
    + ["경상북도", "경북", "경북도", "도청", "군위", "군위군"]
)


def is_place_token(token: str) -> bool:
    """검색에서 빼야 할 지명 어절인가."""
    return token in _PLACE_TOKENS


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
    action = {
        "type": "municipal_office",
        "region": region.name,
        "instruction": f"{region.name}청 민원실로 안내하세요.{tail}",
        "phone": phone,
        "phone_label": label,
    }
    if region.url:
        action["url"] = region.url
        action["url_label"] = f"{region.name} 민원 안내"
    return action
