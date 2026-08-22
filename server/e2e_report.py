"""E2E 결과를 마크다운 보고서로 렌더링한다 (server.e2e_check 가 호출)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def render(
    base: str,
    runtime: dict[str, Any],
    call: dict[str, Any],
    stream: tuple[float, float] | None,
    sessions: list[dict[str, Any]],
    mode: str,
    failures: list[str],
    stage_table: Callable[..., str],
    keyless: dict[str, Any] | None = None,
) -> str:
    card = call["complaint"]
    stages = call["stages"]
    verdict = "전부 통과" if not failures else f"실패 {len(failures)}건: {', '.join(failures)}"

    lines = [
        "# 서버 E2E 검증 결과",
        "",
        "> `python3 -m server.e2e_check` 가 자동 생성한다. 손으로 고치지 마라.",
        "> 브라우저를 쓰지 않는다 — **HTTP 로만** 서버를 검증한다.",
        "",
        f"- 측정 시각: {_now()}",
        f"- 대상 서버: `{base}`",
        f"- 입력 경로: {mode}",
        f"- 결과: **{verdict}**",
        "",
        "## 구성",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 대화 엔진 | {runtime['engine']} ({runtime.get('turn_model') or '—'}) |",
        f"| 요약 모델 | {runtime.get('summary_model') or '—'} |",
        f"| 음성 인식 | {runtime['stt']} |",
        f"| 음성 출력 | {runtime['tts']} |",
        f"| 방언 모듈 | {'연결됨' if runtime['dialect'] else '없음'} |",
        f"| 라우팅 모듈 | {'연결됨' if runtime['routing'] else '없음'} |",
        "",
        "## 1. 통화 왕복",
        "",
        "`POST /api/call/start` → `turn` ×4 → `POST /api/call/end` 를 HTTP 로 실행했다.",
        "",
    ]

    lines.append("| 턴 | 어르신 발화 | 응답 | 오디오 |")
    lines.append("|---|---|---|---|")
    for index, stage in enumerate(stages, 1):
        reply = stage["reply"].replace("|", "\\|")
        line = stage["line"].replace("|", "\\|")
        lines.append(f"| {index} | {line} | {reply} | {'O' if stage['audio'] else '—'} |")

    lines += [
        "",
        "### 생성된 민원카드",
        "",
        "```json",
        f'{{"id": "{card["id"]}",',
        f'  "summary": "{card["summary"]}",',
        f'  "category": "{card["category"]}",',
        f'  "assigned": {{"full_name": "{card["assigned"]["full_name"]}",',
        f'                "phone_token": "{card["assigned"]["phone_token"]}",',
        f'                "evidence": "{card["assigned"]["evidence"][:80]}…"}},',
        f'  "caller": {{"phone_masked": "{card["caller"]["phone_masked"]}"}}}}',
        "```",
        "",
        "## 2. 구간별 지연",
        "",
        "턴 하나가 처리되는 동안 각 구간이 실제로 쓴 시간(ms)이다.",
        "서버가 응답 `meta.timings` 에 실어 보내는 값을 그대로 옮겼다.",
        "`왕복(HTTP)` 은 클라이언트가 잰 전체 왕복 시간이다.",
        "",
    ]
    lines.append(stage_table(stages, call["end_timings"]))

    end_timings = call.get("end_timings") or {}
    if end_timings:
        lines += [
            "",
            "통화 종료(`POST /api/call/end`)는 턴과 구간 구성이 달라 따로 적는다.",
            "요약 LLM 한 번과 부서 라우팅이 전부다.",
            "",
            "| 구간 | 소요 |",
            "|---|---|",
            f"| 요약 생성 (LLM) | {end_timings.get('summary_ms', 0):.0f}ms |",
            f"| 부서 라우팅 + 카드 생성 | {end_timings.get('routing_ms', 0):.0f}ms |",
        ]

    tts_values = [s["timings"].get("tts_ms", 0) for s in stages if s["timings"].get("tts_ms")]
    stt_values = [s["timings"].get("stt_ms", 0) for s in stages if s["timings"].get("stt_ms")]
    llm_values = [s["timings"].get("llm_ms", 0) for s in stages if s["timings"].get("llm_ms")]

    lines += ["", "### 병목", ""]
    ranked = sorted(
        [("STT", stt_values), ("LLM", llm_values), ("TTS", tts_values)],
        key=lambda kv: -(sum(kv[1]) / len(kv[1]) if kv[1] else 0),
    )
    for name, values in ranked:
        if values:
            avg = sum(values) / len(values)
            lines.append(f"- **{name}**: 평균 {avg:.0f}ms (최소 {min(values):.0f} / 최대 {max(values):.0f})")
    if not any(v for _, v in ranked):
        lines.append("- 외부 API 를 쓰지 않는 경로라 측정할 구간이 없다.")

    if stream:
        blocking = sorted(tts_values)[len(tts_values) // 2] if tts_values else 0
        lines += [
            "",
            "### 스트리밍 TTS",
            "",
            "계약서의 `audio_b64` 는 통짜 오디오라 합성이 끝나야 첫 소리가 난다.",
            "`POST /api/tts/stream` 은 청크를 흘려보내므로 첫 음성이 훨씬 빨리 시작된다.",
            "",
            "| 방식 | 첫 음성까지 | 전체 |",
            "|---|---|---|",
            f"| 통짜 합성 (`audio_b64`) | {blocking:.0f}ms | {blocking:.0f}ms |",
            f"| 스트리밍 (`/api/tts/stream`) | **{stream[0]:.0f}ms** | {stream[1]:.0f}ms |",
        ]
        if blocking:
            lines.append("")
            lines.append(
                f"첫 음성까지 **{blocking - stream[0]:.0f}ms 단축**된다 "
                f"({blocking:.0f}ms → {stream[0]:.0f}ms). 통화 데모에서 체감이 가장 큰 구간이다."
            )

    lines += [
        "",
        "## 3. 동시 세션",
        "",
        "세션 3개를 스레드로 동시에 진행하며 각기 다른 지역을 말하게 했다.",
        "상태가 섞이면 `where` 슬롯이 어긋나므로 바로 드러난다.",
        "",
        "| 세션 | 말한 지역 | 서버가 채운 where |",
        "|---|---|---|",
    ]
    for session in sessions:
        lines.append(
            f"| `{session['session_id'][:8]}…` | {session['expected_place']} | "
            f"{session['slots'].get('where') or '—'} |"
        )

    if keyless:
        kcall = keyless["call"]
        kcard = kcall["complaint"]
        waits = [st["wall_ms"] for st in kcall["stages"]]
        lines += [
            "",
            "## 4. 키 없는 텍스트 모드",
            "",
            "API 키를 하나도 주지 않고 띄운 서버(`" + keyless["base"] + "`)에 **같은 HTTP 경로**로",
            "같은 통화를 걸었다. 심사자가 키 없이 저장소만 받아 실행하는 경우다.",
            "",
            "| 항목 | 값 |",
            "|---|---|",
            f"| 대화 엔진 | {keyless['runtime']['engine']} |",
            f"| 음성 인식 | {keyless['runtime']['stt']} |",
            f"| 음성 출력 | {keyless['runtime']['tts']} |",
            f"| 턴당 왕복 | {min(waits):.0f}~{max(waits):.0f}ms |",
            f"| 민원카드 | `{kcard['id']}` — {kcard['summary']} |",
            f"| 배정 | {kcard['assigned']['full_name']} |",
            "",
            "외부 API 를 하나도 부르지 않으므로 턴당 응답이 밀리초 단위다.",
            "대화는 규칙 기반이라 단조롭지만 **슬롯 채우기 → 부서 배정 → 민원카드까지",
            "전 구간이 동일하게 동작한다.**",
        ]

    lines += [
        "",
        "## 재현",
        "",
        "```bash",
        "python3 -m server                  # 서버 기동",
        "python3 -m server.e2e_check        # 이 보고서를 다시 생성",
        "python3 -m server.e2e_check --text-only   # 오디오 없이 텍스트 경로만",
        "",
        "# 키 없는 서버를 따로 띄워 같은 보고서에 담기",
        "env VOISSO_AGENT_PROVIDER=rule VOISSO_TTS_PROVIDER=none VOISSO_STT_PROVIDER=none \\",
        "    OPENAI_API_KEY= ANTHROPIC_API_KEY= TYPECAST_API_KEY= \\",
        "  python3 -m server --port 8002 &",
        "python3 -m server.e2e_check --keyless-base http://127.0.0.1:8002",
        "```",
        "",
        "합성한 WAV 는 `.cache/e2e_audio/` 에 캐시된다. `--fresh` 로 무시할 수 있다.",
        "",
    ]
    return "\n".join(lines)
