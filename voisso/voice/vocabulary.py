"""STT 보조 어휘 — 프라이밍 프롬프트와 후보 재점수화의 공통 재료.

두 곳에서 같은 어휘 자산을 쓴다.

1. **Whisper 프라이밍** — `prompt` 파라미터는 인식 결과를 특정 어휘 쪽으로
   편향시킨다. 방언 사전의 사투리 표기를 미리 물려주면 "고이가꼬", "우얀노"
   같은 표현이 표준어로 뭉개지는 것을 줄일 수 있다.
2. **후보 재점수화** — 브라우저 Web Speech 가 여러 후보를 줄 때, 사투리·경북
   지명·민원 용어가 많이 든 후보를 고른다. 브라우저 인식기는 표준어에 맞춰져
   있어 1순위 후보가 사투리를 엉뚱하게 받아쓰는 일이 잦다.

어느 쪽이든 **P5 사전이 없으면 내장 목록으로 폴백한다.** 사전은 개발 중에
생겨날 수 있으므로 실패를 짧게만 캐시한다.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

log = logging.getLogger("voisso.voice.vocabulary")

# 민원 통화에서 실제로 나올 법한 순서. 앞쪽 도메인이 프라이밍에 먼저 들어간다.
DOMAIN_PRIORITY = (
    "물·상하수",
    "도로",
    "주거",
    "마을행정",
    "교통",
    "신청·서류",
    "날씨",
    "농사",
    "사물",
    "시간",
    "보건의료",
    "사람",
    "일반",
)

# 사투리 어미. Whisper 가 가장 자주 표준어로 뭉개는 부분이라 프라이밍에서
# 우선순위가 가장 높다. P5 의 to_dialect 규칙에서 뽑되, 없으면 이 목록을 쓴다.
FALLBACK_ENDINGS = (
    "습니더", "습니꺼", "습니껴", "입니더", "이라예", "하이소", "주이소",
    "인교", "니껴", "그예", "어예", "가꼬", "카이", "카노", "노", "예",
)

# P5 사전이 없을 때 쓰는 최소 폴백. 사전이 붙으면 이것보다 훨씬 풍부해진다.
FALLBACK_DIALECT_TERMS = (
    "고이가꼬", "우얀노", "그카이", "머라카노", "안됩니더", "그랬어예",
    "입니더", "하이소", "주이소", "인교", "니껴", "예예",
    "또랑", "새미", "구녕", "우째", "쪼매", "억수로", "디게",
)

# 경상북도 22개 시군. voisso.agent.slots 가 원본이고 여기서는 폴백만 둔다.
FALLBACK_PLACES = (
    "포항시", "경주시", "김천시", "안동시", "구미시", "영주시", "영천시",
    "상주시", "문경시", "경산시", "의성군", "청송군", "영양군", "영덕군",
    "청도군", "고령군", "성주군", "칠곡군", "예천군", "봉화군", "울진군", "울릉군",
)

# 민원 접수에서 반복적으로 나오는 행정·생활 용어.
DOMAIN_TERMS = (
    "배수", "하수구", "하수도", "우수관", "침수", "물이 안 빠져", "역류", "맨홀",
    "도로", "포장", "아스팔트", "구멍", "패였", "인도", "보도블록",
    "가로등", "신호등", "축대", "옹벽", "무너",
    "수돗물", "상수도", "단수", "녹물",
    "쓰레기", "폐기물", "분리수거", "악취",
    "농로", "저수지", "수리시설",
    "버스", "노선", "정류장",
    "민원", "접수", "신고", "담당", "면사무소", "읍사무소", "군청", "시청", "도청",
)

_MISS_TTL_SEC = 10.0
_cache: dict[str, Any] = {}
_missed_at: dict[str, float] = {}


def _dialect_module():
    """P5 사전 모듈. 없으면 None (실패는 짧게만 캐시한다)."""
    cached = _cache.get("dialect_module")
    if cached is not None:
        return cached
    missed = _missed_at.get("dialect_module")
    if missed is not None and (time.monotonic() - missed) < _MISS_TTL_SEC:
        return None
    try:
        import voisso.dialect as module

        module.entries  # 존재 확인
    except (ImportError, AttributeError):
        _missed_at["dialect_module"] = time.monotonic()
        return None
    _cache["dialect_module"] = module
    _missed_at.pop("dialect_module", None)
    return module


def dialect_terms() -> list[str]:
    """사투리 표기 목록. 민원 도메인 어휘가 앞으로 온다."""
    module = _dialect_module()
    if module is None:
        return list(FALLBACK_DIALECT_TERMS)

    try:
        entries = module.entries()
    except Exception:
        log.exception("voisso.dialect.entries() 실패 — 내장 목록으로 폴백")
        return list(FALLBACK_DIALECT_TERMS)

    def rank(entry: dict[str, Any]) -> tuple[int, int]:
        # 민원 도메인용으로 큐레이션된 항목을 최우선으로.
        curated = 0 if "민원" in str(entry.get("source") or "") else 1
        domain = str(entry.get("domain") or "")
        try:
            order = DOMAIN_PRIORITY.index(domain)
        except ValueError:
            order = len(DOMAIN_PRIORITY)
        return (curated, order)

    terms: list[str] = []
    seen: set[str] = set()
    for entry in sorted(entries, key=rank):
        term = str(entry.get("dialect") or "").strip()
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms or list(FALLBACK_DIALECT_TERMS)


def dialect_endings() -> list[str]:
    """사투리 어미 목록.

    P5 의 `to_dialect` 규칙에서 뽑는다. 그쪽 `replace` 는 정규식이 아니라
    치환될 문자열 리터럴이라 그대로 어휘로 쓸 수 있다.
    (`to_standard` 쪽 `pattern` 은 룩어헤드가 붙은 정규식이라 부적합하다.)
    """
    cached = _cache.get("endings")
    if cached:
        return cached

    module = _dialect_module()
    endings: list[str] = []
    if module is not None:
        try:
            seen: set[str] = set()
            for rule in module.rules():
                if str(rule.get("dir")) != "to_dialect":
                    continue
                value = str(rule.get("replace") or "").strip()
                # 정규식 역참조(\1 등)가 든 치환은 어휘로 쓸 수 없다.
                if value and "\\" not in value and value not in seen:
                    seen.add(value)
                    endings.append(value)
        except Exception:
            log.exception("voisso.dialect.rules() 실패 — 내장 어미 목록으로 폴백")
            endings = []

    result = endings or list(FALLBACK_ENDINGS)
    # 긴 어미가 더 변별력이 높다.
    result.sort(key=len, reverse=True)
    _cache["endings"] = result
    return result


def place_terms() -> list[str]:
    """경북 시군 이름. 원본은 voisso.agent.slots 가 들고 있다."""
    cached = _cache.get("places")
    if cached:
        return cached
    try:
        # 지연 import — voice 계층이 agent 계층에 import 시점 의존하지 않게 한다.
        from voisso.agent.slots import GB_CITIES

        places = list(GB_CITIES)
    except Exception:
        places = list(FALLBACK_PLACES)
    _cache["places"] = places
    return places


def _estimate_tokens(text: str) -> int:
    """토큰 수 어림값.

    정확히 세려면 토크나이저가 필요한데, 그것 하나 때문에 의존성을 늘리지
    않는다(계약서 6절). 한국어는 글자당 토큰이 1을 넘는 경우가 흔하므로
    **넉넉하게 잡아** 잘라낸다. 과소평가해서 API 가 프롬프트를 잘라먹는 것보다
    조금 덜 넣는 편이 안전하다.
    """
    return int(len(text) * 1.5) + 1


def build_priming_prompt(max_tokens: int, lead: str = "") -> tuple[str, bool]:
    """프라이밍 프롬프트를 만든다. `(프롬프트, 잘렸는지)` 를 돌려준다.

    Whisper 의 prompt 는 '앞선 발화'처럼 취급되므로, 목록만 나열하기보다
    자연스러운 문장으로 시작하는 편이 낫다.
    """
    head = lead or (
        "경상북도 주민이 도청에 전화로 민원을 접수하는 통화입니다. "
        "경상도 사투리가 섞여 나옵니다."
    )

    # 그룹을 번갈아 가며 넣는다. 순서대로 채우면 예산이 빠듯할 때
    # (whisper-1 의 224 토큰) 지명만 들어가고 정작 중요한 사투리 어미가
    # 하나도 안 들어간다.
    groups: list[list[str]] = [
        list(dialect_endings()),
        list(place_terms()),
        list(DOMAIN_TERMS),
        list(dialect_terms()),
    ]

    parts = [head]
    used = _estimate_tokens(head)
    truncated = False
    seen: set[str] = set()
    cursors = [0] * len(groups)

    while True:
        placed_any = False
        for index, group in enumerate(groups):
            cursor = cursors[index]
            if cursor >= len(group):
                continue
            term = group[cursor]
            cursors[index] = cursor + 1
            if term in seen:
                placed_any = True  # 건너뛴 것도 진행으로 친다
                continue
            piece = f" {term},"
            cost = _estimate_tokens(piece)
            if used + cost > max_tokens:
                truncated = True
                break
            seen.add(term)
            parts.append(piece)
            used += cost
            placed_any = True
        if truncated or not placed_any:
            break

    prompt = "".join(parts).rstrip(" ,")
    return prompt, truncated


def score_transcript(text: str) -> float:
    """이 문장이 '경북 어르신의 민원 발화'다울수록 높은 점수.

    후보 재점수화용이다. 절대값에는 의미가 없고 후보 간 비교에만 쓴다.
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0
    # 지명은 가장 강한 신호다. 민원 접수에서 위치는 반드시 나온다.
    for place in place_terms():
        if place in text or place[:-1] in text:
            score += 3.0
            break

    for term in DOMAIN_TERMS:
        if term in text:
            score += 1.5

    # 사투리 어미가 후보를 가르는 핵심이다. 브라우저 인식기는 표준어에
    # 맞춰져 있어 "입니더"를 "입니다"로 바꿔 놓는 일이 잦은데, 그 차이가
    # 바로 여기서 잡힌다. 어미는 문장 끝에 한 번 나오므로 한 번만 센다.
    for ending in dialect_endings():
        if len(ending) >= 2 and ending in text:
            score += 2.5
            break

    hits = 0
    for term in dialect_terms():
        # 1글자 항목은 우연히 걸리기 쉬워 세지 않는다.
        if len(term) >= 2 and term in text:
            hits += 1
            if hits >= 6:  # 한 문장에서 과도하게 누적되는 것을 막는다
                break
    score += hits * 1.0

    return score


def vocabulary_status() -> dict[str, Any]:
    """어떤 어휘 자산이 붙어 있는지(헬스체크용)."""
    module = _dialect_module()
    terms = dialect_terms()
    return {
        "dialect_lexicon": module is not None,
        "dialect_terms": len(terms),
        "dialect_endings": len(dialect_endings()),
        "places": len(place_terms()),
        "domain_terms": len(DOMAIN_TERMS),
        "source": "voisso.dialect" if module is not None else "내장 폴백",
    }
