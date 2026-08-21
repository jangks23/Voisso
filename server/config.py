"""서버 설정 — 전부 환경변수. 하드코딩된 절대경로는 없다.

경로는 모두 저장소 루트(이 파일의 상위 디렉터리) 기준으로 잡는다.
경북도청 저장소로 이관돼도 그대로 돌아가야 하기 때문이다.
"""

from __future__ import annotations

import os
from pathlib import Path

# server/config.py -> server/ -> <repo root>
ROOT_DIR = Path(__file__).resolve().parents[1]


def _resolve(value: str | None, default: Path) -> Path:
    """상대경로는 저장소 루트 기준으로 푼다."""
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else (ROOT_DIR / path).resolve()


def load_dotenv(path: Path | None = None) -> int:
    """`.env` 를 읽어 환경변수에 넣는다. 이미 설정된 값은 덮어쓰지 않는다.

    python-dotenv 를 쓰지 않는 이유는 의존성을 하나라도 줄이기 위해서다.
    형식은 `KEY=VALUE`, `#` 주석, 따옴표 제거만 지원하면 충분하다.
    """
    env_path = path or (ROOT_DIR / ".env")
    if not env_path.is_file():
        return 0

    loaded = 0
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


DATA_DIR = _resolve(os.getenv("VOISSO_DATA_DIR"), ROOT_DIR / "data")
COMPLAINTS_DIR = DATA_DIR / "complaints"
WEB_DIR = ROOT_DIR / "web"
CALL_UI_DIR = WEB_DIR / "call"
DASHBOARD_DIR = WEB_DIR / "dashboard"

HOST = os.getenv("VOISSO_HOST", "127.0.0.1")
PORT = int(os.getenv("VOISSO_PORT", "8000"))

# P7/P8 이 다른 포트에서 붙는다. 기본은 전체 허용이고, 운영에서는
# VOISSO_CORS_ORIGINS 에 콤마로 구분해 도메인을 지정한다.
CORS_ORIGINS = [
    origin.strip()
    for origin in (os.getenv("VOISSO_CORS_ORIGINS") or "*").split(",")
    if origin.strip()
]

# 메모리에 들고 있는 통화 세션의 수명. 끊긴 통화가 쌓여 메모리를 먹는 것을 막는다.
SESSION_TTL_SEC = int(os.getenv("VOISSO_SESSION_TTL_SEC", "3600"))
MAX_SESSIONS = int(os.getenv("VOISSO_MAX_SESSIONS", "500"))
