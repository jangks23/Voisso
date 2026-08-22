"""API 키가 있을 때만 도는 라이브 검사.

    python3 -m scripts.tests.live_checks

키 없이 돌아가는 검증은 다른 스위트가 이미 전부 덮는다. 여기서만 확인할 수 있는 것은
"키를 넣었을 때 실제로 외부 서비스와 왕복이 되는가"다. 키가 없으면 **실패가 아니라
건너뜀**이다. 포크한 기여자와 CI 에는 키가 없는 게 정상이다.

종료 코드
    0  하나 이상 실행됐고 전부 통과
    1  실행된 검사 중 실패가 있다
    3  키가 없어 전부 건너뜀
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIPPED_ALL = 3

_PASS, _FAIL, _SKIP = "PASS", "FAIL", "SKIP"
_rows: list[tuple[str, str, str]] = []


def load_dotenv() -> None:
    """`.env` 를 환경변수로 올린다. 이미 있는 값은 덮지 않는다.

    python-dotenv 를 쓰지 않는다 — 이 저장소의 방침은 의존성 최소화다.
    """
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


def env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def record(status: str, name: str, detail: str = "") -> None:
    _rows.append((status, name, detail))
    mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}[status]
    print(f"  {mark} [{status}] {name}" + (f"  {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 개별 검사
# --------------------------------------------------------------------------

def check_tts(allow_tts: bool = False) -> bytes | None:
    """Typecast / ElevenLabs 실제 합성. 성공하면 오디오 바이트를 돌려준다.

    계약서 5-D — 타입캐스트는 종량제다. 크레딧은 발표·촬영용이므로
    ``--allow-tts`` 를 명시하지 않으면 호출하지 않는다.
    """
    name = "TTS 합성 왕복"
    if not allow_tts:
        record(_SKIP, name, "계약서 5-D — 음성 생성은 --allow-tts 로만 연다")
        return None
    provider = (env("VOISSO_TTS_PROVIDER") or "none").lower()
    if provider in ("", "none"):
        record(_SKIP, name, "VOISSO_TTS_PROVIDER=none")
        return None
    key_name = {"typecast": "TYPECAST_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}.get(provider)
    if key_name and not env(key_name):
        record(_SKIP, name, f"{key_name} 없음")
        return None

    try:
        from voisso.voice import synthesize
        import base64

        result = synthesize("어르신, 접수해 드리겠습니다.")
    except Exception as exc:                       # 네트워크·SDK 문제까지 여기서 잡는다
        record(_FAIL, name, f"{type(exc).__name__}: {exc}")
        return None

    if result.error:
        record(_FAIL, name, f"provider={result.provider} error={result.error}")
        return None
    if not result.audio_b64:
        record(_FAIL, name, f"provider={result.provider} 오디오가 비었다")
        return None

    audio = base64.b64decode(result.audio_b64)
    record(_PASS, name, f"provider={result.provider} {len(audio):,} bytes")
    return audio


def check_stt(audio: bytes | None) -> None:
    """Whisper 왕복. TTS 로 만든 음성을 그대로 다시 텍스트로 되돌린다."""
    name = "STT(Whisper) 왕복"
    provider = (env("VOISSO_STT_PROVIDER") or "none").lower()
    if provider in ("", "none"):
        record(_SKIP, name, "VOISSO_STT_PROVIDER=none")
        return
    if provider == "openai" and not env("OPENAI_API_KEY"):
        record(_SKIP, name, "OPENAI_API_KEY 없음")
        return
    if audio is None:
        record(_SKIP, name, "왕복에 쓸 음성이 없다 (TTS 를 켜면 함께 검사한다)")
        return

    try:
        from voisso.voice import transcribe

        result = transcribe(audio)
    except Exception as exc:
        record(_FAIL, name, f"{type(exc).__name__}: {exc}")
        return

    if result.error:
        record(_FAIL, name, f"provider={result.provider} error={result.error}")
    elif not result.text.strip():
        record(_FAIL, name, "인식 결과가 비었다")
    else:
        record(_PASS, name, f"provider={result.provider} → {result.text.strip()[:40]!r}")


def check_llm() -> None:
    """Claude 대화 엔진이 실제로 응답하는지."""
    name = "LLM 대화 한 턴"
    if not env("ANTHROPIC_API_KEY"):
        record(_SKIP, name, "ANTHROPIC_API_KEY 없음")
        return

    try:
        from voisso.agent import ConversationSession, engine_status

        status = engine_status()
        if not status.get("llm_available"):
            record(_FAIL, name, f"키는 있는데 엔진이 안 붙었다: {status.get('llm_error')}")
            return

        session = ConversationSession()
        session.greet()
        reply = session.turn("집 앞에 물이 안 빠지고 자꾸 고이가꼬 몬 살겠다")
    except Exception as exc:
        record(_FAIL, name, f"{type(exc).__name__}: {exc}")
        return

    if not (reply.get("reply_text") or "").strip():
        record(_FAIL, name, "응답이 비었다")
        return
    used = engine_status().get("primary")
    if used != status.get("provider"):
        # 호출이 실패해 규칙 기반으로 떨어졌다면 키가 있는데도 LLM 을 못 쓴 것이다.
        record(_FAIL, name, f"LLM 대신 {used} 로 폴백했다: {engine_status().get('llm_error')}")
        return
    record(_PASS, name, f"engine={used} → {reply['reply_text'].strip()[:40]!r}")


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # 계약서 5-D. 기본값은 "음성 생성 안 함" 이고, 켜는 길은 명시적 플래그뿐이다.
    allow_tts = "--allow-tts" in args or env("VOISSO_ALLOW_TTS") == "1"

    load_dotenv()
    print("라이브 API 검사 (키가 있는 항목만 실행한다)")
    if not allow_tts:
        print("  TTS 합성은 건너뛴다 — 계약서 5-D 비용 규칙 (켜려면 --allow-tts)")
    print()

    audio = check_tts(allow_tts)
    check_stt(audio)
    check_llm()

    passed = sum(1 for status, _, _ in _rows if status == _PASS)
    failed = sum(1 for status, _, _ in _rows if status == _FAIL)
    skipped = sum(1 for status, _, _ in _rows if status == _SKIP)

    print()
    print(f"결과: 통과 {passed} · 실패 {failed} · 건너뜀 {skipped}")
    if failed:
        return 1
    if passed == 0:
        print("API 키가 없어 라이브 검사를 모두 건너뛰었습니다 (정상입니다)")
        return SKIPPED_ALL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
