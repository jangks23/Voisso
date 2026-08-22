"""담당자 핸드오프 — AI 가 접수하고 사람이 이어받는다.

공공기관은 AI 에게 전권을 주지 않는다. 접수까지는 AI, 그다음은 담당자가
책임지는 구조라야 실제로 채택된다. 이 모듈은 그 인계 지점을 담당한다.

**양방향 통역이 핵심이다.**

    담당자(표준어 입력) --to_dialect()--> 어르신 화면(사투리)
    어르신(사투리 발화) --normalize()---> 담당자 화면(표준어)

모든 메시지는 `dialect` 와 `standard` 를 **둘 다** 담는다. 어느 쪽 화면에서도
원문을 대조할 수 있어야 통역 결과를 믿을 수 있다.

방언 사전이 'AI 응답을 사투리로 바꾸는 장치'에서 **'사람과 사람 사이의 통역기'**
로 확장되는 지점이다. 담당자가 경상도 사람이 아니어도 어르신과 대화할 수 있다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import integrations
from .complaint import mask_name

# 계약서 5-B 의 상태값.
STATUS_NONE = "none"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

ROLE_OFFICER = "officer"
ROLE_CALLER = "caller"
VALID_ROLES = (ROLE_OFFICER, ROLE_CALLER)

# 핸드오프가 열릴 때 통화 화면에 띄우는 안내.
# **누가 말하고 있는지 헷갈리면 그 자체가 신뢰 문제다.**
HANDOFF_NOTICE = "지금부터 담당자가 직접 응대합니다."


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def translate(role: str, text: str) -> tuple[str, str]:
    """`(dialect, standard)` 를 만든다.

    입력이 어느 쪽 언어인지는 **누가 말했느냐**로 정해진다.
    - 담당자는 표준어로 친다 -> 사투리를 만들어 어르신에게 보인다.
    - 어르신은 사투리로 말한다 -> 표준어를 만들어 담당자에게 보인다.

    P5 방언 모듈이 없으면 두 값이 같아진다(항등 통과). 기능이 죽지는 않는다.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return "", ""
    if role == ROLE_OFFICER:
        return integrations.to_dialect(cleaned), cleaned
    return cleaned, integrations.normalize(cleaned)


@dataclass
class HandoffMessage:
    """계약서 5-B 의 메시지 한 건."""

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
class Handoff:
    """민원 한 건에 붙는 담당자 대화 채널."""

    complaint_id: str
    channel_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = STATUS_OPEN
    # **담당자 실명은 저장하지 않는다.** 도청 공개 데이터에 담당자 실명이
    # 없다는 원칙과 일관되게, 마스킹된 표시용 이름만 남긴다.
    officer_name_masked: str = ""
    officer_department: str = ""
    started_at: str = field(default_factory=_utc_now_iso)
    closed_at: str | None = None
    messages: list[HandoffMessage] = field(default_factory=list)

    @classmethod
    def open(cls, complaint_id: str, officer_name: str, department: str) -> Handoff:
        return cls(
            complaint_id=complaint_id,
            officer_name_masked=mask_name(officer_name),
            officer_department=(department or "").strip(),
        )

    def add_message(self, role: str, text: str) -> HandoffMessage:
        dialect, standard = translate(role, text)
        message = HandoffMessage(
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
    def is_open(self) -> bool:
        return self.status == STATUS_OPEN

    def as_dict(self) -> dict[str, Any]:
        """계약서 5-B 의 GET 응답 형태."""
        return {
            "status": self.status,
            "channel_id": self.channel_id,
            "complaint_id": self.complaint_id,
            "officer": {
                # 마스킹된 값이다. 실명은 어디에도 저장하지 않는다.
                "name": self.officer_name_masked,
                "department": self.officer_department,
            },
            "started_at": self.started_at,
            "closed_at": self.closed_at,
            "notice": HANDOFF_NOTICE,
            "messages": [m.as_dict() for m in self.messages],
        }

    # -- 직렬화 -----------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        return {
            "complaint_id": self.complaint_id,
            "channel_id": self.channel_id,
            "status": self.status,
            "officer_name_masked": self.officer_name_masked,
            "officer_department": self.officer_department,
            "started_at": self.started_at,
            "closed_at": self.closed_at,
            "messages": [m.as_dict() for m in self.messages],
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Handoff:
        handoff = cls(
            complaint_id=str(payload.get("complaint_id") or ""),
            channel_id=str(payload.get("channel_id") or uuid.uuid4().hex),
            status=str(payload.get("status") or STATUS_OPEN),
            officer_name_masked=str(payload.get("officer_name_masked") or ""),
            officer_department=str(payload.get("officer_department") or ""),
            started_at=str(payload.get("started_at") or _utc_now_iso()),
            closed_at=payload.get("closed_at"),
        )
        for raw in payload.get("messages") or []:
            handoff.messages.append(
                HandoffMessage(
                    role=str(raw.get("role") or ROLE_CALLER),
                    text=str(raw.get("text") or ""),
                    dialect=str(raw.get("dialect") or ""),
                    standard=str(raw.get("standard") or ""),
                    at=str(raw.get("at") or ""),
                )
            )
        return handoff


def empty_status(complaint_id: str) -> dict[str, Any]:
    """아직 핸드오프가 없는 민원의 응답."""
    return {
        "status": STATUS_NONE,
        "channel_id": None,
        "complaint_id": complaint_id,
        "officer": {"name": "", "department": ""},
        "started_at": None,
        "closed_at": None,
        "notice": "",
        "messages": [],
    }
