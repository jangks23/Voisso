"""최소 HTTP 클라이언트 — 표준 라이브러리 urllib 만 쓴다.

계약서 6절: "파이썬 의존성 최소화. 표준 라이브러리로 되는 일은 표준 라이브러리로."
STT/TTS 는 REST 호출 몇 개가 전부라 전용 HTTP 라이브러리를 끌어올 이유가 없다.
(anthropic SDK 는 httpx2 를 쓰므로 httpx 가 깔려 있으리라 가정할 수도 없다.)
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from typing import Any


class HTTPError(RuntimeError):
    """2xx 가 아닌 응답. 본문 앞부분을 메시지에 실어 원인을 보이게 한다."""

    def __init__(self, status: int, body: bytes, url: str) -> None:
        self.status = status
        self.body = body
        snippet = body[:300].decode("utf-8", "replace").strip()
        super().__init__(f"HTTP {status} from {url}: {snippet}" if snippet else f"HTTP {status} from {url}")


def _request(req: urllib.request.Request, timeout: float) -> tuple[bytes, dict[str, str]]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:  # 4xx/5xx — 본문에 원인이 들어 있다
        raise HTTPError(exc.code, exc.read(), req.full_url) from exc
    except urllib.error.URLError as exc:  # DNS 실패, 연결 거부, 타임아웃
        raise RuntimeError(f"연결 실패 {req.full_url}: {exc.reason}") from exc


def post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 30.0
) -> tuple[bytes, dict[str, str]]:
    """JSON 을 보내고 **원본 바이트**를 받는다(오디오 응답이라 디코딩하지 않는다)."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    merged = {"Content-Type": "application/json; charset=utf-8", **headers}
    return _request(urllib.request.Request(url, data=body, headers=merged, method="POST"), timeout)


def get_json(url: str, headers: dict[str, str], timeout: float = 30.0) -> Any:
    raw, _ = _request(urllib.request.Request(url, headers=headers, method="GET"), timeout)
    return json.loads(raw.decode("utf-8"))


def post_multipart(
    url: str,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    headers: dict[str, str],
    timeout: float = 60.0,
) -> Any:
    """multipart/form-data 로 파일 하나 + 폼 값들을 보내고 JSON 을 받는다."""
    boundary = f"----voisso{uuid.uuid4().hex}"
    sep = f"--{boundary}\r\n".encode()
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.append(sep)
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode("utf-8"))

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts.append(sep)
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(parts)
    merged = {"Content-Type": f"multipart/form-data; boundary={boundary}", **headers}
    raw, _ = _request(
        urllib.request.Request(url, data=body, headers=merged, method="POST"), timeout
    )
    return json.loads(raw.decode("utf-8"))


def post_stream(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float = 60.0,
    chunk_size: int = 8192,
):
    """JSON 을 보내고 응답 본문을 **청크 단위로** 흘려보낸다.

    첫 바이트가 빨리 나오는 것이 목적이라 전체를 메모리에 모으지 않는다.
    (Typecast 스트리밍은 첫 청크에만 WAV 헤더가 있고 이후는 raw PCM 이므로
    순서를 지켜 그대로 전달해야 한다.)
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    merged = {"Content-Type": "application/json; charset=utf-8", **headers}
    req = urllib.request.Request(url, data=body, headers=merged, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except urllib.error.HTTPError as exc:
        raise HTTPError(exc.code, exc.read(), url) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"연결 실패 {url}: {exc.reason}") from exc


def post_sse_lines(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float = 60.0,
):
    """JSON 을 보내고 `data: ...` 형식(SSE) 응답을 줄 단위로 흘려보낸다.

    OpenAI 의 `stream: true` 응답을 읽는 데 쓴다. 토큰이 도착하는 대로
    넘겨줘야 첫 문장을 빨리 뽑을 수 있으므로 버퍼링하지 않는다.
    `[DONE]` 센티널은 걸러내고 파싱된 dict 만 내보낸다.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    merged = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "text/event-stream",
        **headers,
    }
    req = urllib.request.Request(url, data=body, headers=merged, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buffer = b""
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    line = raw.strip()
                    if not line or not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        return
                    try:
                        yield json.loads(data.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
    except urllib.error.HTTPError as exc:
        raise HTTPError(exc.code, exc.read(), url) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"연결 실패 {url}: {exc.reason}") from exc
