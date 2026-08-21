"""슬롯 필링 — 민원 접수에 필요한 최소 4가지.

what    무슨 일이  (민원 내용)
where   어디서     (시군 + 읍면동)
when    언제부터   (발생 시점)
contact 연락처     (회신용 전화번호)

`Slots` 는 값뿐 아니라 **몇 번 물어봤는지**도 센다.
어르신 상대라 같은 질문을 세 번 반복하면 안 되기 때문에,
2회까지 물어보고 못 채우면 '확인 못 함'으로 접고 다음으로 넘어간다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SLOT_ORDER = ("what", "where", "when", "contact")

SLOT_LABELS = {
    "what": "무슨 일",
    "where": "어디서",
    "when": "언제부터",
    "contact": "연락처",
}

# 같은 슬롯을 이 횟수만큼 물어봤는데도 안 채워지면 포기하고 넘어간다.
MAX_ASKS_PER_SLOT = 2

UNKNOWN = "확인 못 함"

# 경상북도 시군 (2026 기준 22개 시군)
GB_CITIES = (
    "포항시", "경주시", "김천시", "안동시", "구미시", "영주시", "영천시",
    "상주시", "문경시", "경산시", "의성군", "청송군", "영양군", "영덕군",
    "청도군", "고령군", "성주군", "칠곡군", "예천군", "봉화군", "울진군", "울릉군",
)
# "안동", "구미" 처럼 접미사 없이 부르는 경우도 잡는다.
GB_BARE = tuple(name[:-1] for name in GB_CITIES)

_CITY_RE = re.compile("(" + "|".join(GB_CITIES) + ")")
_BARE_CITY_RE = re.compile(r"(?<![가-힣])(" + "|".join(GB_BARE) + r")(?![가-힣])")
# 읍/면/동/리 는 조사·어미가 붙어 나온다("옥동입니더", "풍산면에서").
# 그래서 뒤에 올 수 있는 조사/어미를 명시적으로 허용한다.
_PARTICLE_TAIL = (
    r"(?=[\s,.\u00b7]|$|이라|입니|인데|이고|이래|예요|이에|이야|예|요|"
    r"은|는|이|가|에|서|의|쪽|만|도|번|하고|랑|을|를|맞)"
)
_DONG_RE = re.compile(r"(?<![가-힣])([가-힣]{1,4}(?:읍|면|동|리))" + _PARTICLE_TAIL)

# 위 패턴은 "그러면", "소리가" 같은 일반 어휘도 잡는다. 지명이 아닌 것이
# 확실한 말들을 걸러낸다. (Claude 가 붙으면 이 경로는 거의 안 쓰이지만,
# 키 없는 데모에서도 위치가 제대로 잡혀야 한다.)
_NOT_A_PLACE = frozenset(
    """
    그러면 하면 되면 이면 아니면 있으면 없으면 오면 가면 보면 주면 들으면
    나오면 안되면 못하면 같으면 그렇면 어쩌면 왜그러면 빠지면 생기면 막히면
    고이면 내리면 그러니까면 어떻면 이러면 저러면 하려면 오려면
    소리 머리 다리 자리 우리 거리 처리 정리 관리 수리 빨리 멀리 어서리
    활동 운동 이동 자동 수동 행동 작동 감동 아동 노동 출동 공동 합동 진동
    사동 행동 반동 격동 소동 부동 변동 유동 발동
    """.split()
)
_MOBILE_RE = re.compile(r"(01[016-9])[-.\s]?(\d{3,4})[-.\s]?(\d{4})")
_LANDLINE_RE = re.compile(r"(0\d{1,2})[-.\s]?(\d{3,4})[-.\s]?(\d{4})")

_WHEN_PATTERNS = (
    r"[0-9일이삼사오육칠팔구십한두세네다섯여섯일곱여덟아홉열몇]+\s*(?:년|달|개월|주|일|시간)\s*(?:전|쯤|째|정도)?부터",
    r"[0-9일이삼사오육칠팔구십한두세네다섯여섯일곱여덟아홉열몇]+\s*(?:년|달|개월|주|일|시간)\s*전",
    r"(?:그저)?께|어제|오늘|엊그제|엊그저께",
    r"지난\s*(?:주|달|해|봄|여름|가을|겨울)",
    r"올해|작년|재작년|금년",
    r"장마\s*(?:철|때|이후)?(?:부터)?",
    r"태풍\s*(?:때|이후|지나고)?(?:부터)?",
    r"(?:봄|여름|가을|겨울)\s*(?:부터|들어)",
    r"며칠\s*(?:전|째|되)",
    r"한참\s*(?:됐|되었)",
    r"오래\s*(?:됐|되었|전)",
    r"[0-9]+\s*월\s*(?:쯤|경|부터)?",
    r"비\s*(?:만)?\s*오(?:면|기만)",
)
_WHEN_RE = re.compile("(" + "|".join(_WHEN_PATTERNS) + ")")

# 민원 내용으로 볼 만한 문장인지 판단하는 최소 신호.
_PROBLEM_HINTS = (
    "안", "못", "고이", "막히", "깨지", "무너지", "터지", "샌다", "새", "냄새",
    "시끄럽", "위험", "불편", "고장", "파손", "침수", "물", "쓰레기", "구멍",
    "패인", "패여", "꺼지", "기울", "넘치", "역류", "끊기", "없어", "죽",
)


@dataclass
class Slots:
    """4개 슬롯 + 질문 횟수."""

    what: str = ""
    where: str = ""
    when: str = ""
    contact: str = ""
    ask_counts: dict[str, int] = field(default_factory=lambda: {k: 0 for k in SLOT_ORDER})
    # 2회 물어도 못 채운 슬롯 — 다시 묻지 않는다.
    given_up: set[str] = field(default_factory=set)

    # -- 상태 조회 ---------------------------------------------------------
    def get(self, name: str) -> str:
        return getattr(self, name, "") or ""

    def is_filled(self, name: str) -> bool:
        return bool(self.get(name).strip())

    def filled(self) -> list[str]:
        return [s for s in SLOT_ORDER if self.is_filled(s)]

    def missing(self) -> list[str]:
        """아직 못 채웠고, 아직 포기하지도 않은 슬롯."""
        return [s for s in SLOT_ORDER if not self.is_filled(s) and s not in self.given_up]

    def is_complete(self) -> bool:
        """모두 채웠거나, 남은 건 전부 포기한 상태."""
        return not self.missing()

    def next_slot(self) -> str | None:
        pending = self.missing()
        return pending[0] if pending else None

    # -- 상태 변경 ---------------------------------------------------------
    def update(self, name: str, value: str | None) -> bool:
        """슬롯을 채운다. 빈 값으로 기존 값을 덮어쓰지 않는다."""
        if name not in SLOT_ORDER:
            return False
        cleaned = (value or "").strip()
        if not cleaned or cleaned == UNKNOWN:
            return False
        current = self.get(name)
        # 더 길고 구체적인 값이 들어오면 갱신한다 (예: "안동" -> "안동시 옥동").
        if current and len(cleaned) <= len(current) and current in cleaned:
            return False
        if current == cleaned:
            return False
        setattr(self, name, cleaned)
        self.given_up.discard(name)
        return True

    def merge(self, values: dict[str, Any]) -> list[str]:
        """여러 슬롯을 한 번에 갱신하고, 실제로 바뀐 슬롯 이름을 돌려준다."""
        changed = []
        for name in SLOT_ORDER:
            if self.update(name, values.get(name)):
                changed.append(name)
        return changed

    def record_ask(self, name: str) -> None:
        """해당 슬롯을 물어봤다고 기록. 한도를 넘으면 포기 처리한다."""
        if name not in SLOT_ORDER:
            return
        self.ask_counts[name] = self.ask_counts.get(name, 0) + 1
        if self.ask_counts[name] >= MAX_ASKS_PER_SLOT and not self.is_filled(name):
            self.given_up.add(name)

    # -- 직렬화 -----------------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        """P7 통화 UI 가 진행률 표시에 쓰는 형태."""
        return {
            "what": self.what,
            "where": self.where,
            "when": self.when,
            "contact": self.contact,
            "filled": self.filled(),
            "missing": self.missing(),
            "complete": self.is_complete(),
        }

    def for_card(self) -> dict[str, str]:
        """민원카드 본문에 넣을 때는 못 채운 값을 명시적으로 표기한다."""
        return {name: (self.get(name) or UNKNOWN) for name in SLOT_ORDER}


# --------------------------------------------------------------------------
# 규칙 기반 추출 — ANTHROPIC_API_KEY 없이도 슬롯이 채워져야 한다.
# --------------------------------------------------------------------------


def extract_location(text: str) -> str:
    """'안동시 옥동' 같은 행정구역 표현을 뽑는다."""
    if not text:
        return ""
    city_match = _CITY_RE.search(text)
    city = city_match.group(1) if city_match else ""
    if not city:
        bare = _BARE_CITY_RE.search(text)
        if bare:
            # "안동" -> "안동시" 로 정규화 (원래 목록에서 접미사를 되찾는다)
            idx = GB_BARE.index(bare.group(1))
            city = GB_CITIES[idx]

    dong = ""
    for match in _DONG_RE.finditer(text):
        candidate = match.group(1)
        if candidate in _NOT_A_PLACE:
            continue
        if candidate == city or (city and candidate == city[:-1]):
            continue  # "안동시"의 "안동"을 동 이름으로 착각하지 않는다
        dong = candidate
        break

    parts = [p for p in (city, dong) if p]
    return " ".join(parts)


def _merge_location(known: str, found: str) -> str:
    """시군만 알던 상태에서 읍면동만 새로 들으면 둘을 합친다(반대도 마찬가지)."""
    if not known:
        return found
    known_parts = known.split()
    found_parts = found.split()
    merged: list[str] = []
    for part in known_parts + found_parts:
        if part not in merged:
            merged.append(part)
    # 시군이 앞, 읍면동이 뒤로 오도록 정렬한다.
    merged.sort(key=lambda p: 0 if p.endswith(("시", "군")) else 1)
    return " ".join(merged[:2])


def extract_when(text: str) -> str:
    if not text:
        return ""
    match = _WHEN_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_contact(text: str) -> str:
    """휴대폰 우선, 없으면 일반전화. 정규화된 하이픈 형태로 돌려준다."""
    if not text:
        return ""
    # 한글로 읽은 숫자는 다루지 않는다 — STT가 숫자로 받아쓰는 것을 전제한다.
    m = _MOBILE_RE.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _LANDLINE_RE.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def looks_like_problem(text: str) -> bool:
    """민원 내용으로 볼 만한 발화인지."""
    if len(text.strip()) < 6:
        return False
    return any(hint in text for hint in _PROBLEM_HINTS)


def extract_slots(text: str, existing: Slots | None = None) -> dict[str, str]:
    """한 발화에서 채울 수 있는 슬롯을 규칙으로 뽑는다."""
    found: dict[str, str] = {}

    location = extract_location(text)
    if location:
        found["where"] = _merge_location(existing.get("where") if existing else "", location)

    when = extract_when(text)
    if when:
        found["when"] = when

    contact = extract_contact(text)
    if contact:
        found["contact"] = contact

    # what 은 '아직 비어 있고, 문제로 들리는 발화'일 때만 채운다.
    if existing is None or not existing.is_filled("what"):
        if looks_like_problem(text):
            found["what"] = text.strip()

    return found
