"""MCP SDK 없이 동작하는 최소 stdio 구현.

MCP 는 JSON-RPC 2.0 을 개행 구분 stdio 로 주고받는 프로토콜이다. 이 서버가
쓰는 범위(initialize / tools/list / tools/call / ping)는 표준 라이브러리만으로
충분히 구현된다. `pip install mcp` 없이도 Claude Desktop 이 붙게 하려는
용도이며, SDK 가 설치돼 있으면 이 파일은 쓰이지 않는다.

지원 메서드:
    initialize, notifications/initialized, ping,
    tools/list, tools/call, shutdown
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import SERVER_NAME, __version__
from .tools import TOOLS, call_tool

PROTOCOL_VERSION = "2025-06-18"

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INTERNAL_ERROR = -32603


def _write(stream, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stream.flush()


def _ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tools_payload() -> list[dict[str, Any]]:
    return [
        {
            "name": t["name"],
            "title": t.get("title", t["name"]),
            "description": t["description"],
            "inputSchema": t["inputSchema"],
        }
        for t in TOOLS
    ]


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """JSON-RPC 요청 하나를 처리한다. 알림(notification)이면 None."""
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    if method is None:
        return _err(req_id, _INVALID_REQUEST, "method 가 없습니다.")

    if req_id is None:  # notification
        return None

    if method == "initialize":
        from .server import INSTRUCTIONS

        return _ok(
            req_id,
            {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": INSTRUCTIONS,
            },
        )

    if method == "ping":
        return _ok(req_id, {})

    if method in ("tools/list", "tools/listChanged"):
        return _ok(req_id, {"tools": _tools_payload()})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            payload = call_tool(name, args)
            # 구조화된 오류(데이터 없음 등)도 isError 로 표시한다.
            is_error = bool(payload.get("error"))
        except Exception as exc:
            payload = {"error": str(exc), "tool": name}
            is_error = True
        return _ok(
            req_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
                ],
                "structuredContent": payload,
                "isError": is_error,
            },
        )

    if method == "shutdown":
        return _ok(req_id, {})

    return _err(req_id, _METHOD_NOT_FOUND, f"지원하지 않는 메서드입니다: {method}")


def serve_stdio(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _write(stdout, _err(None, _PARSE_ERROR, f"JSON 파싱 실패: {exc}"))
            continue
        try:
            response = handle(message)
        except Exception as exc:  # 서버는 어떤 경우에도 죽지 않는다
            response = _err(message.get("id"), _INTERNAL_ERROR, str(exc))
        if response is not None:
            _write(stdout, response)
