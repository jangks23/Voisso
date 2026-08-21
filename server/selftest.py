"""키 없이 전체 흐름을 검증하는 자체 점검.

    python3 -m server.selftest

서버를 띄우지 않고 프로세스 안에서 통화 한 건을 처음부터 끝까지 돌린다.
심사·인수인계 때 "정말 동작하느냐"에 대한 재현 가능한 답이다.

여기서 확인하는 것:
  1. 어떤 API 키도 없이 start -> turn 4회 -> end 가 완주되는가
  2. 슬롯 4개가 다 채워지는가
  3. 민원카드가 계약서 5절 스키마와 정확히 일치하는가
  4. `assigned.evidence` 가 비어 있지 않은가  (계약서가 명시한 버그 조건)
  5. 원본 전화번호가 카드 어디에도 남지 않는가
"""

from __future__ import annotations

import json
import os
import sys

# 키가 있든 없든 이 점검은 항상 '키 0개' 조건에서 돈다.
for _var in (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "TYPECAST_API_KEY",
    "ELEVENLABS_API_KEY",
):
    os.environ[_var] = ""
os.environ["VOISSO_TTS_PROVIDER"] = "none"
os.environ["VOISSO_STT_PROVIDER"] = "none"

from voisso.agent import ConversationSession  # noqa: E402
from voisso.voice import stt_status, tts_status  # noqa: E402

SCENARIO = [
    "집 앞에 물이 안 빠지고 자꾸 고이가꼬",
    "안동시 옥동입니더",
    "장마철부터 그랬어예",
    "010-1234-5678 이라예",
]

RAW_PHONE = "010-1234-5678"

# 계약서 5절 민원카드의 최상위 키. 더도 덜도 아니어야 한다.
CARD_KEYS = {
    "id",
    "created_at",
    "duration_sec",
    "summary",
    "category",
    "assigned",
    "alternatives",
    "caller",
    "transcript",
}
ASSIGNED_KEYS = {"department_id", "full_name", "phone_token", "evidence"}
CALLER_KEYS = {"name_masked", "phone_masked"}

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def main() -> int:
    print("Voisso 자체 점검 — 키 0개 텍스트 모드\n")
    print(f"  STT 프로바이더: {stt_status()['provider']}")
    print(f"  TTS 프로바이더: {tts_status()['provider']}\n")

    print("통화 진행")
    session = ConversationSession()
    greeting = session.greet()
    print(f"  보이소: {greeting['reply_dialect']}")

    last = greeting
    for utterance in SCENARIO:
        print(f"  어르신: {utterance}")
        last = session.turn(text=utterance)
        print(f"  보이소: {last['reply_dialect']}")

    card = session.end("selftest")
    print("\n검증")

    check("통화가 종료 제안으로 끝났다", last["done"] is True)
    check(
        "슬롯 4개가 모두 채워졌다",
        not card and False or all(session.slots.is_filled(s) for s in ("what", "where", "when", "contact")),
        json.dumps({k: session.slots.get(k) for k in ("what", "where", "when", "contact")}, ensure_ascii=False),
    )
    check("민원카드 최상위 키가 계약서와 일치한다", set(card) == CARD_KEYS, str(sorted(set(card) ^ CARD_KEYS) or "일치"))
    check("assigned 키가 계약서와 일치한다", set(card["assigned"]) == ASSIGNED_KEYS)
    check("caller 키가 계약서와 일치한다", set(card["caller"]) == CALLER_KEYS)

    evidence = str(card["assigned"].get("evidence") or "").strip()
    check("assigned.evidence 가 비어 있지 않다", bool(evidence), evidence[:70])

    check("연락처가 마스킹되었다", card["caller"]["phone_masked"] == "010-****-5678", card["caller"]["phone_masked"])

    serialized = json.dumps(card, ensure_ascii=False)
    check("원본 전화번호가 카드에 남지 않았다", RAW_PHONE not in serialized.replace("010-****-5678", ""))

    check("통화 기록이 담겼다", len(card["transcript"]) >= 2 * len(SCENARIO), f"{len(card['transcript'])}턴")
    check(
        "모든 발화에 role/dialect/standard 가 있다",
        all(set(e) == {"role", "dialect", "standard"} for e in card["transcript"]),
    )

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("전부 통과. 키 없이 전체 흐름이 동작한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
