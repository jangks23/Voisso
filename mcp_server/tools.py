"""MCP 툴 정의 — SDK 비의존 계층.

각 툴은 ``(dict) -> dict`` 순수 함수다. MCP SDK 버전이 바뀌어도 여기는
그대로 두고 ``server.py`` 의 어댑터만 손보면 된다. 셀프테스트도 이 계층을
직접 호출하므로 SDK 없이 전체 동작을 검증할 수 있다.
"""

from __future__ import annotations

from typing import Any, Callable

from voisso import routing

from . import dialect_bridge
from .complaints import ComplaintError, submit_complaint as _submit

# ------------------------------------------------------------------ 스키마

_STR = {"type": "string"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_department",
        "title": "담당 부서 찾기",
        "description": (
            "민원 내용을 경상북도청 담당 부서로 라우팅한다. 각 후보에는 배정 근거가 된 "
            "담당업무/사무분장 원문(evidence)이 함께 온다. confident=false 이면 "
            "단정하지 말고 후보를 함께 제시할 것."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {**_STR, "description": "민원 내용 (표준어 문장 권장)"},
                "top_k": {
                    "type": "integer",
                    "description": "후보 개수 (기본 3, 최대 10)",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_department",
        "title": "부서 상세 조회",
        "description": "부서 id 로 사무분장·직위·담당업무 전체를 조회한다. 전화번호는 토큰으로만 나온다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "department_id": {**_STR, "description": "부서 id (예: gb-6470783-6470793)"},
                "resolve_phone": {
                    "type": "boolean",
                    "description": "true 면 phone_token 을 실제 번호로 변환해 함께 싣는다 "
                    "(매핑이 없으면 경북도청 대표번호 1522-0120)",
                    "default": False,
                },
            },
            "required": ["department_id"],
        },
    },
    {
        "name": "list_departments",
        "title": "부서 목록",
        "description": "경상북도청 본청 부서 목록(요약)을 돌려준다. 이름으로 필터링할 수 있다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contains": {**_STR, "description": "부서명/상위조직명 부분 일치 필터"},
            },
        },
    },
    {
        "name": "normalize_dialect",
        "title": "사투리 → 표준어",
        "description": "경북 사투리 STT 결과를 표준어로 교정한다. (voisso.dialect 위임)",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {**_STR, "description": "사투리 원문"}},
            "required": ["text"],
        },
    },
    {
        "name": "to_dialect",
        "title": "표준어 → 사투리",
        "description": "표준어 문장을 경북 사투리로 바꾼다(TTS 입력용). (voisso.dialect 위임)",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {**_STR, "description": "표준어 문장"}},
            "required": ["text"],
        },
    },
    {
        "name": "submit_complaint",
        "title": "민원카드 접수",
        "description": (
            "계약서 5절 민원카드를 data/complaints/ 에 JSON 으로 저장한다. "
            "assigned.evidence 는 비울 수 없다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "complaint": {
                    "type": "object",
                    "description": "민원카드 (id 생략 시 자동 채번)",
                    "properties": {
                        "id": _STR,
                        "created_at": _STR,
                        "duration_sec": {"type": "number"},
                        "summary": _STR,
                        "category": _STR,
                        "assigned": {
                            "type": "object",
                            "properties": {
                                "department_id": _STR,
                                "full_name": _STR,
                                "phone_token": _STR,
                                "evidence": _STR,
                            },
                            "required": ["department_id", "full_name", "evidence"],
                        },
                        "alternatives": {"type": "array", "items": {"type": "object"}},
                        "caller": {"type": "object"},
                        "transcript": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["summary", "assigned"],
                }
            },
            "required": ["complaint"],
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS]


# ------------------------------------------------------------------ 구현

def _tool_find_department(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query 가 비어 있습니다.")
    top_k = int(args.get("top_k") or 3)
    top_k = max(1, min(top_k, 10))
    return routing.route(query, top_k=top_k)


def _tool_get_department(args: dict[str, Any]) -> dict[str, Any]:
    dept_id = str(args.get("department_id") or "").strip()
    dept = routing.get_department(dept_id)
    if not dept:
        return {"found": False, "department_id": dept_id, "error": "해당 id 의 부서가 없습니다."}
    if args.get("resolve_phone"):
        dept = dict(dept)
        dept["staff"] = [
            {**s, "phone": routing.resolve_phone(s.get("phone_token", ""))}
            for s in dept.get("staff", [])
        ]
    return {"found": True, "department": dept}


def _tool_list_departments(args: dict[str, Any]) -> dict[str, Any]:
    items = routing.list_departments()
    needle = str(args.get("contains") or "").strip()
    if needle:
        items = [d for d in items if needle in d["full_name"] or needle in d["parent"]]
    return {
        "count": len(items),
        "departments": items,
        "data_source": routing.data_source(),
        "is_fixture": routing.is_fixture(),
    }


def _tool_normalize_dialect(args: dict[str, Any]) -> dict[str, Any]:
    return dialect_bridge.normalize_dialect(str(args.get("text") or ""))


def _tool_to_dialect(args: dict[str, Any]) -> dict[str, Any]:
    return dialect_bridge.to_dialect(str(args.get("text") or ""))


def _tool_submit_complaint(args: dict[str, Any]) -> dict[str, Any]:
    card = args.get("complaint")
    if card is None:
        raise ValueError("complaint 가 필요합니다.")
    try:
        result = _submit(card)
    except ComplaintError as exc:
        raise ValueError(str(exc)) from exc
    return {"ok": True, "id": result["id"], "path": result["path"]}


HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "find_department": _tool_find_department,
    "get_department": _tool_get_department,
    "list_departments": _tool_list_departments,
    "normalize_dialect": _tool_normalize_dialect,
    "to_dialect": _tool_to_dialect,
    "submit_complaint": _tool_submit_complaint,
}


def call_tool(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """툴 이름 + 인자 -> 결과 dict. 알 수 없는 툴이면 ValueError."""
    handler = HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"알 수 없는 툴입니다: {name}")
    return handler(args or {})
