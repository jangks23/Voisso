"""대화 품질 회귀 테스트 — LLM 경로가 반드시 통과해야 하는 케이스.

    python3 -m server.dialogue_check

규칙 엔진에서 실제로 관찰된 실패를 케이스로 굳힌 것이다. LLM 을 붙이는 이유가
바로 이것들이라, 여기서 떨어지면 붙인 의미가 없다.

  A) 한 문장에 정보 두 개   — 규칙 엔진도 통과한다. 회귀만 막는다.
  B) 어르신이 되묻는 경우   — 질문을 민원으로 오인하면 실패.
  C) 말을 정정하는 경우     — 앞서 채운 슬롯을 덮어써야 한다.
  D) 요약 품질             — 중복 없이 한 문장.

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


def run_call(utterances: list[str]) -> ConversationSession:
    session = ConversationSession()
    session.greet()
    for line in utterances:
        result = session.turn(text=line)
        print(f"    어르신: {line}")
        print(f"    보이소: {result['reply_text']}")
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


def main() -> int:
    config.load_dotenv()

    parser = argparse.ArgumentParser(prog="python3 -m server.dialogue_check")
    parser.add_argument("--case", choices=["a", "b", "c", "d"], help="한 케이스만 실행")
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

    cases = {"a": case_a, "b": case_b, "c": case_c, "d": case_d}
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
