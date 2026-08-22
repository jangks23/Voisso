#!/usr/bin/env python3
"""통합 리허설 — GOAL.md H1 성공 기준을 자동으로 재현한다.

    python3 scripts/rehearsal.py --runs 3       # 3회 연속 (H1 기준)
    python3 scripts/rehearsal.py                # 1회
    python3 scripts/rehearsal.py --audio        # TTS 합성까지 포함 (API 비용 발생)

H1: "4단계 데모가 3회 연속 끊김 없이 재현된다."
사람이 매번 손으로 확인하면 3회를 못 채운다. 그래서 자동화한다.

브라우저는 쓰지 않는다 (Chrome 은 P7 이 단독으로 쓴다). 전부 HTTP/CLI 로만 확인한다.
대시보드는 4초마다 GET /api/complaints 를 폴링하므로, 그 응답에 민원이 들어오는지를
보면 화면 갱신 여부를 브라우저 없이도 검증할 수 있다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REHEARSAL_DOC = ROOT / "docs" / "REHEARSAL.md"
DATA_JSON = ROOT / "data" / "gb_departments.json"

#: docs/DEMO_SCRIPT.md 와 server/selftest.py 가 쓰는 것과 같은 시나리오.
#: 리허설이 실제 데모와 다른 문장을 쓰면 리허설의 의미가 없다.
SCENARIO = [
    "집 앞에 물이 안 빠지고 자꾸 고이가꼬",
    "안동시 옥동입니더",
    "장마철부터 그랬어예",
    "010-1234-5678 이라예",
]
RAW_PHONE = "010-1234-5678"
MASKED_PHONE = "010-****-5678"
REQUIRED_SLOTS = ("what", "where", "when", "contact")

#: 대시보드(web/dashboard/app.js)의 폴링 주기. 이 안에 안 뜨면 "실시간"이 아니다.
DASHBOARD_POLL_SEC = 4.0

STEP_NAMES = [
    "사전 조건 점검",
    "서버 기동 + 헬스체크",
    "통화 시나리오 완주",
    "민원카드 검증",
    "대시보드 반영 확인",
    "MCP 서버 셀프테스트",
    "서버 정리",
]


class StepFailure(Exception):
    """리허설 한 단계가 실패했다. 메시지에 원인을 담는다."""


# --------------------------------------------------------------------------
# HTTP 헬퍼 (외부 의존성 없이)
# --------------------------------------------------------------------------

def request_json(url: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def http_status(url: str, timeout: float = 10.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return res.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) != 0


def show_path(path: Path) -> str:
    """저장소 기준 상대경로로 보여주되, 밖에 있으면 절대경로 그대로 쓴다."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line[len("export ") :].strip() if line.startswith("export ") else line
        key, sep, value = line.partition("=")
        if sep and key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


# --------------------------------------------------------------------------
# 단계별 구현
# --------------------------------------------------------------------------

def step_preconditions(host: str, port: int) -> dict:
    """데이터·키·포트를 확인한다. 키가 없는 것은 실패가 아니다."""
    if not DATA_JSON.is_file() or DATA_JSON.stat().st_size == 0:
        raise StepFailure(
            f"{show_path(DATA_JSON)} 가 없다. "
            "먼저 `python3 scripts/scrape_gb_departments.py` 로 수집해라."
        )
    try:
        meta = json.loads(DATA_JSON.read_text(encoding="utf-8"))["meta"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise StepFailure(f"부서 데이터셋을 읽을 수 없다: {exc}") from exc
    if meta.get("department_count", 0) < 90:
        raise StepFailure(f"부서 수가 {meta.get('department_count')}개다. 재수집이 필요하다.")

    if not port_is_free(host, port):
        raise StepFailure(
            f"포트 {port} 가 이미 사용 중이다. `--port` 로 다른 포트를 쓰거나 "
            f"`lsof -i :{port}` 로 확인해라."
        )

    keys = {
        name: bool((os.getenv(name) or "").strip())
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TYPECAST_API_KEY")
    }
    return {
        "departments": meta.get("department_count"),
        "staff": meta.get("staff_count"),
        "fetched_at": meta.get("fetched_at"),
        "keys": keys,
    }


def step_start_server(host: str, port: int, audio: bool, log_path: Path):
    """서버를 띄우고 헬스체크가 통과할 때까지 기다린다."""
    env = dict(os.environ)
    if not audio:
        # 텍스트 모드 고정. 리허설을 반복해도 외부 API 비용이 들지 않게 한다.
        env["VOISSO_TTS_PROVIDER"] = "none"
        env["VOISSO_STT_PROVIDER"] = "none"

    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "server", "--host", host, "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT,
    )

    base = f"http://{host}:{port}"
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_file.close()
            tail = "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-15:])
            raise StepFailure(f"서버 프로세스가 죽었다 (exit {process.returncode})\n{tail}")
        try:
            health = request_json(base + "/api/health", timeout=2)
            if health.get("status") == "ok":
                log_file.close()
                return process, health
        except Exception:
            pass
        time.sleep(0.4)

    process.kill()
    log_file.close()
    tail = "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-15:])
    raise StepFailure(f"서버가 40초 안에 헬스체크를 통과하지 못했다\n{tail}")


def step_run_call(base: str) -> dict:
    """start -> turn 4회 -> end. 계약서 5절 API 를 그대로 쓴다."""
    started = request_json(base + "/api/call/start", {})
    session_id = started.get("session_id")
    if not session_id:
        raise StepFailure(f"start 응답에 session_id 가 없다: {started}")

    turns = []
    for index, utterance in enumerate(SCENARIO, start=1):
        reply = request_json(
            base + "/api/call/turn", {"session_id": session_id, "text": utterance}
        )
        for field in ("reply_text", "reply_dialect", "slots"):
            if field not in reply:
                raise StepFailure(f"{index}번째 turn 응답에 {field} 가 없다: {sorted(reply)}")
        if not (reply["reply_text"] or "").strip():
            raise StepFailure(f"{index}번째 turn 의 reply_text 가 비었다")
        turns.append(reply)

    ended = request_json(base + "/api/call/end", {"session_id": session_id})
    card = ended.get("complaint")
    if not isinstance(card, dict):
        raise StepFailure(f"end 응답에 complaint 가 없다: {sorted(ended)}")

    return {"session_id": session_id, "turns": turns, "card": card}


def step_verify_card(call: dict) -> dict:
    """H1 4단계를 민원카드로 확인한다."""
    card = call["card"]
    slots = call["turns"][-1].get("slots") or {}

    # ② 슬롯 4개가 대화만으로 채워졌는가
    empty = [name for name in REQUIRED_SLOTS if not str(slots.get(name) or "").strip()]
    if empty:
        raise StepFailure(f"슬롯이 채워지지 않았다: {', '.join(empty)} (slots={slots})")

    # ③ 사무분장 원문이 근거로 붙었는가 — 계약서가 명시한 버그 조건
    assigned = card.get("assigned") or {}
    evidence = str(assigned.get("evidence") or "").strip()
    if not evidence:
        raise StepFailure(f"assigned.evidence 가 비었다 (assigned={assigned})")
    if not str(assigned.get("full_name") or "").strip():
        raise StepFailure("배정 부서명이 비었다")

    # 개인정보 — 계약서 3절
    caller = card.get("caller") or {}
    if caller.get("phone_masked") != MASKED_PHONE:
        raise StepFailure(f"연락처 마스킹이 안 됐다: {caller.get('phone_masked')!r}")
    serialized = json.dumps(card, ensure_ascii=False)
    if RAW_PHONE in serialized.replace(MASKED_PHONE, ""):
        raise StepFailure("원본 전화번호가 민원카드에 남아 있다")

    # ① 사투리 정규화가 실제로 일어났는가
    transcript = card.get("transcript") or []
    caller_turns = [t for t in transcript if t.get("role") == "caller"]
    if not caller_turns:
        raise StepFailure("통화 기록에 어르신 발화가 없다")
    normalized = [t for t in caller_turns if (t.get("dialect") or "") != (t.get("standard") or "")]
    if not normalized:
        raise StepFailure("사투리 정규화가 한 번도 일어나지 않았다 (dialect == standard)")

    return {
        "complaint_id": card.get("id"),
        "department": assigned.get("full_name"),
        "evidence": evidence,
        "normalized_turns": len(normalized),
        "category": card.get("category"),
        "alternatives": len(card.get("alternatives") or []),
    }


def step_verify_dashboard(base: str, complaint_id: str) -> dict:
    """④ 담당자 대시보드에 뜨는가.

    브라우저 없이 확인한다. 대시보드는 4초마다 GET /api/complaints 를 폴링하므로,
    그 응답에 민원이 들어와 있으면 화면에도 뜬다. 폴링 주기 안에 들어와야
    "새로고침 없이 나타난다"는 조건을 만족한다.
    """
    deadline = time.monotonic() + DASHBOARD_POLL_SEC
    seen = None
    while time.monotonic() < deadline:
        listing = request_json(base + "/api/complaints")
        ids = [c.get("id") for c in listing.get("complaints", [])]
        if complaint_id in ids:
            seen = len(ids)
            break
        time.sleep(0.3)
    if seen is None:
        raise StepFailure(
            f"민원 {complaint_id} 가 대시보드 폴링 주기({DASHBOARD_POLL_SEC}초) 안에 "
            "GET /api/complaints 에 나타나지 않았다"
        )

    detail = request_json(f"{base}/api/complaints/{complaint_id}")
    card = detail.get("complaint") or {}
    if not str((card.get("assigned") or {}).get("evidence") or "").strip():
        raise StepFailure("상세 조회 결과의 evidence 가 비었다")

    if http_status(base + "/dashboard") != 200:
        raise StepFailure("대시보드 화면(/dashboard)이 서빙되지 않는다")

    return {"complaints_in_list": seen}


def step_mcp_selftest() -> dict:
    """MCP 서버 셀프테스트 — 별도 트랙(인프라) 산출물의 증거."""
    result = subprocess.run(
        [sys.executable, "-m", "mcp_server.selftest"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-12:])
        raise StepFailure(f"MCP 셀프테스트 실패 (exit {result.returncode})\n{tail}")
    summary = [line for line in result.stdout.splitlines() if line.startswith("결과:")]
    return {"summary": summary[-1] if summary else "통과"}


def server_diagnostics(process, log_path: Path) -> str:
    """통화 도중 실패했을 때 서버가 살아 있었는지, 로그에 뭐가 남았는지 붙인다.

    RemoteDisconnected 같은 오류는 클라이언트 쪽 메시지만 봐서는 원인을 모른다.
    기록(docs/REHEARSAL.md)만 보고도 진단이 되도록 여기서 서버 상태를 캡처한다.
    """
    if process is None:
        return ""
    code = process.poll()
    lines = [f"서버 상태: {'살아 있음' if code is None else f'종료됨 (exit {code})'}"]
    try:
        tail = log_path.read_text(encoding="utf-8").splitlines()[-8:]
    except OSError:
        tail = []
    if tail:
        lines.append("서버 로그 마지막 8줄:")
        lines += [f"  {line}" for line in tail]
    return "\n".join(lines)


def step_stop_server(process) -> dict:
    if process is None or process.poll() is not None:
        return {"note": "이미 종료됨"}
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return {"pid": process.pid}


# --------------------------------------------------------------------------
# 1회 리허설
# --------------------------------------------------------------------------

def run_once(run_no: int, host: str, port: int, audio: bool, log_dir: Path) -> dict:
    base = f"http://{host}:{port}"
    log_path = log_dir / f"server-run{run_no}.log"
    process = None
    steps: list[dict] = []
    facts: dict = {}
    started_at = time.monotonic()

    def record(index: int, elapsed: float, ok: bool, detail: str = "") -> None:
        steps.append(
            {"no": index, "name": STEP_NAMES[index - 1], "ok": ok,
             "elapsed": round(elapsed, 2), "detail": detail}
        )
        mark = "✓" if ok else "✗"
        line = f"    {mark} {index}. {STEP_NAMES[index - 1]}  ({elapsed:.1f}s)"
        print(line + (f"  {detail}" if detail and ok else ""))
        if not ok:
            for row in detail.splitlines():
                print(f"        {row}")

    try:
        # 1
        tick = time.monotonic()
        pre = step_preconditions(host, port)
        facts["preconditions"] = pre
        active = [name for name, present in pre["keys"].items() if present]
        mode = "텍스트 모드" if not audio else "음성 포함"
        record(1, time.monotonic() - tick, True,
               f"부서 {pre['departments']}개 · 포트 {port} 사용 가능 · "
               f"{mode} · 키 {len(active)}/{len(pre['keys'])}개")

        # 2
        tick = time.monotonic()
        process, health = step_start_server(host, port, audio, log_path)
        facts["health"] = health
        record(2, time.monotonic() - tick, True,
               f"STT={health.get('stt', {}).get('provider')} "
               f"TTS={health.get('tts', {}).get('provider')}")

        # 3
        tick = time.monotonic()
        call = step_run_call(base)
        record(3, time.monotonic() - tick, True, f"턴 {len(call['turns'])}회 완주")

        # 4
        tick = time.monotonic()
        verified = step_verify_card(call)
        facts["card"] = verified
        record(4, time.monotonic() - tick, True,
               f"슬롯 4/4 · 배정 {verified['department']} · 마스킹 OK")

        # 5
        tick = time.monotonic()
        dash = step_verify_dashboard(base, verified["complaint_id"])
        record(5, time.monotonic() - tick, True,
               f"민원 {verified['complaint_id']} 노출 (목록 {dash['complaints_in_list']}건)")

        # 6
        tick = time.monotonic()
        mcp = step_mcp_selftest()
        record(6, time.monotonic() - tick, True, mcp["summary"])

        # 7
        tick = time.monotonic()
        step_stop_server(process)
        process = None
        record(7, time.monotonic() - tick, True)

        return {"run": run_no, "ok": True, "elapsed": round(time.monotonic() - started_at, 1),
                "steps": steps, "facts": facts, "failed_step": None, "error": ""}

    except StepFailure as exc:
        detail = "\n".join(filter(None, [str(exc), server_diagnostics(process, log_path)]))
        record(len(steps) + 1, time.monotonic() - tick, False, detail)
        return {"run": run_no, "ok": False, "elapsed": round(time.monotonic() - started_at, 1),
                "steps": steps, "facts": facts,
                "failed_step": STEP_NAMES[len(steps) - 1], "error": detail}
    except Exception as exc:                       # 예상 못 한 오류도 리허설 실패로 기록한다
        detail = "\n".join(filter(None, [
            f"{type(exc).__name__}: {exc}", server_diagnostics(process, log_path)
        ]))
        record(len(steps) + 1, time.monotonic() - tick, False, detail)
        return {"run": run_no, "ok": False, "elapsed": round(time.monotonic() - started_at, 1),
                "steps": steps, "facts": facts,
                "failed_step": STEP_NAMES[len(steps) - 1], "error": detail}
    finally:
        if process is not None:
            step_stop_server(process)


# --------------------------------------------------------------------------
# 기록
# --------------------------------------------------------------------------

DOC_HEADER = """# 통합 리허설 기록

> `python3 scripts/rehearsal.py --runs 3` 이 자동으로 덧붙인다. **손으로 고치지 마라.**
>
> GOAL.md H1 성공 기준 — *"4단계 데모가 3회 연속 끊김 없이 재현된다."*
> 한 회차는 사전조건 → 서버기동 → 통화 완주 → 민원카드 검증 → 대시보드 반영 →
> MCP 셀프테스트 → 정리 7단계다. 브라우저는 쓰지 않고 HTTP 로만 확인한다.
"""


def append_record(results: list[dict], audio: bool, host: str, port: int) -> None:
    REHEARSAL_DOC.parent.mkdir(parents=True, exist_ok=True)
    if not REHEARSAL_DOC.exists():
        REHEARSAL_DOC.write_text(DOC_HEADER, encoding="utf-8")

    now = datetime.now(timezone.utc).astimezone()
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    verdict = "✅ 전회 통과" if passed == total else f"❌ {total - passed}회 실패"

    lines = [
        "",
        "---",
        "",
        f"## {now.strftime('%Y-%m-%d %H:%M:%S %z')} — {passed}/{total}회 통과 {verdict}",
        "",
        f"- 모드: {'음성 포함 (--audio)' if audio else '텍스트 모드 (기본)'}",
        f"- 접속: `http://{host}:{port}`",
        f"- 파이썬: {sys.version.split()[0]}",
    ]

    first = results[0]["facts"].get("preconditions")
    if first:
        active = [name for name, present in first["keys"].items() if present]
        lines.append(
            f"- 데이터: 부서 {first['departments']}개 / 직원 {first['staff']}명 "
            f"(수집 {first['fetched_at']})"
        )
        lines.append(f"- API 키: {', '.join(active) if active else '없음 — 규칙 기반 폴백으로 동작'}")

    lines += ["", "| 회차 | 결과 | 소요 | 배정 부서 | 실패 단계 |", "|---|---|---|---|---|"]
    for result in results:
        card = result["facts"].get("card") or {}
        lines.append(
            f"| {result['run']} "
            f"| {'통과' if result['ok'] else '**실패**'} "
            f"| {result['elapsed']}s "
            f"| {card.get('department', '—')} "
            f"| {result['failed_step'] or '—'} |"
        )

    failures = [r for r in results if not r["ok"]]
    if failures:
        lines += ["", "### 실패 원인", ""]
        for result in failures:
            lines.append(f"**{result['run']}회차 — {result['failed_step']}**")
            lines.append("")
            lines.append("```")
            lines += result["error"].splitlines()
            lines.append("```")
            lines.append("")
    else:
        sample = results[0]["facts"].get("card") or {}
        if sample.get("evidence"):
            lines += [
                "",
                "### 배정 근거 (1회차)",
                "",
                f"> {sample['evidence']}",
                "",
                f"분류: {sample.get('category', '—')} · 대안 후보 {sample.get('alternatives', 0)}곳 "
                f"· 정규화된 발화 {sample.get('normalized_turns', 0)}개",
            ]

    with REHEARSAL_DOC.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Voisso 통합 리허설 (GOAL.md H1 자동 검증)"
    )
    parser.add_argument("--runs", type=int, default=1, help="반복 횟수 (H1 기준은 3)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8020,
                        help="기본 8020 — 개발용 8000 서버와 부딪히지 않게")
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument("--audio", action="store_true",
                             help="TTS/STT 를 켜고 돈다 (외부 API 비용 발생)")
    audio_group.add_argument("--no-audio", action="store_true",
                             help="텍스트 모드로 돈다 (기본값)")
    args = parser.parse_args()

    load_dotenv()
    audio = args.audio          # --no-audio 는 기본값과 같으므로 명시용이다
    runs = max(1, args.runs)

    log_dir = ROOT / "data" / "rehearsal-logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"Voisso 통합 리허설 — {runs}회")
    print(f"  모드   : {'음성 포함 (--audio, API 비용 발생)' if audio else '텍스트 모드 (기본)'}")
    print(f"  접속   : http://{args.host}:{args.port}")
    print()

    results = []
    for run_no in range(1, runs + 1):
        print(f"  [{run_no}/{runs}회차]")
        result = run_once(run_no, args.host, args.port, audio, log_dir)
        results.append(result)
        print()
        if run_no < runs:
            time.sleep(1)          # 포트가 완전히 풀릴 시간을 준다

    passed = sum(1 for r in results if r["ok"])
    width = max(len(STEP_NAMES[i]) for i in range(len(STEP_NAMES)))

    print("=" * 60)
    print(f"{'회차':<6}{'결과':<8}{'소요':<10}{'실패 단계'}")
    print("-" * 60)
    for result in results:
        verdict = "통과" if result["ok"] else "실패"
        print(f"{result['run']:<7}{verdict:<9}{str(result['elapsed']) + 's':<11}"
              f"{result['failed_step'] or '—'}")
    print("-" * 60)
    print(f"{passed}/{len(results)}회 통과")

    append_record(results, audio, args.host, args.port)
    print(f"\n기록: {show_path(REHEARSAL_DOC)}")

    if passed != len(results):
        print("\nH1 기준 미달 — 3회 연속 통과가 필요하다.", file=sys.stderr)
        return 1
    if len(results) >= 3:
        print("\nGOAL.md H1 충족: 4단계 데모가 3회 연속 재현됐다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
