# -*- coding: utf-8 -*-
"""119 연결 확인 — 긍정/부정/애매 판정 (안전 직결).

응급 시 AI 가 "119 불러 드릴까예?" 라고 묻는다. **다급하면 대답이 한 글자로 온다.**
"어", "야", "예" 를 놓치면 연결이 안 된다.

동시에 **애매한 것을 부정으로 처리하면 위험하다.** 애매는 반드시 재질문으로 간다.
"""

from __future__ import annotations

import unittest

from voisso.dialect import detect_consent, emergency_lines

#: 반드시 긍정으로 잡아야 한다. 놓치면 119 연결이 안 된다.
MUST_BE_POSITIVE = [
    "예", "네", "야", "어", "응", "음", "예예", "어어", "네네",
    "예!", "어...", "야!!", "예.",
    "그래예", "그래 주이소", "그리 해 주이소", "해 주이소", "해 주소",
    "부탁합니더", "부탁드립니더", "좀 해 주이소", "빨리 해 주이소", "퍼뜩 해 주이소",
    "그카이소", "알겠어예", "119 불러 주이소", "좀 불러 주이소", "연결해 주이소",
    "예 좀 불러 주이소", "어 그래 주이소", "네 부탁합니더",
    "아니 빨리 해 주이소",   # '아니'는 군말이고 뜻은 긍정이다
]

#: 반드시 부정으로 잡아야 한다.
MUST_BE_NEGATIVE = [
    "아니예", "아니라예", "아이라예", "아뇨", "아니요",
    "괜찮아예", "괜찮습니더", "갠찮아예",
    "됐어예", "됐심더", "아니 됐어예", "아 됐심더",
    "안 해도 되예", "안 불러도 됩니더", "내가 할게예", "제가 하겠습니더",
    "놔두이소", "냅두이소", "필요 없어예", "하지 마이소",
    "괜찮아예 그냥 놔두이소", "아니요 괜찮아예",
]

#: 긍정도 부정도 아니다. **부정으로 처리하면 위험하다.**
MUST_BE_UNCLEAR = [
    "", "   ", "\n",
    "글쎄예", "글씨예", "모르겠어예", "잘 모르겠습니더",
    "우짜지예", "잠깐만예", "가만 있어 보이소",
    "뭐라꼬예", "안 들립니더", "다시 말해 주이소",
    "날씨가 참 궂네예",      # 동문서답
    "우리 집이 안동인데예",   # 동문서답
]


class MustCatchPositiveTest(unittest.TestCase):
    """놓치면 119 연결이 안 된다."""

    def test_positive_responses(self):
        missed = []
        for text in MUST_BE_POSITIVE:
            result = detect_consent(text)
            if result["verdict"] != "긍정":
                missed.append(f"\n  {text!r} → {result['verdict']} ({result['reason'][:50]})")
        self.assertEqual([], missed, "긍정 응답을 놓쳤다 — 연결이 안 된다." + "".join(missed))

    def test_positive_routes_to_connect(self):
        for text in MUST_BE_POSITIVE[:10]:
            with self.subTest(text=text):
                self.assertEqual("connect", detect_consent(text)["next"])


class MustCatchNegativeTest(unittest.TestCase):
    def test_negative_responses(self):
        wrong = []
        for text in MUST_BE_NEGATIVE:
            result = detect_consent(text)
            if result["verdict"] != "부정":
                wrong.append(f"\n  {text!r} → {result['verdict']}")
        self.assertEqual([], wrong, "부정 응답을 잘못 읽었다." + "".join(wrong))

    def test_short_answer_substring_trap(self):
        """'예'를 부분 문자열로 찾으면 '괜찮아예'·'아니라예'까지 긍정이 된다.

        한 글자 응답은 **발화 전체가 같을 때만** 인정해야 한다. 이 테스트가 그 경계다.
        """
        for text in ["괜찮아예", "아니라예", "됐어예", "모르겠어예"]:
            with self.subTest(text=text):
                self.assertNotEqual("긍정", detect_consent(text)["verdict"])


class MustReaskTest(unittest.TestCase):
    """애매를 부정으로 처리하면 위험하다. 반드시 한 번 더 묻는다."""

    def test_unclear_responses(self):
        wrong = []
        for text in MUST_BE_UNCLEAR:
            result = detect_consent(text)
            if result["verdict"] != "애매" or result["next"] != "reask":
                wrong.append(f"\n  {text!r} → {result['verdict']}/{result['next']}")
        self.assertEqual([], wrong, "애매한 응답을 단정했다." + "".join(wrong))

    def test_unclear_is_never_treated_as_negative(self):
        for text in MUST_BE_UNCLEAR:
            with self.subTest(text=text):
                self.assertNotEqual("stop", detect_consent(text)["next"])

    def test_silence_is_unclear_not_negative(self):
        result = detect_consent("")
        self.assertEqual("애매", result["verdict"])
        self.assertEqual("reask", result["next"])
        self.assertIn("무응답", result["reason"])

    def test_conflicting_cues_reask(self):
        """긍정과 부정이 모두 걸리면 단정하지 않는다."""
        result = detect_consent("예 아니 하지 마이소")
        self.assertIn(result["next"], ("reask", "stop"))
        self.assertNotEqual("connect", result["next"])

    def test_reason_always_present(self):
        for text in MUST_BE_POSITIVE[:5] + MUST_BE_NEGATIVE[:5] + MUST_BE_UNCLEAR[:5]:
            with self.subTest(text=text):
                self.assertTrue(detect_consent(text)["reason"].strip())


class EmergencyLinesTest(unittest.TestCase):
    def test_lines_are_dialect_and_short(self):
        lines = emergency_lines()
        for key in ("ask", "reask", "confirmed", "declined", "button"):
            with self.subTest(key=key):
                self.assertTrue(lines.get(key), f"{key} 문장이 비었다")
                # 다급한 사람에게는 짧아야 한다. 긴 문장은 안 들린다.
                self.assertLessEqual(len(lines[key][0]), 34, f"{key} 문장이 너무 길다")

    def test_ask_line_is_shortest(self):
        self.assertEqual("119 불러 드릴까예?", emergency_lines()["ask"][0])

    def test_reask_tells_how_to_answer(self):
        """재질문은 어떻게 답해야 하는지 알려 줘야 한다."""
        self.assertIn("예", emergency_lines()["reask"][0])

    def test_never_raises(self):
        self.assertTrue(emergency_lines())


if __name__ == "__main__":
    unittest.main()
