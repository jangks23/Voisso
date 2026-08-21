"""Voisso MCP 서버 (stdio transport).

경상북도청 96개 부서의 사무분장·직위·담당업무를 AI 에이전트가 질의할 수 있는
MCP 툴로 노출한다. 홈페이지에는 사람이 눈으로 읽는 HTML 로만 존재하던 자료다.

실행:
    python3 -m mcp_server            # = python3 -m mcp_server.server

MCP SDK(`pip install mcp`)가 있으면 SDK 로 뜨고, 없으면 표준 라이브러리만으로
동일한 JSON-RPC 를 stdio 로 처리한다(`_fallback.py`). 경북도청 인수인계 시
파이썬만 있으면 돌아가야 한다는 전제를 지키기 위한 이중화다.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from voisso import routing

from . import SERVER_NAME, __version__
from .tools import TOOLS, call_tool

INSTRUCTIONS = (
    "경상북도청 본청 부서의 사무분장·담당업무 검색 서버입니다. "
    "민원 내용을 find_department 에 넣으면 담당 부서 후보와 배정 근거(evidence)를 돌려줍니다. "
    "evidence 는 경북도청 홈페이지에 공개된 담당업무 원문이므로 사용자에게 그대로 인용해도 됩니다. "
    "전화번호는 개인정보 보호를 위해 토큰(PHONE_xxxx)으로만 제공되며, "
    "매핑이 없으면 경북도청 대표번호 1522-0120 으로 안내하세요."
)


def _text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ SDK 경로

def _run_with_sdk() -> bool:
    """MCP SDK 로 서버를 띄운다. SDK 가 없거나 API 가 안 맞으면 False."""
    try:
        import anyio
        import mcp.types as types
        from mcp.server import Server
        from mcp.server.models import InitializationOptions
        from mcp.server.stdio import stdio_server
    except Exception:
        return False

    def _tool_objs() -> list[Any]:
        return [
            types.Tool(
                name=t["name"],
                title=t.get("title"),
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in TOOLS
        ]

    def _result(name: str, arguments: dict[str, Any] | None) -> Any:
        try:
            payload = call_tool(name, arguments)
            # call_tool 이 예외를 삼키고 구조화된 오류를 돌려주는 경우
            # (데이터 없음 등)에도 클라이언트에는 오류로 보여야 한다.
            is_error = bool(payload.get("error"))
        except Exception as exc:
            payload = {"error": str(exc), "tool": name}
            is_error = True
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=_text(payload))],
            structuredContent=payload,
            isError=is_error,
        )

    # --- mcp 2.x: 생성자 콜백 방식 -------------------------------------
    try:
        async def on_list_tools(_ctx, _params=None):
            return types.ListToolsResult(tools=_tool_objs())

        async def on_call_tool(_ctx, params):
            return _result(params.name, getattr(params, "arguments", None))

        server = Server(
            SERVER_NAME,
            version=__version__,
            instructions=INSTRUCTIONS,
            on_list_tools=on_list_tools,
            on_call_tool=on_call_tool,
        )
    except TypeError:
        # --- mcp 1.x: 데코레이터 방식 ----------------------------------
        server = Server(SERVER_NAME)

        @server.list_tools()  # type: ignore[attr-defined]
        async def _list_tools():
            return _tool_objs()

        @server.call_tool()  # type: ignore[attr-defined]
        async def _call(name: str, arguments: dict[str, Any] | None):
            try:
                payload = call_tool(name, arguments)
            except Exception as exc:
                payload = {"error": str(exc), "tool": name}
            return [types.TextContent(type="text", text=_text(payload))]

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            try:
                init_options = server.create_initialization_options()
            except Exception:
                init_options = InitializationOptions(
                    server_name=SERVER_NAME,
                    server_version=__version__,
                    capabilities=server.get_capabilities(  # type: ignore[call-arg]
                        notification_options=None, experimental_capabilities={}
                    ),
                )
            await server.run(read_stream, write_stream, init_options)

    anyio.run(_main)
    return True


# ------------------------------------------------------------------ 진입점

def _announce_data_state() -> None:
    """기동 시 데이터 상태를 stderr 에 알린다.

    stdout 은 JSON-RPC 전용이라 아무것도 쓰면 안 된다. 데이터가 없어도
    서버는 정상 기동한다 — 클라이언트가 붙어서 안내 메시지를 받을 수
    있어야 하기 때문이다. 조용히 죽거나 빈 결과를 주지 않는다.
    """
    status = routing.data_status()
    if not status["available"]:
        print("=" * 68, file=sys.stderr)
        print("[voisso-gb] 부서 데이터 없이 기동합니다 — 검색 툴이 동작하지 않습니다.", file=sys.stderr)
        print("=" * 68, file=sys.stderr)
        print(status["message"], file=sys.stderr)
        print("=" * 68, file=sys.stderr)
        return
    if status["is_sample"]:
        print(
            f"[voisso-gb] 합성 샘플 데이터로 기동 ({status['department_count']}개 가상 부서). "
            f"실데이터 수집: {routing.SCRAPER_CMD}",
            file=sys.stderr,
        )
        return
    print(
        f"[voisso-gb] 데이터 {status['department_count']}개 부서 로드 "
        f"(source={status['source']})",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--help" in argv or "-h" in argv:
        print(__doc__)
        print("옵션:")
        print("  --no-sdk   MCP SDK 를 무시하고 내장 stdio 구현으로 실행")
        print("  --check    데이터 상태만 출력하고 종료 (서버를 띄우지 않음)")
        return 0

    if "--check" in argv:
        status = routing.data_status()
        if not status["available"]:
            print(status["message"])
            return 1
        label = "합성 샘플" if status["is_sample"] else "실데이터"
        print(f"데이터 OK — {label} / {status['department_count']}개 부서 / source={status['source']}")
        if status.get("message"):
            print(status["message"])
        return 0

    _announce_data_state()

    if "--no-sdk" not in argv and _run_with_sdk():
        return 0

    from ._fallback import serve_stdio

    serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
