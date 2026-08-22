"""LLM 스트리밍 응답에서 **문장을 조기에 뽑아내는** 파서.

왜 필요한가: 구조화 출력(JSON)을 통째로 기다리면 LLM 2.3초가 끝나야 TTS 를
시작할 수 있다. 하지만 우리가 첫 소리를 내는 데 필요한 것은 `reply` 의 **첫
문장** 하나뿐이다. "아이고, 그러셨구나예." 를 먼저 들려주고 뒷문장을 이어
붙이면 LLM 시간과 TTS 시간이 겹쳐진다. 실제 상담원도 그렇게 말한다.

그래서 스트리밍으로 들어오는 JSON 조각에서 `"reply"` 값만 증분 파싱한다.
JSON 전체를 파싱할 수 없는 중간 상태에서도 문자열 값은 읽어낼 수 있다.

프로퍼티 순서는 보장되지 않으므로, `reply` 를 못 찾으면 조용히 아무것도
내보내지 않고 호출자가 완성된 JSON 을 쓰게 둔다(폴백).
"""

from __future__ import annotations

import re

# 한국어 문장 끝. 마침표·물음표·느낌표 뒤에 공백이나 끝이 오면 한 문장으로 본다.
_SENTENCE_END = re.compile(r"[.!?…]+[\s]*")

# 너무 짧은 조각을 따로 합성하면 오히려 어색하고 호출만 는다.
MIN_SENTENCE_CHARS = 6


class ReplySentenceExtractor:
    """스트리밍 JSON 조각을 먹여 주면 완성된 문장을 뱉는다."""

    def __init__(self) -> None:
        self._raw = ""
        self._reply = ""
        self._emitted = 0
        self._started = False
        self._closed = False

    def feed(self, delta: str) -> list[str]:
        """조각을 넣고, 이번에 새로 완성된 문장들을 돌려준다."""
        if self._closed or not delta:
            return []
        self._raw += delta
        self._sync_reply()
        return self._take_sentences()

    def finish(self) -> list[str]:
        """스트림이 끝났다. 남은 꼬리를 마지막 문장으로 넘긴다."""
        self._sync_reply()
        self._closed = True
        tail = self._reply[self._emitted :].strip()
        self._emitted = len(self._reply)
        return [tail] if tail else []

    @property
    def reply(self) -> str:
        return self._reply

    # -- 내부 ------------------------------------------------------------
    def _sync_reply(self) -> None:
        """누적된 원문에서 `"reply"` 문자열 값을 다시 읽는다."""
        if not self._started:
            match = re.search(r'"reply"\s*:\s*"', self._raw)
            if match is None:
                return
            self._started = True
            self._value_start = match.end()

        body = self._raw[self._value_start :]
        out: list[str] = []
        index = 0
        while index < len(body):
            char = body[index]
            if char == "\\":
                # 이스케이프 시퀀스. 아직 뒷글자가 안 왔으면 여기서 멈춘다.
                if index + 1 >= len(body):
                    break
                nxt = body[index + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                index += 2
                continue
            if char == '"':
                # 값이 끝났다.
                self._closed = True
                break
            out.append(char)
            index += 1
        self._reply = "".join(out)

    def _take_sentences(self) -> list[str]:
        """아직 안 내보낸 구간에서 문장 경계까지 잘라낸다."""
        pending = self._reply[self._emitted :]
        sentences: list[str] = []
        cursor = 0
        for match in _SENTENCE_END.finditer(pending):
            piece = pending[cursor : match.end()].strip()
            if not piece:
                continue
            if len(piece) < MIN_SENTENCE_CHARS and sentences:
                # 짧은 꼬리는 앞 문장에 붙인다.
                sentences[-1] = f"{sentences[-1]} {piece}"
            elif len(piece) < MIN_SENTENCE_CHARS:
                continue  # 다음 문장과 합쳐질 때까지 기다린다
            else:
                sentences.append(piece)
            cursor = match.end()
        if sentences:
            self._emitted += cursor
        return sentences
