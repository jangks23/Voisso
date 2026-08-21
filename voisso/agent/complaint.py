"""민원카드 생성 — 계약서 5절 스키마.

두 가지가 이 파일의 존재 이유다.

1. **`assigned.evidence` 는 절대 비지 않는다.** 담당 공무원이 "AI가 왜 나한테
   이걸 보냈는지" 확인하는 값이다. 라우팅 모듈이 근거를 안 주면 부서 사무분장
   원문에서 끌어오고, 그것도 없으면 '미배정'이라는 사실 자체를 근거로 적는다.
   빈 문자열로 나가는 경로는 없다.
2. **신고자 연락처는 마스킹해서만 저장한다.** 원본은 카드에 넣지 않는다.
   `caller.phone_masked` 만이 아니라 **통화 기록 본문도 마스킹한다.** 어르신은
   전화번호를 말로 불러 주기 때문에, 그대로 두면 원본이 통화 기록에 그대로
   남는다. 카드는 담당 공무원에게 전달되고 파일로 저장되는 산출물이다.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from . import integrations
from .slots import UNKNOWN, Slots

log = logging.getLogger("voisso.agent.complaint")

ANONYMOUS = "익명"
UNASSIGNED_NAME = "미배정 (수동 배정 필요)"

# 통화 기록 본문에서 전화번호를 찾아내기 위한 패턴.
# 휴대폰(010-...)과 일반전화(054-...)를 모두 잡는다.
_PHONE_IN_TEXT = re.compile(r"(?<!\d)(01[016-9]|0\d{1,2})[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)")

_NAME_PATTERNS = (
    re.compile(r"(?:저는|제가|나는|내가)\s*([가-힣]{2,4})(?:입니다|이라고|라고|이고|예요|이에요|입니더|이라예)"),
    re.compile(r"([가-힣]{2,4})(?:이라고|라고)\s*합니다"),
    re.compile(r"이름은\s*([가-힣]{2,4})"),
)
# 위 패턴에 걸리지만 이름이 아닌 말들.
_NOT_A_NAME = frozenset("사람 주민 어르신 할매 할배 아저씨 아줌마 여기 저기 그거 이거".split())


def mask_phone(raw: str) -> str:
    """010-1234-5678 -> 010-****-5678. 가운데 자리만 가린다."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) < 7:
        return ""
    head = digits[:2] if digits.startswith("02") else digits[:3]
    tail = digits[-4:]
    middle = digits[len(head) : -4]
    return f"{head}-{'*' * max(len(middle), 3)}-{tail}"


def mask_name(raw: str) -> str:
    """김철수 -> 김○○. 성만 남긴다."""
    name = (raw or "").strip()
    if not name:
        return ANONYMOUS
    if len(name) == 1:
        return "○"
    return name[0] + "○" * (len(name) - 1)


def redact_phones(text: str) -> str:
    """본문에 섞여 있는 전화번호를 마스킹된 형태로 바꾼다.

    "010-1234-5678 이라예" -> "010-****-5678 이라예"
    """
    if not text:
        return text
    return _PHONE_IN_TEXT.sub(lambda m: mask_phone(m.group(0)), text)


def extract_name(transcript: list[dict[str, Any]]) -> str:
    """어르신이 스스로 이름을 밝힌 경우에만 잡는다. 캐묻지는 않는다."""
    for entry in transcript:
        if entry.get("role") != "caller":
            continue
        text = entry.get("standard") or entry.get("dialect") or ""
        for pattern in _NAME_PATTERNS:
            match = pattern.search(text)
            if match and match.group(1) not in _NOT_A_NAME:
                return match.group(1)
    return ""


def _evidence_from_match(match: dict[str, Any]) -> str:
    """라우팅 결과에서 근거 문자열을 찾아낸다. 절대 빈 값을 돌려주지 않는다."""
    for key in ("evidence", "duty"):
        value = match.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # 라우팅이 근거를 안 줬으면 부서 사무분장 원문에서 직접 끌어온다.
    department = integrations.get_department(str(match.get("department_id") or ""))
    duties = department.get("duties")
    if isinstance(duties, list):
        joined = " / ".join(str(d).strip() for d in duties if str(d).strip())
        if joined:
            return joined[:500]

    staff = department.get("staff")
    if isinstance(staff, list):
        for member in staff:
            duty = (member or {}).get("duty")
            if isinstance(duty, str) and duty.strip():
                return duty.strip()

    full_name = str(match.get("full_name") or "").strip()
    if full_name:
        return f"부서명 기준 매칭: {full_name} (사무분장 원문 확인 필요)"
    return "매칭 근거 원문을 확인하지 못했습니다. 담당자 확인 필요."


def _unassigned(slots: Slots, reason: str) -> dict[str, Any]:
    """라우팅이 아무 후보도 못 준 경우의 배정 블록."""
    what = slots.get("what") or "통화 기록 참조"
    return {
        "department_id": "",
        "full_name": UNASSIGNED_NAME,
        "phone_token": "",
        # 여기도 비우지 않는다. 담당자에게 '왜 미배정인지'가 곧 근거다.
        "evidence": f"자동 배정 보류({reason}). 접수 내용: {what}",
    }


def build_assignment(
    routing_query: str, slots: Slots
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(assigned, alternatives) 를 만든다."""
    query = (routing_query or "").strip()
    if not query:
        query = " ".join(p for p in (slots.get("what"), slots.get("where")) if p).strip()

    if not integrations.routing_available():
        return _unassigned(slots, "부서 라우팅 모듈 미탑재"), []

    matches = integrations.find_department(query, top_k=3)
    if not matches:
        return _unassigned(slots, f"검색어 '{query[:40]}' 에 대한 후보 없음"), []

    top = matches[0]
    assigned = {
        "department_id": str(top.get("department_id") or ""),
        "full_name": str(top.get("full_name") or "").strip() or UNASSIGNED_NAME,
        "phone_token": str(top.get("phone_token") or ""),
        "evidence": _evidence_from_match(top),
    }

    alternatives = []
    for match in matches[1:]:
        alternatives.append(
            {
                "full_name": str(match.get("full_name") or "").strip(),
                "score": _as_score(match.get("score")),
                "evidence": _evidence_from_match(match),
            }
        )

    return assigned, alternatives


def _as_score(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def build_complaint(
    *,
    complaint_id: str,
    created_at: str,
    duration_sec: int,
    transcript: list[dict[str, Any]],
    slots: Slots,
    summary: str,
    category: str,
    routing_query: str = "",
) -> dict[str, Any]:
    """계약서 5절 민원카드를 만든다. 키 구성은 계약서와 정확히 같다."""
    assigned, alternatives = build_assignment(routing_query, slots)

    # 방어: 어떤 경로로든 evidence 가 비면 그건 버그다. 여기서 막는다.
    if not str(assigned.get("evidence") or "").strip():
        log.error("assigned.evidence 가 비었습니다 — 폴백 근거로 채웁니다. id=%s", complaint_id)
        assigned["evidence"] = _unassigned(slots, "근거 문자열 누락")["evidence"]

    resolved_summary = (summary or "").strip()
    if not resolved_summary:
        parts = [p for p in (slots.get("where"), slots.get("what")) if p]
        resolved_summary = ", ".join(parts) if parts else "통화 내용 확인 필요"

    contact_raw = slots.get("contact")
    return {
        "id": complaint_id,
        "created_at": created_at,
        "duration_sec": int(duration_sec),
        "summary": redact_phones(resolved_summary),
        "category": (category or "").strip() or "기타 민원",
        "assigned": assigned,
        "alternatives": alternatives,
        "caller": {
            "name_masked": mask_name(extract_name(transcript)),
            # 원본 번호는 카드에 넣지 않는다. 마스킹된 값만 저장된다.
            "phone_masked": mask_phone(contact_raw) if contact_raw else "",
        },
        "transcript": [_clean_entry(e) for e in transcript],
    }


def _clean_entry(entry: dict[str, Any]) -> dict[str, str]:
    """계약서에 정의된 키만 남기고, 본문의 전화번호를 마스킹한다."""
    return {
        "role": str(entry.get("role") or "caller"),
        "dialect": redact_phones(str(entry.get("dialect") or "")),
        "standard": redact_phones(str(entry.get("standard") or "")),
    }
