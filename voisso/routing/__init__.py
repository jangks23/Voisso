"""voisso.routing — 민원 텍스트를 경상북도청 담당 부서로 라우팅한다.

계약서 4절 공개 인터페이스:

    find_department(query: str, top_k: int = 3) -> list[Match]
    get_department(department_id: str) -> dict
    list_departments() -> list[dict]

Match = {"department_id","full_name","position","duty","phone_token","score","evidence"}

evidence 는 **매칭 근거가 된 사무분장/담당업무 원문**이다. 절대 비지 않는다.
(원문에 섞여 있는 전화번호만 privacy.scrub 으로 제거한다.)
"""

from __future__ import annotations

from typing import Any, TypedDict

from . import engine
from .dataaccess import (
    FALLBACK_PHONE,
    data_source,
    is_fixture,
    load_departments,
    load_departments_with_source,
    resolve_phone,
)
from .lexicon import lexicon_size
from .privacy import scrub

__all__ = [
    "find_department",
    "get_department",
    "list_departments",
    "route",
    "resolve_phone",
    "load_departments",
    "data_source",
    "is_fixture",
    "lexicon_size",
    "FALLBACK_PHONE",
]


class Match(TypedDict):
    department_id: str
    full_name: str
    position: str
    duty: str
    phone_token: str
    score: float
    evidence: str


def _index() -> engine.RoutingIndex:
    payload, source = load_departments_with_source()
    return engine.get_index(payload, source)


def _pick_staff(dept: dict, *units) -> dict:
    """Match 에 실을 담당자 1명을 고른다.

    **근거(evidence)를 만든 담당자를 우선한다.** 담당업무가 배정 사유인데
    정작 연결되는 사람이 다른 직원이면 "왜 나한테 보냈나"에 답할 수 없다.
    그래서 evidence 유닛의 직원 → 최고점 직원 → 담당업무가 적힌 첫 직원
    (대개 과장/팀장) 순으로 고른다.
    """
    staff_list = dept.get("staff") or []
    for unit in units:
        if unit is None or unit.staff_idx is None:
            continue
        if 0 <= unit.staff_idx < len(staff_list):
            return staff_list[unit.staff_idx]
    for staff in staff_list:
        if (staff.get("duty") or "").strip():
            return staff
    return staff_list[0] if staff_list else {}


def find_department(query: str, top_k: int = 3) -> list[Match]:
    """민원 문장 -> 담당 부서 후보 (점수 내림차순, 최대 top_k 개).

    점수가 낮거나 1·2위 격차가 작으면 단정하지 않고 후보를 여러 개 돌려준다.
    확신 여부는 :func:`route` 의 ``confident`` 로 확인할 수 있다.
    """
    top_k = max(1, int(top_k or 1))
    if not query or not query.strip():
        return []

    candidates = _index().search(query, limit=top_k * 4)
    if not candidates:
        return []

    matches: list[Match] = []
    for cand in candidates:
        if cand["score"] < engine.SCORE_FLOOR:
            continue
        dept = cand["dept"]
        evidence_unit = cand["evidence_unit"]
        evidence = scrub(evidence_unit.text) if evidence_unit is not None else ""
        if not evidence:
            evidence = engine.fallback_evidence(dept)

        staff = _pick_staff(dept, evidence_unit, cand["staff_unit"])
        matches.append(
            Match(
                department_id=dept.get("id", ""),
                full_name=dept.get("full_name", "") or dept.get("name", ""),
                position=staff.get("position", "") or "",
                duty=scrub(staff.get("duty", "") or ""),
                phone_token=staff.get("phone_token", "") or "",
                score=round(float(cand["score"]), 4),
                evidence=evidence,
            )
        )
        if len(matches) >= top_k:
            break
    return matches


def route(query: str, top_k: int = 3) -> dict[str, Any]:
    """find_department 결과 + 확신도 판단을 함께 돌려주는 편의 함수.

    MCP 툴과 대시보드가 "AI가 단정했는지 / 후보를 제시했는지"를 구분해
    보여줄 수 있게 한다.
    """
    matches = find_department(query, top_k=top_k)
    if not matches:
        return {
            "query": query,
            "confident": False,
            "reason": "일치하는 사무분장을 찾지 못했습니다. 경북도청 대표번호로 안내하세요.",
            "fallback_phone": FALLBACK_PHONE,
            "matches": [],
            "data_source": data_source(),
            "is_fixture": is_fixture(),
        }

    top = matches[0]["score"]
    margin = top - matches[1]["score"] if len(matches) > 1 else top
    confident = top >= engine.CONFIDENT_SCORE and margin >= engine.CONFIDENT_MARGIN
    if confident:
        reason = f"1순위 점수 {top:.2f}, 2순위와 격차 {margin:.2f} — 단독 배정 가능"
    elif top < engine.CONFIDENT_SCORE:
        reason = f"1순위 점수 {top:.2f}가 낮습니다 — 후보 {len(matches)}곳을 담당자가 확인해야 합니다"
    else:
        reason = f"1·2순위 격차가 {margin:.2f}로 작습니다 — 후보 {len(matches)}곳을 함께 제시하세요"

    return {
        "query": query,
        "confident": confident,
        "reason": reason,
        "fallback_phone": FALLBACK_PHONE,
        "matches": matches,
        "data_source": data_source(),
        "is_fixture": is_fixture(),
    }


def get_department(department_id: str) -> dict:
    """부서 상세. 없으면 빈 dict."""
    payload, _ = load_departments_with_source()
    for dept in payload.get("departments", []):
        if dept.get("id") == department_id:
            out = dict(dept)
            out["duties"] = [scrub(d) for d in dept.get("duties") or []]
            out["staff"] = [
                {**s, "duty": scrub(s.get("duty", ""))} for s in dept.get("staff") or []
            ]
            return out
    return {}


def list_departments() -> list[dict]:
    """부서 목록(요약). 담당업무 원문은 get_department 로 조회한다."""
    payload, _ = load_departments_with_source()
    out: list[dict] = []
    for dept in payload.get("departments", []):
        staff = dept.get("staff") or []
        out.append(
            {
                "id": dept.get("id", ""),
                "name": dept.get("name", ""),
                "parent": dept.get("parent", ""),
                "full_name": dept.get("full_name", ""),
                "duty_count": len(dept.get("duties") or []),
                "staff_count": sum(1 for s in staff if (s.get("duty") or "").strip()),
                "source_url": dept.get("source_url", ""),
            }
        )
    return out
