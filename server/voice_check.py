"""음성 왕복 회귀 테스트 — TTS 로 합성 -> STT 로 받아쓰기 -> 유사도 측정.

    python3 -m server.voice_check
    python3 -m server.voice_check --threshold 90 --model whisper-1
    python3 -m server.voice_check --compare-priming

사투리 인식은 이 프로젝트의 핵심인데, 눈으로 확인하려면 매번 마이크에 대고
말해 봐야 했다. Typecast 로 사투리 대사를 합성해 그걸 다시 Whisper 에 넣으면
사람 없이도 왕복을 잴 수 있다. 프라이밍 프롬프트나 모델을 바꿨을 때
품질이 떨어졌는지 잡아내는 용도다.

**키가 없으면 실패가 아니라 '건너뜀'이다.** 키 없이도 데모가 돌아야 한다는
조건과 마찬가지로, 이 스크립트도 키가 없다고 CI 를 빨갛게 만들지 않는다.

한계 두 가지를 알고 쓸 것.

1. 합성 음성은 사람 목소리가 아니다. 실제 어르신 발화보다 또렷하므로 여기서
   나온 점수는 **상한에 가깝다.** 회귀 감지용이지 절대 성능 지표가 아니다.
2. **같은 문장도 실행마다 몇 %p 씩 흔들린다.** TTS 합성과 STT 인식 양쪽이
   비결정적이라 그렇다. 단발 실행으로 임계값을 걸면 오탐이 나므로,
   회귀 판정에는 `--repeat 3` 정도로 평균을 내는 편이 안전하다.
"""

from __future__ import annotations

import argparse
import re
import sys
from difflib import SequenceMatcher

from voisso.voice import synthesize, transcribe
from voisso.voice.stt import get_stt_provider, priming_prompt
from voisso.voice.tts import get_tts_provider

from . import config

# 민원 통화에서 실제로 나올 법한 사투리 대사.
# 슬롯 4종(무슨 일/어디서/언제/연락처)을 고루 덮는다.
FIXTURES = (
    "집 앞에 물이 안 빠지고 자꾸 고이가꼬 큰일이라예",
    "농로가 무너져가 트랙터가 몬 지나간다 카이",
    "우리 동네 가로등이 며칠째 안 들어오는데 우째 해야 되노",
    "안동시 옥동 사는데예",
    "장마철부터 계속 그랬어예",
)

# 이 아래로 떨어지면 회귀로 본다.
DEFAULT_THRESHOLD = 85.0

_NORMALIZE_RE = re.compile(r"[\s.,!?…·\"'’”\)\(\[\]]+")


def normalize(text: str) -> str:
    """구두점·공백 차이는 인식 오류가 아니므로 지우고 비교한다."""
    return _NORMALIZE_RE.sub("", text or "")


def similarity(expected: str, actual: str) -> float:
    a, b = normalize(expected), normalize(actual)
    if not a and not b:
        return 100.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio() * 100.0


def diff_note(expected: str, actual: str) -> str:
    """어디가 틀렸는지 짧게. 회귀를 눈으로 좇을 수 있게."""
    a, b = normalize(expected), normalize(actual)
    matcher = SequenceMatcher(None, a, b)
    notes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        notes.append(f"{a[i1:i2] or '∅'}->{b[j1:j2] or '∅'}")
    return ", ".join(notes[:4])


def main() -> int:
    config.load_dotenv()

    parser = argparse.ArgumentParser(
        prog="python3 -m server.voice_check", description="TTS→STT 왕복 회귀 테스트"
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD, help=f"기본 {DEFAULT_THRESHOLD}%%"
    )
    parser.add_argument("--model", default=None, help="STT 모델 (기본: VOISSO_STT_MODEL)")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="문장당 반복 횟수. 실행 간 편차가 있어 회귀 판정에는 3 이상을 권한다",
    )
    parser.add_argument(
        "--compare-priming",
        action="store_true",
        help="프라이밍 프롬프트 유무를 비교한다 (API 호출이 2배로 는다)",
    )
    args = parser.parse_args()

    tts = get_tts_provider()
    stt = get_stt_provider()
    if args.model:
        stt.model = args.model

    print("음성 왕복 회귀 테스트\n")
    print(f"  TTS: {tts.name}")
    print(f"  STT: {stt.name}" + (f" ({getattr(stt, 'model', '')})" if stt.available else ""))

    # -- 건너뛸 조건 -------------------------------------------------------
    missing = []
    if tts.name == "none":
        missing.append("TTS(VOISSO_TTS_PROVIDER + 해당 API 키)")
    if not stt.available:
        missing.append("STT(VOISSO_STT_PROVIDER=openai + OPENAI_API_KEY)")
    if missing:
        print("\n건너뜀 — 다음이 설정되지 않았습니다:")
        for item in missing:
            print(f"  - {item}")
        print("\n이 테스트는 실제 음성 API 를 호출하므로 키가 있어야 돕니다.")
        print("키 없이 도는 검증은 `python3 -m server.selftest` 를 쓰세요.")
        return 0

    prompt = priming_prompt(stt.model)
    print(f"  프라이밍: {len(prompt)}자")
    if args.repeat > 1:
        print(f"  반복: 문장당 {args.repeat}회 평균")
    print()

    header = f"{'대사':46s} {'일치율':>7s}"
    if args.compare_priming:
        header += f"  {'프라이밍없음':>10s}"
    print(header)
    print("-" * 70)

    scores: list[float] = []
    bare_scores: list[float] = []
    failures: list[tuple[str, str, float]] = []

    repeat = max(1, args.repeat)

    for line in FIXTURES:
        line_scores: list[float] = []
        line_bare: list[float] = []
        worst_text = ""
        error: str | None = None

        for _ in range(repeat):
            speech = synthesize(line)
            if not speech.audio_b64:
                error = f"TTS 실패: {speech.error}"
                break

            import base64

            audio = base64.b64decode(speech.audio_b64)
            result = transcribe(audio)
            if result.error:
                error = f"STT 실패: {result.error}"
                break

            score = similarity(line, result.text)
            if not line_scores or score < min(line_scores):
                worst_text = result.text
            line_scores.append(score)

            if args.compare_priming:
                line_bare.append(similarity(line, _transcribe_without_priming(stt, audio)))

        if error or not line_scores:
            print(f"{line:46s} {'실패':>7s}  {error}")
            failures.append((line, error or "측정 실패", 0.0))
            continue

        score = sum(line_scores) / len(line_scores)
        scores.append(score)
        row = f"{line:46s} {score:6.1f}%"
        if args.compare_priming and line_bare:
            bare_score = sum(line_bare) / len(line_bare)
            bare_scores.append(bare_score)
            row += f"  {bare_score:9.1f}%"
        if repeat > 1:
            row += f"   (최저 {min(line_scores):.1f}%)"
        print(row)

        if score < args.threshold:
            note = diff_note(line, worst_text)
            print(f"{'':46s}         받아쓴 값: {worst_text}")
            if note:
                print(f"{'':46s}         차이: {note}")
            failures.append((line, worst_text, score))

    if not scores:
        print("\n측정된 항목이 없습니다.")
        return 1

    mean = sum(scores) / len(scores)
    print(f"\n  평균 일치율: {mean:.1f}%  (기준 {args.threshold:.0f}%)")
    if bare_scores:
        bare_mean = sum(bare_scores) / len(bare_scores)
        print(f"  프라이밍 없음: {bare_mean:.1f}%  -> 프라이밍 효과 {mean - bare_mean:+.1f}%p")

    if failures:
        print(f"\n기준 미달 {len(failures)}건 — STT 설정이 바뀌었는지 확인하세요.")
        return 1
    print("\n전부 기준 통과.")
    return 0


def _transcribe_without_priming(stt, audio: bytes) -> str:
    """프라이밍 효과를 재기 위해 prompt 없이 한 번 더 호출한다."""
    import os

    from voisso.voice._http import post_multipart
    from voisso.voice.stt import OPENAI_STT_URL, _sniff_extension

    try:
        payload = post_multipart(
            OPENAI_STT_URL,
            fields={"model": stt.model, "language": "ko", "response_format": "json"},
            file_field="file",
            filename=f"call.{_sniff_extension(audio)}",
            file_bytes=audio,
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY') or ''}"},
            timeout=60.0,
        )
        return (payload.get("text") or "").strip()
    except Exception as exc:
        return f"(실패: {exc})"


if __name__ == "__main__":
    sys.exit(main())
