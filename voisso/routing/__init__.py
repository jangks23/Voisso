"""voisso.routing — 민원 텍스트를 경상북도청 담당 부서로 라우팅한다.

계약서 4절 공개 인터페이스:

    find_department(query: str, top_k: int = 3) -> list[Match]
    get_department(department_id: str) -> dict
    list_departments() -> list[dict]

Match = {"department_id","full_name","position","duty","phone_token","score","evidence"}

evidence 는 **매칭 근거가 된 사무분장/담당업무 원문**이다. 절대 비지 않는다.
(원문에 섞여 있는 전화번호만 privacy.scrub 으로 제거한다.)

부서 데이터가 없으면 빈 결과 대신 :class:`MissingDataError` 를 던진다.
메시지에 크롤러 실행 방법이 들어 있다. 예외를 던지지 않고 상태만 보려면
:func:`data_available` / :func:`data_status` 를 쓴다.
"""

from __future__ import annotations

from typing import Any, TypedDict

from . import concepts, engine, regions
from .dataaccess import (
    FALLBACK_PHONE,
    SCRAPER_CMD,
    MissingDataError,
    data_available,
    data_source,
    data_status,
    is_sample,
    load_departments,
    load_departments_with_source,
    missing_data_message,
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
    "data_available",
    "data_source",
    "data_status",
    "is_sample",
    "lexicon_size",
    "MissingDataError",
    "missing_data_message",
    "FALLBACK_PHONE",
    "SCRAPER_CMD",
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

    # 시군 소관 업무(가로등·주민등록·쓰레기 수거 등)는 도청 사무분장에 없다.
    # 억지로 비슷한 부서를 붙이면 민원인이 두 번 전화하게 된다.
    _hits = concepts.detect(query)
    if concepts.municipal_only(_hits) or concepts.external_only(_hits):
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
    hits = concepts.detect(query)
    matches = find_department(query, top_k=top_k)

    if concepts.external_only(hits):
        labels = ", ".join(dict.fromkeys(h.concept.label for h in hits))
        return {
            "query": query,
            "confident": False,
            "outcome": "external_referral",
            "reason": f"'{labels}' 은(는) 지자체 소관이 아닙니다. 도청 부서를 배정하지 않습니다.",
            "referral": concepts.external_note(hits),
            "next_action": {
                "type": "external_agency",
                "region": "",
                "instruction": concepts.external_note(hits),
                "phone": "119",
                "phone_label": "위험하면 즉시 119",
            },
            "concepts": [h.concept.label for h in hits],
            "grounded": False,
            "matched_terms": [],
            "fallback_phone": FALLBACK_PHONE,
            "matches": [],
            "data_source": data_source(),
            "is_sample": is_sample(),
        }

    if concepts.municipal_only(hits):
        labels = ", ".join(dict.fromkeys(h.concept.label for h in hits))
        action = regions.municipal_next_action(query)
        return {
            "query": query,
            "confident": False,
            "outcome": "municipal_referral",
            "reason": f"'{labels}' 은(는) 경상북도청이 아니라 시·군 소관 업무입니다. "
                      "도청 부서를 배정하지 않습니다.",
            "referral": concepts.referral_note(hits),
            "next_action": action,
            "concepts": [h.concept.label for h in hits],
            "grounded": False,
            "matched_terms": [],
            "fallback_phone": FALLBACK_PHONE,
            "matches": [],
            "data_source": data_source(),
            "is_sample": is_sample(),
        }

    if not matches:
        return {
            "query": query,
            "confident": False,
            "outcome": "no_match",
            "reason": "96개 부서 사무분장 어디에도 일치하는 담당업무가 없습니다. "
                      "추측해서 배정하지 말고 경북도청 대표번호로 안내하세요.",
            "grounded": False,
            "matched_terms": [],
            "concepts": [h.concept.label for h in hits],
            "next_action": {
                "type": "province_main",
                "region": "",
                "instruction": "담당 부서를 특정하지 못했습니다. 추측해서 배정하지 말고 "
                               f"경상북도청 대표번호 {FALLBACK_PHONE} 로 안내하세요.",
                "phone": FALLBACK_PHONE,
                "phone_label": "경상북도청 대표번호",
            },
            "fallback_phone": FALLBACK_PHONE,
            "matches": [],
            "data_source": data_source(),
            "is_sample": is_sample(),
        }

    grounding = _index().grounding(query)
    top = matches[0]["score"]
    margin = top - matches[1]["score"] if len(matches) > 1 else top
    confident = top >= engine.CONFIDENT_SCORE and margin >= engine.CONFIDENT_MARGIN

    unclear = concepts.unresolved_context(hits)
    if unclear is not None:
        # 같은 말이라도 원인에 따라 소관이 갈리는 민원이다. 후보를 함께 낸다.
        confident = False
        reason = (
            f"'{unclear.label}' 은(는) 맥락에 따라 소관이 갈립니다 — "
            f"후보 {len(matches)}곳을 함께 제시하고 담당자가 판단하게 하세요"
        )
    elif not grounding["grounded"]:
        # 민원인이 쓴 말이 96개 부서 사무분장 어디에도 없다. 유사어로 좁힌
        # 결과일 뿐이므로 단정하지 않는다. 모른다고 말할 수 있어야 한다.
        confident = False
        words = ", ".join(grounding["tokens"]) or "(검색어 없음)"
        reason = (
            f"'{words}' 이(가) 도청 사무분장 원문에 없어 유사어로 찾은 결과입니다 — "
            f"직접 근거가 없으니 후보 {len(matches)}곳을 담당자가 확인해야 합니다"
        )
    elif confident:
        reason = f"1순위 점수 {top:.2f}, 2순위와 격차 {margin:.2f} — 단독 배정 가능"
    elif top < engine.CONFIDENT_SCORE:
        reason = f"1순위 점수 {top:.2f}가 낮습니다 — 후보 {len(matches)}곳을 담당자가 확인해야 합니다"
    else:
        reason = f"1·2순위 격차가 {margin:.2f}로 작습니다 — 후보 {len(matches)}곳을 함께 제시하세요"

    top_match = matches[0]
    if confident:
        action = {
            "type": "call_department",
            "region": "",
            "instruction": f"{top_match['full_name']} {top_match['position']} 에게 연결하세요. "
                           "배정 근거(evidence)를 함께 전달하면 담당자가 바로 확인할 수 있습니다.",
            "phone": "",
            "phone_label": top_match["phone_token"],
        }
    elif unclear is not None:
        action = {
            "type": "need_context",
            "region": "",
            "instruction": unclear.needs_context,
            "phone": FALLBACK_PHONE,
            "phone_label": "판단이 안 서면 경상북도청 대표번호",
        }
    else:
        action = {
            "type": "confirm_candidates",
            "region": "",
            "instruction": f"1순위 {top_match['full_name']} 를 포함해 후보 {len(matches)}곳을 "
                           "근거와 함께 제시하고 담당자가 고르게 하세요. 단독 배정하지 마세요.",
            "phone": FALLBACK_PHONE,
            "phone_label": "판단이 안 서면 경상북도청 대표번호",
        }

    notes = concepts.shared_notes(hits)
    result: dict[str, Any] = {
        "query": query,
        "confident": confident,
        "outcome": "department",
        "reason": reason,
        "grounded": grounding["grounded"],
        "matched_terms": grounding["grounded_terms"],
        "concepts": [h.concept.label for h in hits],
        "next_action": action,
        "fallback_phone": FALLBACK_PHONE,
        "matches": matches,
        "data_source": data_source(),
        "is_sample": is_sample(),
    }
    if notes:
        # 도와 시군이 나눠 맡는 업무라는 사실을 담당자에게 알린다.
        result["jurisdiction_note"] = " ".join(notes)
    if concepts.external_hits(hits):
        # 다른 민원과 섞여 들어와도 안전 안내는 절대 빠뜨리지 않는다.
        result["external_referral"] = concepts.external_note(hits)
    return result


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
