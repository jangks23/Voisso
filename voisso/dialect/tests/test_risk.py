# -*- coding: utf-8 -*-
"""위험 신호 탐지 — 안전 직결 테스트 (계약서 5-A).

**놓치는 것이 과잉 탐지보다 훨씬 나쁘다.** 아래 «반드시 잡아야 한다» 목록이 하나라도
깨지면 응급 상황이 "보통"으로 접수된다는 뜻이다. 되돌릴 수 없는 실패다.

동시에 늑대소년이 되면 표시 자체가 무시되므로, «올리면 안 된다» 목록도 함께 지킨다.
"""

from __future__ import annotations

import unittest

from voisso.dialect import detect_risk, load_risk_signals

#: 반드시 응급으로 잡아야 하는 발화. 사투리 그대로 넣는다.
MUST_BE_EMERGENCY = [
    "불이 났어예 퍼뜩 좀 와 주이소",
    "가스 내미가 심하게 나는데예",
    "타는 내미가 나예",
    "연기가 자욱합니더",
    "전깃줄이 끊어져가 늘어졌어예",
    "물이 자꾸 차올라가 무릎까지 왔어예",
    "물팍까지 물이 찼어예",
    "집이 물에 다 잠깄어예",
    "다리가 떠내리갔어예",
    "뚝이 터졌어예",
    "담부랑이 무너질 것 같아예",
    "집에 금이 쫙 갔어예",
    "축대가 기울어졌어예",
    "질이 푹 꺼졌어예",
    "할매가 넘어져가 몬 일어납니더",
    "안에 갇혔어예 몬 나갑니더",
    "사람이 다쳤어예 피가 나예",
    "숨을 몬 쉬겠어예",
    "사람 살리 주이소",
    "지금 당장 좀 와 주이소",
    # ── 2026-08-22 실사용 실패에서 추가 ─────────────────────────────────────
    # "물이 차오른다"는 잡는데 "물이 들어온다"를 못 잡아 응급이 "중요"로 접수됐다.
    "집에 물이 들어와요", "물이 들어옵니더", "물이 들어와예", "물이 들어온다",
    "방에 물이 들어옵니더", "마당에 물이 들어와예", "물이 들어오는데예",
    "물이 넘어와예", "물이 밀려옵니더", "물이 찹니더", "물이 찬다", "물이 차고 있어예",
    "발목까지 왔어예", "무릎까지 찼어예", "물이 잠깁니더", "도랑이 넘칩니더",
    "비가 억수로 와가 물이 넘어예",
    "타는 것 같아예", "뭔가 탑니더",
    "질이 꺼졌습니더",
    "길이 끊겼어예", "일어나지를 못하겠어예", "움직이지를 못하겠어예", "못 나가겠어예",
]

#: 위험 신호가 아닌데 응급으로 올리면 안 되는 발화.
#: 이게 깨지면 진짜 응급이 묻힌다 — 늑대소년 문제다.
MUST_NOT_ESCALATE = [
    "큰일이라예",
    "신청 서류 때문에 죽겠어예. 언제 되노",
    "우리 마실 버스가 하루에 두 번밖에 안 옵니더",
    "노인 수당을 우예 신청하노",
    "고맙심더. 단디 좀 봐 주이소.",
    "집 앞에 물이 안 빠지고 자꾸 고이가꼬",   # 데모 대표 민원 — 만성 불편이지 응급이 아니다
    "우리 할매가 혼차 사십니더",              # 고령 1인 거주만으로는 응급이 아니다
]


class MustCatchTest(unittest.TestCase):
    """놓치면 사람이 다친다."""

    def test_emergencies_are_caught(self):
        missed = []
        for text in MUST_BE_EMERGENCY:
            result = detect_risk(text)
            if result["level"] != "응급":
                missed.append(f"\n  {text!r} → {result['level']} ({result['reason'][:60]})")
        self.assertEqual(
            [], missed,
            "응급을 놓쳤다. 묻힌 응급은 되돌릴 수 없다. "
            "risk_signals.json 에 패턴을 추가하라." + "".join(missed),
        )

    def test_emergencies_carry_a_referral(self):
        """응급이면 119 안내가 붙어야 한다 (계약서 5-A: 접수가 신고를 대체하면 안 된다)."""
        for text in MUST_BE_EMERGENCY:
            with self.subTest(text=text):
                result = detect_risk(text)
                if result["level"] == "응급" and result["matched"]:
                    if any(m["referral"] for m in result["matched"]):
                        self.assertIsNotNone(result["safety_referral"])

    def test_reason_is_never_empty(self):
        """담당자가 '왜 응급인가'를 납득하지 못하면 그 표시는 무시된다."""
        for text in MUST_BE_EMERGENCY + MUST_NOT_ESCALATE:
            with self.subTest(text=text):
                self.assertTrue(detect_risk(text)["reason"].strip())


class MustNotCryWolfTest(unittest.TestCase):
    """과잉 탐지도 실패다. 전부 응급이면 아무것도 응급이 아니다."""

    def test_ordinary_complaints_stay_calm(self):
        wrong = []
        for text in MUST_NOT_ESCALATE:
            result = detect_risk(text)
            if result["level"] == "응급":
                wrong.append(f"\n  {text!r} → 응급 ({result['reason'][:70]})")
        self.assertEqual([], wrong, "일상 표현을 응급으로 올렸다." + "".join(wrong))

    def test_emphasis_alone_is_not_risk(self):
        for text in ["큰일이라예", "미치겠어예", "죽겠어예"]:
            with self.subTest(text=text):
                result = detect_risk(text)
                self.assertEqual("보통", result["level"])
                self.assertTrue(result["ambiguous"], "모호 표현이라는 단서를 남겨야 한다")
                self.assertTrue(result["ambiguous"][0]["disambiguate"])

    def test_chronic_is_not_acute(self):
        """'자꾸 고인다'(만성)와 '점점 심해진다'(악화)를 갈라야 한다."""
        self.assertEqual("중요", detect_risk("물이 안 빠지고 자꾸 고이가꼬")["level"])
        self.assertEqual("응급", detect_risk("물이 안 빠지는데 점점 심해집니더")["level"])


class EscalationTest(unittest.TestCase):
    def test_elderly_alone_plus_incident_escalates(self):
        alone = detect_risk("우리 할매가 혼차 사십니더")
        both = detect_risk("할매가 혼차 계시는데 넘어져가 몬 일어납니더")
        self.assertEqual("중요", alone["level"])
        self.assertEqual("응급", both["level"])

    def test_adverbs_do_not_break_matching(self):
        """부사가 끼어들어도 걸려야 한다. 어순 고정 패턴은 안전 데이터에서 치명적이다."""
        for text in ["물이 차오릅니더", "물이 자꾸 차오릅니더", "물이 지금 막 차올라예"]:
            with self.subTest(text=text):
                self.assertEqual("응급", detect_risk(text)["level"])

    def test_dialect_and_standard_both_match(self):
        """normalize 전후 어디에 매칭해도 걸려야 한다."""
        self.assertEqual("응급", detect_risk("몬 일어납니더")["level"])
        self.assertEqual("응급", detect_risk("못 일어납니다")["level"])


class TenseTest(unittest.TestCase):
    """같은 표현이라도 진행 중인지 지나간 일인지 가른다."""

    def test_progress_stays_emergency(self):
        for text in ["지금 물이 들어와요", "계속 물이 들어옵니더", "자꾸 물이 들어와예",
                     "아직도 물이 들어옵니더", "점점 물이 차오릅니더"]:
            with self.subTest(text=text):
                result = detect_risk(text)
                self.assertEqual("응급", result["level"])
                self.assertEqual("진행", result["tense"]["verdict"])

    def test_past_flood_is_lowered(self):
        """과거 피해 신고를 응급으로 두면 진짜 응급이 묻힌다."""
        result = detect_risk("어제 물이 들어왔어예")
        self.assertEqual("중요", result["level"])
        self.assertEqual("과거", result["tense"]["verdict"])

    def test_past_marker_alone_does_not_lower(self):
        """'어제부터 물이 들어옵니더' 는 어제가 붙어도 진행 중이다."""
        self.assertEqual("응급", detect_risk("어제부터 물이 들어옵니더")["level"])

    def test_fire_and_collapse_never_lowered(self):
        """불·붕괴·부상은 과거형이어도 현장이 그대로일 수 있다. 내리지 않는다."""
        for text in ["어제 불이 났어예", "저번에 담이 무너졌어예",
                     "어제 넘어져가 몬 일어났어예"]:
            with self.subTest(text=text):
                self.assertEqual("응급", detect_risk(text)["level"])

    def test_pressure_blocks_lowering(self):
        """다급함이 반복되면 과거 표현이어도 내리지 않는다."""
        result = detect_risk("어제 물이 들어왔어예",
                             history=["빨리와요!!!", "빨리와요!!!", "빨리와요!!!"])
        self.assertEqual("응급", result["level"])


class RiskSchemaTest(unittest.TestCase):
    def test_schema(self):
        data = load_risk_signals()
        self.assertGreaterEqual(len(data["signals"]), 25)
        for signal in data["signals"]:
            with self.subTest(signal=signal.get("id")):
                for field in ("id", "category", "level", "standard", "why", "patterns", "source"):
                    self.assertTrue(signal.get(field), f"{field} 가 비었다")
                self.assertIn(signal["level"], ("응급", "중요"))
                self.assertTrue(signal["source"].startswith("curated:"))
                for pattern in signal["patterns"]:
                    self.assertGreaterEqual(len(pattern.strip()), 2, "짧은 패턴은 오탐을 만든다")

    def test_never_raises(self):
        for text in ["", "   ", None]:
            with self.subTest(text=text):
                self.assertEqual("보통", detect_risk(text)["level"])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
