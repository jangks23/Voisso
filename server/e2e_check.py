"""서버 E2E — 브라우저 없이 HTTP 로만 전 구간 검증.

    python3 -m server.e2e_check                     # 실제 오디오 왕복 + 지연 + 동시 세션
    python3 -m server.e2e_check --text-only         # 키 없는 텍스트 모드 경로만
    python3 -m server.e2e_check --base http://...   # 다른 서버를 가리킬 때

지금까지의 검증은 파이썬 함수를 직접 부르는 수준이었다. 이 스크립트는
**실행 중인 서버에 HTTP 로만** 말을 건다. 확인하는 것:

  1. 실제 오디오 왕복 — Typecast 로 WAV 를 만들어 audio_b64 로 POST 하고,
     STT 가 받아쓰고, 대화가 진행되고, 응답 오디오가 돌아오는지.
     브라우저 MediaRecorder(webm) 대신 **WAV** 가 들어오는 경로라
     `_sniff_extension` 이 HTTP 경유에서도 도는지 함께 확인된다.
  2. 구간별 지연 — STT / LLM / 방언 / TTS 를 나눠 잰다. 병목을 숫자로 남긴다.
  3. 동시 세션 — 2~3개를 동시에 진행해 상태가 섞이지 않는지.

비용을 아끼려고 합성한 WAV 는 디스크에 캐시한다(`--fresh` 로 무시).
"""

from __future__ import annotations

import argparse
import base64
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

DEFAULT_BASE = "http://127.0.0.1:8000"

# 통화 한 건을 이루는 발화. 슬롯 4개를 채운다.
SCRIPT = [
    "아 저기 집 앞에 물이 안 빠지고 자꾸 고여서 큰일이라예",
    "안동시 옥동입니더",
    "장마철부터 그랬어예",
    "010-1234-5678 이라예",
]


class ApiError(RuntimeError):
    pass


def api(base: str, path: str, payload: dict | None = None, timeout: float = 120.0) -> dict:
    """서버에 HTTP 로 말을 건다. 이 스크립트는 이 함수로만 서버를 만진다."""
    url = f"{base}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(f"{path} -> HTTP {exc.code}: {exc.read()[:200].decode('utf-8','replace')}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{path} -> 연결 실패: {exc.reason}") from exc


# --------------------------------------------------------------------------
# 오디오 픽스처 (합성 결과를 캐시해 비용을 아낀다)
# --------------------------------------------------------------------------


def audio_fixtures(cache_dir: Path, fresh: bool = False) -> dict[str, bytes] | None:
    from voisso.voice.tts import TypecastProvider

    provider = TypecastProvider()
    if not provider.available:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, bytes] = {}
    for index, line in enumerate(SCRIPT):
        path = cache_dir / f"turn{index}.wav"
        if path.is_file() and not fresh:
            out[line] = path.read_bytes()
            continue
        result = provider.synthesize(line)
        if not result.audio_b64:
            print(f"  TTS 합성 실패: {result.error}")
            return None
        audio = base64.b64decode(result.audio_b64)
        path.write_bytes(audio)
        out[line] = audio
    return out


# --------------------------------------------------------------------------
# 검증
# --------------------------------------------------------------------------

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)
    return ok


def run_call(base: str, audio: dict[str, bytes] | None, label: str = "") -> dict:
    """통화 한 건을 HTTP 로 완주하고 구간별 지연을 모은다."""
    started = api(base, "/api/call/start", {})
    session_id = started["session_id"]
    stages: list[dict] = []

    for line in SCRIPT:
        payload: dict = {"session_id": session_id}
        if audio is not None:
            payload["audio_b64"] = base64.b64encode(audio[line]).decode("ascii")
        else:
            payload["text"] = line

        wall = time.perf_counter()
        result = api(base, "/api/call/turn", payload)
        wall_ms = round((time.perf_counter() - wall) * 1000, 1)

        meta = result.get("meta") or {}
        stages.append(
            {
                "line": line,
                "wall_ms": wall_ms,
                "timings": meta.get("timings") or {},
                "engine": meta.get("engine"),
                "heard": _heard(result),
                "reply": result.get("reply_dialect", ""),
                "audio": bool(result.get("audio_b64")),
                "done": result.get("done"),
                "slots": result.get("slots", {}),
            }
        )
        if label:
            print(f"    [{label}] {line[:22]}… -> {result.get('reply_dialect','')[:34]}…")

    ended = api(base, "/api/call/end", {"session_id": session_id})
    return {
        "session_id": session_id,
        "stages": stages,
        "complaint": ended["complaint"],
        "end_timings": (ended.get("meta") or {}).get("timings", {}),
    }


def stream_turn(base: str, session_id: str, payload_extra: dict) -> dict:
    """스트리밍 턴을 돌리고 **첫 오디오 청크까지의 시간(TTFA)** 을 잰다."""
    url = f"{base}/api/call/turn/stream"
    body = json.dumps({"session_id": session_id, **payload_extra}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    start = time.perf_counter()
    ttfa = None
    first_sentence = None
    final = None
    sentences = 0

    # 반드시 readline() 으로 읽는다. read(n) 은 n 바이트가 찰 때까지 블록해서
    # 작은 `sentence` 줄이 뒤따르는 오디오 청크와 함께 도착한 것처럼 보인다
    # (첫 문장과 첫 음성이 1ms 차이로 찍히면 이 함정에 빠진 것이다).
    with urllib.request.urlopen(req, timeout=180) as resp:
        while True:
            raw = resp.readline()
            if not raw:
                break
            if not raw.strip():
                continue
            event = json.loads(raw.decode("utf-8"))
            now = (time.perf_counter() - start) * 1000
            kind = event.get("type")
            if kind == "sentence":
                sentences += 1
                if first_sentence is None:
                    first_sentence = now
            elif kind == "audio_chunk" and ttfa is None:
                ttfa = now
            elif kind == "final":
                final = event
    total = (time.perf_counter() - start) * 1000
    return {
        "ttfa_ms": round(ttfa, 1) if ttfa else None,
        "first_sentence_ms": round(first_sentence, 1) if first_sentence else None,
        "total_ms": round(total, 1),
        "sentences": sentences,
        "final": final or {},
    }


def run_call_streaming(base: str, audio: dict[str, bytes] | None) -> dict:
    """스트리밍 경로로 통화 한 건. 턴마다 TTFA 를 기록한다."""
    started = api(base, "/api/call/start", {})
    session_id = started["session_id"]
    turns = []
    for line in SCRIPT:
        extra = (
            {"audio_b64": base64.b64encode(audio[line]).decode("ascii")}
            if audio is not None
            else {"text": line}
        )
        result = stream_turn(base, session_id, extra)
        result["line"] = line
        turns.append(result)
    ended = api(base, "/api/call/end", {"session_id": session_id})
    return {"session_id": session_id, "turns": turns, "complaint": ended["complaint"]}


def _heard(result: dict) -> str:
    """서버가 무엇으로 알아들었는지 — 통화 기록 대신 슬롯으로 확인한다."""
    slots = result.get("slots") or {}
    return " / ".join(f"{k}={slots.get(k)}" for k in ("what", "where", "when", "contact") if slots.get(k))


def stage_table(stages: list[dict], end_timings: dict) -> str:
    keys = ("stt_ms", "normalize_ms", "llm_ms", "dialect_ms", "tts_ms", "total_ms")
    header = f"| {'턴':2s} | " + " | ".join(f"{k.replace('_ms',''):>9s}" for k in keys) + " | 왕복(HTTP) |"
    sep = "|----|" + "|".join(["-----------"] * len(keys)) + "|------------|"
    rows = [header, sep]
    for index, stage in enumerate(stages, 1):
        t = stage["timings"]
        cells = " | ".join(f"{t.get(k, 0):9.0f}" for k in keys)
        rows.append(f"| {index:2d} | {cells} | {stage['wall_ms']:10.0f} |")
    return "\n".join(rows)


def measure_tts_stream(base: str) -> tuple[float, float] | None:
    """스트리밍 TTS 의 첫 바이트까지 시간과 전체 시간(ms)."""
    url = f"{base}/api/tts/stream"
    body = json.dumps(
        {"text": "아이고, 그러셨구나예. 그기 어디쯤인교?", "previous_text": "집 앞에 물이 안 빠져예"}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    start = time.perf_counter()
    first: float | None = None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                if first is None:
                    first = (time.perf_counter() - start) * 1000
    except Exception as exc:
        print(f"  스트리밍 측정 실패: {exc}")
        return None
    total = (time.perf_counter() - start) * 1000
    return (round(first or total, 1), round(total, 1))


def concurrent_sessions(base: str, count: int = 3) -> list[dict]:
    """세션 여러 개를 동시에 진행해 상태가 섞이는지 본다."""
    results: list[dict | None] = [None] * count
    errors: list[str] = []

    # 세션마다 다른 지역을 말하게 해서 섞이면 바로 드러나게 한다.
    places = ["안동시 옥동입니더", "구미시 원평동입니더", "예천군 호명면입니더"]

    def worker(index: int) -> None:
        try:
            started = api(base, "/api/call/start", {})
            sid = started["session_id"]
            api(base, "/api/call/turn", {"session_id": sid, "text": SCRIPT[0]})
            api(base, "/api/call/turn", {"session_id": sid, "text": places[index % len(places)]})
            final = api(base, "/api/call/turn", {"session_id": sid, "text": "010-1234-567%d 이라예" % index})
            results[index] = {
                "session_id": sid,
                "expected_place": places[index % len(places)],
                "slots": final.get("slots", {}),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"세션 {index}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        for e in errors:
            print(f"    {e}")
    return [r for r in results if r]


def main() -> int:
    config.load_dotenv()
    parser = argparse.ArgumentParser(prog="python3 -m server.e2e_check")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--text-only", action="store_true", help="오디오 없이 텍스트 경로만")
    parser.add_argument("--fresh", action="store_true", help="오디오 캐시를 무시하고 재합성")
    parser.add_argument("--report", default="docs/E2E_SERVER.md", help="결과를 쓸 파일")
    parser.add_argument(
        "--keyless-base",
        default=None,
        help="키 없이 띄운 서버 주소. 주면 텍스트 모드 경로도 같은 보고서에 담는다",
    )
    args = parser.parse_args()

    base = args.base.rstrip("/")
    print(f"서버 E2E — {base}\n")

    try:
        health = api(base, "/api/health")
    except ApiError as exc:
        print(f"서버에 연결할 수 없습니다: {exc}")
        print("먼저 `python3 -m server` 로 서버를 띄우세요.")
        return 1

    runtime = health["runtime"]
    print(f"  대화 엔진 : {runtime['engine']} ({runtime.get('turn_model') or '—'})")
    print(f"  음성 인식 : {runtime['stt']}")
    print(f"  음성 출력 : {runtime['tts']}")
    print(f"  옆 모듈   : 방언 {runtime['dialect']} / 라우팅 {runtime['routing']}\n")

    audio = None
    if not args.text_only:
        cache = Path(config.ROOT_DIR) / ".cache" / "e2e_audio"
        print("오디오 픽스처 준비 중…")
        audio = audio_fixtures(cache, fresh=args.fresh)
        if audio is None:
            print("  TTS 를 쓸 수 없어 텍스트 경로로 진행합니다.\n")
        else:
            sizes = ", ".join(f"{len(v)//1024}KB" for v in audio.values())
            print(f"  WAV {len(audio)}개 준비됨 ({sizes})\n")

    mode = "오디오(WAV)" if audio else "텍스트"
    print(f"1) 통화 왕복 — {mode} 경로")
    call = run_call(base, audio)
    stages = call["stages"]

    if audio:
        check("STT 가 오디오를 받아썼다", any(s["timings"].get("stt_ms") for s in stages))
        check("WAV 가 400 없이 처리됐다", all(s["heard"] or s["reply"] for s in stages))
    check("모든 턴이 응답을 돌려줬다", all(s["reply"] for s in stages))
    if runtime["tts"] != "none":
        check("응답 오디오가 돌아왔다", all(s["audio"] for s in stages))
    check("마지막 턴에서 통화 종료를 제안했다", bool(stages[-1]["done"]), str(stages[-1]["done"]))

    slots = stages[-1]["slots"]
    filled = [k for k in ("what", "where", "when", "contact") if slots.get(k)]
    check("슬롯 4개가 채워졌다", len(filled) == 4, ", ".join(filled))

    card = call["complaint"]
    check("민원카드가 생성됐다", bool(card.get("id")), card.get("id"))
    check("assigned.evidence 가 비어 있지 않다", bool(card["assigned"]["evidence"].strip()))
    check("연락처가 마스킹됐다", "****" in (card["caller"]["phone_masked"] or ""), card["caller"]["phone_masked"])
    print(f"  요약: {card['summary']}")
    print(f"  배정: {card['assigned']['full_name']}")

    print("\n2) 구간별 지연 (ms)")
    table = stage_table(stages, call["end_timings"])
    print("  " + table.replace("\n", "\n  "))

    streaming = None
    if runtime["tts"] != "none" or True:
        print("\n2-1) 스트리밍 경로 — 첫 음성까지(TTFA)")
        streaming = run_call_streaming(base, audio)
        for index, turn in enumerate(streaming["turns"], 1):
            fs = turn["first_sentence_ms"]
            ttfa = turn["ttfa_ms"]
            print(
                f"    턴 {index}: 첫 문장 {fs or 0:6.0f}ms → 첫 음성 {ttfa or 0:6.0f}ms "
                f"(전체 {turn['total_ms']:.0f}ms, 문장 {turn['sentences']}개)"
            )
        ttfas = [t["ttfa_ms"] for t in streaming["turns"] if t["ttfa_ms"]]
        if ttfas:
            print(f"    TTFA 중앙값 {statistics.median(ttfas):.0f}ms / 최소 {min(ttfas):.0f}ms")

        if audio is not None:
            # 데모 기본 경로는 브라우저 음성인식(text)이다. STT 가 빠지면
            # 얼마나 빨라지는지 같은 방식으로 재서 함께 남긴다.
            print("    텍스트 입력 경로(브라우저 음성인식 사용 시)")
            text_run = run_call_streaming(base, None)
            streaming["text_turns"] = text_run["turns"]
            t_ttfas = [t["ttfa_ms"] for t in text_run["turns"] if t["ttfa_ms"]]
            for index, turn in enumerate(text_run["turns"], 1):
                print(
                    f"      턴 {index}: 첫 문장 {turn['first_sentence_ms'] or 0:6.0f}ms "
                    f"→ 첫 음성 {turn['ttfa_ms'] or 0:6.0f}ms"
                )
            if t_ttfas:
                print(
                    f"      TTFA 중앙값 {statistics.median(t_ttfas):.0f}ms "
                    f"/ 최소 {min(t_ttfas):.0f}ms"
                )
                check(
                    "기본 경로 TTFA 가 1.5초 이내다",
                    statistics.median(t_ttfas) <= 1500,
                    f"{statistics.median(t_ttfas):.0f}ms",
                )
        blocking_totals = [st["wall_ms"] for st in stages]
        check(
            "스트리밍 TTFA 가 일괄 경로보다 빠르다",
            bool(ttfas) and statistics.median(ttfas) < statistics.median(blocking_totals),
            f"{statistics.median(ttfas):.0f}ms vs {statistics.median(blocking_totals):.0f}ms",
        )

    stream = None
    if runtime["tts"] != "none":
        print("\n  스트리밍 TTS 비교")
        stream = measure_tts_stream(base)
        if stream:
            tts_values = [s["timings"].get("tts_ms", 0) for s in stages if s["timings"].get("tts_ms")]
            blocking = statistics.median(tts_values) if tts_values else 0
            print(f"    통짜 합성(중앙값): {blocking:.0f}ms")
            print(f"    스트리밍 첫 바이트: {stream[0]:.0f}ms  (전체 {stream[1]:.0f}ms)")
            if blocking:
                print(f"    -> 첫 음성까지 {blocking - stream[0]:.0f}ms 단축")

    print("\n3) 동시 세션")
    sessions = concurrent_sessions(base, 3)
    check("동시 세션 3개가 모두 완료됐다", len(sessions) == 3, f"{len(sessions)}/3")
    ids = {s["session_id"] for s in sessions}
    check("세션 ID 가 서로 다르다", len(ids) == 3)
    mixed = [
        s for s in sessions
        if s["expected_place"].replace("입니더", "").split()[0] not in (s["slots"].get("where") or "")
    ]
    check(
        "세션 간 상태가 섞이지 않았다",
        not mixed,
        "; ".join(f"{s['expected_place']} != {s['slots'].get('where')}" for s in mixed),
    )
    for s in sessions:
        print(f"    {s['session_id'][:8]}… where={s['slots'].get('where')}")

    keyless = None
    if args.keyless_base:
        print("\n4) 키 없는 텍스트 모드 (같은 HTTP 경로)")
        kbase = args.keyless_base.rstrip("/")
        try:
            khealth = api(kbase, "/api/health")
            kcall = run_call(kbase, None)
            kslots = kcall["stages"][-1]["slots"]
            kfilled = [k for k in ("what", "where", "when", "contact") if kslots.get(k)]
            check("키 없이도 슬롯 4개가 채워졌다", len(kfilled) == 4, ", ".join(kfilled))
            check("키 없이도 민원카드가 나왔다", bool(kcall["complaint"].get("id")))
            check(
                "키 없이도 evidence 가 비어 있지 않다",
                bool(kcall["complaint"]["assigned"]["evidence"].strip()),
            )
            keyless = {"base": kbase, "runtime": khealth["runtime"], "call": kcall}
            waits = [st["wall_ms"] for st in kcall["stages"]]
            print(f"    턴당 왕복 {min(waits):.0f}~{max(waits):.0f}ms (외부 API 호출 없음)")
        except ApiError as exc:
            check("키 없는 서버에 연결됐다", False, str(exc))

    report = write_report(
        args.report, base, runtime, call, stream, sessions, mode, keyless, streaming
    )
    print(f"\n결과를 {report} 에 남겼습니다.")

    print(f"\n  실패 {len(_failures)}건")
    if _failures:
        print("  " + ", ".join(_failures))
        return 1
    print("\n전부 통과.")
    return 0


def write_report(
    path_str, base, runtime, call, stream, sessions, mode, keyless=None, streaming=None
) -> Path:
    from .e2e_report import render

    path = Path(config.ROOT_DIR) / path_str
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render(
            base, runtime, call, stream, sessions, mode, _failures, stage_table, keyless, streaming
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    sys.exit(main())
