# -*- coding: utf-8 -*-
"""재촉·다급함 반복 탐지 — 실사용 안전 결함에서 나온 테스트.

집에 물이 차오르는 민원인이 "빨리와요!!!" 를 세 번 반복했는데 시스템이 긴급도를
올리지 못하고 "더 하실 말씀 있으신가예?" 루프를 돌았다. 이 파일이 그 재발을 막는다.

균형이 전부다. 놓치면 사람이 다치고, 과잉 탐지가 쏟아지면 진짜 응급이 묻힌다.
"""

from __future__ import annotations

import unittest

from voisso.dialect import detect_pressure, detect_risk

#: 단발로는 절대 올리면 안 되는 표현. 경북에서 아주 흔한 일상 강조다.
SINGLE_MUST_NOT_ESCALATE = [
    "큰일이라예", "아이고", "죽겠어예", "미치겠어예", "빨리요", "쫌 빨리",
    "야단났네예", "우짜노", "몬 살겠다", "좀 봐 주이소",
]


class ReportedIncidentTest(unittest.TestCase):
    """보고된 실패 그대로."""

    def test_repeated_hurry_escalates(self):
        result = detect_pressure(["빨리와요!!!", "빨리와요!!!", "빨리와요!!!"])
        self.assertTrue(result["escalate"], "재촉 3회 반복을 놓쳤다")
        self.assertGreaterEqual(result["count"], 3)
        self.assertGreaterEqual(result["repeated_turns"], 2)

    def test_full_incident_reaches_emergency(self):
        """위험은 1턴에 나오고 재촉은 그 뒤에 반복된다. 통화 전체를 봐야 잡힌다."""
        history = ["집에 물이 차올라예", "빨리와요!!!", "빨리와요!!!"]
        result = detect_risk("빨리와요!!!", history=history)
        self.assertEqual("응급", result["level"])
        self.assertIsNotNone(result["safety_referral"], "119 안내가 붙어야 한다")

    def test_hazard_in_history_is_not_forgotten(self):
        """이후 턴이 짧은 대답이어도 앞서 말한 위험이 사라지면 안 된다."""
        self.assertEqual("응급", detect_risk("예", history=["집에 물이 차올라예"])["level"])

    def test_contracted_forms_are_caught(self):
        """'빨리 좀 와 주이소' 만 잡고 '빨리와요' 를 놓친 것이 결함의 절반이었다."""
        for text in ["빨리와요", "빨리 와요", "빨리와예", "빨리 오이소", "퍼뜩 오이소"]:
            with self.subTest(text=text):
                self.assertTrue(detect_pressure(text)["matched"], f"{text!r} 를 못 잡았다")


class BalanceTest(unittest.TestCase):
    """과잉 탐지도 실패다. 전부 응급이면 아무것도 응급이 아니다."""

    def test_single_emphasis_does_not_escalate(self):
        wrong = []
        for text in SINGLE_MUST_NOT_ESCALATE:
            if detect_pressure(text)["escalate"]:
                wrong.append(text)
        self.assertEqual([], wrong, f"단발 강조를 올렸다: {wrong}")

    def test_demo_complaint_stays_calm_across_turns(self):
        """데모 대표 민원. 4턴 내내 응급으로 튀면 안 된다."""
        turns = ["집 앞에 물이 안 빠지고 자꾸 고이가꼬 몬 살겠다", "안동시 옥동입니더",
                 "장마철부터 그랬어예", "010-1234-5678 이라예"]
        for index, text in enumerate(turns):
            with self.subTest(turn=index):
                self.assertNotEqual("응급", detect_risk(text, history=turns[:index])["level"])

    def test_weak_expression_needs_three(self):
        """'큰일이라예' 는 3회는 되어야 신호다."""
        self.assertFalse(detect_pressure(["큰일이라예"])["escalate"])
        self.assertFalse(detect_pressure(["큰일이라예", "큰일이네예"])["escalate"])
        self.assertTrue(detect_pressure(["큰일이라예", "큰일이네예", "큰일입니더"])["escalate"])

    def test_medium_expression_needs_two(self):
        self.assertFalse(detect_pressure(["빨리요"])["escalate"])
        self.assertTrue(detect_pressure(["빨리요", "언능 좀"])["escalate"])


class StrengthTest(unittest.TestCase):
    def test_strength_is_reported(self):
        self.assertEqual("강", detect_pressure("사람 살리 주이소")["strength"])
        self.assertEqual("중", detect_pressure("빨리요")["strength"])
        self.assertEqual("약", detect_pressure("큰일이라예")["strength"])

    def test_strong_escalates_alone(self):
        for text in ["사람 살리 주이소", "119 좀 불러 주이소", "지금 당장 와 주이소", "급합니더"]:
            with self.subTest(text=text):
                self.assertTrue(detect_pressure(text)["escalate"])

    def test_intensity_markers_counted(self):
        plain = detect_pressure(["빨리요"])
        loud = detect_pressure(["빨리요!!!"])
        self.assertFalse(plain["escalate"])
        self.assertTrue(loud["intensity"], "느낌표 반복을 못 잡았다")

    def test_reason_explains_the_threshold(self):
        result = detect_pressure(["빨리요", "언능 좀"])
        self.assertIn("회", result["reason"])
        self.assertTrue(result["signals"])

    def test_never_raises(self):
        for value in ["", [], None, [""], ["", "  "]]:
            with self.subTest(value=value):
                self.assertFalse(detect_pressure(value)["escalate"])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
