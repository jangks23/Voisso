"""데이터 소스 해석 계층.

## 데이터는 저장소에 없다

경상북도청 조직도 파생 데이터는 재배포 라이선스 리스크 때문에 저장소에
커밋하지 않는다. 새로 clone 한 사람은 크롤러를 한 번 돌려야 한다.

    python3 scripts/scrape_gb_departments.py

## 탐색 순서

  1. ``voisso.data`` (P3 제공 공용 모듈) — 있으면 무조건 이쪽을 쓴다.
  2. ``$VOISSO_DATA_FILE`` — 데이터 파일을 직접 지정. 셀프테스트가 합성
     샘플(``mcp_server/fixtures/sample_departments.json``)을 물릴 때 쓴다.
  3. ``$VOISSO_DATA_DIR/gb_departments.json`` (기본값 ``<repo>/data``)

어디에도 없으면 :class:`MissingDataError` 를 던진다. **조용히 빈 결과를
돌려주지 않는다.** "담당 부서를 못 찾음"과 "데이터가 아예 없음"은 전혀 다른
상황이고, 처음 실행하는 사람은 그 차이를 즉시 알아야 한다.

실데이터가 나중에 생기면 재시작 없이 자동으로 잡힌다(mtime 감시).
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
SAMPLE_FILENAME = "sample_departments.json"
SCRAPER_CMD = "python3 scripts/scrape_gb_departments.py"

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "data": None, "source": None}


class MissingDataError(RuntimeError):
    """부서 데이터셋을 찾지 못했을 때. 메시지에 다음 할 일이 들어 있다."""


def repo_root() -> Path:
    """<repo>/voisso/routing/dataaccess.py -> <repo>"""
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    env = os.environ.get("VOISSO_DATA_DIR")
    return Path(env).expanduser().resolve() if env else repo_root() / "data"


def data_file() -> Path | None:
    """``VOISSO_DATA_FILE`` 로 명시 지정된 데이터 파일."""
    env = os.environ.get("VOISSO_DATA_FILE")
    return Path(env).expanduser().resolve() if env else None


def sample_path() -> Path:
    """셀프테스트용 합성 샘플. 실제 공공데이터가 아니다."""
    return repo_root() / "mcp_server" / "fixtures" / SAMPLE_FILENAME


def _candidates() -> list[Path]:
    explicit = data_file()
    paths = [explicit] if explicit else []
    paths.append(data_dir() / DATA_FILENAME)
    return paths


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(repo_root()))
    except ValueError:
        return str(path)


def missing_data_message() -> str:
    """처음 실행한 담당자가 한 줄로 다음 할 일을 알 수 있는 안내문."""
    lines = [
        "경상북도청 부서 데이터가 없습니다. 먼저 크롤러를 실행하세요:",
        "",
        f"    {SCRAPER_CMD}",
        "",
        "탐색한 경로:",
    ]
    lines += [f"    - {_relative(p)}" for p in _candidates()]
    lines += [
        "",
        "도청 조직도 파생 데이터는 재배포 라이선스 때문에 저장소에 커밋하지 않습니다.",
        "데이터 수집 없이 기능만 확인하려면 합성 샘플을 물릴 수 있습니다:",
        "",
        f"    VOISSO_DATA_FILE={_relative(sample_path())} python3 -m mcp_server",
        "",
        "합성 샘플은 가상 부서(테스트국 가상수도과 등)라 실제 민원 라우팅에는 쓸 수 없습니다.",
    ]
    return "\n".join(lines)


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
        # P3 모듈도 데이터가 없으면 터진다. 여기서 삼키고 아래 경로를 계속 찾는다.
        return None
    if isinstance(payload, dict) and payload.get("departments"):
        return payload, "voisso.data.load_departments()"
    return None


def load_departments() -> dict:
    """계약서 3절 스키마의 dict 를 반환한다. 없으면 MissingDataError."""
    return load_departments_with_source()[0]


def load_departments_with_source() -> tuple[dict, str]:
    with _lock:
        # VOISSO_DATA_FILE 이 명시되면(셀프테스트의 합성 샘플) 그것이 최우선이다.
        # 그러지 않으면 P3 모듈이 실데이터를 물고 와 샘플 테스트가 무의미해진다.
        if data_file() is None:
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
            try:
                with path.open(encoding="utf-8") as fh:
                    payload = json.load(fh)
            except json.JSONDecodeError as exc:
                raise MissingDataError(
                    f"{_relative(path)} 를 읽을 수 없습니다 (JSON 형식 오류: {exc}).\n"
                    f"파일이 손상됐을 수 있습니다. 다시 수집하세요:\n\n    {SCRAPER_CMD} --refresh"
                ) from exc
            if not payload.get("departments"):
                raise MissingDataError(
                    f"{_relative(path)} 에 departments 가 비어 있습니다.\n"
                    f"다시 수집하세요:\n\n    {SCRAPER_CMD} --refresh"
                )
            _cache.update(key=key, data=payload, source=_relative(path))
            return payload, _cache["source"]

    raise MissingDataError(missing_data_message())


# ------------------------------------------------------------------ 상태 조회

def data_available() -> bool:
    """예외 없이 데이터 유무만 확인한다(서버 기동 시 안내용)."""
    try:
        load_departments_with_source()
        return True
    except MissingDataError:
        return False


def is_sample() -> bool:
    """현재 물린 데이터가 합성 샘플이면 True (실제 민원 라우팅 불가)."""
    try:
        payload, _ = load_departments_with_source()
    except MissingDataError:
        return False
    return bool(payload.get("meta", {}).get("sample"))


def data_source() -> str:
    return load_departments_with_source()[1]


def data_status() -> dict[str, Any]:
    """진단용 상태 요약. 예외를 던지지 않는다."""
    try:
        payload, source = load_departments_with_source()
    except MissingDataError as exc:
        return {
            "available": False,
            "is_sample": False,
            "source": None,
            "department_count": 0,
            "next_step": SCRAPER_CMD,
            "message": str(exc),
        }
    meta = payload.get("meta", {})
    status: dict[str, Any] = {
        "available": True,
        "is_sample": bool(meta.get("sample")),
        "source": source,
        "org": meta.get("org", ""),
        "department_count": len(payload.get("departments", [])),
        "fetched_at": meta.get("fetched_at", ""),
    }
    if status["is_sample"]:
        status["message"] = (
            "합성 샘플 데이터로 동작 중입니다. 부서명·담당업무가 모두 가상이므로 "
            f"실제 민원 라우팅에 쓰지 마세요. 실데이터 수집: {SCRAPER_CMD}"
        )
    return status


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
