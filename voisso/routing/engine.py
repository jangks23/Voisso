"""민원 라우팅 랭킹 엔진 — 외부 의존성 없는 문자 n-gram TF-IDF + BM25.

## 왜 이렇게 만들었나

- 형태소 분석기(konlpy/mecab)는 JVM/사전 설치가 필요해 "README만으로 실행"을
  깨뜨린다. 그래서 문자 2~3gram 으로 대체했다. 한국어는 한자어 명사가 겹치는
  경우가 많아("하수구"↔"하수도", "재난지원금"↔"자연재난 피해조사") n-gram 이 잘 듣는다.
- 코사인만 쓰면 짧은 문서("업무 전반")가 과대평가되고, BM25만 쓰면 점수 스케일이
  질의마다 달라져 임계값을 못 잡는다. 둘을 섞어 0~1 로 고정했다.

## 색인 단위 (unit)

부서가 아니라 **문장 단위**로 색인한다. 그래야 evidence 로 쓸 원문이
정확히 어떤 문장이었는지 특정할 수 있다.

  - ``staff`` : 직원 담당업무 1건            (가장 구체적 → evidence 1순위)
  - ``duty``  : 부서 사무분장 1줄
  - ``name``  : 부서명 / 상위조직명

## 부서 점수

  1) 상위 유닛 점수의 감쇠 합 — 한 부서에서 여러 문장이 걸리면 가산
  2) 부서 전체 텍스트의 질의어 커버리지 (idf 가중)
     → "메타버스"만 걸린 인공지능산업과보다, 버스·교통·여객이 두루 걸린
       교통정책과가 위로 올라오게 하는 장치다.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import tokenizer
from . import concepts
from .lexicon import expand_query
from .privacy import scrub

# ------------------------------------------------------------------ 튜닝값

BM25_K1 = 1.4
BM25_B = 0.55
BM25_SAT = 5.0          # BM25 원점수를 0~1 로 눌러주는 포화 상수

W_COSINE = 0.62         # 유닛 점수 = 코사인 + BM25 + 어절 커버리지
W_BM25 = 0.30
W_COVERAGE = 0.08

W_UNITS = 0.74          # 부서 점수 = 유닛 감쇠합 + 부서 커버리지
W_DEPT_COVERAGE = 0.26

# 확장 사전(lexicon)으로만 걸린 부서는 근거가 약하다. 민원인이 실제로 쓴
# 어절이 그 부서 어디에도 없으면 감점한다. "농로 유실"에 대해 "농업기술원
# 이전사업"이 후보로 올라오는 것 같은 사고를 막는다.
UNGROUNDED_PENALTY = 0.62

# 2글자 n-gram 겹침만으로 걸린 유닛은 대개 우연이다.
#   "가로등" vs "가로수"  -> 겹치는 건 '가로' 뿐
#   "카이"(사투리) vs "하이테크" -> 겹치는 건 '하이' 뿐
# 3글자 이상이 걸렸거나 개념 사전이 확인해 준 용어가 걸린 경우만 "실질 매칭"으로 본다.
WEAK_MATCH_PENALTY = 0.25

FIELD_WEIGHT = {"staff": 1.00, "duty": 1.00, "name": 0.85}

# 한 부서 안에서 여러 담당업무가 걸리면 그 부서가 그 일의 주인일 가능성이 높다.
# 반대로 초단문 하나("배수개선사업")만 걸린 부서는 우연히 튀어오를 수 있다.
# 상위 5개 유닛까지 감쇠 합산해, 폭넓게 걸린 부서가 이기게 한다.
UNIT_DECAY = (1.0, 0.28, 0.16, 0.09, 0.05)

# "◦ 하수도팀 업무 전반" 같은 문구는 부서를 맞히는 데는 쓸모 있지만
# evidence 로는 근거가 안 된다. 점수를 약간 깎아 구체적인 문장에 자리를 내준다.
GENERIC_RE = re.compile(r"업무\s*(전반|총괄)|소관\s*업무|업무\s*전반\s*총괄")
GENERIC_PENALTY = 0.80

# evidence 는 점수가 아니라 "민원인이 쓴 말이 원문에 실제로 있는지"로 고른다.
EVIDENCE_EXACT_BONUS = 0.60

# 이보다 낮으면 후보로도 내보내지 않는다. 0.2 미만은 대부분 스쳐간 겹침이라
# 담당자에게 보여줘도 판단에 도움이 안 된다.
SCORE_FLOOR = 0.20
CONFIDENT_MARGIN = 0.10 # 1위-2위 격차가 이보다 작으면 "여러 후보 제시"

# 단정해도 되는 최소 점수. 실데이터(96개 부서)에서 측정해 잡았다.
#   정상 민원 질의 10건  : 0.653 ~ 1.000
#   도청 소관이 아닌 질의 5건: 0.000 ~ 0.312
#     ("심해 잠수정 도색", "화성 이주 신청", "강아지가 아픈데", "빙하 탐사선 견인")
# 두 분포 사이가 비어 있어 그 가운데를 임계값으로 잡았다. 이 아래는
# 후보만 제시하고 단정하지 않는다 — 틀린 부서로 확신에 차 보내는 것보다
# "확실하지 않다"고 말하는 편이 담당자에게 훨씬 낫다.
CONFIDENT_SCORE = 0.48


@dataclass
class _Unit:
    dept_idx: int
    kind: str
    text: str                      # 전화번호만 제거한 사무분장 원문 (= evidence 원본)
    staff_idx: int | None
    tf: Counter = field(default_factory=Counter)
    length: int = 0
    norm: float = 0.0
    generic: bool = False


class RoutingIndex:
    """부서 데이터셋 하나에 대한 역색인."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.departments: list[dict] = payload.get("departments", [])
        self.units: list[_Unit] = []
        self.dept_terms: list[set[str]] = []
        self.df: Counter = Counter()
        self.idf: dict[str, float] = {}
        self.idf_bm: dict[str, float] = {}
        self.avgdl: float = 1.0
        self._build()

    # -------------------------------------------------------------- 색인

    def _add_unit(self, dept_idx: int, kind: str, text: str, staff_idx: int | None = None) -> None:
        # 색인 단계에서 전화번호를 제거한다. 검색어에서도 빠지고, evidence 로
        # 그대로 나가도 안전해진다. (계약서 3절 개인정보 규칙)
        text = scrub(text)
        if not text:
            return
        terms = tokenizer.terms(text)
        if not terms:
            return
        unit = _Unit(
            dept_idx=dept_idx,
            kind=kind,
            text=text,
            staff_idx=staff_idx,
            tf=Counter(terms),
            length=len(terms),
            generic=bool(GENERIC_RE.search(text)),
        )
        self.units.append(unit)

    def _build(self) -> None:
        for i, dept in enumerate(self.departments):
            name_bits = " ".join(b for b in (dept.get("parent"), dept.get("name")) if b)
            self._add_unit(i, "name", name_bits or dept.get("full_name", ""))
            for duty in dept.get("duties") or []:
                self._add_unit(i, "duty", duty)
            for j, staff in enumerate(dept.get("staff") or []):
                self._add_unit(i, "staff", staff.get("duty", ""), staff_idx=j)

        n = max(len(self.units), 1)
        for unit in self.units:
            self.df.update(unit.tf.keys())
        for term, df in self.df.items():
            self.idf[term] = math.log(n / df) + 1.0
            self.idf_bm[term] = math.log(1.0 + (n - df + 0.5) / (df + 0.5))

        self.avgdl = sum(u.length for u in self.units) / n
        for unit in self.units:
            acc = 0.0
            for term, tf in unit.tf.items():
                w = (1.0 + math.log(tf)) * self.idf[term] * tokenizer.term_weight(term)
                acc += w * w
            unit.norm = math.sqrt(acc) or 1.0

        self.dept_terms = [set() for _ in self.departments]
        for unit in self.units:
            self.dept_terms[unit.dept_idx].update(unit.tf.keys())

    # -------------------------------------------------------------- 검색

    def _query_vector(self, query: str) -> tuple[Counter, dict[str, float], float, list[str], set[str], set[str]]:
        """(가중 tf, 코사인 벡터, 노름, 원어절, 접지된 항, 개념 사전이 확인한 항)"""
        base_tokens = tokenizer.analyze(query)
        expanded = expand_query(base_tokens)   # {어절: 가중치}, 원어절은 1.0

        # 개념 사전이 "물이 안 빠진다 = 하수도/배수" 같은 다리를 놓는다.
        # 사람이 검증한 대응이라 우연한 n-gram 겹침보다 높은 가중치를 준다.
        hits = concepts.detect(query)
        concept_tokens = concepts.admin_terms(hits)   # {용어: 가중치}
        for term, weight in concept_tokens.items():
            expanded[term] = max(expanded.get(term, 0.0), weight)

        qtf: Counter = Counter()
        grounded: set[str] = set()
        concept_grams: set[str] = set()
        for token, boost in expanded.items():
            grams = tokenizer.ngrams(token)
            for gram in grams:
                qtf[gram] += boost
            if boost >= 1.0:                   # 민원인이 실제로 말한 어절
                grounded.update(grams)
            if token in concept_tokens:
                concept_grams.update(grams)

        vec: dict[str, float] = {}
        acc = 0.0
        for term, tf in qtf.items():
            idf = self.idf.get(term)
            if idf is None:
                continue                      # 데이터에 없는 항은 버린다
            w = (1.0 + math.log(tf)) * idf * tokenizer.term_weight(term)
            vec[term] = w
            acc += w * w
        keys = vec.keys()
        return qtf, vec, math.sqrt(acc) or 1.0, base_tokens, grounded & keys, concept_grams & keys

    def grounding(self, query: str) -> dict[str, Any]:
        """질의 어절이 사무분장 원문에 실제로 존재하는지 본다.

        하나도 없으면 이 검색은 전적으로 확장 사전(유사어)에 의존한 것이다.
        그런 결과는 절대 단정하면 안 된다.
        """
        _qtf, _vec, _norm, base_tokens, grounded, _concept = self._query_vector(query)
        return {
            "tokens": base_tokens,
            "grounded_terms": sorted(grounded),
            "grounded": bool(grounded),
        }

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """질의 -> 부서 단위 후보 리스트 (점수 내림차순)."""
        qtf, qvec, qnorm, base_tokens, grounded, concept_grams = self._query_vector(query)
        if not qvec:
            return []
        qmass = sum(qvec.values()) or 1.0
        exact_tokens = [t for t in base_tokens if len(t) >= 2]

        per_dept: dict[int, list[tuple[float, _Unit]]] = {}
        strong_depts: set[int] = set()
        for unit in self.units:
            dot = 0.0
            bm = 0.0
            hit = False
            strong = False
            for term, qw in qvec.items():
                tf = unit.tf.get(term)
                if not tf:
                    continue
                hit = True
                if len(term) >= 3 or term in concept_grams:
                    strong = True
                dw = (1.0 + math.log(tf)) * self.idf[term] * tokenizer.term_weight(term)
                dot += qw * dw
                denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * unit.length / self.avgdl)
                bm += self.idf_bm[term] * (tf * (BM25_K1 + 1)) / denom * min(qtf[term], 3.0)
            if not hit:
                continue

            cosine = dot / (qnorm * unit.norm)
            bm_norm = bm / (bm + BM25_SAT)
            cover = _coverage(exact_tokens, unit.text)
            score = W_COSINE * cosine + W_BM25 * bm_norm + W_COVERAGE * cover
            score *= FIELD_WEIGHT.get(unit.kind, 1.0)
            if unit.generic:
                score *= GENERIC_PENALTY
            if not strong:
                # 2글자 겹침만으로 걸렸다. 우연일 가능성이 높다.
                score *= WEAK_MATCH_PENALTY
            per_dept.setdefault(unit.dept_idx, []).append((score, unit))
            if strong:
                strong_depts.add(unit.dept_idx)

        results: list[dict[str, Any]] = []
        for dept_idx, hits in per_dept.items():
            hits.sort(key=lambda p: p[0], reverse=True)

            decayed = sum(
                s * UNIT_DECAY[r] for r, (s, _u) in enumerate(hits[: len(UNIT_DECAY)])
            )
            terms_in_dept = self.dept_terms[dept_idx]
            dept_cover = sum(w for t, w in qvec.items() if t in terms_in_dept) / qmass
            total = min(W_UNITS * decayed + W_DEPT_COVERAGE * dept_cover, 1.0)

            # 부서 커버리지는 유닛 점수와 따로 계산되므로, 유닛에 걸어 둔
            # 짧은-겹침 감점을 우회한다. 질의어가 2글자 겹침으로만 걸린
            # 부서는 커버리지도 신뢰할 수 없다 — 같은 감점을 총점에 적용한다.
            #   "비만 오면 마당에 물이 찬다" 에서 '마당' 하나로 전통시장 부서가
            #   0.30 을 받던 경로가 여기였다.
            if dept_idx not in strong_depts:
                total *= WEAK_MATCH_PENALTY

            # 민원인이 실제로 쓴 어절이 이 부서 어디에도 없으면 확장어만으로
            # 걸린 것이다. 후보로 남기되 아래로 민다.
            is_grounded = bool(grounded & terms_in_dept) if grounded else True
            if not is_grounded:
                total *= UNGROUNDED_PENALTY

            results.append(
                {
                    "dept": self.departments[dept_idx],
                    "score": total,
                    "best_score": hits[0][0],
                    "dept_coverage": dept_cover,
                    "grounded": is_grounded,
                    "evidence_unit": _pick_evidence(hits, exact_tokens),
                    "staff_unit": next((u for _s, u in hits if u.kind == "staff"), None),
                    "hit_count": len(hits),
                }
            )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]


def _coverage(tokens: list[str], text: str) -> float:
    """질의 어절이 원문에 문자열 그대로 등장하는 비율."""
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t in text) / len(tokens)


def _pick_evidence(hits: list[tuple[float, _Unit]], exact_tokens: list[str]) -> _Unit | None:
    """evidence 전용 선택.

    부서를 고르는 점수와 근거를 고르는 기준은 다르다. 담당자가 납득하려면
    "민원인이 말한 단어가 실제로 내 담당업무에 적혀 있어야" 한다. 그래서
    질의 어절이 원문에 그대로 있는 유닛을 우대하고, 부서명 유닛과
    "업무 전반" 류는 내용 있는 문장이 있으면 뒤로 민다.
    """
    if not hits:
        return None
    best = None
    best_key = -1.0
    for score, unit in hits:
        key = score * (1.0 + EVIDENCE_EXACT_BONUS * _coverage(exact_tokens, unit.text))
        if unit.kind == "name":
            key *= 0.5          # 부서명은 근거가 아니다
        if unit.generic:
            key *= 0.85
        if key > best_key:
            best_key, best = key, unit
    return best


# ------------------------------------------------------------ 캐시된 색인

_index_lock = threading.Lock()
_index_cache: dict[str, Any] = {"source": None, "index": None}


def get_index(payload: dict, source: str) -> RoutingIndex:
    with _index_lock:
        if _index_cache["source"] != source or _index_cache["index"] is None:
            _index_cache["index"] = RoutingIndex(payload)
            _index_cache["source"] = source
        return _index_cache["index"]


def fallback_evidence(dept: dict) -> str:
    """어떤 유닛도 못 고른 극단적 상황에서도 evidence 를 비우지 않기 위한 폴백."""
    for duty in dept.get("duties") or []:
        if scrub(duty):
            return scrub(duty)
    for staff in dept.get("staff") or []:
        if scrub(staff.get("duty", "")):
            return scrub(staff["duty"])
    return f"{dept.get('full_name', '')} 소관 업무"
