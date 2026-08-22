"""저장소 — 통화 세션은 메모리, 민원카드는 파일.

세션은 통화가 끝나면 버려도 되는 휘발성 상태라 메모리 dict 로 충분하다.
민원카드는 담당 공무원에게 전달되는 산출물이므로 `data/complaints/*.json`
파일로 남긴다. 서버를 재시작해도 접수된 민원은 살아 있어야 한다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from voisso.agent import ConversationSession
from voisso.agent.callback import Callback
from voisso.agent.handoff import Handoff

from .config import MAX_SESSIONS, SESSION_TTL_SEC

log = logging.getLogger("voisso.server.store")


class SessionStore:
    """진행 중인 통화. 프로세스 메모리에만 산다."""

    def __init__(self, ttl_sec: int = SESSION_TTL_SEC, max_sessions: int = MAX_SESSIONS) -> None:
        self._sessions: dict[str, tuple[ConversationSession, float]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_sec
        self._max = max_sessions

    def create(self) -> ConversationSession:
        session = ConversationSession()
        with self._lock:
            self._evict_locked()
            self._sessions[session.id] = (session, time.monotonic())
        return session

    def get(self, session_id: str) -> ConversationSession | None:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            session, _ = entry
            # 접근할 때마다 수명을 갱신한다(통화 중에 만료되면 안 된다).
            self._sessions[session_id] = (session, time.monotonic())
            return session

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _evict_locked(self) -> None:
        """만료된 세션을 치우고, 그래도 넘치면 오래된 것부터 버린다."""
        now = time.monotonic()
        expired = [sid for sid, (_, seen) in self._sessions.items() if now - seen > self._ttl]
        for sid in expired:
            self._sessions.pop(sid, None)
        if expired:
            log.info("만료된 통화 세션 %d건 정리", len(expired))

        overflow = len(self._sessions) - self._max + 1
        if overflow > 0:
            oldest = sorted(self._sessions.items(), key=lambda kv: kv[1][1])[:overflow]
            for sid, _ in oldest:
                self._sessions.pop(sid, None)
            log.warning("세션 수 상한 초과 — 오래된 %d건 정리", len(oldest))


class ComplaintStore:
    """민원카드 파일 저장소. `data/complaints/{id}.json`."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def next_id(self) -> str:
        """0001 부터 증가하는 4자리 접수번호."""
        with self._lock:
            highest = 0
            for path in self.directory.glob("*.json"):
                try:
                    highest = max(highest, int(path.stem))
                except ValueError:
                    continue  # 사람이 손으로 넣은 파일명은 무시
            return f"{highest + 1:04d}"

    def save(self, complaint: dict[str, Any]) -> Path:
        complaint_id = str(complaint.get("id") or "").strip()
        if not complaint_id:
            raise ValueError("민원카드에 id 가 없습니다.")

        path = self.directory / f"{complaint_id}.json"
        # 원자적 쓰기 — 대시보드가 읽는 중에 반쪽짜리 파일을 보지 않게.
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            tmp.write_text(
                json.dumps(complaint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            tmp.replace(path)
        log.info("민원카드 저장: %s", path.name)
        return path

    def get(self, complaint_id: str) -> dict[str, Any] | None:
        # 경로 조작 방어 — id 는 숫자/영문/하이픈만 허용한다.
        safe = "".join(ch for ch in str(complaint_id) if ch.isalnum() or ch in "-_")
        if not safe:
            return None
        path = self.directory / f"{safe}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.exception("민원카드 읽기 실패: %s", path.name)
            return None

    def list_all(self) -> list[dict[str, Any]]:
        """최신순. 파일 하나가 깨져도 나머지는 보여준다."""
        complaints: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                complaints.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                log.warning("민원카드 건너뜀(파싱 실패): %s", path.name)
        complaints.sort(key=lambda c: str(c.get("created_at") or ""), reverse=True)
        return complaints

    def count(self) -> int:
        return sum(1 for _ in self.directory.glob("*.json"))


class HandoffStore:
    """담당자 핸드오프 채널. `data/handoffs/{complaint_id}.json`.

    민원카드와 **별도 파일**로 둔다. 계약서 5절의 카드 스키마는 고정이고,
    P7/P8 이 동시에 붙는 중이라 기존 필드를 건드리지 않는 쪽이 안전하다.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, complaint_id: str) -> Path | None:
        safe = "".join(ch for ch in str(complaint_id) if ch.isalnum() or ch in "-_")
        return self.directory / f"{safe}.json" if safe else None

    def _load_unlocked(self, complaint_id: str) -> Handoff | None:
        path = self._path(complaint_id)
        if path is None or not path.is_file():
            return None
        try:
            return Handoff.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            log.exception("핸드오프 읽기 실패: %s", path.name)
            return None

    def _write_unlocked(self, handoff: Handoff) -> Path:
        path = self._path(handoff.complaint_id)
        if path is None:
            raise ValueError("complaint_id 가 비어 있습니다.")
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(handoff.to_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def get(self, complaint_id: str) -> Handoff | None:
        with self._lock:
            return self._load_unlocked(complaint_id)

    def save(self, handoff: Handoff) -> Path:
        with self._lock:
            return self._write_unlocked(handoff)

    def mutate(self, complaint_id: str, change):
        """읽기→수정→쓰기를 **락 안에서** 한 번에 한다.

        예전에는 엔드포인트가 `get()` 으로 읽고, 수정하고, `save()` 로 썼다.
        그 사이에 다른 요청이 끼어들면 한쪽 변경이 통째로 사라진다
        (동시 호출 2건에 메시지가 1건만 남는 것을 실측했다).
        클라이언트가 타임아웃으로 재전송하면 반대로 중복처럼 보인다.

        `change(obj)` 는 읽어 온 객체를 받아 수정하고 결과를 돌려준다.
        `None` 을 돌려주면 저장하지 않는다.
        """
        with self._lock:
            obj = self._load_unlocked(complaint_id)
            if obj is None:
                return None, None
            result = change(obj)
            if result is not None:
                self._write_unlocked(obj)
            return obj, result


    def statuses(self) -> dict[str, str]:
        """{민원번호: 상태} — 대시보드가 목록에서 한눈에 보도록."""
        out: dict[str, str] = {}
        for path in self.directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out[path.stem] = str(payload.get("status") or "open")
        return out


class CallbackStore:
    """진행 안내 콜백. `data/callbacks/{complaint_id}.json`.

    핸드오프와 같은 모양의 저장소다. 민원 한 건에 채널 하나.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, complaint_id: str) -> Path | None:
        safe = "".join(ch for ch in str(complaint_id) if ch.isalnum() or ch in "-_")
        return self.directory / f"{safe}.json" if safe else None

    def _load_unlocked(self, complaint_id: str) -> Callback | None:
        path = self._path(complaint_id)
        if path is None or not path.is_file():
            return None
        try:
            return Callback.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            log.exception("콜백 읽기 실패: %s", path.name)
            return None

    def _write_unlocked(self, callback: Callback) -> Path:
        path = self._path(callback.complaint_id)
        if path is None:
            raise ValueError("complaint_id 가 비어 있습니다.")
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(callback.to_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def get(self, complaint_id: str) -> Callback | None:
        with self._lock:
            return self._load_unlocked(complaint_id)

    def save(self, callback: Callback) -> Path:
        with self._lock:
            return self._write_unlocked(callback)

    def mutate(self, complaint_id: str, change):
        """읽기→수정→쓰기를 **락 안에서** 한 번에 한다.

        예전에는 엔드포인트가 `get()` 으로 읽고, 수정하고, `save()` 로 썼다.
        그 사이에 다른 요청이 끼어들면 한쪽 변경이 통째로 사라진다
        (동시 호출 2건에 메시지가 1건만 남는 것을 실측했다).
        클라이언트가 타임아웃으로 재전송하면 반대로 중복처럼 보인다.

        `change(obj)` 는 읽어 온 객체를 받아 수정하고 결과를 돌려준다.
        `None` 을 돌려주면 저장하지 않는다.
        """
        with self._lock:
            obj = self._load_unlocked(complaint_id)
            if obj is None:
                return None, None
            result = change(obj)
            if result is not None:
                self._write_unlocked(obj)
            return obj, result


    def statuses(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in self.directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out[path.stem] = str(payload.get("status") or "pending")
        return out
