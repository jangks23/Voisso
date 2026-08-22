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


# 뒤에서 이만큼은 항상 남긴다. 담당자가 번호를 대조할 수 있어야 한다.
_KEEP_TAIL = 4


def _head_length(digits: str) -> int:
    """앞에서 남길 자릿수. **형태를 가정하지 않고 실제 구성을 본다.**

    - 02 로 시작하면 지역번호가 두 자리다.
    - 그 밖에 0 으로 시작하면 세 자리(010, 031, 054 …).
    - 1 로 시작하는 8자리는 대표번호(1522-0120) 형태다.
    - 나머지(지역번호 없는 8자리 등)는 앞을 남기지 않는다.
      판별이 안 되면 **훼손보다 과한 마스킹이 낫다.**
    """
    if digits.startswith("02"):
        head = 2
    elif digits.startswith("0"):
        head = 3
    elif digits.startswith("1") and len(digits) == 8:
        head = 4
    else:
        head = 0

    # 앞뒤로 남길 것을 합쳐 번호 전체를 덮어 버리면 가려지는 자리가 거의
    # 없어진다(8자리에서 1자리만 가려지는 식). 그럴 때는 앞을 통째로 가린다 —
    # **훼손보다 과한 마스킹이 낫다.**
    if head + _KEEP_TAIL >= len(digits):
        head = 0
    return head


def mask_phone(raw: str) -> str:
    """전화번호의 가운데만 가린다.

    **자릿수와 구분자 위치를 그대로 보존한다.** 예전 구현은 번호가 항상
    `지역번호-국번-가입자번호` 3분할이라고 가정하고 가운데를 별 3개로
    바꿨는데, 그러면 "1234-5678"(8자리)이 "123-***-5678"(10자리처럼 보임)이
    되어 **번호 자체가 훼손됐다.** 담당자가 그 번호로 다시 전화를 걸 수 없다.

        010-1234-5678 -> 010-****-5678
        054-000-4567  -> 054-***-4567
        1234-5678     -> ****-5678
        01012345678   -> 010****5678      (구분자가 없으면 없는 대로)
    """
    source = (raw or "").strip()
    digits = re.sub(r"\D", "", source)
    if len(digits) < 7:
        return ""

    head = _head_length(digits)
    keep_from = len(digits) - _KEEP_TAIL

    out = []
    index = 0
    for char in source:
        if char.isdigit():
            out.append(char if (index < head or index >= keep_from) else "*")
            index += 1
        else:
            # 하이픈·공백·괄호는 위치를 그대로 둔다.
            out.append(char)
    return "".join(out)


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


def resolve_routing_query(llm_query: str, slots: Slots) -> tuple[str, str]:
    """부서 검색에 쓸 질의를 정한다. `(질의, 어떻게 정했는지)`.

    **사전 우선, 미스 시 LLM.** P4 의 개념 사전은 빠르고 결정적이라 먼저 쓴다.
    다만 사전은 구어체에 약하다 — "아 저기 집 앞에 물이 안 빠지고 자꾸 고여서
    큰일이에요" 는 96개 부서 어디에도 안 걸린다(matched_terms 가 비어 나온다).
    그때 LLM 이 뽑아 둔 행정 용어("하수도 배수 불량")로 다시 시도한다.
    경쟁이 아니라 보완이다.
    """
    spoken = " ".join(p for p in (slots.get("what"), slots.get("where")) if p).strip()
    llm_query = (llm_query or "").strip()

    # 1) 사전 먼저 — 발화 그대로 넣어 본다.
    if spoken:
        verdict = integrations.route(spoken)
        if verdict.get("confident"):
            return spoken, "사전(발화 그대로)"

    # 2) 사전이 미스했으면 LLM 이 뽑은 행정 용어로.
    if llm_query:
        verdict = integrations.route(llm_query)
        if verdict.get("confident"):
            return llm_query, "LLM 주제 추출(사전 미스)"
        return llm_query, "LLM 주제 추출(확신 없음)"

    return spoken, "발화 그대로(LLM 질의 없음)"


def build_assignment(
    routing_query: str, slots: Slots
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(assigned, alternatives) 를 만든다."""
    if not integrations.routing_available():
        return _unassigned(slots, "부서 라우팅 모듈 미탑재"), []

    query, how = resolve_routing_query(routing_query, slots)
    if not query:
        return _unassigned(slots, "검색어를 만들지 못했습니다"), []
    log.info("라우팅 질의 '%s' (%s)", query[:60], how)

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
    notes: list[dict[str, Any]] | None = None,
    urgency: dict[str, Any] | None = None,
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
        # 계약서 5-A. 담당자가 무엇을 먼저 볼지 정해 준다.
        "urgency": urgency or {
            "level": "보통",
            "reason": "위험 신호가 없어 정상 처리 일정으로 분류했습니다.",
            "signals": [],
            "decided_by": "rule",
            "safety_referral": None,
            "history": [],
        },
        "assigned": assigned,
        "alternatives": alternatives,
        "caller": {
            "name_masked": mask_name(extract_name(transcript)),
            # 원본 번호는 카드에 넣지 않는다. 마스킹된 값만 저장된다.
            "phone_masked": mask_phone(contact_raw) if contact_raw else "",
        },
        # 슬롯에 안 맞지만 담당자에게 중요한 추가 정보.
        # ("아침에만 그래예", "옆집도 같이 그래예" 같은 것들이 실제로 중요하다)
        "notes": [_clean_note(n) for n in (notes or [])],
        "transcript": [_clean_entry(e) for e in transcript],
    }


def _clean_note(note: dict[str, Any]) -> dict[str, str]:
    """메모도 전화번호를 마스킹해서 저장한다."""
    return {
        "text": redact_phones(str(note.get("text") or "").strip()),
        "at": str(note.get("at") or ""),
        "source": str(note.get("source") or "caller"),
    }


def _clean_entry(entry: dict[str, Any]) -> dict[str, str]:
    """계약서에 정의된 키만 남기고, 본문의 전화번호를 마스킹한다."""
    return {
        "role": str(entry.get("role") or "caller"),
        "dialect": redact_phones(str(entry.get("dialect") or "")),
        "standard": redact_phones(str(entry.get("standard") or "")),
    }
