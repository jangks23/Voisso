"""STT — OpenAI Whisper **API** 기반 음성 인식.

계약서 6절: 개발 환경은 노트북이다. **로컬 모델 가중치를 내려받지 않는다.**
Whisper large 체크포인트(수 GB)를 로컬에 두는 대신 클라우드 API로 처리한다.
의존성도 최소로 — 전용 SDK 도, HTTP 라이브러리도 없이 표준 라이브러리
`urllib` 로 REST 호출 하나만 한다.

한국어 + 경북 방언 입력이라 정확도가 중요한데, API 쪽 `whisper-1` 은
large-v2 급 모델이라 로컬 large 를 돌리는 것과 품질이 같거나 낫다.

환경변수
--------
VOISSO_STT_PROVIDER   openai | none   (기본 auto: 키가 있으면 openai, 없으면 none)
OPENAI_API_KEY       openai 사용 시 필수
VOISSO_STT_MODEL      기본 whisper-1
VOISSO_STT_LANGUAGE   기본 ko
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
from dataclasses import dataclass
from typing import Any

from ._http import post_multipart

log = logging.getLogger("voisso.voice.stt")

DEFAULT_MODEL = "whisper-1"
DEFAULT_LANGUAGE = "ko"
OPENAI_STT_URL = "https://api.openai.com/v1/audio/transcriptions"

# 방언 화자 발화에서 Whisper 가 엉뚱하게 받아쓰거나 환청을 뱉는 것을 줄이기 위한
# 힌트. 도메인 어휘(지명·민원 용어)를 미리 물려준다.
INITIAL_PROMPT = (
    "경상북도 주민이 도청에 전화로 민원을 접수하는 통화입니다. "
    "안동시, 구미시, 포항시, 경주시, 영주시, 상주시, 문경시, 의성군, 청송군, 예천군 같은 "
    "지명과 배수, 하수구, 도로 포장, 가로등, 상수도, 쓰레기 같은 민원 용어가 나옵니다."
)


@dataclass
class STTResult:
    """음성 인식 결과."""

    text: str
    language: str = DEFAULT_LANGUAGE
    duration_sec: float = 0.0
    provider: str = "none"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration_sec": round(self.duration_sec, 2),
            "provider": self.provider,
            "error": self.error,
        }


class STTProvider:
    """STT 프로바이더 인터페이스."""

    name = "base"

    @property
    def available(self) -> bool:  # pragma: no cover - 인터페이스
        return False

    def transcribe(self, audio: bytes, language: str = DEFAULT_LANGUAGE) -> STTResult:  # pragma: no cover
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "available": self.available}


class NoneSTT(STTProvider):
    """키 없이도 서버가 뜨게 해주는 폴백.

    음성이 들어오면 인식하지 못했다는 사실을 결과에 담아 돌려준다.
    오케스트레이터는 이걸 보고 "텍스트로 입력해 달라"는 흐름을 탄다.
    """

    name = "none"

    def __init__(self, reason: str = "STT 프로바이더가 설정되지 않았습니다.") -> None:
        self.reason = reason

    @property
    def available(self) -> bool:
        return False

    def transcribe(self, audio: bytes, language: str = DEFAULT_LANGUAGE) -> STTResult:
        return STTResult(text="", language=language, provider=self.name, error=self.reason)

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "available": False, "audio_in": False, "reason": self.reason}


class OpenAIWhisperSTT(STTProvider):
    """OpenAI Whisper API. 로컬 추론 없음, SDK 없음 — REST 한 방."""

    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self.model = model or os.getenv("VOISSO_STT_MODEL") or DEFAULT_MODEL

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio: bytes, language: str = DEFAULT_LANGUAGE) -> STTResult:
        if not audio:
            return STTResult(text="", language=language, provider=self.name, error="빈 오디오")
        try:
            payload = post_multipart(
                OPENAI_STT_URL,
                fields={
                    "model": self.model,
                    "language": (language or DEFAULT_LANGUAGE),
                    "prompt": INITIAL_PROMPT,
                    "response_format": "json",
                },
                # 브라우저 MediaRecorder 는 보통 webm/opus 를 준다. 확장자는
                # 참고용이고 실제 판별은 서버가 한다.
                file_field="file",
                filename="call.webm",
                file_bytes=audio,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60.0,
            )
            return STTResult(
                text=(payload.get("text") or "").strip(),
                language=language,
                provider=self.name,
            )
        except Exception as exc:
            log.warning("Whisper API 실패: %s", exc)
            return STTResult(text="", language=language, provider=self.name, error=str(exc))

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": self.available,
            "audio_in": True,
            "model": self.model,
            "api_key_set": bool(self.api_key),
        }


_provider: STTProvider | None = None
_provider_key: tuple[str, str] | None = None


def get_stt_provider(refresh: bool = False) -> STTProvider:
    """환경변수에 따라 STT 프로바이더를 만든다(프로세스 내 캐시)."""
    global _provider, _provider_key

    choice = (os.getenv("VOISSO_STT_PROVIDER") or "auto").strip().lower()
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    key = (choice, "1" if has_key else "0")
    if _provider is not None and _provider_key == key and not refresh:
        return _provider

    provider: STTProvider
    if choice in ("none", ""):
        provider = NoneSTT("VOISSO_STT_PROVIDER=none 으로 음성 인식이 꺼져 있습니다. 텍스트 모드로 동작합니다.")
    elif choice in ("openai", "whisper", "auto"):
        candidate = OpenAIWhisperSTT()
        if candidate.available:
            provider = candidate
        elif choice == "auto":
            provider = NoneSTT(
                "OPENAI_API_KEY 가 없어 텍스트 모드로 동작합니다. 키를 넣으면 음성 입력이 켜집니다."
            )
        else:
            provider = NoneSTT("VOISSO_STT_PROVIDER=openai 인데 OPENAI_API_KEY 가 없습니다.")
    else:
        provider = NoneSTT(f"알 수 없는 VOISSO_STT_PROVIDER='{choice}'. none 으로 처리합니다.")

    _provider, _provider_key = provider, key
    return provider


def transcribe(
    audio: bytes | str, language: str = DEFAULT_LANGUAGE, *, is_base64: bool = False
) -> STTResult:
    """오디오(bytes 또는 base64 문자열)를 텍스트로 변환한다. 예외를 던지지 않는다."""
    if isinstance(audio, str) or is_base64:
        raw = _decode_b64(audio if isinstance(audio, str) else audio.decode("ascii", "ignore"))
        if raw is None:
            return STTResult(text="", language=language, error="base64 디코딩 실패")
        audio = raw
    lang = (language or os.getenv("VOISSO_STT_LANGUAGE") or DEFAULT_LANGUAGE).strip()
    return get_stt_provider().transcribe(audio, lang or DEFAULT_LANGUAGE)


def _decode_b64(value: str) -> bytes | None:
    payload = value.strip()
    if payload.startswith("data:"):  # data:audio/webm;base64,xxxx
        _, _, payload = payload.partition(",")
    try:
        return base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None


def stt_status() -> dict[str, Any]:
    return get_stt_provider().status()
