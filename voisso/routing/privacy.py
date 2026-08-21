"""공개 출력(evidence/duty)에서 전화번호를 제거하는 방어 계층.

계약서 3절: "전화번호는 공개 데이터셋에 절대 넣지 않는다."
그런데 경북도청 원문 사무분장 문구 자체에 내선번호가 섞여 있는 경우가 있다.
  예) "행사, 의전 [행정☎ (소방) 880-XXXX, (본부) XXXX]"
크롤러가 이를 그대로 담아도 MCP 로 나가는 순간에는 걸러지도록, 라우팅
출력 경로에서 한 번 더 마스킹한다. 업무 내용("행사, 의전")은 원문 그대로
남기고 번호 부기만 떼어낸다.
"""

from __future__ import annotations

import re

# "[행정☎ (소방) 880-XXXX, (본부) XXXX]" 처럼 전화 부기 전용 대괄호 블록
_PHONE_BRACKET = re.compile(r"\[[^\[\]]*[☎☏][^\[\]]*\]|（[^（）]*[☎☏][^（）]*）")
# 남은 전화번호 형태 (054-880-XXXX / 880-XXXX / 1522-0120)
_PHONE_NUM = re.compile(r"(?<!\d)\d{2,4}[-‑–]\d{3,4}(?:[-‑–]\d{4})?(?!\d)")
_TELMARK = re.compile(r"[☎☏]")
_WS = re.compile(r"\s{2,}")


def scrub(text: str) -> str:
    """사무분장 원문에서 전화번호만 제거한 문자열을 돌려준다."""
    if not text:
        return ""
    cleaned = _PHONE_BRACKET.sub(" ", text)
    cleaned = _PHONE_NUM.sub("***", cleaned)
    cleaned = _TELMARK.sub(" ", cleaned)
    cleaned = _WS.sub(" ", cleaned).strip(" ,·・-[]()")
    if not cleaned:
        # 번호를 빼고 나면 아무것도 안 남는 경우: 최소한 빈 evidence 는 만들지 않는다.
        cleaned = _WS.sub(" ", _PHONE_NUM.sub("***", text)).strip()
    return cleaned


def contains_phone(text: str) -> bool:
    return bool(text) and bool(_PHONE_NUM.search(text) or _TELMARK.search(text))
