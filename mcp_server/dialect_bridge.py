"""voisso.dialect (P5) 위임 계층.

P5 모듈이 아직 없어도 서버가 죽으면 안 된다. import 실패 시 원문을 그대로
돌려주는 스텁으로 동작하고, ``available: false`` 를 응답에 실어 호출자가
"방언 모듈 준비 중"임을 알 수 있게 한다.

모듈이 나중에 생기면 재시작 없이 붙는다(매 호출마다 import 재시도).
"""

from __future__ import annotations

from typing import Any

_STUB_NOTE = "방언 모듈 준비 중 (voisso.dialect 미탑재) — 입력 텍스트를 그대로 반환했습니다."


def _dialect_module():
    try:
        from voisso import dialect  # type: ignore

        return dialect
    except Exception:
        return None


def _call(func_name: str, text: str) -> dict[str, Any]:
    module = _dialect_module()
    func = getattr(module, func_name, None) if module is not None else None
    if func is None:
        return {"text": text, "available": False, "note": _STUB_NOTE}
    try:
        return {"text": func(text), "available": True}
    except Exception as exc:  # 방언 모듈이 터져도 통화는 계속돼야 한다
        return {
            "text": text,
            "available": False,
            "note": f"voisso.dialect.{func_name}() 호출 실패: {exc}",
        }


def normalize_dialect(text: str) -> dict[str, Any]:
    """사투리 -> 표준어 (STT 결과 교정)."""
    return _call("normalize", text)


def to_dialect(text: str) -> dict[str, Any]:
    """표준어 -> 경북 사투리 (TTS 입력)."""
    return _call("to_dialect", text)


def status() -> dict[str, Any]:
    module = _dialect_module()
    if module is None:
        return {"available": False, "lexicon_size": 0, "note": _STUB_NOTE}
    size_fn = getattr(module, "lexicon_size", None)
    try:
        size = int(size_fn()) if size_fn else 0
    except Exception:
        size = 0
    return {"available": True, "lexicon_size": size}
