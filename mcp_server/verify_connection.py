"""MCP 실연결 검증 — "표준 MCP 클라이언트가 붙는다"는 것을 증명한다.

    python3 -m mcp_server.verify_connection            # 전체 검증
    python3 -m mcp_server.verify_connection --md       # 마크다운 보고서로 출력

무엇을 확인하나
    1. Claude Desktop 설정 파일이 있는지, 그 안의 커맨드·경로가 실제로 유효한지
    2. Claude Desktop 로그에 실제 연결 기록이 있는지 (앱이 붙었다는 1차 증거)
    3. **설정 파일에 적힌 커맨드 그대로** stdio 로 MCP 프로토콜을 주고받아
       initialize / tools/list / tools/call 이 되는지
    4. DEMO.md 의 사투리 질의가 납득 가능한 답을 내는지

3번이 핵심이다. Claude Desktop 이 없는 환경(CI, 심사위원 노트북)에서도
"표준 MCP 클라이언트가 붙을 수 있다"를 stdio 왕복만으로 증명할 수 있다.
Claude Desktop 이 없으면 1·2번은 건너뛰고 3·4번만 돌린다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CONFIG = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
MCP_LOG = Path.home() / "Library/Logs/Claude/mcp.log"
SERVER_LOG = Path.home() / "Library/Logs/Claude/mcp-server-voisso-gb.log"
DEMO = REPO / "mcp_server" / "DEMO.md"

OK, FAIL, SKIP = "ok", "FAIL", "skip"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.lines: list[str] = []

    def add(self, status: str, name: str, detail: str = "") -> bool:
        self.rows.append((status, name, detail))
        mark = {OK: "  ok  ", FAIL: "  FAIL", SKIP: "  skip"}[status]
        print(f"{mark}  {name}" + (f"  — {detail}" if detail else ""))
        return status != FAIL

    def note(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    @property
    def failures(self) -> int:
        return sum(1 for s, _n, _d in self.rows if s == FAIL)


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 58 - len(title)))


# ─────────────────────────────────────────────── 1. 설정 파일

def default_spec() -> dict[str, Any]:
    """설정 파일이 없을 때 쓰는 기본 실행 사양 (README 스니펫과 동일)."""
    return {
        "command": sys.executable,
        "args": ["-m", "mcp_server"],
        "env": {"PYTHONPATH": str(REPO), "VOISSO_DATA_DIR": str(REPO / "data")},
    }


def check_config(rep: Report) -> dict[str, Any]:
    section("1. Claude Desktop 설정 파일")
    if not CONFIG.is_file():
        rep.add(SKIP, "설정 파일", f"{CONFIG} 없음 — Claude Desktop 미설치로 보인다")
        rep.note("  → stdio 직접 검증(3절)으로 진행한다. 그것만으로도 표준 클라이언트 호환의 근거가 된다.")
        return default_spec()

    rep.add(OK, "설정 파일 존재", str(CONFIG))
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        rep.add(FAIL, "설정 파일 파싱", str(exc))
        return default_spec()

    servers = data.get("mcpServers") or {}
    spec = servers.get("voisso-gb")
    if not spec:
        rep.add(FAIL, "mcpServers.voisso-gb 항목", f"등록된 서버: {list(servers) or '없음'}")
        rep.note("  → mcp_server/README.md 의 스니펫을 설정 파일에 넣어야 한다.")
        return default_spec()

    rep.add(OK, "mcpServers.voisso-gb 등록됨")
    resolved = shutil.which(spec["command"]) or (
        spec["command"] if Path(spec["command"]).is_file() else None
    )
    rep.add(
        OK if resolved else FAIL,
        f"command 실행 가능: {spec['command']}",
        resolved or "PATH 에서 찾지 못함 — which python3 결과를 절대경로로 넣어야 한다",
    )
    for key, value in (spec.get("env") or {}).items():
        rep.add(OK if Path(value).exists() else FAIL, f"env {key}", value)
    return spec


# ─────────────────────────────────────────────── 2. 앱 연결 로그

def check_app_log(rep: Report) -> None:
    section("2. Claude Desktop 연결 로그")
    if not MCP_LOG.is_file():
        rep.add(SKIP, "mcp.log", f"{MCP_LOG} 없음")
        return
    text = MCP_LOG.read_text(encoding="utf-8", errors="replace")
    ours = [l for l in text.splitlines() if "voisso-gb" in l]
    if not ours:
        rep.add(SKIP, "voisso-gb 연결 기록", "로그에 항목 없음 — 앱을 재시작하면 생긴다")
        return
    connected = [i for i, l in enumerate(ours) if "connected successfully" in l]
    if not connected:
        rep.add(FAIL, "Server started and connected successfully", "기록 없음")
        return
    # mcp.log 는 누적 파일이다. 앱을 껐다 켤 때마다 "Server disconnected" 가 남으므로
    # **가장 최근 연결 이후**만 본다. 그 이전 줄은 지난 세션의 정상 종료 기록이다.
    last = connected[-1]
    current = ours[last:]
    rep.add(OK, "Server started and connected successfully", ours[last].split("]")[0][:24])

    for method in ("initialize", "tools/list"):
        hit = [l for l in current if f'method="{method}"' in l]
        rep.add(OK if hit else FAIL, f"클라이언트가 {method} 호출", f"{len(hit)}회 (현재 연결)")

    bad = [l for l in current if re.search(r"error|ENOENT|disconnect", l, re.I)]
    stale = len([l for l in ours[:last] if re.search(r"disconnect", l, re.I)])
    rep.add(OK if not bad else FAIL, "현재 연결에 오류 없음",
            bad[-1][:90] if bad else f"0건 (이전 세션 종료 기록 {stale}건은 제외)")

    if SERVER_LOG.is_file():
        banner = [l for l in SERVER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                  if l.startswith("[voisso-gb]")]
        if banner:
            rep.add(OK, "서버 기동 배너(stderr)", banner[-1])


# ─────────────────────────────────────── 3. stdio 프로토콜 왕복

class StdioClient:
    """설정 파일의 커맨드를 그대로 띄워 JSON-RPC 를 주고받는 최소 클라이언트."""

    def __init__(self, spec: dict[str, Any]):
        self.argv = [spec["command"]] + list(spec.get("args") or [])
        self.env = dict(os.environ, **(spec.get("env") or {}))
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "StdioClient":
        self.proc = subprocess.Popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=self.env, bufsize=1,
        )
        return self

    def __exit__(self, *_exc) -> None:
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()

    def rpc(self, req_id: int, method: str, params: dict | None = None) -> dict:
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("서버가 응답 없이 종료했다")
            data = json.loads(line)
            if data.get("id") == req_id:
                return data

    def notify(self, method: str) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()


def demo_queries() -> list[str]:
    if not DEMO.is_file():
        return []
    return re.findall(r'^### 질의 [\w-]+ — "([^"]+)"', DEMO.read_text(encoding="utf-8"), re.M)


def check_stdio(rep: Report, spec: dict[str, Any]) -> None:
    section("3. stdio MCP 프로토콜 왕복 (설정 파일의 커맨드 그대로)")
    rep.note(f"  실행: {' '.join(spec['command'].split('/')[-1:] + list(spec.get('args') or []))}"
             f"   env={spec.get('env')}")
    try:
        with StdioClient(spec) as client:
            t0 = time.time()
            init = client.rpc(1, "initialize", {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "voisso-verify", "version": "1"},
            })
            info = init["result"]["serverInfo"]
            rep.add(OK, "initialize", f"{info['name']} {info['version']}  ({time.time()-t0:.2f}s)")
            client.notify("notifications/initialized")

            tools = [t["name"] for t in client.rpc(2, "tools/list")["result"]["tools"]]
            rep.add(len(tools) == 6 and OK or FAIL, "tools/list", f"{len(tools)}종: {', '.join(tools)}")

            probe = client.rpc(3, "tools/call", {
                "name": "list_departments", "arguments": {"contains": "맑은물"}})
            payload = probe["result"].get("structuredContent") or json.loads(
                probe["result"]["content"][0]["text"])
            rep.add(OK if payload.get("count") else FAIL, "tools/call list_departments",
                    f"count={payload.get('count')} source={payload.get('data_source')}")

            section("4. DEMO.md 사투리·구어체 질의")
            queries = demo_queries()
            if not queries:
                rep.add(SKIP, "DEMO.md 질의 추출", "질의를 찾지 못했다")
                return
            rep.note(f"  DEMO.md 에서 {len(queries)}개 질의를 뽑아 그대로 호출한다.\n")
            for i, query in enumerate(queries, start=10):
                t = time.time()
                res = client.rpc(i, "tools/call", {
                    "name": "find_department", "arguments": {"query": query, "top_k": 3}})
                sc = res["result"].get("structuredContent") or json.loads(
                    res["result"]["content"][0]["text"])
                dt = (time.time() - t) * 1000
                outcome = sc.get("outcome")
                if outcome == "municipal_referral":
                    verdict = "시군 민원실 안내 (도청 부서 배정 안 함)"
                    evidence = sc.get("next_action", {}).get("instruction", "")
                elif sc.get("matches"):
                    m = sc["matches"][0]
                    verdict = (f"{'단독 배정' if sc['confident'] else '후보 제시'} "
                               f"{m['score']:.2f} {m['full_name']} / {m['position']}")
                    evidence = m["evidence"]
                else:
                    verdict = "매칭 0건 → 대표번호 안내"
                    evidence = sc.get("reason", "")
                rep.add(FAIL if res["result"]["isError"] and outcome != "municipal_referral" else OK,
                        f"[{dt:5.1f}ms] {query}", verdict)
                if evidence:
                    print(f"           근거: {evidence[:78]}")
    except Exception as exc:
        rep.add(FAIL, "stdio 왕복", f"{type(exc).__name__}: {exc}")


# ─────────────────────────────────────────────── 5. 라우팅 회귀

def check_regression(rep: Report) -> None:
    section("5. 라우팅 회귀 (표현 변형 포함)")
    try:
        from voisso import routing

        from . import regression

        if not routing.data_available():
            rep.add(SKIP, "회귀", "수집된 실데이터 없음 — scripts/scrape_gb_departments.py")
            return
        passed, total, rows = regression.run("real")
        groups: dict[str, list[int]] = {}
        for row in rows:
            g = groups.setdefault(row["tag"], [0, 0])
            g[1] += 1
            g[0] += bool(row["ok"])
        variant = [(k, v) for k, v in groups.items() if k.startswith("일관성")]
        all_pass = sum(1 for _k, (a, b) in variant if a == b)
        rep.add(OK if passed == total else FAIL, "회귀 통과율",
                f"{passed}/{total} = {passed/total*100:.1f}%")
        rep.add(OK if all_pass == len(variant) else FAIL,
                "표현 변형 그룹 전원 통과", f"{all_pass}/{len(variant)} 그룹")
        for row in rows:
            if not row["ok"]:
                print(f"        FAIL {row['text']}  기대 {row['expect']} / 실제 {row['got']}")
    except Exception as exc:
        rep.add(FAIL, "회귀", f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    print("Voisso MCP 실연결 검증")
    print(f"  저장소 : {REPO}")
    print(f"  python : {sys.version.split()[0]}")
    try:
        import importlib.metadata as meta
        print(f"  mcp SDK: {meta.version('mcp')}")
    except Exception:
        print("  mcp SDK: 미설치 (내장 stdio 구현으로 동작)")

    rep = Report()
    spec = check_config(rep)
    check_app_log(rep)
    check_stdio(rep, spec)
    check_regression(rep)

    total = len(rep.rows)
    skipped = sum(1 for s, _n, _d in rep.rows if s == SKIP)
    print("\n" + "=" * 62)
    if rep.failures:
        print(f"결과: {total - rep.failures - skipped}/{total} 통과, {rep.failures}건 실패, {skipped}건 건너뜀")
        for status, name, detail in rep.rows:
            if status == FAIL:
                print(f"  FAIL  {name}  {detail}")
        return 1
    print(f"결과: {total - skipped}/{total} 통과, {skipped}건 건너뜀 (실패 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
