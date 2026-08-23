"""진행 안내 콜백 — **시스템이 먼저 전화를 건다.**

지금 어르신이 민원 진행 상황을 알려면 다시 전화해 ARS 를 또 뚫어야 한다.
우리가 없애려던 벽을 어르신이 다시 만나는 것이다. 방향을 뒤집으면 사라진다.

핸드오프(5-B)와 **같은 인프라를 쓴다.** 채널을 다시 열되, 담당자가 타이핑하는
대신 AI 가 담당자의 글을 사투리로 읽어 준다.

## 안전 설계 — 이 파일에서 가장 중요한 부분

**AI 는 담당자가 쓴 내용만 전달한다.** 브리핑은 LLM 이 생성하지 않는다.
담당자가 쓴 표준어 문장을 `to_dialect()` 로 **변환만** 한다. 생성이 아니라
번역이므로 없는 사실이 끼어들 여지가 구조적으로 없다.

어르신의 추가 질문에도 AI 는 답하지 않는다. 예외는 **이미 확정된 사실**
(접수번호·담당 부서·접수 시점·브리핑 원문)뿐이고, 그 답변조차 LLM 이 아니라
민원카드에서 값을 꺼내 쓰는 고정 문장이다. 그 밖의 질문은 전부
"담당자에게 여쭤보고 다시 연락드릴게예" 로 넘기고 담당자에게 전달한다.

일정·가능 여부를 AI 가 지어내면 그것은 **행정 약속**이 된다.
이 프로젝트가 하지 않기로 한 것을 정면으로 위반하는 일이고, 공공기관은 그런 시스템을 채택하지 않는다.

## 한계 (숨기지 마라)

**실제 전화망(PSTN) 연동은 아직 없다.** 지금은 브라우저에 수신 화면을 띄우는
시뮬레이션이다. 문서와 발표에서 이 점을 그대로 밝힌다.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import integrations
from .complaint import mask_name
from .handoff import ROLE_CALLER, translate

STATUS_NONE = "none"
STATUS_PENDING = "pending"
STATUS_ANSWERED = "answered"
STATUS_CLOSED = "closed"

ROLE_AGENT = "agent"
VALID_ROLES = (ROLE_CALLER, ROLE_AGENT)

# 수신 화면에 띄우는 안내. 어르신 모드 — 짧고 명확하게.
INCOMING_TITLE = "경상북도청에서 전화가 왔습니더"

# 브리핑에 없는 것을 물었을 때. **여기서 지어내면 안 된다.**
DEFER_REPLY = "그건 담당자에게 여쭤보고 다시 연락드리겠습니다."

# PSTN 미연동 사실을 API 응답에도 실어 둔다. 화면과 문서가 어긋나지 않게.
TRANSPORT_NOTE = "브라우저 수신 화면 시뮬레이션 (실제 전화망 연동 아님)"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class CallbackMessage:
    role: str
    text: str
    dialect: str
    standard: str
    at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "dialect": self.dialect,
            "standard": self.standard,
            "at": self.at,
        }


@dataclass
class Callback:
    """민원 한 건에 대한 진행 안내 통화."""

    complaint_id: str
    callback_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = STATUS_PENDING
    # 담당자가 쓴 원문과 그 사투리 변환. **둘 다 보관한다** —
    # 담당자가 "내가 쓴 대로 전달됐는가" 를 확인할 수 있어야 한다.
    briefing_standard: str = ""
    briefing_dialect: str = ""
    officer_name_masked: str = ""
    officer_department: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    answered_at: str | None = None
    closed_at: str | None = None
    messages: list[CallbackMessage] = field(default_factory=list)

    @classmethod
    def schedule(
        cls, complaint_id: str, briefing: str, officer_name: str, department: str
    ) -> Callback:
        text = (briefing or "").strip()
        return cls(
            complaint_id=complaint_id,
            briefing_standard=text,
            # 생성이 아니라 변환이다. 담당자가 안 쓴 말은 들어갈 수 없다.
            briefing_dialect=integrations.to_dialect(text),
            officer_name_masked=mask_name(officer_name),
            officer_department=(department or "").strip(),
        )

    def answer(self) -> CallbackMessage | None:
        """어르신이 전화를 받았다. 브리핑을 첫 발화로 남긴다."""
        if self.status != STATUS_PENDING:
            return None
        self.status = STATUS_ANSWERED
        self.answered_at = _utc_now_iso()
        if not self.briefing_standard:
            return None
        message = CallbackMessage(
            role=ROLE_AGENT,
            text=self.briefing_standard,
            dialect=self.briefing_dialect,
            standard=self.briefing_standard,
            at=_utc_now_iso(),
        )
        self.messages.append(message)
        return message

    def add_message(self, role: str, text: str) -> CallbackMessage:
        dialect, standard = translate(
            # agent 발화는 표준어로 들어와 사투리로 나간다(담당자와 같은 방향).
            "officer" if role == ROLE_AGENT else ROLE_CALLER,
            text,
        )
        message = CallbackMessage(
            role=role,
            text=(text or "").strip(),
            dialect=dialect,
            standard=standard,
            at=_utc_now_iso(),
        )
        self.messages.append(message)
        return message

    def close(self) -> None:
        self.status = STATUS_CLOSED
        self.closed_at = _utc_now_iso()

    @property
    def caller_questions(self) -> list[CallbackMessage]:
        """담당자에게 전달할 어르신의 추가 문의."""
        return [m for m in self.messages if m.role == ROLE_CALLER]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "callback_id": self.callback_id,
            "complaint_id": self.complaint_id,
            "briefing": {"standard": self.briefing_standard, "dialect": self.briefing_dialect},
            "officer": {"name": self.officer_name_masked, "department": self.officer_department},
            "incoming_title": INCOMING_TITLE,
            "transport": TRANSPORT_NOTE,
            "created_at": self.created_at,
            "answered_at": self.answered_at,
            "closed_at": self.closed_at,
            "messages": [m.as_dict() for m in self.messages],
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "complaint_id": self.complaint_id,
            "callback_id": self.callback_id,
            "status": self.status,
            "briefing_standard": self.briefing_standard,
            "briefing_dialect": self.briefing_dialect,
            "officer_name_masked": self.officer_name_masked,
            "officer_department": self.officer_department,
            "created_at": self.created_at,
            "answered_at": self.answered_at,
            "closed_at": self.closed_at,
            "messages": [m.as_dict() for m in self.messages],
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Callback:
        callback = cls(
            complaint_id=str(payload.get("complaint_id") or ""),
            callback_id=str(payload.get("callback_id") or uuid.uuid4().hex),
            status=str(payload.get("status") or STATUS_PENDING),
            briefing_standard=str(payload.get("briefing_standard") or ""),
            briefing_dialect=str(payload.get("briefing_dialect") or ""),
            officer_name_masked=str(payload.get("officer_name_masked") or ""),
            officer_department=str(payload.get("officer_department") or ""),
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            answered_at=payload.get("answered_at"),
            closed_at=payload.get("closed_at"),
        )
        for raw in payload.get("messages") or []:
            callback.messages.append(
                CallbackMessage(
                    role=str(raw.get("role") or ROLE_CALLER),
                    text=str(raw.get("text") or ""),
                    dialect=str(raw.get("dialect") or ""),
                    standard=str(raw.get("standard") or ""),
                    at=str(raw.get("at") or ""),
                )
            )
        return callback


# --------------------------------------------------------------------------
# 확정된 사실만 답하는 응답기 — LLM 을 쓰지 않는다
# --------------------------------------------------------------------------

# 물어본 것이 '이미 확정된 사실'인지 가르는 패턴.
# 여기 없는 것은 전부 담당자에게 넘긴다.
_FACT_PATTERNS = (
    ("complaint_id", re.compile(r"(접수\s*번호|민원\s*번호|번호가\s*몇|접수번호)")),
    ("department", re.compile(r"(어느\s*과|무슨\s*과|어디\s*서|담당\s*(부서|과)|어느\s*부서)")),
    ("received_at", re.compile(r"(언제\s*접수|접수.*언제|신고.*언제)")),
)

# 일정·가능 여부를 묻는 말. **절대 답하지 않는다.**
_PROMISE_RE = re.compile(
    r"(언제|며칠|얼마나|시간|일정|되는\s*지|될까|해\s*주|고쳐|공사|처리.*(되|하)|가능)"
)


def answer_from_facts(question: str, complaint: dict[str, Any] | None) -> str:
    """확정된 사실만 답한다. 나머지는 담당자에게 넘긴다.

    **LLM 을 쓰지 않는다.** 민원카드에서 값을 꺼내 고정 문장에 끼우는 것이
    전부다. 그래서 없는 사실이 생길 수 없다.
    """
    text = (question or "").strip()
    if not text or not complaint:
        return DEFER_REPLY

    # 일정·처리 여부를 묻는 것이면 사실 조회보다 우선해서 넘긴다.
    # ("언제 접수됐어예" 와 "언제 고쳐 주는교" 를 가르는 것보다,
    #  약속으로 읽힐 수 있는 쪽을 넘기는 편이 안전하다.)
    if _PROMISE_RE.search(text):
        for key, pattern in _FACT_PATTERNS:
            if key == "received_at" and pattern.search(text):
                break
        else:
            return DEFER_REPLY

    for key, pattern in _FACT_PATTERNS:
        if not pattern.search(text):
            continue
        if key == "complaint_id":
            return f"접수번호는 {complaint.get('id', '')}번입니다."
        if key == "department":
            name = (complaint.get("assigned") or {}).get("full_name") or ""
            return f"{name}에서 맡고 있습니다." if name else DEFER_REPLY
        if key == "received_at":
            created = str(complaint.get("created_at") or "")
            return f"{created[:10]}에 접수됐습니다." if created else DEFER_REPLY

    return DEFER_REPLY


def empty_status(complaint_id: str) -> dict[str, Any]:
    return {
        "status": STATUS_NONE,
        "callback_id": None,
        "complaint_id": complaint_id,
        "briefing": {"standard": "", "dialect": ""},
        "officer": {"name": "", "department": ""},
        "incoming_title": INCOMING_TITLE,
        "transport": TRANSPORT_NOTE,
        "created_at": None,
        "answered_at": None,
        "closed_at": None,
        "messages": [],
    }
