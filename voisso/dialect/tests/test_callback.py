# -*- coding: utf-8 -*-
"""진행 안내 콜백 — 브리핑 변환과 질문 처리 (계약서 5-C).

**절대 규칙: AI 는 담당자가 쓴 내용만 전달한다.** 브리핑에 없는 답을 지어내면
그것은 행정 약속이 된다. 이 테스트가 그 경계를 지킨다.
"""

from __future__ import annotations

import unittest

from voisso.dialect import (
    briefing_to_dialect,
    callback_question,
    deflection_line,
    expand_noun_final,
    normalize,
    officer_to_dialect,
)

#: AI 가 답하면 안 되는 질문. 하나라도 새면 행정 약속이 나간다.
MUST_RELAY = [
    "그라믄 언제 됩니꺼?", "언제쯤 되노?", "얼매나 걸리노?", "며칠이나 걸립니꺼?",
    "진짜 되는 거 맞나예?", "돈은 얼마나 드노?", "비용이 듭니꺼?",
    "가능하나예?", "안 되나예?", "누가 오노?", "확실합니꺼?",
    "그라믄 다음 주에 오는 거라예?",
]

#: 이미 확정된 사실이라 답해도 되는 질문.
ANSWERABLE = [
    "접수번호가 몇 번이라예?", "어느 부서에서 맡아 하노?", "누가 담당이라예?",
]


class BriefingConversionTest(unittest.TestCase):
    def test_noun_final_is_expanded(self):
        """브리핑은 소리 내어 읽는다. 명사로 끝나면 공문 낭독이 된다."""
        cases = [
            ("현장 확인 완료.", "현장 확인 다 했습니다."),
            ("현장 점검 결과 이상 없음.", "현장 점검 결과 이상 없습니다."),
            ("본 공사는 다음 주 진행 예정.", "본 공사는 다음 주 진행할 예정입니다."),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, expand_noun_final(text))

    def test_noun_final_does_not_touch_mid_sentence(self):
        """'완료했습니다' 처럼 문장 중간에 나오는 것은 건드리면 안 된다."""
        for text in ["처리 완료했습니다.", "확인 완료하였고 조치 중입니다."]:
            with self.subTest(text=text):
                self.assertEqual(text, expand_noun_final(text))

    def test_briefing_pipeline(self):
        self.assertEqual(
            "현장 확인 다 했습니더. 이번 주 내 배수관 바닥 흙 파내는 작업 예정입니더.",
            briefing_to_dialect("현장 확인 완료. 이번 주 내 배수관 준설 예정입니다."),
        )

    def test_briefing_preserves_dates_and_departments(self):
        text = "8월 25일 오전에 건설도시국 도로과에서 굴착 작업 예정입니다."
        out = briefing_to_dialect(text)
        self.assertIn("8월 25일", out)
        self.assertIn("건설도시국 도로과", out)

    def test_briefing_differs_from_handoff(self):
        """핸드오프는 채팅이라 명사형을 그대로 둔다. 브리핑은 읽어야 하므로 편다."""
        text = "현장 확인 완료."
        self.assertEqual(text, officer_to_dialect(text))
        self.assertNotEqual(text, briefing_to_dialect(text))

    def test_briefing_adds_no_content(self):
        """숫자·고유명사가 늘어나면 안 된다. AI 가 일정을 지어내지 않는다는 최소 보증."""
        import re
        for text in ["업체 선정 중입니다.", "추가 확인이 필요하여 처리가 지연되고 있습니다."]:
            with self.subTest(text=text):
                out = briefing_to_dialect(text)
                self.assertEqual(re.findall(r"\d+", text), re.findall(r"\d+", out))


class CallbackQuestionTest(unittest.TestCase):
    def test_new_information_is_always_relayed(self):
        leaked = []
        for question in MUST_RELAY:
            result = callback_question(question)
            if result["verdict"] != "relay":
                leaked.append(f"\n  {question!r} → {result['verdict']}")
        self.assertEqual(
            [], leaked,
            "AI 가 답해서는 안 되는 질문이 answerable 로 샜다. "
            "브리핑에 없는 답은 행정 약속이 된다." + "".join(leaked),
        )

    def test_settled_facts_are_answerable(self):
        for question in ANSWERABLE:
            with self.subTest(question=question):
                self.assertEqual("answerable", callback_question(question)["verdict"])

    def test_unknown_defaults_to_relay(self):
        """애매하면 넘긴다. 지어내는 것보다 넘기는 편이 낫다."""
        for question in ["고맙심더", "음 글쎄예", ""]:
            with self.subTest(question=question):
                self.assertEqual("relay", callback_question(question)["verdict"])

    def test_relay_carries_a_reply_and_reason(self):
        result = callback_question("언제 됩니꺼?")
        self.assertTrue(result["suggested_reply"].strip())
        self.assertTrue(result["reason"].strip())

    def test_deflection_is_dialect_and_makes_no_promise(self):
        line = deflection_line()
        self.assertTrue(line.endswith("니더.") or line.endswith("예."))
        # 일정·가능 여부를 단정하는 말이 들어가면 안 된다.
        for forbidden in ["됩니다", "가능합니다", "해 드리겠습니다만", "내일", "이번 주"]:
            self.assertNotIn(forbidden, line)

    def test_deflection_round_trips(self):
        for index in range(3):
            with self.subTest(index=index):
                self.assertTrue(normalize(deflection_line(index)).strip())


if __name__ == "__main__":
    unittest.main()
