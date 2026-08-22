# -*- coding: utf-8 -*-
"""자막용 짧은 표현 — 길이와 정중함을 함께 지킨다.

자막은 길면 안 읽힌다. 그렇다고 줄이다 보면 무뚝뚝해진다.
**그 균형이 이 작업의 전부고, 여기서 기계로 강제한다.**
"""

from __future__ import annotations

import unittest

from voisso.dialect import line, normalize, short_forms, to_dialect
from voisso.dialect.core import short_form_limits

#: 경북 정중체 종결. 하나도 없으면 반말이다.
_POLITE_ENDINGS = ("니더", "니꺼", "예", "이소", "습니다", "시더")

#: "주-" 없이 쓰면 명령조가 되는 동사. 줄이더라도 이건 남겨야 한다.
_NEEDS_BENEFACTIVE = ("말하이소", "적으이소", "누르이소", "오이소", "하이소만")


class LengthTest(unittest.TestCase):
    def test_within_limits(self):
        limits = short_form_limits()
        over = []
        for key, form in short_forms().items():
            emergency = form["category"] == "응급"
            cap_short = limits["emergency_short"] if emergency else limits["short"]
            cap_normal = limits["emergency_normal"] if emergency else limits["normal"]
            if len(form["short"]) > cap_short:
                over.append(f"\n  {key}.short {len(form['short'])}자 > {cap_short}")
            if len(form["normal"]) > cap_normal:
                over.append(f"\n  {key}.normal {len(form['normal'])}자 > {cap_normal}")
        self.assertEqual([], over, "자막 길이 상한을 넘었다." + "".join(over))

    def test_short_is_not_longer_than_normal(self):
        for key, form in short_forms().items():
            with self.subTest(key=key):
                self.assertLessEqual(len(form["short"]), len(form["normal"]),
                                     "짧은 판이 보통 판보다 길다")

    def test_emergency_lines_are_shortest(self):
        """다급한 사람은 긴 문장을 못 듣는다."""
        for key, form in short_forms().items():
            if form["category"] == "응급":
                with self.subTest(key=key):
                    self.assertLessEqual(len(form["short"]), 20)


class PolitenessTest(unittest.TestCase):
    """짧아지면서 무뚝뚝해지지 않았는가. 어르신 대상 공공 서비스다."""

    def test_every_line_is_polite(self):
        rude = []
        for key, form in short_forms().items():
            for style in ("short", "normal"):
                text = form[style].rstrip(" .!?…")
                if not text.endswith(_POLITE_ENDINGS):
                    rude.append(f"\n  {key}.{style}: {form[style]!r}")
        self.assertEqual([], rude, "정중 종결이 아니다 — 반말로 떨어졌다." + "".join(rude))

    def test_no_bare_imperative(self):
        """'주-'가 빠진 명령형은 명령조다. 2~3자 아끼자고 어조를 잃지 않는다."""
        bad = []
        for key, form in short_forms().items():
            for style in ("short", "normal"):
                for pattern in _NEEDS_BENEFACTIVE:
                    if pattern in form[style]:
                        bad.append(f"\n  {key}.{style}: {form[style]!r} — '{pattern}'")
        self.assertEqual([], bad, "명령조로 떨어졌다." + "".join(bad))

    def test_benefactive_costs_almost_nothing(self):
        """줄여서 아끼는 글자가 얼마 안 된다는 근거. 이 값이 커지면 판단을 다시 해야 한다."""
        for polite, curt in [("말씀해 주세요.", "말하세요."), ("119 눌러 주세요.", "119 누르세요.")]:
            with self.subTest(polite=polite):
                saved = len(to_dialect(polite)) - len(to_dialect(curt))
                self.assertLessEqual(saved, 4, "줄임 이득이 예상보다 크다 — 재검토가 필요하다")


class ContentTest(unittest.TestCase):
    def test_round_trips(self):
        """문구가 정상적인 사투리인지. 표준어로 되돌려 확인한다."""
        for key, form in short_forms().items():
            with self.subTest(key=key):
                self.assertTrue(normalize(form["short"]).strip())

    def test_placeholder_survives(self):
        """{부서} 같은 치환 자리가 변환에 깨지면 안 된다."""
        for style in ("short", "normal"):
            with self.subTest(style=style):
                self.assertIn("{부서}", short_forms()["assigned"][style])

    def test_numbers_survive(self):
        for key in ("emergency_first", "ask_119", "button_119", "declined_119"):
            with self.subTest(key=key):
                if "119" in short_forms()[key]["standard_short"]:
                    self.assertIn("119", short_forms()[key]["short"])

    def test_line_helper(self):
        self.assertEqual(short_forms()["ask_where"]["short"], line("ask_where"))
        self.assertEqual(short_forms()["ask_where"]["normal"], line("ask_where", "normal"))
        self.assertEqual("", line("없는_키"))

    def test_covers_every_stage(self):
        """데모 6단계가 모두 자막 문구를 가지고 있는가."""
        forms = short_forms()
        for key in ("greeting", "ask_where", "accepted", "closing_question",
                    "handoff_wait", "callback_greeting", "ask_119", "button_119"):
            with self.subTest(key=key):
                self.assertIn(key, forms)


if __name__ == "__main__":
    unittest.main()
