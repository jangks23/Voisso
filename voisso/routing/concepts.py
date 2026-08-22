"""민원 개념 사전 — 구어 표현과 행정 용어 사이의 다리.

## 왜 필요한가

어르신은 "하수구"라고 말하지 않는다. **증상**을 말한다.

    "집 앞에 물이 안 빠지고 자꾸 고여서 큰일이에요"

이 문장에는 도청 사무분장에 등장하는 단어가 하나도 없다. 문자 n-gram 만으로는
영원히 못 잡는다. 그래서 구어 표현 -> 행정 용어 매핑을 사람이 직접 적었다.

## 출처 / 라이선스

**이 사전은 Voisso 프로젝트가 직접 작성한 창작물이다.** 어떤 공공데이터·외부
사전에서도 복제하지 않았다. 표현은 경북 지역 민원 전화에서 실제로 나올 법한
구어체를 기준으로 골랐고, 대응하는 행정 용어는 경상북도청 사무분장에 실제로
쓰이는 어휘로 맞췄다. 저장소 라이선스(LICENSE)를 그대로 따른다.

## 관할 구분이 중요하다

경상북도청이 하는 일과 시·군이 하는 일은 다르다. 가로등·보안등 유지관리,
생활폐기물 수거, 주민등록 사무는 **시군 소관**이라 도청 사무분장에 아예 없다.
그런 질의에 억지로 부서를 붙이면 민원인이 두 번 전화하게 된다. 그래서 각
개념에 관할을 표시하고, 시군 소관이면 부서를 배정하지 않고 안내로 돌린다.

    province : 도청 소관. 행정 용어를 검색어에 주입한다
    shared   : 도청도 하고 시군도 한다. 배정하되 안내 문구를 붙인다
    municipal: 시군 소관. 부서를 배정하지 않고 시군 민원실로 안내한다

## 패턴 작성 규칙

- 정규화된 문자열(한글·영숫자·공백만 남은 상태)에 대해 매칭한다.
- 어미 변화를 흡수하도록 어간까지만 적는다. "빠지고/빠져서/빠집니다" -> ``빠지``
- 사투리 표기도 함께 넣는다. "수채구영"(하수구), "맥히"(막히), "씨레기"(쓰레기)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .tokenizer import normalize

Jurisdiction = Literal["province", "shared", "municipal"]

# 개념이 걸리면 그 행정 용어를 이 가중치로 질의에 넣는다.
# 원어절(1.0)보다 높다 — 사람이 검증한 대응이라 우연한 n-gram 겹침보다 믿을 만하다.
CONCEPT_WEIGHT = 1.35

MUNICIPAL_NOTE = (
    "이 업무는 시·군 소관입니다. 관할 시·군청 민원실로 안내하세요. "
    "어디로 걸어야 할지 모르면 경상북도청 대표번호 1522-0120 에서 연결받을 수 있습니다."
)


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    patterns: tuple[str, ...]
    admin_terms: tuple[str, ...] = ()
    jurisdiction: Jurisdiction = "province"
    note: str = ""
    _compiled: tuple[re.Pattern, ...] = field(default=(), repr=False, compare=False)


def _c(
    cid: str,
    label: str,
    patterns: tuple[str, ...],
    admin_terms: tuple[str, ...] = (),
    jurisdiction: Jurisdiction = "province",
    note: str = "",
) -> Concept:
    return Concept(
        id=cid,
        label=label,
        patterns=patterns,
        admin_terms=admin_terms,
        jurisdiction=jurisdiction,
        note=note,
        _compiled=tuple(re.compile(p) for p in patterns),
    )


# ══════════════════════════════════════════════════════════ 상하수도 · 배수

CONCEPTS: tuple[Concept, ...] = (
    _c("drain_blocked", "하수구 막힘 / 물이 안 빠짐",
       (r"하수\s*구", r"수채\s*구영", r"수채\s*구멍", r"하수\s*구멍", r"배수\s*구",
        r"물\s*이?\s*안\s*빠", r"물\s*이?\s*잘\s*안\s*빠", r"물\s*이?\s*고여", r"물\s*이?\s*고이",
        r"물\s*이?\s*괴어", r"물\s*이?\s*넘쳐", r"물\s*이?\s*넘친", r"물\s*이?\s*차올",
        r"맨홀", r"빗물\s*받이", r"하수\s*도", r"맥히", r"막혀\s*서?", r"막혔"),
       ("하수도", "하수관로", "배수", "우수", "준설", "빗물받이", "배수개선"),
       note="하수도 정책·시설은 도, 소규모 관로 준설은 시군이 하는 경우가 많다"),

    _c("sewage_backflow", "오수 역류",
       (r"역류", r"거꾸로\s*올라", r"오수", r"정화조", r"똥물"),
       ("하수도", "오수", "하수관로", "정화조", "배수")),

    _c("flooding", "침수 / 물바다",
       (r"침수", r"물바다", r"잠겨", r"잠겼", r"물\s*난리", r"수해"),
       ("침수", "배수개선", "우수", "자연재난", "풍수해", "복구")),

    _c("water_none", "수돗물이 안 나옴 / 단수",
       (r"수돗?물\s*이?\s*안\s*나", r"물\s*이?\s*안\s*나", r"단수", r"수도\s*가?\s*끊",
        r"급수\s*가?\s*안", r"상수\s*도"),
       ("상수도", "급수", "수도", "상수관로")),

    _c("water_quality", "녹물 / 흙탕물",
       (r"녹물", r"흙탕물", r"물\s*이?\s*뿌옇", r"물\s*맛\s*이?\s*이상", r"물\s*에서\s*냄새"),
       ("상수도", "수질", "정수", "급수")),

    _c("water_leak", "누수 / 물이 샘",
       (r"누수", r"물\s*이?\s*새", r"수도\s*관\s*이?\s*터", r"파열"),
       ("상수도", "누수", "상수관로", "유지관리")),

    _c("drought", "가뭄 / 물 부족",
       (r"가뭄", r"물\s*이?\s*부족", r"논\s*이?\s*말라", r"저수지\s*가?\s*말라"),
       ("가뭄", "한해", "용수", "저수지", "재해")),

    # ══════════════════════════════════════════════════════════════ 농업

    _c("farm_road", "농로 / 농삿길 파손",
       (r"농로", r"농삿?\s*길", r"논\s*둑", r"밭\s*둑", r"경운기\s*길", r"트랙터\s*가?\s*못"),
       ("농업생산기반", "농업기반", "농어촌", "정비", "복구", "농업재해"),
       note="농로 정비는 도의 농업생산기반 정비 사업과 시군 사업이 나뉜다"),

    _c("farm_infra", "수리시설 / 저수지 / 용수로",
       (r"저수지", r"용수\s*로", r"배수\s*로", r"수로\s*가", r"보\s*가\s*무너", r"양수장",
        r"경지\s*정리"),
       ("수리시설", "저수지", "용수", "농업생산기반", "농업기반")),

    _c("farm_disaster", "농작물 재해 피해",
       (r"농작물\s*이?\s*피해", r"작물\s*이?\s*다\s*죽", r"우박", r"서리\s*피해",
        r"태풍\s*에\s*농", r"농사\s*를?\s*망", r"밭\s*이?\s*떠내", r"떠내려", r"떠내리"),
       ("농업재해", "재해대책", "복구", "피해", "농작물")),

    _c("wild_animal", "멧돼지 / 고라니 등 야생동물 피해",
       (r"멧돼지", r"산돼지", r"고라니", r"노루", r"야생\s*동물", r"들짐승", r"까치\s*가?\s*피해"),
       ("야생동물", "수렵", "유해야생동물", "피해")),

    _c("livestock", "가축 / 축산",
       (r"가축", r"소\s*를?\s*키", r"돼지\s*를?\s*키", r"닭\s*을?\s*키", r"축사",
        r"구제역", r"조류\s*독감", r"방역"),
       ("축산", "가축", "방역", "축산정책")),

    _c("farm_support", "영농 지원 / 직불금 / 비료",
       (r"직불금", r"직불\s*제", r"비료\s*지원", r"농약", r"영농\s*자재", r"농기계\s*지원"),
       ("직불제", "농업", "영농", "지원", "농업정책")),

    _c("return_farming", "귀농 / 귀촌",
       (r"귀농", r"귀촌", r"농사\s*지으러", r"시골\s*로\s*내려"),
       ("귀농", "귀촌", "정착", "농촌")),

    # ══════════════════════════════════════════════════════════════ 환경

    _c("illegal_dumping", "쓰레기 무단투기",
       (r"쓰레기\s*를?\s*(몰래|막|마카)?\s*버리", r"씨레기", r"무단\s*투기", r"불법\s*투기",
        r"쓰레기\s*가?\s*쌓", r"내삐리", r"내버리", r"폐기물"),
       ("폐기물", "자원순환", "투기", "지도점검", "재활용"),
       jurisdiction="shared",
       note="폐기물 정책·처리시설은 도, 생활쓰레기 수거·단속은 시군이 한다"),

    _c("garbage_collection", "쓰레기 수거 / 종량제 봉투",
       (r"쓰레기\s*를?\s*안\s*가져", r"쓰레기\s*수거", r"종량제\s*봉투", r"음식물\s*쓰레기\s*통",
        r"분리\s*수거\s*함", r"청소차"),
       jurisdiction="municipal",
       note="생활폐기물 수거와 종량제 봉투 판매는 시군 소관이다"),

    _c("odor_noise", "악취 / 소음",
       (r"악취", r"냄새\s*가?\s*(너무|심|나)", r"소음", r"시끄러", r"공장\s*에서\s*냄새"),
       ("환경", "오염", "지도점검", "악취"),
       jurisdiction="shared"),

    _c("air_quality", "미세먼지 / 대기오염",
       (r"미세\s*먼지", r"매연", r"대기\s*오염", r"공기\s*가?\s*나쁘"),
       ("대기", "환경", "오염", "미세먼지")),

    _c("water_pollution", "하천 오염",
       (r"하천\s*이?\s*더러", r"물고기\s*가?\s*죽", r"강\s*물\s*이?\s*이상", r"폐수",
        r"기름\s*이?\s*떠"),
       ("수질", "하천", "오염", "물환경")),

    _c("forest_use", "산림 / 임산물",
       (r"임산물", r"산나물", r"벌채", r"나무\s*를?\s*베", r"산림\s*경영", r"표고\s*버섯"),
       ("산림", "임산물", "산림경영")),

    # ══════════════════════════════════════════════════════════════ 교통

    _c("bus_service", "버스 노선 / 배차",
       (r"버스", r"뻐스", r"버스\s*가?\s*안\s*(와|오)", r"배차", r"노선", r"차\s*가?\s*하루에"),
       ("버스", "대중교통", "노선", "여객", "운수", "운행")),

    _c("bus_stop", "정류장 / 승강장",
       (r"정류장", r"정류소", r"승강장", r"버스\s*정거장"),
       ("정류소", "승강장", "대중교통")),

    _c("taxi", "택시",
       (r"택시", r"콜택시", r"부르는\s*택시"),
       ("택시", "여객", "운수")),

    _c("road_damage", "도로 파손 / 포트홀",
       (r"도로\s*가?\s*파", r"포트\s*홀", r"길\s*이?\s*패", r"아스팔트\s*가?\s*깨",
        r"도로\s*가?\s*갈라"),
       ("도로", "포장", "유지관리", "보수"),
       jurisdiction="shared",
       note="지방도는 도, 시군도·농어촌도로는 시군이 관리한다"),

    _c("traffic_safety", "신호등 / 교통안전시설",
       (r"신호등", r"과속\s*방지", r"횡단\s*보도", r"교통\s*표지", r"반사경"),
       ("교통안전시설", "교통"),
       jurisdiction="shared"),

    _c("snow_removal", "제설",
       (r"제설", r"눈\s*을?\s*안\s*치", r"빙판", r"눈\s*이?\s*쌓여\s*서?\s*차"),
       ("제설", "도로", "재난"),
       jurisdiction="shared"),

    # ═══════════════════════════════════════════════ 시군 소관 (부서 배정 금지)

    _c("streetlight", "가로등 / 보안등",
       (r"가로등", r"보안등", r"street\s*light", r"등\s*이?\s*안\s*들어",
        r"불\s*이?\s*안\s*들어", r"전등\s*이?\s*나갔"),
       jurisdiction="municipal",
       note="가로등·보안등 설치와 유지관리는 시군 소관이라 도청 사무분장에 없다"),

    _c("resident_service", "주민등록 / 각종 증명서",
       (r"주민\s*등록", r"등본", r"초본", r"인감", r"가족\s*관계\s*증명", r"전입\s*신고"),
       jurisdiction="municipal",
       note="주민등록·제증명 발급은 시군 및 읍면동 소관이다"),

    _c("village_road", "마을 안길 / 골목길",
       (r"마을\s*안\s*길", r"골목\s*길", r"동네\s*길\s*이?\s*좁", r"안길\s*포장"),
       jurisdiction="municipal",
       note="마을 안길·소로 정비는 시군 소관이다"),

    _c("parking", "주차 / 불법주차 단속",
       (r"주차\s*단속", r"불법\s*주차", r"주차장\s*이?\s*없", r"차\s*를?\s*댈\s*데"),
       jurisdiction="municipal",
       note="주차 단속과 공영주차장 운영은 시군 소관이다"),

    _c("water_bill", "수도요금 고지서",
       (r"수도\s*요금", r"수도\s*세", r"요금\s*이?\s*많이\s*나", r"고지서\s*가?\s*이상"),
       jurisdiction="municipal",
       note="상수도 요금 부과·수납은 시군 상수도사업소 소관이다"),

    _c("stray_animal", "유기견 / 길고양이",
       (r"유기견", r"떠돌이\s*개", r"들개", r"길\s*고양이", r"개\s*가?\s*돌아다"),
       jurisdiction="municipal",
       note="유기동물 구조·보호는 시군 소관이다"),

    # ══════════════════════════════════════════════════════════════ 복지

    _c("senior_center", "경로당 / 노인정",
       (r"경로당", r"노인정", r"마을\s*회관\s*에\s*어르신"),
       ("경로당", "노인", "어르신", "복지")),

    _c("senior_care", "어르신 돌봄 / 독거노인",
       (r"돌봄", r"독거\s*노인", r"혼자\s*사시는", r"혼차\s*사시", r"요양", r"간병",
        r"어르신\s*이?\s*계신데"),
       ("돌봄", "노인", "어르신", "복지", "요양")),

    _c("senior_job", "노인 일자리",
       (r"노인\s*일자리", r"어르신\s*일자리", r"나이\s*들어\s*일", r"일\s*할\s*데\s*가?\s*없"),
       ("노인일자리", "일자리", "어르신", "사회활동")),

    _c("basic_livelihood", "기초생활 / 생계 지원",
       (r"기초\s*생활", r"수급자", r"생계\s*비", r"생활\s*이?\s*어려", r"먹고\s*살기",
        r"긴급\s*복지"),
       ("기초생활보장", "생계급여", "저소득", "긴급복지")),

    _c("disability", "장애인 지원",
       (r"장애인", r"장애\s*등급", r"활동\s*지원사?", r"휠체어"),
       ("장애인", "복지", "재활", "활동지원")),

    _c("childcare", "보육 / 아동",
       (r"어린이집", r"유치원", r"아이\s*를?\s*맡", r"보육", r"아동\s*수당"),
       ("보육", "아동", "돌봄", "육아")),

    _c("birth_support", "출산 / 저출생",
       (r"출산\s*지원", r"산후\s*조리", r"아기\s*를?\s*낳", r"저출생", r"난임"),
       ("출산", "인구", "저출생", "지원")),

    _c("medical", "의료 / 보건",
       (r"병원\s*이?\s*없", r"진료", r"약값", r"보건소", r"응급실", r"의료\s*비"),
       ("보건", "의료", "공공의료", "진료")),

    _c("multicultural", "다문화 / 외국인",
       (r"다문화", r"외국인\s*근로", r"결혼\s*이민", r"이주\s*여성"),
       ("다문화", "외국인", "가족")),

    # ══════════════════════════════════════════════════════════════ 재난

    _c("disaster_relief", "재난지원금 / 피해 보상",
       (r"재난\s*지원금", r"재해\s*지원", r"피해\s*보상", r"피해\s*조사", r"복구\s*비",
        r"이재민"),
       ("재난", "재난지원", "피해조사", "복구", "재해복구", "구호")),

    _c("wildfire", "산불",
       (r"산불", r"산에\s*불", r"검불\s*이?\s*쌓", r"낙엽\s*이?\s*쌓", r"불\s*나면",
        r"불\s*날까"),
       ("산불", "산림", "예방", "산불방지")),

    _c("landslide", "산사태 / 축대 붕괴",
       (r"산사태", r"축대\s*가?\s*무너", r"옹벽", r"토사\s*가?\s*흘러", r"급경사"),
       ("사방", "산림", "재해", "급경사지", "복구")),

    _c("storm_damage", "태풍 / 호우 피해",
       (r"태풍", r"호우", r"집중\s*호우", r"폭우", r"비\s*가?\s*많이\s*와\s*서?\s*피해"),
       ("자연재난", "풍수해", "피해조사", "복구", "재해")),

    _c("earthquake", "지진",
       (r"지진", r"땅\s*이?\s*흔들", r"내진"),
       ("지진", "재난", "안전")),

    # ══════════════════════════════════════════════════════ 일자리 · 경제

    _c("job_seeking", "일자리 / 취업",
       (r"일자리", r"취직", r"취업", r"직장\s*을?\s*구", r"실업", r"채용"),
       ("일자리", "고용", "취업", "채용")),

    _c("startup_fund", "창업 / 자금 지원",
       (r"창업", r"사업\s*을?\s*시작", r"운영\s*자금", r"대출\s*을?\s*받", r"융자"),
       ("창업", "자금", "융자", "기업", "소상공인")),

    _c("small_business", "소상공인 / 전통시장",
       (r"소상공인", r"자영업", r"장사\s*가?\s*안", r"전통\s*시장", r"가게\s*를?\s*하는"),
       ("소상공인", "민생경제", "시장", "상인")),

    _c("youth_support", "청년 지원",
       (r"청년\s*지원", r"청년\s*수당", r"청년\s*주택", r"젊은\s*사람\s*들?\s*이?\s*떠나"),
       ("청년", "지원", "정착")),

    # ══════════════════════════════════════════════════════════════ 기타

    _c("local_tax", "지방세",
       (r"지방세", r"재산세", r"자동차세", r"취득세", r"세금\s*이?\s*많이"),
       ("지방세", "세정", "부과", "징수")),

    _c("festival_tourism", "축제 / 관광",
       (r"축제", r"관광\s*지", r"여행\s*객", r"관광\s*안내"),
       ("축제", "관광", "문화", "마케팅")),

    _c("sports_facility", "체육시설",
       (r"체육관", r"운동장", r"체육\s*시설", r"게이트\s*볼"),
       ("체육", "생활체육", "시설")),

    _c("housing", "주택 / 빈집",
       (r"빈집", r"폐가", r"주택\s*을?\s*고치", r"집수리", r"슬레이트"),
       ("주택", "건축", "정비", "주거")),

    _c("school_edu", "학교 / 교육",
       (r"학교\s*가?\s*멀", r"통학", r"교육\s*지원", r"장학금", r"방과\s*후"),
       ("교육", "청소년", "장학")),
)

CONCEPTS_BY_ID = {c.id: c for c in CONCEPTS}


@dataclass(frozen=True)
class ConceptHit:
    concept: Concept
    matched: str          # 실제로 걸린 표현

    @property
    def id(self) -> str:
        return self.concept.id

    @property
    def jurisdiction(self) -> Jurisdiction:
        return self.concept.jurisdiction


def detect(text: str) -> list[ConceptHit]:
    """문장에서 걸리는 개념을 모두 찾는다."""
    if not text:
        return []
    norm = normalize(text)
    if not norm:
        return []
    hits: list[ConceptHit] = []
    for concept in CONCEPTS:
        for pattern in concept._compiled:
            m = pattern.search(norm)
            if m:
                hits.append(ConceptHit(concept=concept, matched=m.group(0).strip()))
                break
    return hits


# 같은 개념 안에서도 앞에 적은 용어가 더 대표적이다.
#   drain_blocked -> ("하수도", "하수관로", "배수", ...) 순서에 의미가 있다.
# 뒤로 갈수록 가중치를 조금씩 낮춰, 대표 용어를 가진 부서가 위로 오게 한다.
TERM_DECAY = 0.06
TERM_FLOOR = 0.70


def admin_terms(hits: list[ConceptHit]) -> dict[str, float]:
    """개념 히트 -> {행정 용어: 가중치}. 시군 소관 개념은 용어를 내지 않는다."""
    out: dict[str, float] = {}
    for hit in hits:
        if hit.jurisdiction == "municipal":
            continue
        for i, term in enumerate(hit.concept.admin_terms):
            weight = CONCEPT_WEIGHT * max(1.0 - TERM_DECAY * i, TERM_FLOOR)
            if weight > out.get(term, 0.0):
                out[term] = weight
    return out


def municipal_only(hits: list[ConceptHit]) -> bool:
    """걸린 개념이 전부 시군 소관이면 True (부서를 배정하면 안 된다)."""
    return bool(hits) and all(h.jurisdiction == "municipal" for h in hits)


def referral_note(hits: list[ConceptHit]) -> str:
    notes = [h.concept.note for h in hits if h.jurisdiction == "municipal" and h.concept.note]
    if not notes:
        return MUNICIPAL_NOTE
    head = notes[0].rstrip()
    if not head.endswith((".", "다", "요")):
        head += "."
    elif head.endswith("다"):
        head += "."
    return f"{head} {MUNICIPAL_NOTE}"


def shared_notes(hits: list[ConceptHit]) -> list[str]:
    return [h.concept.note for h in hits if h.jurisdiction == "shared" and h.concept.note]


def concept_count() -> int:
    return len(CONCEPTS)
