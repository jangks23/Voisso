# -*- coding: utf-8 -*-
"""숫자 낱자 읽기 — TTS 입력용 표기.

TTS 가 "119"를 "백십구"로 읽으면 어르신이 못 알아듣는다.
**화면에는 숫자를, TTS 에는 한글을 보낸다.**

⚠️ 이 표기는 실제 음성 생성 없이 정했다(계약서 5-D). 근거는 한국어 수사 읽기 규칙이고,
실제 확인은 촬영 전에 사용자가 한다.
"""

from __future__ import annotations

import unittest

from voisso.dialect import for_tts, line, normalize, number_speech, to_dialect


class EmergencyNumberTest(unittest.TestCase):
    """긴급번호를 한자어로 읽으면 사람이 못 부른다."""

    def test_119_and_112(self):
        self.assertEqual("위험하시믄 일일구 눌러 주이소.", for_tts("위험하시믄 119 눌러 주이소."))
        self.assertEqual("일일이에 신고하이소.", for_tts("112에 신고하이소."))

    def test_never_reads_as_sino_korean(self):
        """'백십구'가 나오면 안 된다."""
        for text in ["119", "119 불러 드릴까예?", "지금 119 누르이소."]:
            with self.subTest(text=text):
                self.assertNotIn("백십구", for_tts(text))
                self.assertIn("일일구", for_tts(text))

    def test_representative_number(self):
        self.assertIn("일오이이 공일이공", for_tts("대표번호는 1522-0120입니더."))


class PhoneNumberTest(unittest.TestCase):
    def test_mobile(self):
        self.assertIn("공일공 일이삼사 오육칠팔", for_tts("010-1234-5678로 문자 드릴게예."))

    def test_landline(self):
        self.assertIn("공오사 팔팔공 이일일삼", for_tts("054-880-2113으로 연락드리겠습니더."))

    def test_zero_is_gong_and_six_is_yuk(self):
        """전화 문맥에서 0은 '공', 6은 '육'이다."""
        spoken = for_tts("010-0666-0000")
        self.assertIn("공", spoken)
        self.assertIn("육", spoken)
        self.assertNotIn("영", spoken)
        self.assertNotIn("륙", spoken)


class MustNotTouchTest(unittest.TestCase):
    """날짜·개수·시각은 한자어로 읽는 것이 맞다. 낱자로 바꾸면 오히려 못 알아듣는다."""

    KEEP = [
        "3일 이내 처리됩니더.",
        "14일 안에 됩니더.",
        "오전 9시부터 오후 6시까지입니더.",
        "2주 걸립니더.",
        "예산 1억 2천만 원입니더.",
        "8월 25일 오전에 옵니더.",
        "2026년 8월 22일입니더.",
        "2026-08-22 접수했습니더.",
        "8월 25일-27일 공사합니더.",
        "1000-2000원 정도 듭니더.",
        "1500-3000명 정도입니더.",
        "오후 2-3시에 옵니더.",
        "PHONE_0042 로 확인하이소.",
        "건설도시국 도로과입니더.",
    ]

    def test_untouched(self):
        changed = []
        for text in self.KEEP:
            if for_tts(text) != text:
                changed.append(f"\n  {text!r} → {for_tts(text)!r}")
        self.assertEqual([], changed, "건드리면 안 되는 숫자를 바꿨다." + "".join(changed))

    def test_reference_number_is_spelled(self):
        """접수번호는 낱자가 맞다. '이천이십육 사백십칠'로 읽으면 안 된다."""
        spoken = for_tts("접수번호 2026-0417번입니더.")
        self.assertIn("이공이육 공사일칠", spoken)


class TableTest(unittest.TestCase):
    def test_every_entry_is_hangul(self):
        for item in number_speech():
            with self.subTest(written=item["written"]):
                self.assertFalse(any(c.isdigit() for c in item["spoken"]),
                                 "발음 표기에 숫자가 남아 있으면 TTS 가 다시 헷갈린다")

    def test_longest_match_first(self):
        """1522-0120 이 120 에 잡아먹히면 안 된다."""
        self.assertIn("일오이이 공일이공", for_tts("1522-0120"))

    def test_never_raises(self):
        for value in ["", "   ", "숫자 없음"]:
            with self.subTest(value=value):
                self.assertEqual(value, for_tts(value))


class LocationQuestionTest(unittest.TestCase):
    """어르신은 행정구역으로 생각하지 않는다. '어느 시·군'을 물으면 되묻게 된다."""

    def test_asks_where_they_are_now(self):
        self.assertEqual("지금 어데 계신가예?", line("ask_where"))
        self.assertEqual("지금 어데 계신지 말씀해 주이소.", line("ask_where", "normal"))

    def test_short_enough_for_subtitle(self):
        self.assertLessEqual(len(line("ask_where")), 15)

    def test_round_trips(self):
        for style in ("short", "normal"):
            with self.subTest(style=style):
                self.assertTrue(normalize(line("ask_where", style)).strip())

    def test_no_administrative_jargon(self):
        for style in ("short", "normal"):
            with self.subTest(style=style):
                for word in ("시·군", "시군", "행정구역", "읍면동"):
                    self.assertNotIn(word, line("ask_where", style))


if __name__ == "__main__":
    unittest.main()
