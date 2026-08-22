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

# 어르신이 위치 대신 대는 지형지물. 시군이 없어도 담당자에게는 쓸모가 있다.
_LANDMARK_RE = re.compile(
    r"(체육관|경기장|학교|초등학교|중학교|고등학교|대학교|시장|정류장|터미널|역앞|역 앞|"
    r"우체국|파출소|지구대|보건소|복지관|경로당|마을회관|아파트|다리|교회|절|사거리|삼거리|"
    r"공원|저수지|둑|하천|천변|대교|고가|굴다리)"
)

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


# 같은 말이 반복되거나(잡음·혼잣말), 내용이 없는 발화. 실제 통화에서는
# 헛기침·잡음·STT 오인식이 이런 모양으로 들어온다.
_HANGUL_RE = re.compile(r"[가-힣]")
# "가나다"는 한글 자모 순서를 읊는 말이라 내용이 없다. 마이크 테스트에서 흔하다.
_FILLER_WORDS = frozenset(
    """
    가나다 가나다라 라마바 아아 어어 음음 흠흠 에이 테스트 테스트중
    여보시오 야야 뭐뭐 그그 저저 아니아니
    """.split()
)


def is_meaningless(text: str) -> bool:
    """민원 내용으로 볼 수 없는 발화인지.

    되묻기 경로로 보내기 위한 판정이다. **어르신이 표현을 잘 못하는 경우와
    구분해야 한다** — "물이... 그게..." 같은 더듬는 말은 의미 있는 발화다.
    그래서 '내용이 빈약하다'가 아니라 '내용이 없다'만 잡는다.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return True

    # 한글이 하나도 없으면(기호·잡음) 내용이 없다. 숫자만 있는 것은 연락처일
    # 수 있으므로 제외한다.
    if not _HANGUL_RE.search(cleaned) and not any(ch.isdigit() for ch in cleaned):
        return True

    tokens = cleaned.replace(",", " ").split()
    if not tokens:
        return True

    # 같은 토큰만 2번 이상 반복 — "가나다 가나다 가나다"
    unique = {t.strip(".,!?~") for t in tokens}
    if len(tokens) >= 2 and len(unique) == 1:
        return True

    # 전부 무의미어로만 이루어진 경우
    if unique and all(t in _FILLER_WORDS for t in unique):
        return True

    # 한 글자 감탄사만 있는 짧은 발화
    if len(cleaned) <= 2 and cleaned in ("어", "음", "아", "네", "예", "응", "흠"):
        return True

    return False


# 통화 마무리 신호. **P5 사전(`voisso.dialect.closing_cues`)이 원본이다.**
# 어르신이 "더 없다"를 말하는 방식은 아주 다양해서(없어예 / 괘안타 / 그기 다라예 /
# 그거뿐이라예 …) 직접 정규식으로 감당하기 어렵다. 방언 지식은 P5 소관이라
# 그쪽 목록을 쓰고, 모듈이 없을 때만 아래 최소 폴백으로 버틴다.
_FALLBACK_CLOSING_NEGATIVE = (
    "없어예", "없습니더", "없어요", "됐어예", "됐습니더", "됐어요",
    "그만", "그마 됐다", "괜찮습니더", "괜찮아요", "다 했어예", "다 말했어예",
    "끝이라예", "이상입니더", "아니요", "그거뿐이라예",
)
_FALLBACK_CLOSING_POSITIVE = (
    "더 있어예", "또 있어예", "하나 더", "아 맞다", "아 참", "그란데예", "저기예",
)

# 민원 내용의 부정 표현을 종료로 오인하면 안 된다.
# ("전기가 안 들어와예" 의 '안', "물이 안 빠져서 못 살겠어예" 의 '못')
_NOT_DONE_HINTS = ("빠지", "안 나", "안 들어", "안 되", "못 하", "고장", "안 와", "안 켜")

_CLOSING_CACHE: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}


def _closing_cues() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`(종료 신호, 계속 신호)`. P5 사전 우선, 없으면 내장 폴백."""
    cached = _CLOSING_CACHE.get("cues")
    if cached is not None:
        return cached

    negative: tuple[str, ...] = _FALLBACK_CLOSING_NEGATIVE
    positive: tuple[str, ...] = _FALLBACK_CLOSING_POSITIVE
    try:
        import voisso.dialect as dialect

        cues = dialect.closing_cues()
        neg = tuple(str(x) for x in (cues.get("closing_negative") or []) if str(x).strip())
        pos = tuple(str(x) for x in (cues.get("closing_positive") or []) if str(x).strip())
        if neg:
            negative = neg
        if pos:
            positive = pos
    except Exception:
        pass  # 사전이 아직 없다. 폴백으로 진행한다.

    # 긴 표현이 먼저 걸려야 "됐다"보다 "그마 됐다"가 우선 매칭된다.
    result = (
        tuple(sorted(negative, key=len, reverse=True)),
        tuple(sorted(positive, key=len, reverse=True)),
    )
    _CLOSING_CACHE["cues"] = result
    return result


def closing_intent(text: str) -> str | None:
    """`"close"` | `"continue"` | None.

    **계속 신호가 종료 신호를 이긴다.** "아 맞다, 그라고 하나 더 있어예" 처럼
    두 신호가 같이 들어오면 어르신은 아직 할 말이 남은 것이다.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    negative, positive = _closing_cues()

    for cue in positive:
        if cue in cleaned:
            return "continue"

    # 민원 내용을 말하는 중이면 종료로 보지 않는다.
    if any(hint in cleaned for hint in _NOT_DONE_HINTS):
        return None

    for cue in negative:
        if cue in cleaned:
            return "close"
    return None


def looks_finished(text: str) -> bool:
    """어르신이 '더 할 말 없다'는 뜻으로 말했는가."""
    return closing_intent(text) == "close"


def has_gb_city(text: str) -> bool:
    """경상북도 시군 이름이 들어 있는가."""
    if not text:
        return False
    return bool(_CITY_RE.search(text) or _BARE_CITY_RE.search(text))


def extract_city(text: str) -> str:
    """시군만 뽑는다. 없으면 빈 문자열."""
    match = _CITY_RE.search(text or "")
    if match:
        return match.group(1)
    bare = _BARE_CITY_RE.search(text or "")
    if bare:
        return GB_CITIES[GB_BARE.index(bare.group(1))]
    return ""


def extract_dong(text: str) -> str:
    """읍/면/동/리 만 뽑는다. 없으면 빈 문자열."""
    city = extract_city(text or "")
    for match in _DONG_RE.finditer(text or ""):
        candidate = match.group(1)
        if candidate in _NOT_A_PLACE:
            continue
        if city and (candidate == city or candidate == city[:-1]):
            continue
        return candidate
    return ""


@dataclass
class Slots:
    """4개 슬롯 + 질문 횟수."""

    what: str = ""
    where: str = ""
    when: str = ""
    contact: str = ""
    # 어르신은 시군 대신 랜드마크를 말하는 일이 잦다("포스텍 체육관 앞").
    # 그건 버릴 정보가 아니라 담당자에게 그대로 전달해야 할 단서다.
    # 다만 `where` 는 아니므로 시군은 따로 확보한다.
    landmark: str = ""
    # 시군 없이 읍면동만 들은 경우 임시 보관. 시군이 오면 합친다.
    pending_dong: str = ""
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
        """**값이 없는 슬롯. 오직 값에서만 파생된다.**

        불변식: 값이 빈 슬롯은 반드시 여기에 있다. 예외 없다.

        예전에는 여기서 `given_up` 을 빼고 계산했는데, 그러면 두 번 물어보고
        포기한 슬롯이 **값이 비어 있는데도 missing 에서 사라졌다.**
        "채워진 걸로 치는데 값은 비어 있는" 모순 상태가 되고, 그대로 통화가
        끝나면 민원카드의 위치가 공란으로 나간다. 담당자가 어디로 출동할지
        모르게 되는 것이다.

        '더 물어볼지'는 값의 문제가 아니라 대화 진행의 문제다. `askable()` 이
        따로 판단한다.
        """
        return [s for s in SLOT_ORDER if not self.is_filled(s)]

    def askable(self) -> list[str]:
        """아직 값이 없고, 더 여쭤봐도 되는 슬롯.

        `missing` 에서 이미 두 번 물어본 것(`given_up`)을 뺀 목록이다.
        질문을 고를 때만 쓴다. 슬롯 상태 보고에는 쓰지 마라.
        """
        return [s for s in self.missing() if s not in self.given_up]

    def is_complete(self) -> bool:
        """더 물어볼 것이 없는 상태.

        **'다 채웠다'는 뜻이 아니다.** 두 번 물어도 답을 못 얻은 슬롯이 있으면
        비어 있어도 여기서는 완료로 본다 — 같은 질문을 세 번 하지 않기 위해서다.
        실제로 무엇이 비었는지는 `missing()` 이 정직하게 알려준다.
        """
        return not self.askable()

    def next_slot(self) -> str | None:
        pending = self.askable()
        return pending[0] if pending else None

    # -- 상태 변경 ---------------------------------------------------------
    def add_landmark(self, value: str) -> None:
        """랜드마크 단서를 모은다. 중복은 넣지 않는다."""
        cleaned = (value or "").strip()
        if not cleaned or cleaned in self.landmark:
            return
        self.landmark = f"{self.landmark}, {cleaned}".strip(", ")[:200]

    def _update_where(self, cleaned: str) -> bool:
        """`where` 는 **경북 시군이 확인된 값만** 받는다.

        "보스텍 체육관이요" 같은 값이 그대로 들어가면 담당자는 어느 시군인지
        알 수 없고, 라우팅도 지명을 못 쓴다. 시군이 없으면 landmark 로 돌리고
        `where` 는 비워 둬서 **다시 여쭙게** 한다. 단서는 버리지 않는다.
        """
        city = extract_city(cleaned)
        dong = extract_dong(cleaned)

        if not city:
            if dong:
                # 읍면동만 들었다. 시군이 올 때까지 들고 있는다.
                self.pending_dong = dong
            else:
                self.add_landmark(cleaned)
            return False

        dong = dong or self.pending_dong
        resolved = f"{city} {dong}".strip()
        if resolved == self.where:
            return False
        self.where = resolved
        self.pending_dong = ""
        self.given_up.discard("where")
        return True

    def update(self, name: str, value: str | None) -> bool:
        """슬롯을 채운다. 빈 값으로 기존 값을 덮어쓰지 않는다."""
        if name not in SLOT_ORDER:
            return False
        cleaned = (value or "").strip()
        if not cleaned or cleaned == UNKNOWN:
            return False

        if name == "where":
            return self._update_where(cleaned)

        # 무의미한 발화가 민원 내용으로 굳는 것을 막는다.
        if name == "what" and is_meaningless(cleaned):
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
            "landmark": self.landmark,
            "filled": self.filled(),
            # 값이 비어 있는 슬롯. 값에서만 파생된다(불변식).
            "missing": self.missing(),
            # 두 번 물어도 답을 못 얻어 더 묻지 않는 슬롯. missing 의 부분집합.
            "unanswered": sorted(s for s in self.given_up if not self.is_filled(s)),
            # 더 물어볼 것이 없다는 뜻. "다 채웠다"가 아니다.
            "complete": self.is_complete(),
        }

    def for_card(self) -> dict[str, str]:
        """민원카드 본문에 넣을 때는 못 채운 값을 명시적으로 표기한다."""
        data = {name: (self.get(name) or UNKNOWN) for name in SLOT_ORDER}
        if self.landmark:
            # 담당자가 현장을 찾는 데 쓰는 단서다. 반드시 함께 전달한다.
            data["landmark"] = self.landmark
        return data


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
    elif existing is not None and _LANDMARK_RE.search(text or ""):
        # 시군이 안 잡혔지만 랜드마크로 보이는 표현이 있다.
        existing.add_landmark(text.strip())

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
