"""데이터 소스 해석 계층.

우선순위:
  1. ``voisso.data`` (P3 제공 공용 모듈) — 있으면 무조건 이쪽을 쓴다.
  2. ``$VOISSO_DATA_DIR/gb_departments.json`` (기본값 <repo>/data)
  3. ``<repo>/mcp_server/fixtures/gb_departments.json`` (개발용 소규모 픽스처)

P3가 실제 데이터를 올리면 재시작 없이 자동으로 승격된다(mtime 감시).
절대경로 하드코딩 없음 — 전부 이 파일 위치 기준 상대경로 또는 환경변수.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

FALLBACK_PHONE = "1522-0120"
DATA_FILENAME = "gb_departments.json"

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "data": None, "source": None}


def repo_root() -> Path:
    """<repo>/voisso/routing/dataaccess.py -> <repo>"""
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    env = os.environ.get("VOISSO_DATA_DIR")
    return Path(env).expanduser().resolve() if env else repo_root() / "data"


def fixture_path() -> Path:
    return repo_root() / "mcp_server" / "fixtures" / DATA_FILENAME


def _candidates() -> list[Path]:
    return [data_dir() / DATA_FILENAME, fixture_path()]


def _load_via_p3() -> tuple[dict, str] | None:
    """P3의 voisso.data 가 이미 있으면 그쪽에 위임한다."""
    try:
        from voisso import data as voisso_data  # type: ignore
    except Exception:
        return None
    loader = getattr(voisso_data, "load_departments", None)
    if loader is None:
        return None
    try:
        payload = loader()
    except Exception:
        return None
    if isinstance(payload, dict) and payload.get("departments"):
        return payload, "voisso.data.load_departments()"
    return None


def load_departments() -> dict:
    """계약서 3절 스키마의 dict 를 반환한다."""
    payload, _ = load_departments_with_source()
    return payload


def load_departments_with_source() -> tuple[dict, str]:
    with _lock:
        via_p3 = _load_via_p3()
        if via_p3 is not None:
            _cache.update(key="p3", data=via_p3[0], source=via_p3[1])
            return via_p3

        for path in _candidates():
            if not path.is_file():
                continue
            key = (str(path), path.stat().st_mtime_ns)
            if _cache["key"] == key:
                return _cache["data"], _cache["source"]
            with path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            source = str(path.relative_to(repo_root())) if path.is_relative_to(repo_root()) else str(path)
            _cache.update(key=key, data=payload, source=source)
            return payload, source

    raise FileNotFoundError(
        f"{DATA_FILENAME} 을 찾을 수 없습니다. 탐색 경로: "
        + ", ".join(str(p) for p in _candidates())
    )


def is_fixture() -> bool:
    payload, _ = load_departments_with_source()
    return bool(payload.get("meta", {}).get("fixture"))


def data_source() -> str:
    return load_departments_with_source()[1]


# ------------------------------------------------------------------ 전화번호

def resolve_phone(token: str) -> str:
    """토큰 -> 실번호. 공개 데이터셋에는 토큰만 있다.

    P3의 ``voisso.data.resolve_phone`` 이 있으면 그쪽에 위임하고,
    없으면 ``data/private/phone_map.json`` 을 직접 읽는다. 매핑이 없으면
    경북도청 대표번호로 폴백한다. 가짜 번호를 생성하지 않는다.
    """
    if not token:
        return FALLBACK_PHONE
    try:
        from voisso import data as voisso_data  # type: ignore

        resolver = getattr(voisso_data, "resolve_phone", None)
        if resolver is not None:
            return resolver(token)
    except Exception:
        pass

    path = data_dir() / "private" / "phone_map.json"
    if path.is_file():
        try:
            with path.open(encoding="utf-8") as fh:
                mapping = json.load(fh)
            value = mapping.get(token)
            if value:
                return str(value)
        except Exception:
            pass
    return FALLBACK_PHONE
