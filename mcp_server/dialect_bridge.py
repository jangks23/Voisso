"""voisso.dialect (P5) 위임 계층.

P5 모듈이 아직 없어도 서버가 죽으면 안 된다. import 실패 시 원문을 그대로
돌려주는 스텁으로 동작하고, ``available: false`` 를 응답에 실어 호출자가
"방언 모듈 준비 중"임을 알 수 있게 한다.

모듈이 나중에 생기면 재시작 없이 붙는다(매 호출마다 import 재시도).

## 계약서 5-D — 개발 중 유료 API 호출 금지

``voisso.dialect`` 는 ``VOISSO_DIALECT_LLM=1`` 이고 ``ANTHROPIC_API_KEY`` 가 있으면
LLM 다듬기를 태운다. ``.env`` 를 source 한 셸에서 셀프테스트를 돌리면 매번 과금된다.
그래서 **테스트 진입점은 ``use_llm=False`` 로 못 박는다**(mcp_server/selftest.py).
서버 런타임은 기존대로 환경변수를 따른다 — 운영에서 켤지 말지는 배포자가 정한다.
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


def _call(func_name: str, text: str, *, use_llm: bool | None = None) -> dict[str, Any]:
    """voisso.dialect 호출. ``use_llm=False`` 면 유료 LLM 다듬기를 끈다.

    ``use_llm`` 을 그대로 넘기지 못하는(구버전) 모듈이면 인자 없이 재시도한다.
    """
    module = _dialect_module()
    func = getattr(module, func_name, None) if module is not None else None
    if func is None:
        return {"text": text, "available": False, "note": _STUB_NOTE}
    try:
        try:
            result = func(text, use_llm=use_llm)
        except TypeError:
            result = func(text)          # use_llm 을 안 받는 구현
        return {"text": result, "available": True}
    except Exception as exc:  # 방언 모듈이 터져도 통화는 계속돼야 한다
        return {
            "text": text,
            "available": False,
            "note": f"voisso.dialect.{func_name}() 호출 실패: {exc}",
        }


def normalize_dialect(text: str, *, use_llm: bool | None = None) -> dict[str, Any]:
    """사투리 -> 표준어 (STT 결과 교정).

    ``use_llm=None`` 이면 P5 의 환경변수(``VOISSO_DIALECT_LLM``)를 따른다.
    테스트 경로는 계약서 5-D 에 따라 ``use_llm=False`` 로 못 박는다.
    """
    return _call("normalize", text, use_llm=use_llm)


def to_dialect(text: str, *, use_llm: bool | None = None) -> dict[str, Any]:
    """표준어 -> 경북 사투리 (TTS 입력)."""
    return _call("to_dialect", text, use_llm=use_llm)


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
