# -*- coding: utf-8 -*-
"""통화 마무리 흐름 — 종료 신호 인식과 행정용어 순화.

슬롯이 다 차면 "더 하실 말씀 있으십니꺼?" 를 묻고, 없다고 하면 담당자에게 넘긴다.
**어르신이 "없다"를 말하는 방식을 못 알아들으면 통화가 끝나지 않는다.**
"""

from __future__ import annotations

import unittest

from voisso.dialect import admin_plain, closing_cues, normalize, soften, to_dialect

#: 실제로 나올 법한 종료 표현. 전부 표준형으로 펴져야 한다.
CLOSING = {
    "없어예": "없어요", "엄써예": "없어요", "엄따": "없다",
    "됐어예": "됐어요", "그마 됐다": "그만 됐다", "고마 됐어예": "그만 됐어요",
    "이자 됐다": "이제 됐다", "아이다": "아니다",
    "괘안타": "괜찮다", "개안타": "괜찮다",
    "그기 다라예": "그게 다예요", "그마 하이소": "그만하세요",
}


class ClosingCueTest(unittest.TestCase):
    def test_dialect_closing_forms_are_normalized(self):
        for dialect, expected in CLOSING.items():
            with self.subTest(dialect=dialect):
                self.assertEqual(expected, normalize(dialect))

    def test_cue_lists_exist_and_are_disjoint(self):
        cues = closing_cues()
        neg, pos = set(cues["closing_negative"]), set(cues["closing_positive"])
        self.assertGreaterEqual(len(neg), 40)
        self.assertGreaterEqual(len(pos), 20)
        self.assertEqual(set(), neg & pos, "같은 표현이 종료와 계속 양쪽에 있으면 판정이 흔들린다")

    def test_cues_cover_both_dialect_and_standard(self):
        """normalize 전후 어느 쪽에 매칭해도 걸려야 한다."""
        neg = set(closing_cues()["closing_negative"])
        for pair in (("없어예", "없어요"), ("됐어예", "됐어요"), ("다 했어예", "다 했어요")):
            with self.subTest(pair=pair):
                self.assertTrue(set(pair) <= neg)

    def test_decision_simulation(self):
        """P6 가 쓸 방식 그대로 — 긍정을 먼저 본다(놓치면 민원을 잃는다)."""
        cues = closing_cues()

        def decide(text: str) -> str:
            said = normalize(text)
            if any(c in said or c in text for c in cues["closing_positive"]):
                return "계속"
            if any(c in said or c in text for c in cues["closing_negative"]):
                return "종료"
            return "판정 불가"

        for text, expected in [
            ("없어예", "종료"), ("그마 됐다", "종료"), ("괘안타", "종료"),
            ("그기 다라예", "종료"), ("다 했심더", "종료"), ("끝이라예", "종료"),
            ("하나 더 있는데예", "계속"), ("또 있어예", "계속"), ("아 맞다", "계속"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(expected, decide(text))


class AdminPlainTest(unittest.TestCase):
    def test_softens_bureaucratic_terms(self):
        cases = [
            ("해당 건은 검토 후 회신드리겠습니다.", "연락"),
            ("금일 접수된 건은 익일 처리 예정입니다.", "오늘"),
            ("담당자가 부재중이라 확인 후 회신드리겠습니다.", "자리를 비워서"),
        ]
        for text, must_contain in cases:
            with self.subTest(text=text):
                self.assertIn(must_contain, soften(text))

    def test_soften_output_is_grammatical(self):
        """겹치는 매핑이 문장을 깨뜨리지 않는지. 셋 다 한 번씩 물렸던 것들이다."""
        broken = ["맞지 못하여", "담당하는 곳으로 넘겨 처리하도록 하겠습니다 담당",
                  "조건을 맞지"]
        for text in [
            "신청 자격 요건을 충족하지 못하여 반려되었습니다.",
            "관련 부서에 이첩하여 처리하도록 하겠습니다.",
        ]:
            with self.subTest(text=text):
                out = soften(text)
                for bad in broken:
                    self.assertNotIn(bad, out)

    def test_soften_preserves_numbers_and_department_names(self):
        text = "건설도시국 도로과에서 14일 이내에 회신드리겠습니다."
        out = soften(text)
        self.assertIn("건설도시국 도로과", out)
        self.assertIn("14", out)

    def test_soften_is_not_applied_automatically(self):
        """to_dialect 는 의역을 하지 않는다. 부르는 쪽이 선택한다."""
        self.assertIn("회신", to_dialect("회신드리겠습니다."))

    def test_handoff_pipeline_is_natural(self):
        """soften → to_dialect 가 담당자 발화의 정식 경로다."""
        out = to_dialect(soften("해당 건은 검토 후 회신드리겠습니다."))
        self.assertEqual("말씀하신 건은 살펴보고 연락드리겠습니더.", out)

    def test_admin_table_has_no_self_mapping(self):
        for item in admin_plain():
            with self.subTest(admin=item["admin"]):
                self.assertNotEqual(item["admin"], item["plain"])


class ClosingPhraseTest(unittest.TestCase):
    """추천 문구가 실제로 그렇게 나오는지. 문구가 바뀌면 여기서 잡힌다."""

    def test_recommended_phrases(self):
        cases = [
            ("더 하실 말씀 있으십니까?", "더 하실 말씀 있으십니꺼?"),
            ("또 불편하신 거 있으시면 말씀해 주세요.", "또 불편하신 거 있으시믄 말씀해 주이소."),
            ("담당자분 바꿔 드릴게요. 끊지 마시고 잠깐만 기다려 주세요.",
             "담당자분 바꿔 드릴게예. 끊지 마시고 잠깐만 기다려 주이소."),
        ]
        for standard, expected in cases:
            with self.subTest(standard=standard):
                self.assertEqual(expected, to_dialect(standard))

    def test_recommended_phrases_round_trip(self):
        for standard in ["더 하실 말씀 있으십니까?",
                         "담당자분 바꿔 드릴게요. 끊지 마시고 잠깐만 기다려 주세요."]:
            with self.subTest(standard=standard):
                self.assertEqual(standard, normalize(to_dialect(standard)))


if __name__ == "__main__":
    unittest.main()
