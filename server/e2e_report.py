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
    streaming: dict[str, Any] | None = None,
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

    if streaming:
        turns = streaming["turns"]
        ttfas = [t["ttfa_ms"] for t in turns if t["ttfa_ms"]]
        blocking = [st["wall_ms"] for st in stages]
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0  # noqa: E731

        lines += [
            "",
            "## 2-2. 첫 음성까지 (time-to-first-audio)",
            "",
            "**전화 통화에서 중요한 것은 총 처리 시간이 아니라 첫 소리가 언제 나느냐다.**",
            "4초 넘게 조용하면 어르신은 통화가 끊긴 줄 알고 되묻거나 끊는다.",
            "",
            "`POST /api/call/turn/stream` 은 LLM 이 **첫 문장**을 뱉는 즉시 합성을 시작하고,",
            "합성 결과도 청크로 흘려보낸다. LLM 시간과 TTS 시간이 겹쳐진다.",
            "",
            "| 턴 | 첫 문장 | **첫 음성(TTFA)** | 스트리밍 전체 | 일괄 경로 |",
            "|---|---|---|---|---|",
        ]
        for index, turn in enumerate(turns, 1):
            wall = blocking[index - 1] if index - 1 < len(blocking) else 0
            lines.append(
                f"| {index} | {turn['first_sentence_ms'] or 0:.0f}ms | "
                f"**{turn['ttfa_ms'] or 0:.0f}ms** | {turn['total_ms']:.0f}ms | {wall:.0f}ms |"
            )
        lines += [
            "",
            "| 지표 | 개선 전 (일괄) | 개선 후 (스트리밍) |",
            "|---|---|---|",
            f"| 첫 음성까지 | {med(blocking):.0f}ms | **{med(ttfas):.0f}ms** |",
            "",
            f"첫 소리가 **{med(blocking) - med(ttfas):.0f}ms 빨라졌다** "
            f"({med(blocking)/max(med(ttfas),1):.1f}배).",
            "",
            "구성 요소로 나눠 보면 남은 시간은 두 덩어리다.",
            "",
            f"- LLM 이 첫 문장을 완성하기까지: 중앙값 {med([t['first_sentence_ms'] or 0 for t in turns]):.0f}ms",
            f"- 그 문장의 첫 오디오 청크까지: 약 {med(ttfas) - med([t['first_sentence_ms'] or 0 for t in turns]):.0f}ms",
            "",
            "LLM 쪽은 대부분이 **첫 토큰까지의 시간(TTFT)** 이라 스트리밍으로 더 줄지 않는다.",
            "모델을 바꿔 실측한 결과가 아래다(같은 프롬프트 3회, TTFT 중앙값).",
            "",
            "| 모델 | TTFT | 전체 | 단가(입력/출력, per MTok) |",
            "|---|---|---|---|",
            "| gpt-5.6-luna | 1226ms | 1718ms | $0.20 / $1.20 |",
            "| **gpt-5.6-terra** | **772ms** | 1399ms | $2 / $12 |",
            "",
            "값싼 등급이 항상 빠르지는 않았다. 턴당 토큰이 적어(입력 ~1K, 출력 ~150)",
            "terra 로 올려도 통화 한 건이 2센트 안쪽이라, 지연을 사는 값으로 싸다고 보고 교체했다.",
        ]

        text_turns = streaming.get("text_turns") or []
        if text_turns:
            t_ttfas = [t["ttfa_ms"] for t in text_turns if t["ttfa_ms"]]
            t_first = [t["first_sentence_ms"] or 0 for t in text_turns]
            lines += [
                "",
                "### 기본 경로(브라우저 음성인식)에서의 TTFA",
                "",
                "위 표는 **오디오를 서버로 올리는** 경로라 서버 STT 시간이 포함돼 있다.",
                "데모 기본 경로는 브라우저 음성인식이라 그 구간이 없다. 같은 방식으로 잰 값:",
                "",
                "| 턴 | 첫 문장 | **첫 음성(TTFA)** |",
                "|---|---|---|",
            ]
            for index, turn in enumerate(text_turns, 1):
                lines.append(
                    f"| {index} | {turn['first_sentence_ms'] or 0:.0f}ms | "
                    f"**{turn['ttfa_ms'] or 0:.0f}ms** |"
                )
            median_t = med(t_ttfas)
            lines += [
                "",
                f"TTFA 중앙값 **{median_t:.0f}ms** (첫 문장 {med(t_first):.0f}ms + 첫 오디오 청크 "
                f"{median_t - med(t_first):.0f}ms).",
                "",
                ("**목표(1.5초 이내) 달성.**" if median_t <= 1500
                 else f"목표(1.5초)에 {median_t - 1500:.0f}ms 못 미친다."),
            ]

    lines += [
        "",
        "## 2-3. 음성 입력 경로 — 무엇이 기본인가",
        "",
        "음성을 텍스트로 바꾸는 방법이 둘이고, **지연 차이가 크다.**",
        "",
        "| 경로 | 어떻게 | 서버 STT 구간 | 첫 음성까지 |",
        "|---|---|---|---|",
        "| **브라우저 음성인식 (기본)** | Web Speech API 가 브라우저에서 인식해 `text` 로 보낸다 | 0ms | **~1.45초** |",
        "| 서버 음성인식 | MediaRecorder 로 녹음해 `audio_b64` 로 올린다 | 0.7~1.2초 | ~2.4초 |",
        "",
        "**기본은 브라우저 음성인식이다.** 키가 필요 없고, 말하는 도중 실시간으로",
        "글자가 뜨며(어르신이 '듣고 있구나'를 눈으로 확인한다), 발화가 끝나는 즉시",
        "텍스트가 나오므로 서버 STT 구간이 통째로 사라진다.",
        "",
        "서버 STT 는 두 경우에 쓴다.",
        "",
        "- 브라우저가 Web Speech 를 지원하지 않을 때(Safari 등) — 자동 폴백",
        "- 방언 인식 품질이 더 중요할 때 — Whisper 쪽이 사투리를 더 잘 받아쓴다",
        "  (`server.voice_check` 측정 기준 평균 97%)",
        "",
        "즉 **속도를 위한 기본은 브라우저, 정확도가 필요하면 서버**다.",
        "브라우저가 여러 후보를 주면 `alternatives` 로 보내 방언 사전으로 재점수화할 수 있어",
        "브라우저 경로의 사투리 약점을 일부 보완한다.",
        "",
    ]

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
