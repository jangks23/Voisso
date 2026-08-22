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
VOISSO_STT_MODEL      whisper-1 | gpt-4o-transcribe(기본) | gpt-4o-mini-transcribe | gpt-transcribe
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

# 기본 모델을 gpt-4o-transcribe 로 둔 이유:
#   1. 한국어 인식 품질이 whisper-1 보다 낫다. whisper-1 은 OpenAI 문서에서도
#      legacy 로 분류되고, 새 구현에는 신형 transcribe 계열을 권한다.
#   2. **프라이밍 프롬프트 예산이 훨씬 크다.** whisper-1 은 224 토큰이 상한이라
#      방언 어미 몇 개 넣으면 끝나는데, 신형은 사투리 어휘를 충분히 물릴 수 있다.
#      사투리 인식이 이 프로젝트의 핵심이라 이 차이가 결정적이다.
# whisper-1 은 타임스탬프·번역이 필요할 때를 위해 그대로 선택 가능하게 둔다.
# 더 최신인 gpt-transcribe 도 VOISSO_STT_MODEL 로 지정하면 그대로 쓰인다.
DEFAULT_MODEL = "gpt-4o-transcribe"

# 모델별 프라이밍 프롬프트 예산(토큰).
# whisper-1 의 224 는 문서에 명시된 상한이고, 신형 계열은 명시된 수치가 없어
# 보수적으로 잡았다. 넘치면 API 가 잘라내므로 우리가 먼저 자른다.
WHISPER_PROMPT_TOKENS = 224
MODERN_PROMPT_TOKENS = 900
DEFAULT_LANGUAGE = "ko"
OPENAI_STT_URL = "https://api.openai.com/v1/audio/transcriptions"

# 방언 화자 발화가 표준어로 뭉개지거나 환청이 섞이는 것을 줄이기 위한 힌트.
# P5 방언 사전이 있으면 거기서 동적으로 만들고(build_priming_prompt),
# 없으면 아래 고정 문구로 폴백한다.
FALLBACK_PROMPT = (
    "경상북도 주민이 도청에 전화로 민원을 접수하는 통화입니다. "
    "안동시, 구미시, 포항시, 경주시, 영주시, 상주시, 문경시, 의성군, 청송군, 예천군 같은 "
    "지명과 배수, 하수구, 도로 포장, 가로등, 상수도, 쓰레기 같은 민원 용어가 나옵니다."
)

_prompt_cache: dict[str, str] = {}


def _prompt_budget(model: str) -> int:
    return WHISPER_PROMPT_TOKENS if model.startswith("whisper") else MODERN_PROMPT_TOKENS


def priming_prompt(model: str = DEFAULT_MODEL) -> str:
    """모델 예산에 맞춘 프라이밍 프롬프트. 사전이 없으면 고정 문구."""
    from .vocabulary import build_priming_prompt, vocabulary_status

    status = vocabulary_status()
    # 사전이 나중에 붙을 수 있으므로 사전 상태까지 캐시 키에 넣는다.
    key = f"{model}|{status['dialect_lexicon']}|{status['dialect_terms']}"
    cached = _prompt_cache.get(key)
    if cached is not None:
        return cached

    if not status["dialect_lexicon"]:
        log.info("방언 사전 없음 — 고정 프라이밍 문구를 씁니다.")
        _prompt_cache[key] = FALLBACK_PROMPT
        return FALLBACK_PROMPT

    budget = _prompt_budget(model)
    prompt, truncated = build_priming_prompt(budget)
    if truncated:
        log.info(
            "프라이밍 프롬프트를 %s 예산(%d 토큰)에 맞춰 잘랐습니다 "
            "— 사용 %d자, 사전 어휘 %d개 중 일부만 반영됨.",
            model,
            budget,
            len(prompt),
            status["dialect_terms"],
        )
    _prompt_cache[key] = prompt
    return prompt


_AUDIO_MAGIC = (
    (b"RIFF", b"WAVE", "wav"),
    (b"\x1a\x45\xdf\xa3", None, "webm"),
    (b"OggS", None, "ogg"),
    (b"fLaC", None, "flac"),
    (b"ID3", None, "mp3"),
    (b"\xff\xfb", None, "mp3"),
    (b"\xff\xf3", None, "mp3"),
)


def audio_duration_sec(audio: bytes) -> float:
    """오디오 길이(초). WAV 는 헤더에서 정확히 계산한다.

    STT 는 오디오 길이로 과금되므로 이 값이 곧 비용이다. WAV 가 아니면
    (브라우저 webm 등) 헤더만으로는 알 수 없어 0 을 돌려준다 — 추정치를
    지어내느니 모른다고 하는 편이 낫다.
    """
    if len(audio) < 44 or not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
        return 0.0
    try:
        import io
        import wave

        with wave.open(io.BytesIO(audio)) as handle:
            rate = handle.getframerate()
            return round(handle.getnframes() / rate, 2) if rate else 0.0
    except Exception:
        return 0.0


def _sniff_extension(audio: bytes) -> str:
    """오디오 바이트의 매직 넘버로 컨테이너를 판별한다.

    OpenAI 오디오 엔드포인트는 업로드 파일의 **확장자**로 포맷을 판단한다.
    확장자가 실제 내용과 어긋나면 400 "Audio file might be corrupted or
    unsupported" 로 거부한다. 브라우저 MediaRecorder(webm/opus)만 가정하면
    TTS 가 만든 WAV 나 업로드된 mp3 가 그대로 실패하므로 내용으로 판별한다.
    """
    head = audio[:16]
    for prefix, marker, ext in _AUDIO_MAGIC:
        if head.startswith(prefix) and (marker is None or marker in head):
            return ext
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "m4a"
    return "webm"


@dataclass
class STTResult:
    """음성 인식 결과."""

    text: str
    language: str = DEFAULT_LANGUAGE
    duration_sec: float = 0.0
    provider: str = "none"
    error: str | None = None
    model: str = ""
    # 응답이 usage 를 주면 그대로 담는다. 분 단위 과금이라 duration_sec 이
    # 실질 비용 지표이고, 토큰 과금 모델이면 usage 쪽이 정확하다.
    usage: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration_sec": round(self.duration_sec, 2),
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage,
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
        # 키가 '있다'와 '통한다'는 다르다. 마지막 실패를 기억해 두고
        # 상태 조회에 실어 보낸다 — 안 그러면 401 나는 키를 두고도
        # 화면에는 "음성 인식 켜짐"이라고 뜬다.
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio: bytes, language: str = DEFAULT_LANGUAGE) -> STTResult:
        if not audio:
            return STTResult(text="", language=language, provider=self.name, error="빈 오디오")
        try:
            self.last_error = None
            payload = post_multipart(
                OPENAI_STT_URL,
                fields={
                    "model": self.model,
                    "language": (language or DEFAULT_LANGUAGE),
                    "prompt": priming_prompt(self.model),
                    "response_format": "json",
                },
                # OpenAI 는 업로드 파일의 확장자로 포맷을 판단한다. 실제
                # 바이트를 보고 확장자를 맞춰야 WAV/mp3 도 통과한다.
                file_field="file",
                filename=f"call.{_sniff_extension(audio)}",
                file_bytes=audio,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60.0,
            )
            return STTResult(
                text=(payload.get("text") or "").strip(),
                language=language,
                duration_sec=audio_duration_sec(audio),
                provider=self.name,
                model=self.model,
                usage=payload.get("usage"),
            )
        except Exception as exc:
            message = _explain(exc)
            self.last_error = message
            log.warning("음성 인식 실패: %s", message)
            return STTResult(
                text="", language=language, provider=self.name, model=self.model, error=message
            )

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": self.available,
            "audio_in": True,
            "model": self.model,
            "prompt_tokens_budget": _prompt_budget(self.model),
            "api_key_set": bool(self.api_key),
            "last_error": self.last_error,
        }


def _explain(exc: Exception) -> str:
    """실패 원인을 담당자가 바로 고칠 수 있는 문장으로 바꾼다."""
    from ._http import HTTPError

    if isinstance(exc, HTTPError):
        if exc.status == 401:
            return "OPENAI_API_KEY 가 거부되었습니다(401). 키가 올바른지 확인하세요."
        if exc.status == 429:
            return "OpenAI 사용 한도에 걸렸습니다(429). 잠시 후 다시 시도하세요."
        if exc.status == 400:
            return f"요청이 거부되었습니다(400). 오디오 형식이나 모델명을 확인하세요. {exc}"
        return str(exc)
    return str(exc)


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
