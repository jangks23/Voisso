"""대화 품질 회귀 테스트 — LLM 경로가 반드시 통과해야 하는 케이스.

    python3 -m server.dialogue_check

규칙 엔진에서 실제로 관찰된 실패를 케이스로 굳힌 것이다. LLM 을 붙이는 이유가
바로 이것들이라, 여기서 떨어지면 붙인 의미가 없다.

  A) 한 문장에 정보 두 개   — 규칙 엔진도 통과한다. 회귀만 막는다.
  B) 어르신이 되묻는 경우   — 질문을 민원으로 오인하면 실패.
  C) 말을 정정하는 경우     — 앞서 채운 슬롯을 덮어써야 한다.
  D) 요약 품질             — 중복 없이 한 문장.
  E) 무의미한 발화          — 잡음·오인식이 슬롯을 오염시키면 실패.
  F) 랜드마크로 말하는 위치 — 어르신의 기본 화법이다. 시군을 확보해야 한다.
  G) 슬롯 불변식            — 값이 빈 슬롯은 반드시 missing 에 있어야 한다.
  H) 마무리 확인            — 슬롯이 차도 바로 끊지 않고 더 하실 말씀을 여쭙는다.

**키가 없으면 건너뛴다.** 실제 API 를 호출하므로 비용이 든다. 케이스를
4개로 제한한 것도 그래서다. 키 없이 도는 검증은 `server.selftest` 를 쓴다.
"""

from __future__ import annotations

import argparse
import sys

from voisso.agent import ConversationSession
from voisso.agent.engine import engine_status

from . import config

_failures: list[str] = []
_passes = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global _passes
    print(f"    [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if ok:
        _passes += 1
    else:
        _failures.append(label)
    return ok


SLOT_NAMES = ("what", "where", "when", "contact")


def assert_invariant(result: dict, where: str) -> list[str]:
    """값이 빈 슬롯은 반드시 missing 에 있다. 예외 없다."""
    slots = result.get("slots") or {}
    missing = set(slots.get("missing") or [])
    broken = []
    for name in SLOT_NAMES:
        empty = not (slots.get(name) or "").strip()
        if empty and name not in missing:
            broken.append(f"{where}: {name} 값이 비었는데 missing 에 없음")
        if not empty and name in missing:
            broken.append(f"{where}: {name} 값이 있는데 missing 에 있음")
    return broken


def run_call(utterances: list[str]) -> ConversationSession:
    session = ConversationSession()
    session.greet()
    for index, line in enumerate(utterances, 1):
        result = session.turn(text=line)
        print(f"    어르신: {line}")
        print(f"    보이소: {result['reply_text']}")
        broken = assert_invariant(result, f"턴 {index}")
        for message in broken:
            print(f"    [FAIL] 불변식 위반 — {message}")
            _failures.append("슬롯 불변식")
    return session


def case_a() -> None:
    print("\nA) 한 문장에 정보 두 개")
    session = run_call(["안동시 옥동인데 장마철부터 물이 안 빠져예"])
    slots = session.slots
    check("where 를 잡았다", "안동" in slots.get("where"), slots.get("where"))
    check("when 을 잡았다", bool(slots.get("when")), slots.get("when"))
    check("what 을 잡았다", bool(slots.get("what")), slots.get("what"))


def case_b() -> None:
    print("\nB) 어르신이 되묻는 경우")
    session = run_call(
        [
            "집 앞에 물이 안 빠져서 전화했어예",
            "아들이 대신 신청해도 되능교?",
        ]
    )
    replies = [e["standard"] for e in session.transcript if e["role"] == "agent"]
    last = replies[-1]

    # 질문을 민원 내용으로 삼키지 않았는가
    what = session.slots.get("what")
    check("질문을 민원 내용으로 오인하지 않았다", "대신 신청" not in what and "아들" not in what, what)
    # 질문에 실제로 답했는가
    answered = any(word in last for word in ("됩니다", "되십니다", "가능", "괜찮", "하셔도"))
    check("질문에 답했다", answered, last[:60])
    # 같은 질문을 그대로 반복하지 않았는가
    check("직전 질문을 그대로 반복하지 않았다", len(replies) < 2 or replies[-1] != replies[-2])


def case_c() -> None:
    print("\nC) 말을 정정하는 경우")
    session = run_call(
        [
            "가로등이 안 들어와예",
            "아니 아니, 가로등 말고 물이 안 빠지는 게 더 급해예",
        ]
    )
    what = session.slots.get("what")
    check("민원 내용을 배수 문제로 갱신했다", any(k in what for k in ("물", "배수", "빠지")), what)
    check("가로등이 남아 있지 않다", "가로등" not in what, what)


def case_d() -> None:
    print("\nD) 요약 품질")
    session = run_call(
        [
            "아 저기 집 앞에 물이 안 빠지고 자꾸 고여서 큰일이라예",
            "안동시 옥동입니더",
            "장마철부터 그랬어예",
            "010-1234-5678 이라예",
            "없어예",
        ]
    )
    card = session.end("dialogue-check")
    summary = card["summary"]
    print(f"    요약: {summary}")
    print(f"    분류: {card['category']}")
    print(f"    배정: {card['assigned']['full_name']}")
    print(f"    근거: {card['assigned']['evidence'][:70]}")

    check("요약이 한 문장이다", summary.count(".") <= 1 and len(summary) <= 60, f"{len(summary)}자")
    # "안동시 옥동" 이 두 번 나오면 템플릿 이어붙이기다
    check("지역명이 중복되지 않는다", summary.count("옥동") <= 1, summary)
    check("시점이 중복되지 않는다", summary.count("장마철") <= 1, summary)
    check("구어체 종결어미가 남지 않았다", not any(e in summary for e in ("라예", "어예", "습니더", "예요", "이에요")), summary)
    check("담당 부서가 배정됐다", "미배정" not in card["assigned"]["full_name"], card["assigned"]["full_name"])
    check("배정 근거가 비어 있지 않다", bool(card["assigned"]["evidence"].strip()))


def case_e() -> None:
    print("\nE) 무의미한 발화가 들어올 때")
    session = run_call(
        [
            "가나다 가나다 가나다",
            "집 앞에 물이 안 빠져예",
        ]
    )
    what = session.slots.get("what")
    check("무의미한 발화가 민원 내용에 섞이지 않았다", "가나다" not in what, what)
    check("이후 정상 발화는 정상 처리됐다", any(k in what for k in ("물", "배수", "빠")), what)

    replies = [e["standard"] for e in session.transcript if e["role"] == "agent"]
    check("되묻되 통화를 끊지 않았다", len(replies) >= 2)


def case_f() -> None:
    print("\nF) 랜드마크로 위치를 말하는 경우")
    session = run_call(
        [
            "집 앞에 물이 안 빠져예",
            "포항공대요",
        ]
    )
    where = session.slots.get("where")
    landmark = session.slots.landmark

    check("랜드마크에서 시·군을 확보했다", "포항" in where, f"where={where!r}")
    check("랜드마크를 버리지 않았다", "포항공대" in landmark, f"landmark={landmark!r}")

    last = session.turn(text="가나다")
    check(
        "위치가 비었으면 missing 에 남는다",
        not assert_invariant(last, "추가턴"),
        "; ".join(assert_invariant(last, "추가턴")) or "정상",
    )


def case_g() -> None:
    print("\nG) 시군 없는 값은 where 에 들어가지 않는다")
    session = run_call(
        [
            "집 앞에 물이 안 빠져예",
            "보스텍 체육관이요",
        ]
    )
    where = session.slots.get("where")
    slots = session.slots.as_dict()
    check(
        "시군이 없는 값이 where 에 들어가지 않았다",
        not where or any(city[:-1] in where for city in ("포항시", "안동시", "구미시")),
        f"where={where!r}",
    )
    check(
        "where 가 비었으면 missing 에 있다",
        bool(where) or "where" in slots["missing"],
        f"missing={slots['missing']}",
    )
    check("단서는 landmark 로 보존됐다", "체육관" in session.slots.landmark, session.slots.landmark)


def case_h() -> None:
    print("\nH) 마무리 확인과 추가 정보")
    session = ConversationSession()
    session.greet()
    replies = []
    for line in [
        "집 앞에 물이 안 빠져예",
        "안동시 옥동입니더",
        "장마철부터예",
        "010-1234-5678 이라예",
    ]:
        result = session.turn(text=line)
        replies.append(result)
        print(f"    어르신: {line}")
        print(f"    보이소: {result['reply_text']}")

    check("슬롯이 다 차도 바로 끊지 않았다", replies[-1]["done"] is False, str(replies[-1]["done"]))
    check(
        "더 하실 말씀을 여쭤봤다",
        "말씀" in replies[-1]["reply_text"],
        replies[-1]["reply_text"][:44],
    )

    extra = session.turn(text="아침에만 그래예")
    print(f"    어르신: 아침에만 그래예")
    print(f"    보이소: {extra['reply_text']}")
    check("추가 정보가 메모로 쌓였다", len(session.notes) >= 1, str([n["text"] for n in session.notes]))
    check("메모를 받고도 통화가 계속된다", extra["done"] is False)

    final = session.turn(text="없어예")
    print(f"    어르신: 없어예")
    print(f"    보이소: {final['reply_text']}")
    check("종료 신호에 통화를 마쳤다", final["done"] is True)
    check("담당자 연결을 안내했다", "담당자" in final["reply_text"], final["reply_text"][:44])

    card = session.end("dialogue-check-h")
    check("민원카드에 notes 가 실렸다", len(card["notes"]) >= 1, str([n["text"] for n in card["notes"]]))
    check(
        "notes 항목이 계약 형태다",
        all(set(n) == {"text", "at", "source"} for n in card["notes"]),
    )


def main() -> int:
    config.load_dotenv()

    parser = argparse.ArgumentParser(prog="python3 -m server.dialogue_check")
    parser.add_argument(
        "--case", choices=["a", "b", "c", "d", "e", "f", "g", "h"], help="한 케이스만 실행"
    )
    args = parser.parse_args()

    status = engine_status()
    print("대화 품질 회귀 테스트\n")
    print(f"  프로바이더: {status['provider'] or '없음'}")
    print(f"  대화 모델  : {status['turn_model'] or '—'}")
    print(f"  요약 모델  : {status['summary_model'] or '—'}")

    if not status["llm_available"]:
        print("\n건너뜀 — LLM 키가 없습니다.")
        print("  OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 를 설정하세요.")
        print("  (규칙 엔진은 B/C/D 를 통과하지 못합니다. 그게 LLM 을 붙인 이유입니다.)")
        print("\n키 없이 도는 검증은 `python3 -m server.selftest` 를 쓰세요.")
        return 0

    cases = {"a": case_a, "b": case_b, "c": case_c, "d": case_d,
             "e": case_e, "f": case_f, "g": case_g, "h": case_h}
    for key, func in cases.items():
        if args.case and args.case != key:
            continue
        try:
            func()
        except Exception as exc:
            print(f"    [FAIL] 케이스 {key.upper()} 실행 중 오류: {exc}")
            _failures.append(f"case_{key}")

    print(f"\n  통과 {_passes} / 실패 {len(_failures)}")
    if _failures:
        print("  실패 항목: " + ", ".join(_failures))
        return 1
    print("\n전부 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
