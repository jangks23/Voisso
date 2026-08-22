"""pytest 없이 도는 자체 점검.

    python3 -m mcp_server.selftest             # 요약
    python3 -m mcp_server.selftest -v          # 라우팅 상위 후보까지 출력
    python3 -m mcp_server.selftest --no-sdk    # 내장 stdio 구현으로 왕복 검증
    python3 -m mcp_server.selftest --real-data # 수집된 실데이터로 검증

기본값은 **합성 샘플**(mcp_server/fixtures/sample_departments.json)이다.
도청 조직도 파생 데이터는 저장소에 커밋하지 않으므로, 새로 clone 한 사람도
아무것도 수집하지 않고 이 셀프테스트를 통과시킬 수 있어야 한다. 샘플의
부서명·담당업무는 전부 가상이며 어떤 공공데이터에서도 파생되지 않았다.

점검 항목
    1) 데이터 로딩 (합성 샘플 기본, --real-data 로 실데이터)
    2) 라우팅 5개 대표 질의 — evidence 가 비지 않는지, 상위 후보가 납득 가능한지
    3) evidence·duty 에 전화번호가 새지 않는지 (계약서 3절)
    4) get_department / list_departments
    5) 방언 위임 (voisso.dialect 없으면 스텁으로 살아있는지)
    6) 민원카드 저장/재조회 + evidence 누락 시 거부
    7) 데이터가 없을 때의 안내 (빈 결과·스택트레이스 대신 실행할 명령 제시)
    8) MCP stdio 왕복 (initialize / tools/list / tools/call)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from voisso import routing
from voisso.routing import concepts, regions
from voisso.routing.dataaccess import SCRAPER_CMD, MissingDataError, sample_path
from voisso.routing.privacy import contains_phone

from . import SERVER_NAME, dialect_bridge
from . import regression
from .complaints import ComplaintError, get_complaint, submit_complaint
from .tools import TOOL_NAMES, call_tool

# 검증 질의 -> 상위 후보에 반드시 들어와야 하는 조직 키워드
# 합성 샘플(가상 부서)로 돌 때 기대하는 부서 키워드
SAMPLE_CASES: list[tuple[str, tuple[str, ...]]] = [
    ("집 앞 하수구가 막혀서 물이 안 빠진다", ("가상수도과",)),
    ("농로가 무너졌다", ("가상농정과",)),
    ("버스 노선을 늘려달라", ("가상교통과",)),
    ("일자리 지원 사업 문의", ("가상일자리과",)),
    ("재난지원금 신청 방법", ("가상재난과",)),
]

# 수집된 실데이터(--real-data)로 돌 때 기대하는 부서 키워드
REAL_CASES: list[tuple[str, tuple[str, ...]]] = [
    ("집 앞 하수구가 막혀서 물이 안 빠진다", ("맑은물", "하수", "수자원")),
    ("농로가 무너졌다", ("농업", "농축산", "자연재난")),
    ("버스 노선을 늘려달라", ("교통",)),
    ("일자리 지원 사업 문의", ("일자리", "경제정책노동", "여성가족")),
    ("재난지원금 신청 방법", ("재난", "복지")),
]

CASES = SAMPLE_CASES

# 사투리 질의는 표준어 질의와 같은 부서로 가야 한다. (query, 표준어 대응)
SAMPLE_DIALECT_PAIRS = [
    ("우리 동네 하수구가 막혔는데 어데 전화하믄 되노?", "하수구가 막혔습니다"),
    ("경로당 지원 사업은 누가 담당하노?", "경로당 지원 사업 문의"),
]
REAL_DIALECT_PAIRS = SAMPLE_DIALECT_PAIRS
DIALECT_PAIRS = SAMPLE_DIALECT_PAIRS

# 사무분장 원문에 존재하지 않는 어휘 -> "모르겠다"고 말해야 하는 질의
UNGROUNDED_QUERY = "빙하 탐사선 견인은 누가 담당하노?"

# 개념 사전 — 행정 용어가 하나도 없는 구어 증상 표현
CONCEPT_PROBES = [
    ("집 앞에 물이 안 빠지고 자꾸 고여서 큰일이에요", "drain_blocked"),
    ("며칠째 수돗물이 안 나옵니다", "water_none"),
    ("농로가 무너져서 트랙터가 못 지나간다", "farm_road"),
    ("밤에 누가 길가에 쓰레기를 몰래 버리고 갑니다", "illegal_dumping"),
    ("멧돼지가 밭에 내려와서 다 망쳐놨어요", "wild_animal"),
]

# 시군 소관 -> 도청 부서를 배정하면 안 되는 질의
MUNICIPAL_PROBES = [
    "우리 동네 가로등이 며칠째 안 들어와요",
    "주민등록등본 떼려면 어디로 가야 되나요?",
    "종량제 봉투는 어디서 사나요?",
]

# 시군 감지 — 지명이 일상어와 겹치는 경우를 특히 본다
REGION_PROBES = [
    ("안동시 옥동인데 가로등이 안 들어와요", "안동시"),
    ("안동 사는데 가로등이", "안동시"),
    ("안동네 골목이 어두워요", None),
    ("울릉도 사는데 종량제 봉투 어디서 사노", "울릉군"),
    ("영양 상태가 안 좋아서 병원 갑니다", None),
    ("영양군에 사는데 가로등이", "영양군"),
    ("고령자 운전면허 반납은 어디서 하나요", None),
    ("우리 동네 가로등이 안 들어와요", None),
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


REPO_ROOT = str(Path(__file__).resolve().parents[1])


def _reset_data_cache() -> None:
    """환경변수를 바꾼 뒤 이전 데이터가 캐시에서 되살아나지 않게 한다."""
    from voisso.routing import dataaccess, engine

    dataaccess._cache.update(key=None, data=None, source=None)
    engine._index_cache.update(source=None, index=None)


def _child_env() -> dict:
    """자식 프로세스가 저장소를 import 할 수 있도록 PYTHONPATH 를 넣는다."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = REPO_ROOT + (os.pathsep + existing if existing else "")
    return env


# ------------------------------------------------------------------ 1. 데이터

def check_data(rep: Report) -> None:
    _section("1. 데이터")
    status = routing.data_status()
    if not rep.check("데이터 사용 가능", status["available"], status.get("next_step", "")):
        print("\n" + status["message"] + "\n")
        return
    payload = routing.load_departments()
    depts = payload.get("departments", [])
    rep.check(
        "부서 데이터 로딩",
        bool(depts),
        f"{len(depts)}개 부서 / source={status['source']}"
        + ("  [합성 샘플]" if status["is_sample"] else "  [실데이터]"),
    )
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

    # 사투리 그대로 넣어도 표준어와 같은 부서로 가야 한다 (STT 원문 직결 대비)
    for dialect, standard in DIALECT_PAIRS:
        d_top = routing.find_department(dialect, top_k=1)
        s_top = routing.find_department(standard, top_k=1)
        rep.check(
            f"[사투리] {dialect}",
            bool(d_top) and bool(s_top) and d_top[0]["department_id"] == s_top[0]["department_id"],
            (d_top[0]["full_name"] + " / " + d_top[0]["evidence"][:40]) if d_top else "후보 없음",
        )

    # 사무분장 원문에 없는 어휘로만 이뤄진 질의는 절대 단정하지 않는다
    unknown = routing.route(UNGROUNDED_QUERY, top_k=3)
    rep.check(
        "근거 없는 질의는 단정하지 않음",
        unknown["grounded"] is False and unknown["confident"] is False,
        unknown["reason"][:70],
    )

    # 개념 사전 — 구어 증상 표현이 행정 용어로 이어지는지
    rep.check("개념 사전 로드", concepts.concept_count() >= 40,
              f"{concepts.concept_count()}개 개념")
    for text, expect_id in CONCEPT_PROBES:
        hits = concepts.detect(text)
        rep.check(
            f"[개념] {text}",
            any(h.id == expect_id for h in hits),
            ", ".join(f"{h.id}({h.matched})" for h in hits) or "감지 없음",
        )

    # 시군 소관 업무는 도청 부서를 배정하지 않는다
    for text in MUNICIPAL_PROBES:
        result = routing.route(text, top_k=3)
        rep.check(
            f"[시군] {text}",
            result.get("outcome") == "municipal_referral" and not result["matches"],
            result.get("reason", "")[:60],
        )

    # 시군 감지 — 지명이 일상어와 겹쳐도 오탐하지 않아야 한다
    rep.check("시군 목록", regions.REGION_COUNT == 22,
              f"{regions.REGION_COUNT}개 (군위군 2023년 대구 편입 반영)")
    for text, expect in REGION_PROBES:
        got = regions.detect(text)
        rep.check(f"[시군] {text}", (got.name if got else None) == expect,
                  f"{got.name if got else '감지 없음'} (기대 {expect or '없음'})")

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


# ------------------------------------------------------------ 6.5 라우팅 회귀

def check_regression(rep: Report, real_data: bool) -> None:
    """라우팅 회귀 — 고친 것이 다음 수정에서 깨지지 않게 붙잡는다.

    실측 실패 케이스 3건, P5 demo_lines 대사(사투리/STT/정규화 3입력),
    시군 소관 질의, 범위 밖 질의를 한 번에 채점한다.
    """
    _section("6.5 라우팅 회귀")
    dataset = "real" if real_data else "sample"
    passed, total, rows = regression.run(dataset)
    if not real_data:
        print("  (합성 샘플 — 부서명 기대값 케이스는 제외하고 관할·범위 판단만 채점)")

    rep.check(
        f"회귀 통과율 {passed}/{total}",
        passed == total,
        "전부 통과" if passed == total else ", ".join(r["text"][:24] for r in rows if not r["ok"]),
    )
    for row in rows:
        if not row["ok"]:
            print(f"        FAIL {row['text']}")
            print(f"             기대 {row['expect']} / 실제 {row['got']}")


# --------------------------------------------------------- 7. 데이터 부재 안내

def check_missing_data(rep: Report) -> None:
    """데이터가 하나도 없는 상태를 재현해 안내가 제대로 나오는지 본다."""
    _section("7. 데이터 부재 안내")
    empty = tempfile.mkdtemp(prefix="voisso-nodata-")
    saved = {k: os.environ.get(k) for k in ("VOISSO_DATA_FILE", "VOISSO_DATA_DIR")}
    try:
        os.environ["VOISSO_DATA_DIR"] = empty
        os.environ["VOISSO_DATA_FILE"] = str(Path(empty) / "없는파일.json")
        _reset_data_cache()

        rep.check("data_available() == False", routing.data_available() is False)

        status = routing.data_status()
        rep.check("data_status() 가 예외 없이 상태 반환", status["available"] is False)
        message = status.get("message", "")
        rep.check(
            "안내에 크롤러 명령 포함",
            SCRAPER_CMD in message,
            SCRAPER_CMD,
        )
        rep.check("안내에 탐색 경로 포함", "탐색한 경로" in message)
        rep.check("안내에 합성 샘플 대안 포함", "sample_departments.json" in message)

        # 빈 결과가 아니라 예외로 알린다
        try:
            routing.find_department("하수구가 막혔다")
            rep.check("find_department 가 조용히 빈 결과를 주지 않음", False, "예외 없이 반환됨")
        except MissingDataError as exc:
            rep.check(
                "find_department 가 MissingDataError",
                SCRAPER_CMD in str(exc),
                str(exc).splitlines()[0],
            )

        # MCP 툴은 스택트레이스 대신 구조화된 안내를 준다
        out = call_tool("find_department", {"query": "하수구가 막혔다"})
        rep.check(
            "MCP 툴이 구조화된 안내 반환",
            out.get("error") == "data_unavailable" and out.get("next_step") == SCRAPER_CMD,
            f"error={out.get('error')} next_step={out.get('next_step')}",
        )
        rep.check("list_departments 도 동일하게 안내",
                  call_tool("list_departments", {}).get("error") == "data_unavailable")

        # MCP 프로토콜 상으로도 오류로 표시돼야 에이전트가 알아챈다
        from ._fallback import handle as _handle

        rpc_out = _handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "find_department", "arguments": {"query": "하수구"}},
        })
        rep.check("tools/call 응답이 isError=true", rpc_out["result"]["isError"] is True)

        # 데이터 없이도 서버는 뜨고, --check 가 안내 후 1로 종료한다
        proc = subprocess.run(
            [sys.executable, "-m", "mcp_server", "--check"],
            capture_output=True, text=True, env=_child_env(), timeout=60,
        )
        rep.check(
            "python3 -m mcp_server --check 안내",
            proc.returncode == 1 and SCRAPER_CMD in proc.stdout,
            (proc.stdout.strip().splitlines() or ["(출력 없음)"])[0],
        )
        rep.check("--check 가 스택트레이스를 뱉지 않음", "Traceback" not in (proc.stdout + proc.stderr))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _reset_data_cache()
        shutil.rmtree(empty, ignore_errors=True)


# ------------------------------------------------------------------ 8. stdio

def check_stdio(rep: Report, no_sdk: bool) -> None:
    _section("8. MCP stdio 왕복" + (" (내장 구현)" if no_sdk else ""))
    argv = [sys.executable, "-m", "mcp_server"] + (["--no-sdk"] if no_sdk else [])
    env = _child_env()

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
            "arguments": {"query": CASES[2][0], "top_k": 1},
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
    global CASES
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in argv or "--verbose" in argv
    no_sdk = "--no-sdk" in argv
    real_data = "--real-data" in argv

    print("Voisso MCP 서버 자체 점검")
    print(f"  python  : {sys.version.split()[0]}")
    try:
        import mcp  # noqa: F401
        import importlib.metadata as meta
        print(f"  mcp SDK : {meta.version('mcp')}")
    except Exception:
        print("  mcp SDK : 미설치 (내장 stdio 구현으로 동작)")
        no_sdk = True

    if real_data:
        # 수집된 실데이터로 검증한다. VOISSO_DATA_FILE 을 비워 기본 탐색을 태운다.
        os.environ.pop("VOISSO_DATA_FILE", None)
        CASES = REAL_CASES
        print("  데이터  : 실데이터 (--real-data)")
        if not routing.data_available():
            print("\n" + routing.data_status()["message"])
            return 1
    else:
        # 기본값: 합성 샘플. 저장소를 새로 clone 한 사람도 수집 없이 통과해야 한다.
        os.environ["VOISSO_DATA_FILE"] = str(sample_path())
        CASES = SAMPLE_CASES
        print(f"  데이터  : 합성 샘플 ({sample_path().name}) — 실데이터 검증은 --real-data")
        if not sample_path().is_file():
            print(f"\n합성 샘플이 없습니다: {sample_path()}")
            return 1
    _reset_data_cache()

    rep = Report(verbose=verbose)
    check_data(rep)
    check_routing(rep)
    check_privacy(rep)
    check_lookup(rep)
    check_dialect(rep)
    check_complaints(rep)
    check_regression(rep, real_data)
    check_missing_data(rep)
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
