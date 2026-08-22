"""API 사용량 집계 — 통화 한 건이 얼마를 쓰는지.

OpenAI 는 응답마다 `usage` 를 돌려주는데 지금까지 그걸 버리고 있었다.
auto-billing 환경에서 "얼마나 쓰는지 아무도 모르는" 상태는 그 자체가 위험이다.
API 키에 `api.usage.read` 스코프가 없으면 대시보드 말고는 조회 수단도 없으므로,
**우리가 직접 세는 수밖에 없다.**

집계 단위는 두 가지다.

- `Usage` — 통화 한 건. 세션에 붙어 다니고 종료 시 로그·응답에 실린다.
- `PROCESS_TOTAL` — 서버가 뜬 뒤 누적. 리허설 스크립트가 한 줄로 뽑아 쓴다.

필드 규약(P3 리허설 집계용)은 `as_dict()` 가 정의한다. 이름을 바꾸지 마라.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Usage:
    """한 통화(또는 한 번의 리허설)가 쓴 양."""

    # 대화·요약 LLM
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # 프롬프트 캐시로 재사용된 입력 토큰. 과금이 싸므로 따로 센다.
    cached_input_tokens: int = 0

    # 음성 인식 — 분 단위 과금이라 오디오 길이가 곧 비용이다.
    stt_calls: int = 0
    stt_audio_sec: float = 0.0
    stt_input_tokens: int = 0

    # 음성 합성 — 글자 수 과금.
    tts_calls: int = 0
    tts_characters: int = 0

    # 모델별 분해 (어느 모델이 얼마나 썼는지)
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    # -- 기록 -------------------------------------------------------------
    def add_llm(self, model: str, usage: dict[str, Any] | None) -> None:
        """채팅 응답의 usage 객체를 그대로 받아 누적한다.

        OpenAI 는 `prompt_tokens`/`completion_tokens`, Anthropic 은
        `input_tokens`/`output_tokens` 를 쓴다. 둘 다 받는다.
        """
        payload = usage or {}
        prompt = int(payload.get("prompt_tokens") or payload.get("input_tokens") or 0)
        completion = int(payload.get("completion_tokens") or payload.get("output_tokens") or 0)

        details = payload.get("prompt_tokens_details") or {}
        cached = int(
            details.get("cached_tokens")
            or payload.get("cache_read_input_tokens")
            or 0
        )

        with self._lock:
            self.llm_calls += 1
            self.input_tokens += prompt
            self.output_tokens += completion
            self.cached_input_tokens += cached
            slot = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0})
            slot["calls"] += 1
            slot["input"] += prompt
            slot["output"] += completion

    def add_stt(self, model: str, audio_sec: float = 0.0, usage: dict[str, Any] | None = None) -> None:
        payload = usage or {}
        tokens = int(payload.get("input_tokens") or payload.get("prompt_tokens") or 0)
        with self._lock:
            self.stt_calls += 1
            self.stt_audio_sec = round(self.stt_audio_sec + max(audio_sec, 0.0), 2)
            self.stt_input_tokens += tokens
            slot = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0})
            slot["calls"] += 1
            slot["input"] += tokens

    def add_tts(self, model: str, characters: int) -> None:
        with self._lock:
            self.tts_calls += 1
            self.tts_characters += max(characters, 0)
            slot = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0})
            slot["calls"] += 1

    def merge(self, other: Usage) -> None:
        with self._lock:
            self.llm_calls += other.llm_calls
            self.input_tokens += other.input_tokens
            self.output_tokens += other.output_tokens
            self.cached_input_tokens += other.cached_input_tokens
            self.stt_calls += other.stt_calls
            self.stt_audio_sec = round(self.stt_audio_sec + other.stt_audio_sec, 2)
            self.stt_input_tokens += other.stt_input_tokens
            self.tts_calls += other.tts_calls
            self.tts_characters += other.tts_characters
            for model, counts in other.by_model.items():
                slot = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0})
                for key, value in counts.items():
                    slot[key] = slot.get(key, 0) + value

    # -- 조회 -------------------------------------------------------------
    @property
    def total_tokens(self) -> int:
        """대화 토큰 합계. 상한 판정에 쓴다."""
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        """**필드 규약.** 리허설 집계(P3)와 대시보드가 이 이름을 그대로 쓴다."""
        return {
            "llm": {
                "calls": self.llm_calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cached_input_tokens": self.cached_input_tokens,
            },
            "stt": {
                "calls": self.stt_calls,
                "audio_sec": round(self.stt_audio_sec, 2),
                "input_tokens": self.stt_input_tokens,
            },
            "tts": {"calls": self.tts_calls, "characters": self.tts_characters},
            "total_tokens": self.total_tokens,
            "by_model": self.by_model,
        }

    def one_line(self, label: str = "") -> str:
        """로그·스크립트용 한 줄 요약."""
        head = f"{label} " if label else ""
        return (
            f"{head}입력 {self.input_tokens:,}토큰 / 출력 {self.output_tokens:,}토큰"
            f" (캐시 {self.cached_input_tokens:,})"
            f" · 오디오 {self.stt_audio_sec:.1f}초"
            f" · TTS {self.tts_characters:,}자"
            f" · 호출 {self.llm_calls + self.stt_calls + self.tts_calls}회"
        )


# 프로세스 전체 누적. 서버가 뜬 뒤 총 얼마를 썼는지.
PROCESS_TOTAL = Usage()
