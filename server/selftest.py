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
  6. 마스킹이 번호를 훼손하지 않는가 (자릿수·뒤 4자리 보존)
  7. 긴급도 판정이 기대 단계와 맞는가 · reason 이 비지 않는가
  8. 응급이면 119/112 안내가 접수보다 먼저 나가는가
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
# 키를 지워도 프로바이더 지정이 남아 있으면 안 된다.
os.environ["VOISSO_AGENT_PROVIDER"] = "rule"
os.environ["VOISSO_TTS_PROVIDER"] = "none"
os.environ["VOISSO_STT_PROVIDER"] = "none"

import re  # noqa: E402

from voisso.agent import ConversationSession  # noqa: E402
from voisso.agent.complaint import mask_phone  # noqa: E402
from voisso.agent.urgency import assess as assess_urgency  # noqa: E402
from voisso.agent.engine import engine_status  # noqa: E402
from voisso.voice import stt_status, tts_status  # noqa: E402

SCENARIO = [
    "집 앞에 물이 안 빠지고 자꾸 고이가꼬",
    "안동시 옥동입니더",
    "장마철부터 그랬어예",
    "010-1234-5678 이라예",
    # 슬롯이 다 차도 바로 끊지 않는다. "더 하실 말씀?" 에 답해야 종료된다.
    "없어예",
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
    # 계약서 5-A 확장. 담당자가 무엇을 먼저 볼지 정해 준다.
    "urgency",
    # 계약서 5절 확장. 슬롯에 안 맞는 추가 정보를 담는다.
    "notes",
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


# 실제로 들어오는 다양한 형식. 형태를 가정하면 번호가 훼손된다.
PHONE_CASES = (
    "010-1234-5678",
    "054-000-4567",
    "1234-5678",
    "01012345678",
    "02-000-1234",
    "010 1234 5678",
    "(054) 123-4567",
    "054-1234",
    "0505-000-4567",
)


def check_masking() -> None:
    """마스킹 불변식: 자릿수 보존 · 뒤 4자리 보존 · 가운데는 가려짐.

    "1234-5678" 이 "123-***-5678" 로 바뀌어 자릿수가 늘어난 적이 있다.
    담당자가 그 번호로 다시 전화를 걸 수 없게 되는 치명적 버그였다.
    """
    print("\n전화번호 마스킹")
    for raw in PHONE_CASES:
        masked = mask_phone(raw)
        digits = re.sub(r"\D", "", raw)
        shown = re.sub(r"[^\d*]", "", masked)

        same_len = len(digits) == len(shown)
        keeps_tail = masked.endswith(digits[-4:])
        has_mask = "*" in masked
        ok = same_len and keeps_tail and has_mask

        detail = f"{raw} -> {masked}"
        if not same_len:
            detail += f" (자릿수 {len(digits)} -> {len(shown)})"
        elif not keeps_tail:
            detail += " (뒤 4자리 손실)"
        elif not has_mask:
            detail += " (가려진 자리 없음)"
        check(f"마스킹 {raw}", ok, detail)


# (발화, 기대 단계, 119/112 안내 필요 여부)
# 기대가 애매한 항목은 주석에 판단 근거를 적었다.
URGENCY_CASES = (
    ("집에 가스 냄새가 나예", "응급", True),
    ("축대가 무너질 것 같습니더", "응급", True),
    ("물이 자꾸 차올라예 무릎까지 왔어예", "응급", True),
    ("상수도가 터져서 물이 안 나와예", "중요", False),
    # 가로등: 계약서의 중요 예시는 '전면 소등'이라 단일 등은 보통에 가깝다.
    # 다만 야간 보행 안전이 걸리고 '며칠째' 지속이라 중요로 둔다.
    # 낮추더라도 안전 쪽으로 치우치는 편이 낫다는 판단이다.
    ("가로등이 며칠째 안 들어와예", "중요", False),
    # 포트홀은 보통. '함몰/푹 꺼짐'과 구분해야 해서 '구멍'은 응급 규칙에 넣지 않았다.
    ("도로에 구멍이 났어예", "보통", False),
    ("농기계 지원 사업 문의드립니더", "낮음", False),
)


def check_urgency() -> None:
    print("\n긴급도 판정")
    for text, expected, needs_referral in URGENCY_CASES:
        result = assess_urgency(text)
        level_ok = result.level == expected
        reason_ok = bool(result.reason.strip())
        referral_ok = bool(result.safety_referral) == needs_referral

        detail = f"{text} -> {result.level}"
        if not level_ok:
            detail += f" (기대 {expected})"
        if not reason_ok:
            detail += " · reason 비어 있음"
        if not referral_ok:
            detail += f" · 안내 {'필요한데 없음' if needs_referral else '불필요한데 있음'}"
        check(f"긴급도 {expected}", level_ok and reason_ok and referral_ok, detail)


def check_safety_first() -> None:
    """응급 안내가 슬롯 채우기보다 먼저 나가는가."""
    print("\n응급 안전 안내")
    session = ConversationSession()
    session.greet()
    result = session.turn(text="집에 가스 냄새가 나예")
    reply = result["reply_text"]

    check("응급으로 판정됐다", session.urgency.is_emergency, session.urgency.level)
    check("119 안내가 응답에 포함됐다", "119" in reply, reply[:56])
    # 접수 이야기보다 안내가 앞에 와야 한다.
    notice_at = reply.find("119")
    intake_at = reply.find("접수")
    check(
        "안내가 접수 안내보다 앞에 있다",
        notice_at >= 0 and (intake_at < 0 or notice_at < intake_at),
        f"119 위치 {notice_at}, 접수 위치 {intake_at}",
    )
    check("안전 안내 턴에 통화를 끝내지 않았다", result["done"] is False)

    again = session.turn(text="안동시 옥동입니더")
    check("같은 안내를 반복하지 않았다", "119" not in again["reply_text"], again["reply_text"][:44])


def main() -> int:
    print("Voisso 자체 점검 — 키 0개 텍스트 모드\n")
    engine = engine_status()
    print(f"  대화 엔진     : {engine['primary']}  (LLM 프로바이더: {engine['provider'] or '없음'})")
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

    check_masking()
    check_urgency()
    check_safety_first()

    print("\n검증")

    check("통화가 종료 제안으로 끝났다", last["done"] is True)
    check(
        "마무리 확인을 거쳤다",
        session.wrapup_rounds >= 1,
        f"{session.wrapup_rounds}회 여쭤봄",
    )
    check(
        "마무리 안내에 담당자 연결이 포함됐다",
        "담당자" in last["reply_text"],
        last["reply_text"][:44],
    )
    check("notes 가 배열이다", isinstance(card["notes"], list))
    check(
        "urgency.reason 이 비어 있지 않다",
        bool(str(card["urgency"].get("reason") or "").strip()),
        card["urgency"].get("reason", "")[:50],
    )
    check(
        "urgency.level 이 유효하다",
        card["urgency"].get("level") in ("응급", "중요", "보통", "낮음"),
        str(card["urgency"].get("level")),
    )
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
