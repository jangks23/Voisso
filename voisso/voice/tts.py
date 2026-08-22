"""TTS — 프로바이더 추상화.

계약서 6절에 따라 **로컬 음향 모델을 쓰지 않는다.** 전부 REST 호출이고,
전용 SDK 도 HTTP 라이브러리도 없이 표준 라이브러리 `urllib` 만 쓴다.

`VOISSO_TTS_PROVIDER` 로 전환한다.

- ``typecast``   : 1순위. 한국어 음성 품질이 좋고 로컬 자원을 안 쓴다.
- ``elevenlabs`` : 대안.
- ``none``       : **기본값.** 오디오를 만들지 않고 텍스트만 돌려준다.
                   어떤 키도 없이 데모 전체가 돌아가야 하므로 이게 기본이다.

프로바이더가 선택됐는데 키가 없거나 호출이 실패하면(429/5xx/타임아웃)
예외를 던지지 않고 텍스트 모드로 내려간다. 통화 중에 TTS 때문에 접수가
끊기는 게 더 나쁜 실패다.

**사투리에 대해 정직하게.** Voisso 가 만드는 것은 사투리 *텍스트* 다
(`voisso.dialect.to_dialect`). 그 텍스트를 어떤 억양으로 읽어줄지는 **보이스
선택에 달려 있다.** Typecast API 메타데이터에는 언어·억양 필드가 없어서
특정 보이스가 경상도 억양인지 API 로 확인할 방법이 없다. 그래서 이 코드는
어떤 보이스도 "사투리를 구사한다"고 단정하지 않는다. 억양까지 맞추려면
사람이 직접 들어보고 `TYPECAST_VOICE_ID` 를 고르는 수밖에 없다.

환경변수
--------
VOISSO_TTS_PROVIDER    typecast | elevenlabs | none  (기본 none)
TYPECAST_API_KEY      typecast 사용 시 필수
TYPECAST_VOICE_ID     보이스 id (비우면 DEFAULT_TYPECAST_VOICE)
TYPECAST_MODEL        기본 ssfm-v30
VOISSO_TTS_TEMPO      말하기 속도 0.5~2.0 (기본 0.85, 어르신 대상이라 늦춤)
                      0.85 가 실질적 하한 — 그 아래로는 차이가 측정 편차에 묻힌다
ELEVENLABS_API_KEY    elevenlabs 사용 시 필수
ELEVENLABS_VOICE_ID   voice id (비우면 공개 데모 보이스)
ELEVENLABS_MODEL_ID   기본 eleven_multilingual_v2
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator

from ._http import get_json, post_json, post_stream

log = logging.getLogger("voisso.voice.tts")

DEFAULT_LANGUAGE = "ko"

# --- Typecast -------------------------------------------------------------
TYPECAST_BASE = "https://api.typecast.ai"
TYPECAST_TTS_URL = f"{TYPECAST_BASE}/v1/text-to-speech"
TYPECAST_STREAM_URL = f"{TYPECAST_BASE}/v1/text-to-speech/stream"
TYPECAST_VOICES_URL = f"{TYPECAST_BASE}/v2/voices"
TYPECAST_RECOMMEND_URL = f"{TYPECAST_BASE}/v1/voices/recommendations"

DEFAULT_TYPECAST_MODEL = "ssfm-v30"

# 검토한 한국어 보이스들. API 메타데이터에 억양 필드가 없으므로
# "사투리 보이스"라고 표시하지 않는다. 최종 선택은 사람이 듣고 정했다.
TYPECAST_VOICE_CANDIDATES = {
    # Yongsik — male / Conversational. 청취 비교 후 최종 채택.
    "yongsik": "tc_5feb2085cca1a479e73bac37",
    "nari": "tc_606c6b127b9f53b4cd1743f5",
    "kyungsook": "tc_5ebea266728f5b00075e6215",
    "duckchun": "tc_5c3c52c95827e00008dd7f34",
    "mija": "tc_6059db64e2d12a32cce1b0c7",
    "moonjung": "tc_68f9c6a72f0f04a417bb136f",
}
# TYPECAST_VOICE_ID 가 비어 있을 때 쓰는 기본 보이스. 환경변수가 항상 우선한다.
DEFAULT_TYPECAST_VOICE = TYPECAST_VOICE_CANDIDATES["yongsik"]

# 말하기 속도. 어르신이 알아듣기 쉽도록 표준 속도(1.0)보다 늦춘다.
#
# 0.85 가 실질적 하한이다. 같은 문장을 3회씩 측정한 결과:
#   1.00 -> 5.75초 / 0.90 -> 7.06초 / 0.85 -> 7.65초 / 0.80 -> 7.63초
# 1.0~0.85 구간에서는 값을 내릴수록 확실히 느려지지만, 0.85 아래로는
# 차이가 실행 간 편차(같은 설정에서 7.18~7.71초)에 묻혀 사라진다.
# 더 또박또박 들리게 하려면 문장을 짧게 쓰는 쪽이 낫다 —
# 무음 마크업은 이 조합에서 먹지 않는다(아래 참고).
DEFAULT_TYPECAST_TEMPO = 0.85
# API 가 허용하는 범위. 벗어나면 클램프한다.
TYPECAST_TEMPO_MIN = 0.5
TYPECAST_TEMPO_MAX = 2.0

# 무음 마크업(`<|0.5s|>`)은 쓰지 않는다 — **측정해 보니 먹지 않는다.**
# ssfm-v30 + /v1/text-to-speech 조합에서 같은 문장으로 확인한 결과:
#   마크업 없음 -> 전체 4.47초 / 최장 무음 0.23초
#   <|0.5s|>    -> 전체 4.71초 / 최장 무음 0.28초
#   <|2s|>      -> 전체 4.12초 / 최장 무음 0.30초
# 무음이 실제로 삽입됐다면 <|2s|> 에서 최장 무음이 2초 가까이 나와야 하는데
# 0.3초에 머물렀고, 전체 길이는 오히려 <|0.5s|> 보다 짧았다. 마크업이
# 무음이 아니라 텍스트로 소비된다는 뜻이다. 다시 시도하려면 이 수치부터
# 재현해 보고 판단할 것.

# 응답마다 음량이 튀지 않도록 라우드니스를 고정한다.
# 통화 데모에서 턴마다 볼륨이 달라지면 조악하게 들린다.
TYPECAST_TARGET_LUFS = -14

# Typecast 는 ISO 639-3 을 쓴다. ko -> kor
TYPECAST_LANG = {"ko": "kor", "en": "eng", "ja": "jpn", "zh": "zho"}
TYPECAST_MAX_CHARS = 2000

# Typecast 가 요구하는 출처 표기. **정적 상수다.**
# 사용자명·이메일·저장소명·API 키·세션 ID 등 런타임 정보를 절대 넣지 않는다.
# source=api-page 는 이 지침을 API 페이지에서 받았다는 뜻이고,
# generated_by=claude-code 는 통합을 만든 도구를 가리킨다.
TYPECAST_USER_AGENT = (
    "typecast-direct/1 urllib typecast-integration/1 "
    "(source=api-page; generated_by=claude-code)"
)

# --- ElevenLabs -----------------------------------------------------------
ELEVEN_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_ELEVEN_MODEL = "eleven_multilingual_v2"
DEFAULT_ELEVEN_VOICE = "21m00Tcm4TlvDq8ikWAM"


def resolve_tempo(raw: str | float | None = None) -> float:
    """말하기 속도를 정한다. 잘못된 값이 통화를 막지는 않게 한다."""
    value = raw if raw is not None else os.getenv("VOISSO_TTS_TEMPO")
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_TYPECAST_TEMPO
    try:
        tempo = float(value)
    except (TypeError, ValueError):
        log.warning(
            "VOISSO_TTS_TEMPO='%s' 를 숫자로 읽을 수 없습니다. 기본값 %.2f 를 씁니다.",
            value,
            DEFAULT_TYPECAST_TEMPO,
        )
        return DEFAULT_TYPECAST_TEMPO

    clamped = min(max(tempo, TYPECAST_TEMPO_MIN), TYPECAST_TEMPO_MAX)
    if clamped != tempo:
        log.warning(
            "audio_tempo %.2f 는 허용 범위(%.1f~%.1f) 밖입니다. %.2f 로 조정합니다.",
            tempo,
            TYPECAST_TEMPO_MIN,
            TYPECAST_TEMPO_MAX,
            clamped,
        )
    return clamped


@dataclass
class SpeechContext:
    """감정 추론에 쓰는 앞뒤 문맥.

    Typecast 의 `emotion_type: "smart"` 는 앞뒤 문장을 같이 주면 문맥에 맞는
    감정을 고른다. 민원 통화는 어르신이 방금 한 말에 따라 톤이 달라져야 해서
    이 값이 실제로 도움이 된다.
    """

    previous_text: str = ""
    next_text: str = ""

    def as_prompt_fields(self) -> dict[str, str]:
        fields = {}
        if self.previous_text.strip():
            fields["previous_text"] = self.previous_text.strip()[:TYPECAST_MAX_CHARS]
        if self.next_text.strip():
            fields["next_text"] = self.next_text.strip()[:TYPECAST_MAX_CHARS]
        return fields


@dataclass
class TTSResult:
    """음성 합성 결과. `audio_b64` 가 None 이면 텍스트 모드다."""

    text: str
    audio_b64: str | None = None
    mime: str | None = None
    provider: str = "none"
    error: str | None = None

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_b64)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "audio_b64": self.audio_b64,
            "mime": self.mime,
            "provider": self.provider,
            "error": self.error,
        }


class TTSProvider:
    """TTS 프로바이더 인터페이스."""

    name = "base"
    supports_streaming = False
    # 키가 '있다'와 '통한다'는 다르다. 크레딧 소진(402)·한도(429)처럼
    # 키가 멀쩡해도 실패하는 경우를 상태에 드러내기 위해 기억한다.
    last_error: str | None = None

    @property
    def available(self) -> bool:  # pragma: no cover - 인터페이스
        return False

    def synthesize(  # pragma: no cover - 인터페이스
        self,
        text: str,
        language: str = DEFAULT_LANGUAGE,
        context: SpeechContext | None = None,
    ) -> TTSResult:
        raise NotImplementedError

    def stream(
        self,
        text: str,
        language: str = DEFAULT_LANGUAGE,
        context: SpeechContext | None = None,
    ) -> Iterator[bytes]:
        """스트리밍을 지원하지 않으면 통짜 오디오를 한 청크로 흘린다."""
        result = self.synthesize(text, language, context)
        if result.audio_b64:
            yield base64.b64decode(result.audio_b64)

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "available": self.available}


class NoneTTS(TTSProvider):
    """텍스트 전용 모드. 키가 하나도 없어도 전체 흐름이 돈다."""

    name = "none"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason

    @property
    def available(self) -> bool:
        return True  # 항상 쓸 수 있다. 오디오만 없을 뿐이다.

    def synthesize(
        self,
        text: str,
        language: str = DEFAULT_LANGUAGE,
        context: SpeechContext | None = None,
    ) -> TTSResult:
        return TTSResult(text=text, provider=self.name, error=self.reason)

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "available": True, "audio": False, "reason": self.reason}


class TypecastProvider(TTSProvider):
    """Typecast SSFM.

    - `POST /v1/text-to-speech`        -> 통짜 오디오 (계약서 audio_b64 용)
    - `POST /v1/text-to-speech/stream` -> 32kHz 16bit mono WAV 스트림
                                          (첫 청크에만 헤더, 이후 raw PCM)

    API 키는 **서버에서만** 쓴다. 브라우저로 내려보내지 않는다.
    """

    name = "typecast"
    supports_streaming = True

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model: str | None = None,
        tempo: float | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TYPECAST_API_KEY") or ""
        self.voice_id = voice_id or os.getenv("TYPECAST_VOICE_ID") or DEFAULT_TYPECAST_VOICE
        self.model = model or os.getenv("TYPECAST_MODEL") or DEFAULT_TYPECAST_MODEL
        self.tempo = resolve_tempo(tempo)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        # Authorization: Bearer 는 401/403 이 난다. 반드시 X-API-KEY.
        return {"X-API-KEY": self.api_key, "User-Agent": TYPECAST_USER_AGENT}

    def _payload(
        self, text: str, language: str, context: SpeechContext | None
    ) -> dict[str, Any]:
        # emotion_type "smart" 는 문맥에서 감정을 추론한다. 민원 응대에 맞다.
        # 이 보이스는 tonedown/whisper 도 지원하지만 감정을 직접 지정하면
        # 오히려 부자연스러워진다. 문맥 추론에 맡기는 쪽이 낫다.
        prompt: dict[str, Any] = {"emotion_type": "smart"}
        if context is not None:
            prompt.update(context.as_prompt_fields())
        return {
            "model": self.model,
            "voice_id": self.voice_id,
            "text": text[:TYPECAST_MAX_CHARS],
            "language": TYPECAST_LANG.get(language, "kor"),
            "prompt": prompt,
            # 파일 생성과 스트리밍이 이 페이로드를 공유하므로
            # 속도·음량 설정이 양쪽에 똑같이 걸린다.
            "output": {
                "audio_format": "wav",
                "audio_tempo": self.tempo,
                "target_lufs": TYPECAST_TARGET_LUFS,
            },
        }

    def synthesize(
        self,
        text: str,
        language: str = DEFAULT_LANGUAGE,
        context: SpeechContext | None = None,
    ) -> TTSResult:
        if not text.strip():
            return TTSResult(text=text, provider=self.name, error="빈 텍스트")
        try:
            audio, headers = post_json(
                TYPECAST_TTS_URL,
                self._payload(text, language, context),
                headers=self._headers(),
                timeout=30.0,
            )
            return TTSResult(
                text=text,
                audio_b64=base64.b64encode(audio).decode("ascii"),
                mime=headers.get("content-type", "audio/wav").split(";")[0],
                provider=self.name,
            )
        except Exception as exc:
            # 402 크레딧 소진 / 429 한도초과 / 5xx / 타임아웃 — 통화는 계속돼야 한다.
            message = _explain_tts(exc)
            self.last_error = message
            log.warning("Typecast 합성 실패, 텍스트 모드로 진행: %s", message)
            return TTSResult(text=text, provider=self.name, error=message)

    def stream(
        self,
        text: str,
        language: str = DEFAULT_LANGUAGE,
        context: SpeechContext | None = None,
    ) -> Iterator[bytes]:
        """첫 음성까지의 지연을 줄이는 경로. 실패하면 조용히 끝난다."""
        if not text.strip():
            return
        try:
            yield from post_stream(
                TYPECAST_STREAM_URL,
                self._payload(text, language, context),
                headers=self._headers(),
                timeout=60.0,
            )
        except Exception as exc:
            message = _explain_tts(exc)
            self.last_error = message
            log.warning("Typecast 스트리밍 실패: %s", message)

    # -- 설치 도우미 (통화 경로에서는 쓰지 않는다) -------------------------
    def list_voices(self) -> list[dict[str, Any]]:
        try:
            payload = get_json(TYPECAST_VOICES_URL, headers=self._headers(), timeout=30.0)
            return payload if isinstance(payload, list) else payload.get("voices", [])
        except Exception as exc:
            log.warning("Typecast 보이스 목록 조회 실패: %s", exc)
            return []

    def recommend_voices(self, query: str) -> list[dict[str, Any]]:
        """자연어로 보이스를 찾는다. 억양 보장은 못 한다 — 사람이 들어봐야 한다."""
        from urllib.parse import quote

        try:
            payload = get_json(
                f"{TYPECAST_RECOMMEND_URL}?query={quote(query)}",
                headers=self._headers(),
                timeout=30.0,
            )
            return payload if isinstance(payload, list) else payload.get("voices", [])
        except Exception as exc:
            log.warning("Typecast 보이스 추천 조회 실패: %s", exc)
            return []

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": self.available,
            "audio": True,
            "streaming": True,
            "voice_id": self.voice_id,
            "model": self.model,
            "tempo": self.tempo,
            "target_lufs": TYPECAST_TARGET_LUFS,
            "api_key_set": bool(self.api_key),
            "last_error": self.last_error,
            # 억양은 보이스 선택의 문제다. API 는 억양 정보를 주지 않는다.
            "accent": "보이스 선택에 따름 (API 가 억양 정보를 제공하지 않음)",
        }


class ElevenLabsProvider(TTSProvider):
    """ElevenLabs 대안 경로."""

    name = "elevenlabs"

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY") or ""
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_ELEVEN_VOICE
        self.model_id = model_id or os.getenv("ELEVENLABS_MODEL_ID") or DEFAULT_ELEVEN_MODEL

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def synthesize(
        self,
        text: str,
        language: str = DEFAULT_LANGUAGE,
        context: SpeechContext | None = None,
    ) -> TTSResult:
        if not text.strip():
            return TTSResult(text=text, provider=self.name, error="빈 텍스트")
        try:
            audio, _ = post_json(
                ELEVEN_TTS_URL.format(voice_id=self.voice_id),
                {
                    "text": text,
                    "model_id": self.model_id,
                    "voice_settings": {
                        "stability": 0.45,
                        "similarity_boost": 0.85,
                        "style": 0.35,
                        "use_speaker_boost": True,
                    },
                },
                headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
                timeout=30.0,
            )
            return TTSResult(
                text=text,
                audio_b64=base64.b64encode(audio).decode("ascii"),
                mime="audio/mpeg",
                provider=self.name,
            )
        except Exception as exc:
            message = _explain_tts(exc)
            self.last_error = message
            log.warning("ElevenLabs 합성 실패, 텍스트 모드로 진행: %s", message)
            return TTSResult(text=text, provider=self.name, error=message)

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": self.available,
            "audio": True,
            "streaming": False,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "api_key_set": bool(self.api_key),
            "accent": "보이스 선택에 따름",
        }


def _explain_tts(exc: Exception) -> str:
    """합성 실패를 담당자가 바로 고칠 수 있는 문장으로."""
    from ._http import HTTPError

    if isinstance(exc, HTTPError):
        if exc.status == 402:
            return "TTS 크레딧이 소진되었습니다(402). 계정 잔액을 확인하세요."
        if exc.status == 401:
            return "TTS API 키가 거부되었습니다(401)."
        if exc.status == 429:
            return "TTS 사용 한도에 걸렸습니다(429)."
        return str(exc)
    return str(exc)


_provider: TTSProvider | None = None
_provider_key: str | None = None


def get_tts_provider(refresh: bool = False) -> TTSProvider:
    """`VOISSO_TTS_PROVIDER` 에 따라 프로바이더를 만든다(프로세스 내 캐시)."""
    global _provider, _provider_key

    choice = (os.getenv("VOISSO_TTS_PROVIDER") or "none").strip().lower()
    if _provider is not None and _provider_key == choice and not refresh:
        return _provider

    provider: TTSProvider
    if choice == "typecast":
        candidate: TTSProvider = TypecastProvider()
        provider = (
            candidate
            if candidate.available
            else NoneTTS("TYPECAST_API_KEY 가 없어 텍스트 모드로 강등했습니다.")
        )
    elif choice == "elevenlabs":
        candidate = ElevenLabsProvider()
        provider = (
            candidate
            if candidate.available
            else NoneTTS("ELEVENLABS_API_KEY 가 없어 텍스트 모드로 강등했습니다.")
        )
    elif choice in ("none", ""):
        provider = NoneTTS()
    else:
        provider = NoneTTS(f"알 수 없는 VOISSO_TTS_PROVIDER='{choice}'. none 으로 처리합니다.")

    _provider, _provider_key = provider, choice
    return provider


def synthesize(
    text: str, language: str | None = None, context: SpeechContext | None = None
) -> TTSResult:
    """텍스트를 음성으로 합성한다. 실패해도 예외를 던지지 않는다."""
    lang = (language or os.getenv("VOISSO_TTS_LANGUAGE") or DEFAULT_LANGUAGE).strip()
    return get_tts_provider().synthesize(text, lang or DEFAULT_LANGUAGE, context)


def stream(
    text: str, language: str | None = None, context: SpeechContext | None = None
) -> Iterator[bytes]:
    """오디오를 청크 단위로 흘린다. 첫 음성까지의 지연을 줄이는 경로."""
    lang = (language or os.getenv("VOISSO_TTS_LANGUAGE") or DEFAULT_LANGUAGE).strip()
    return get_tts_provider().stream(text, lang or DEFAULT_LANGUAGE, context)


def tts_status() -> dict[str, Any]:
    return get_tts_provider().status()
