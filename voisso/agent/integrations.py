"""병렬 작업 중인 옆 모듈(P3/P4/P5)로의 느슨한 다리.

계약서 4절 시그니처만 지키고, 모듈이 아직 없으면 **조용히 폴백**한다.
7개 에이전트가 동시에 개발 중이라 import 시점에 상대 모듈이 없을 수 있고,
개발 도중 생겨날 수도 있다. 그래서 실패한 import 는 짧게(TTL)만 캐시해
나중에 모듈이 추가되면 서버 재시작 없이 자동으로 붙는다.

- voisso.routing.find_department / get_department  (P4)
- voisso.dialect.normalize / to_dialect            (P5)
- voisso.data.resolve_phone                        (P3)
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any, Callable

log = logging.getLogger("voisso.agent.integrations")

# 상대 모듈이 아직 없을 때 매 호출마다 ImportError 를 반복하지 않도록 하는 캐시.
# 반대로 영구 캐시하면 P4/P5가 나중에 파일을 추가해도 못 붙으므로 TTL 을 둔다.
_MISS_TTL_SEC = 10.0
_resolved: dict[str, Callable[..., Any]] = {}
_missed_at: dict[str, float] = {}

# 계약서 3절: 전화번호 매핑이 없으면 경북도청 대표번호로 폴백한다.
GB_MAIN_PHONE = "1522-0120"


def _lookup(module_name: str, func_name: str) -> Callable[..., Any] | None:
    key = f"{module_name}.{func_name}"
    cached = _resolved.get(key)
    if cached is not None:
        return cached

    missed = _missed_at.get(key)
    if missed is not None and (time.monotonic() - missed) < _MISS_TTL_SEC:
        return None

    try:
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
    except (ImportError, AttributeError) as exc:
        if missed is None:
            log.info("%s 아직 없음 — 폴백으로 진행합니다 (%s)", key, exc.__class__.__name__)
        _missed_at[key] = time.monotonic()
        return None

    if not callable(func):
        _missed_at[key] = time.monotonic()
        return None

    log.info("%s 연결됨", key)
    _resolved[key] = func
    _missed_at.pop(key, None)
    return func


# --------------------------------------------------------------------------
# P5 — 방언 변환. 없으면 항등 함수(identity)로 통과시킨다.
# --------------------------------------------------------------------------


def normalize(text: str) -> str:
    """사투리 -> 표준어 (STT 결과 교정). P5 미탑재 시 원문 그대로."""
    if not text:
        return text
    func = _lookup("voisso.dialect", "normalize")
    if func is None:
        return text
    try:
        result = func(text)
    except Exception:
        log.exception("voisso.dialect.normalize 실패 — 원문 유지")
        return text
    return result if isinstance(result, str) and result.strip() else text


def to_dialect(text: str) -> str:
    """표준어 -> 경북 사투리 (TTS 입력). P5 미탑재 시 원문 그대로."""
    if not text:
        return text
    func = _lookup("voisso.dialect", "to_dialect")
    if func is None:
        return text
    try:
        result = func(text)
    except Exception:
        log.exception("voisso.dialect.to_dialect 실패 — 원문 유지")
        return text
    return result if isinstance(result, str) and result.strip() else text


def dialect_available() -> bool:
    return _lookup("voisso.dialect", "to_dialect") is not None


# --------------------------------------------------------------------------
# P4 — 부서 라우팅. 없으면 빈 결과. 민원카드는 '미배정'으로 만들어진다.
# --------------------------------------------------------------------------


def find_department(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """담당 부서 후보를 찾는다. P4 미탑재 시 빈 리스트."""
    if not query or not query.strip():
        return []
    func = _lookup("voisso.routing", "find_department")
    if func is None:
        return []
    try:
        matches = func(query, top_k)
    except Exception:
        log.exception("voisso.routing.find_department 실패 — 미배정으로 진행")
        return []
    if not isinstance(matches, list):
        return []
    return [m for m in matches if isinstance(m, dict)]


def get_department(department_id: str) -> dict[str, Any]:
    """부서 상세. P4 미탑재 시 빈 dict."""
    if not department_id:
        return {}
    func = _lookup("voisso.routing", "get_department")
    if func is None:
        return {}
    try:
        dept = func(department_id)
    except Exception:
        log.exception("voisso.routing.get_department 실패")
        return {}
    return dept if isinstance(dept, dict) else {}


def routing_available() -> bool:
    return _lookup("voisso.routing", "find_department") is not None


# --------------------------------------------------------------------------
# P3 — 전화번호 토큰 해석. 매핑이 없으면 경북도청 대표번호.
# --------------------------------------------------------------------------


def resolve_phone(token: str) -> str:
    """PHONE_0042 -> 실제 번호. 매핑이 없으면 1522-0120."""
    if not token:
        return GB_MAIN_PHONE
    func = _lookup("voisso.data", "resolve_phone")
    if func is None:
        return GB_MAIN_PHONE
    try:
        phone = func(token)
    except Exception:
        log.exception("voisso.data.resolve_phone 실패 — 대표번호로 폴백")
        return GB_MAIN_PHONE
    return phone if isinstance(phone, str) and phone.strip() else GB_MAIN_PHONE


def integration_status() -> dict[str, bool]:
    """대시보드/헬스체크용 — 어떤 옆 모듈이 붙었는지."""
    return {
        "routing": routing_available(),
        "dialect": dialect_available(),
        "data": _lookup("voisso.data", "resolve_phone") is not None,
    }
