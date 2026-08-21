"""Voisso 음성 계층 — STT / TTS 프로바이더 추상화.

설계 원칙: **어떤 API 키도 없는 상태에서 import 되고 동작해야 한다.**
프로바이더가 없거나 호출이 실패하면 예외 대신 텍스트 모드로 내려간다.
외부 호출은 전부 표준 라이브러리 `urllib` 로 한다(의존성 최소화).
"""

from .stt import STTResult, get_stt_provider, stt_status, transcribe
from .tts import (
    SpeechContext,
    TTSResult,
    get_tts_provider,
    stream,
    synthesize,
    tts_status,
)

__all__ = [
    "STTResult",
    "SpeechContext",
    "TTSResult",
    "get_stt_provider",
    "get_tts_provider",
    "stream",
    "stt_status",
    "synthesize",
    "transcribe",
    "tts_status",
]
