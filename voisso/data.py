"""경상북도청 부서 데이터셋 로더 (P3 제공 · 다른 모듈은 읽기 전용으로 사용).

데이터는 ``scripts/scrape_gb_departments.py`` 가 생성한다.

    from voisso.data import load_departments, resolve_phone

    data = load_departments()
    for dept in data["departments"]:
        ...
    resolve_phone("PHONE_0042")   # -> "054-880-XXXX" (매핑 없으면 "1522-0120")

전화번호 원칙(docs/CONTRACT.md 3절): 공개 데이터셋에는 ``PHONE_0042`` 같은
토큰만 들어간다. 실제 번호는 ``data/private/phone_map.json`` 에만 있고 이 파일은
저장소에 커밋하지 않는다. 매핑이 없으면 경상북도청 대표번호로 폴백한다.
"""

from __future__ import annotations

import json
import os
from typing import Any

__all__ = [
    "FALLBACK_PHONE",
    "data_dir",
    "load_departments",
    "resolve_phone",
]

FALLBACK_PHONE = "1522-0120"   # 경상북도청 대표번호

_PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(_PACKAGE_ROOT), "data")

_departments_cache: dict[str, Any] | None = None
_phone_cache: dict[str, str] | None = None
_cache_key: str | None = None


def data_dir() -> str:
    """데이터 디렉터리 경로. 환경변수 ``VOISSO_DATA_DIR`` 로 덮어쓸 수 있다."""
    return os.path.abspath(os.environ.get("VOISSO_DATA_DIR") or _DEFAULT_DATA_DIR)


def _invalidate_if_moved() -> None:
    """실행 중 VOISSO_DATA_DIR 이 바뀌면 캐시를 버린다 (테스트 편의)."""
    global _cache_key, _departments_cache, _phone_cache
    current = data_dir()
    if _cache_key != current:
        _cache_key = current
        _departments_cache = None
        _phone_cache = None


def load_departments() -> dict[str, Any]:
    """``data/gb_departments.json`` 전체를 그대로 돌려준다 (계약서 3절 스키마).

    한 번 읽은 뒤에는 메모리에 캐시한다.
    """
    global _departments_cache
    _invalidate_if_moved()
    if _departments_cache is None:
        path = os.path.join(data_dir(), "gb_departments.json")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"부서 데이터셋이 없다: {path}\n"
                "먼저 `python3 scripts/scrape_gb_departments.py` 를 실행해라."
            )
        with open(path, encoding="utf-8") as handle:
            _departments_cache = json.load(handle)
    return _departments_cache


def _load_phone_map() -> dict[str, str]:
    global _phone_cache
    _invalidate_if_moved()
    if _phone_cache is None:
        path = os.path.join(data_dir(), "private", "phone_map.json")
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            _phone_cache = {
                str(key): str(value) for key, value in loaded.items()
            }
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            # 매핑 파일은 커밋되지 않으므로 없는 게 정상적인 상황이다.
            _phone_cache = {}
    return _phone_cache


def resolve_phone(token: str) -> str:
    """전화번호 토큰을 실제 번호로 되돌린다.

    매핑이 없으면 경상북도청 대표번호 ``1522-0120`` 을 돌려준다.
    """
    if not token:
        return FALLBACK_PHONE
    return _load_phone_map().get(token, FALLBACK_PHONE)
