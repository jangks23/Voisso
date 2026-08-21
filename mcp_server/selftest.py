"""pytest 없이 도는 자체 점검.

    python3 -m mcp_server.selftest            # 요약
    python3 -m mcp_server.selftest -v         # 라우팅 상위 후보까지 출력
    python3 -m mcp_server.selftest --no-sdk   # 내장 stdio 구현으로 왕복 검증

점검 항목
    1) 데이터 로딩 (P3 실데이터 / 픽스처 자동 선택)
    2) 라우팅 5개 대표 질의 — evidence 가 비지 않는지, 상위 후보가 납득 가능한지
    3) evidence·duty 에 전화번호가 새지 않는지 (계약서 3절)
    4) get_department / list_departments
    5) 방언 위임 (voisso.dialect 없으면 스텁으로 살아있는지)
    6) 민원카드 저장/재조회 + evidence 누락 시 거부
    7) MCP stdio 왕복 (initialize / tools/list / tools/call)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from voisso import routing
from voisso.routing.privacy import contains_phone

from . import dialect_bridge
from .complaints import ComplaintError, get_complaint, submit_complaint
from .tools import TOOL_NAMES, call_tool

# 검증 질의 -> 상위 후보에 반드시 들어와야 하는 조직 키워드
CASES: list[tuple[str, tuple[str, ...]]] = [
    ("집 앞 하수구가 막혀서 물이 안 빠진다", ("맑은물", "하수", "수자원")),
    ("농로가 무너졌다", ("농업", "농축산", "자연재난")),
    ("버스 노선을 늘려달라", ("교통",)),
    ("일자리 지원 사업 문의", ("일자리", "경제정책노동", "여성가족")),
    ("재난지원금 신청 방법", ("재난", "복지")),
]

_PASS, _FAIL = "PASS", "FAIL"


class Report:
    def __init__(self, verbose: bool = False):
        self.rows: list[tuple[str, str, str]] = []
        self.verbose = verbose

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((_PASS if ok else _FAIL, name, detail))
        mark = "  ok " if ok else "  FAIL"
        print(f"{mark}  {name}" + (f"  — {detail}" if detail else ""))
        return ok

    @property
    def failures(self) -> int:
        return sum(1 for status, _n, _d in self.rows if status == _FAIL)


def _section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


# ------------------------------------------------------------------ 1. 데이터

def check_data(rep: Report) -> None:
    _section("1. 데이터")
    payload = routing.load_departments()
    depts = payload.get("departments", [])
    source = routing.data_source()
    rep.check("부서 데이터 로딩", bool(depts), f"{len(depts)}개 부서 / source={source}")
    if routing.is_fixture():
        print("  주의: 실데이터가 아직 없어 mcp_server/fixtures 픽스처로 동작 중입니다.")
    staff = sum(len(d.get("staff") or []) for d in depts)
    duty_text = sum(1 for d in depts for s in (d.get("staff") or []) if (s.get("duty") or "").strip())
    rep.check("담당업무 원문 존재", duty_text > 0, f"직원 {staff}명 중 담당업무 기재 {duty_text}건")
    rep.check("meta.phone_masked", bool(payload.get("meta", {}).get("phone_masked")), "전화번호 토큰화 표시")


# ------------------------------------------------------------------ 2. 라우팅

def check_routing(rep: Report) -> None:
    _section("2. 라우팅 (대표 질의 5건)")
    for query, expect in CASES:
        result = routing.route(query, top_k=3)
        matches = result["matches"]
        if not rep.check(f"[{query}] 후보 반환", bool(matches)):
            continue

        top = matches[0]
        joined = " ".join(m["full_name"] for m in matches)
        rep.check(
            f"[{query}] 기대 부서군 포함",
            any(k in joined for k in expect),
            f"1위 {top['full_name']} ({top['score']:.3f}), {'단독배정' if result['confident'] else '후보제시'}",
        )
        rep.check(
            f"[{query}] evidence 비어있지 않음",
            all(m["evidence"].strip() for m in matches),
            f"1위 근거: {top['evidence'][:60]}",
        )
        if rep.verbose:
            for i, m in enumerate(matches, 1):
                print(f"        {i}. {m['score']:.3f}  {m['full_name']} / {m['position']}")
                print(f"           ↳ {m['evidence'][:100]}")

    rep.check("빈 질의는 빈 결과", routing.find_department("") == [])
    rep.check("top_k 존중", len(routing.find_department("민원", top_k=2)) <= 2)


# ------------------------------------------------------------------ 3. 개인정보

def check_privacy(rep: Report) -> None:
    _section("3. 개인정보 (계약서 3절)")
    leaks: list[str] = []
    probes = [q for q, _ in CASES] + ["소방 화재 신고", "구급차 이송", "재난 대응 상황실"]
    for query in probes:
        for m in routing.find_department(query, top_k=5):
            for field in ("evidence", "duty"):
                if contains_phone(m[field]):
                    leaks.append(f"{m['full_name']}.{field}: {m[field][:60]}")
    rep.check("라우팅 출력에 전화번호 없음", not leaks, leaks[0] if leaks else "5개 질의 x 상위 5건 검사")

    token_leaks = [
        d["full_name"]
        for d in routing.list_departments()[:5]
        if any(k for k in d if k == "phone")
    ]
    rep.check("목록 API 에 실번호 필드 없음", not token_leaks)

    phone = routing.resolve_phone("PHONE_XXXX_NOT_EXIST")
    rep.check("미매핑 토큰은 대표번호 폴백", phone == routing.FALLBACK_PHONE, phone)


# ------------------------------------------------------------------ 4. 조회 API

def check_lookup(rep: Report) -> None:
    _section("4. 조회 API")
    items = routing.list_departments()
    rep.check("list_departments()", len(items) > 0, f"{len(items)}개")
    target = next((d for d in items if d["staff_count"] > 0), items[0] if items else None)
    if target is None:
        rep.check("get_department()", False, "부서가 없습니다")
        return
    dept = routing.get_department(target["id"])
    rep.check("get_department()", dept.get("id") == target["id"], dept.get("full_name", ""))
    rep.check("없는 id 는 빈 dict", routing.get_department("gb-존재하지-않음") == {})


# ------------------------------------------------------------------ 5. 방언

def check_dialect(rep: Report) -> None:
    _section("5. 방언 위임 (P5)")
    status = dialect_bridge.status()
    out = call_tool("normalize_dialect", {"text": "하수구가 막혔어예"})
    rep.check(
        "normalize_dialect 응답",
        "text" in out,
        "voisso.dialect 연결됨" if status["available"] else "미탑재 → 스텁 반환 (서버 정상)",
    )
    out2 = call_tool("to_dialect", {"text": "하수구가 막혔습니다"})
    rep.check("to_dialect 응답", "text" in out2, out2.get("note", out2.get("text", ""))[:60])


# ------------------------------------------------------------------ 6. 민원카드

def check_complaints(rep: Report) -> None:
    _section("6. 민원카드 저장")
    tmpdir = tempfile.mkdtemp(prefix="voisso-selftest-")
    prev = os.environ.get("VOISSO_COMPLAINTS_DIR")
    os.environ["VOISSO_COMPLAINTS_DIR"] = tmpdir
    try:
        match = routing.find_department("집 앞 하수구가 막혀서 물이 안 빠진다", top_k=3)
        top = match[0]
        card: dict[str, Any] = {
            "summary": "주택가 배수 불량, 강우 시 침수 반복",
            "category": "하수·배수 유지관리",
            "duration_sec": 108,
            "assigned": {
                "department_id": top["department_id"],
                "full_name": top["full_name"],
                "phone_token": top["phone_token"],
                "evidence": top["evidence"],
            },
            "alternatives": [
                {"full_name": m["full_name"], "score": m["score"], "evidence": m["evidence"]}
                for m in match[1:]
            ],
            "caller": {"name_masked": "김○○", "phone_masked": "010-****-1234"},
            "transcript": [{"role": "caller", "dialect": "하수구가 막혔어예", "standard": "하수구가 막혔습니다"}],
        }
        saved = call_tool("submit_complaint", {"complaint": card})
        rep.check("민원카드 저장", saved.get("ok") is True, f"id={saved.get('id')}")

        reread = get_complaint(saved["id"])
        rep.check("저장본 재조회", reread.get("id") == saved["id"])
        rep.check(
            "assigned.evidence 보존",
            bool(reread.get("assigned", {}).get("evidence", "").strip()),
            reread.get("assigned", {}).get("evidence", "")[:60],
        )

        bad = dict(card)
        bad["assigned"] = {**card["assigned"], "evidence": ""}
        try:
            submit_complaint(bad)
            rep.check("evidence 없는 카드 거부", False, "거부되지 않았습니다")
        except ComplaintError as exc:
            rep.check("evidence 없는 카드 거부", True, str(exc)[:60])
    finally:
        if prev is None:
            os.environ.pop("VOISSO_COMPLAINTS_DIR", None)
        else:
            os.environ["VOISSO_COMPLAINTS_DIR"] = prev
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------------------ 7. stdio

def check_stdio(rep: Report, no_sdk: bool) -> None:
    _section("7. MCP stdio 왕복" + (" (내장 구현)" if no_sdk else ""))
    argv = [sys.executable, "-m", "mcp_server"] + (["--no-sdk"] if no_sdk else [])
    env = dict(os.environ)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, bufsize=1,
    )
    try:
        def rpc(req_id: int, method: str, params: dict | None = None) -> dict:
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params:
                msg["params"] = params
            proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("서버가 응답 없이 종료했습니다")
                data = json.loads(line)
                if data.get("id") == req_id:
                    return data

        init = rpc(1, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "voisso-selftest", "version": "1"},
        })
        rep.check("initialize", init["result"]["serverInfo"]["name"] == "voisso-gb")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        listed = rpc(2, "tools/list")
        names = [t["name"] for t in listed["result"]["tools"]]
        rep.check("tools/list 6종", sorted(names) == sorted(TOOL_NAMES), ", ".join(names))

        called = rpc(3, "tools/call", {
            "name": "find_department",
            "arguments": {"query": "버스 노선을 늘려달라", "top_k": 1},
        })
        payload = called["result"].get("structuredContent") or json.loads(
            called["result"]["content"][0]["text"]
        )
        rep.check(
            "tools/call find_department",
            bool(payload.get("matches")) and bool(payload["matches"][0]["evidence"]),
            payload["matches"][0]["full_name"] if payload.get("matches") else "결과 없음",
        )
    except Exception as exc:
        rep.check("MCP stdio 왕복", False, str(exc)[:120])
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in argv or "--verbose" in argv
    no_sdk = "--no-sdk" in argv

    print("Voisso MCP 서버 자체 점검")
    print(f"  python  : {sys.version.split()[0]}")
    try:
        import mcp  # noqa: F401
        import importlib.metadata as meta
        print(f"  mcp SDK : {meta.version('mcp')}")
    except Exception:
        print("  mcp SDK : 미설치 (내장 stdio 구현으로 동작)")
        no_sdk = True

    rep = Report(verbose=verbose)
    check_data(rep)
    check_routing(rep)
    check_privacy(rep)
    check_lookup(rep)
    check_dialect(rep)
    check_complaints(rep)
    check_stdio(rep, no_sdk)

    total = len(rep.rows)
    print("\n" + "=" * 64)
    if rep.failures:
        print(f"결과: {total - rep.failures}/{total} 통과, {rep.failures}건 실패")
        for status, name, detail in rep.rows:
            if status == _FAIL:
                print(f"  FAIL  {name}  {detail}")
        return 1
    print(f"결과: {total}/{total} 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
