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
