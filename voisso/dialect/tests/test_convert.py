# -*- coding: utf-8 -*-
"""변환 동작·사전 스키마·라이선스 가드 테스트."""

from __future__ import annotations

import re
import time
import unittest

from voisso.dialect import (
    entries,
    explain,
    lexicon_size,
    load_lexicon,
    normalize,
    restricted_entries,
    rule_count,
    rules,
    source_counts,
    to_dialect,
)
from voisso.dialect.core import RESTRICTED_SOURCE_PREFIXES, SOURCE_PREFIXES

VALID_PREFIXES = ("curated:", "wikipedia:", "nikl:")


class ContractTest(unittest.TestCase):
    """docs/CONTRACT.md §4 가 요구하는 시그니처 그대로 부를 수 있어야 한다."""

    def test_signatures(self):
        self.assertIsInstance(normalize("어데 가노"), str)
        self.assertIsInstance(to_dialect("가겠습니다"), str)
        self.assertIsInstance(lexicon_size(), int)

    def test_empty_and_none_like_input(self):
        for value in ["", "   ", "\n"]:
            self.assertEqual(value, normalize(value))
            self.assertEqual(value, to_dialect(value))

    def test_long_input_does_not_blow_up(self):
        text = "물이 안 빠집니다. " * 500
        self.assertIn("빠집니더", to_dialect(text))

    def test_invalid_strength_rejected(self):
        with self.assertRaises(ValueError):
            to_dialect("확인했습니다.", strength="아무거나")


class LicenseGuardTest(unittest.TestCase):
    """공개 저장소에 넣으면 안 되는 출처가 섞이지 않았는지.

    docs/DATA_LICENSE.md §1 — AI Hub 이용정책 제5항은 승인 없는 제3자 제공을
    금지한다. 이 저장소는 공개 GitHub + MIT 라이선스이므로 AI Hub 유래 항목을
    커밋하면 규정 위반이다.
    """

    def test_no_restricted_sources(self):
        offenders = restricted_entries()
        self.assertEqual(
            [], offenders,
            f"재배포가 금지된 출처({', '.join(RESTRICTED_SOURCE_PREFIXES)})에서 온 항목이 "
            f"{len(offenders)}건 있다. 저장소에 커밋하면 안 된다. "
            "docs/DATA_LICENSE.md §1 을 확인하고, tools/filter_lexicon.py 로 걷어내라. "
            "P1이 '재배포 가능'으로 결론을 바꾼 경우에만 이 테스트를 조정하라.",
        )

    def test_every_item_has_a_source(self):
        for item in [*entries(), *rules()]:
            with self.subTest(item=item.get("dialect") or item.get("desc")):
                source = item.get("source", "")
                self.assertTrue(source.strip(), "source 가 비어 있다")
                self.assertTrue(
                    source.startswith(SOURCE_PREFIXES),
                    f"출처 접두사 규약 위반: {source!r}",
                )

    def test_sources_are_redistributable(self):
        for prefix in source_counts():
            with self.subTest(prefix=prefix):
                self.assertIn(prefix, VALID_PREFIXES)


class LexiconSchemaTest(unittest.TestCase):
    def test_size_floor(self):
        self.assertGreaterEqual(lexicon_size(), 300, "어휘 300개 하한을 밑돈다")
        self.assertGreaterEqual(rule_count(), 40, "규칙 40개 하한을 밑돈다")

    def test_meta_counts_match(self):
        meta = load_lexicon()["meta"]
        self.assertEqual(meta["entry_count"], lexicon_size())
        self.assertEqual(meta["rule_count"], rule_count())

    def test_required_fields(self):
        for entry in entries():
            with self.subTest(entry=entry.get("dialect")):
                for field in ("dialect", "standard", "pos", "source"):
                    self.assertTrue(entry.get(field), f"{field} 가 비었다")

    def test_no_identity_pairs(self):
        """방언형과 표준형이 같은 항목은 변환에 아무 일도 하지 않는다.

        사전 규모만 부풀리는 패딩이므로 넣지 않는다.
        """
        same = [e["dialect"] for e in entries() if e["dialect"] == e["standard"]]
        self.assertEqual([], same, f"동일쌍 {len(same)}건: {same[:10]}")

    def test_no_duplicate_headwords(self):
        seen = [e["dialect"] for e in entries()]
        dupes = {w for w in seen if seen.count(w) > 1}
        self.assertEqual(set(), dupes)

    def test_rule_patterns_compile(self):
        for rule in rules():
            with self.subTest(desc=rule.get("desc")):
                re.compile(rule["pattern"])

    def test_rule_directions_are_known(self):
        for rule in rules():
            with self.subTest(desc=rule.get("desc")):
                self.assertIn(rule.get("dir"), ("to_standard", "to_dialect", "both"))


class ConversionTest(unittest.TestCase):
    def test_longest_match_wins(self):
        """짧은 표제어가 긴 표제어를 잡아먹으면 안 된다."""
        self.assertIn("길바닥", normalize("질바닥이 패였다"))

    def test_backtracks_to_shorter_headword(self):
        """긴 표제어의 뒤 문맥이 안 맞으면 짧은 쪽으로 되돌아가야 한다."""
        self.assertIn("막혀서", normalize("수채구영이 맥히가꼬 넘칩니더"))

    def test_josa_follows_new_final_consonant(self):
        """어휘를 바꾸면 조사도 받침에 맞춰야 한다. (차부가 → 버스터미널이)"""
        self.assertIn("버스터미널이", normalize("차부가 어데고?"))

    def test_josa_fix_does_not_touch_word_endings(self):
        """'마을'의 끝 글자 '을'을 조사로 착각해 '마를'로 만들면 안 된다."""
        self.assertIn("마을 앞", normalize("마실 앞 질바닥"))

    def test_numbers_and_department_names_survive(self):
        text = "건설도시국 도로과로 접수했습니다. 대표번호는 1522-0120입니다."
        for direction in (to_dialect, normalize):
            with self.subTest(direction=direction.__name__):
                result = direction(text)
                self.assertIn("건설도시국 도로과", result)
                self.assertIn("1522-0120", result)

    def test_connective_rules_do_not_eat_real_words(self):
        """연결어미 규칙이 실제 낱말을 잡아먹으면 안 된다. 전부 한 번씩 물렸던 것들이다."""
        cases = [
            ("기와가 떨어졌다", "기와가"),      # -와가 규칙
            ("차에 타고 가버렸다", "가버렸다"),  # ㅂ불규칙 -버 규칙
            ("학교에 가고 싶다", "가고"),        # -가꼬 규칙
            ("나이가 많다", "나이가"),          # -이가 (규칙으로 만들지 않은 이유)
            ("질문이 있습니다", "질문"),        # '질'(길)을 사전에서 뺀 이유
        ]
        for text, must_survive in cases:
            with self.subTest(text=text):
                self.assertIn(must_survive, normalize(text))

    def test_standard_text_is_left_alone(self):
        """사투리 요소가 없으면 normalize 가 건드리지 않아야 한다."""
        for text in ["담당자가 확인 후 연락드리겠습니다.", "서류를 준비해 오세요."]:
            with self.subTest(text=text):
                self.assertEqual(text, normalize(text))

    def test_key_ending_transforms(self):
        cases = [
            ("접수해 드리겠습니다.", "접수해 드리겠습니더."),
            ("연락드릴게요.", "연락드릴게예."),
            ("잠시만 기다려 주세요.", "잠시만 기다려 주이소."),
            ("어디십니까?", "어데십니꺼?"),
        ]
        for standard, expected in cases:
            with self.subTest(standard=standard):
                self.assertEqual(expected, to_dialect(standard))

    def test_strength_light_is_conservative(self):
        """light 는 종결어미만 건드린다 — 어휘는 그대로다."""
        self.assertIn("조금", to_dialect("조금 기다려 주세요.", strength="light"))

    def test_explain_reports_applied_items(self):
        hits = explain("접수해 드리겠습니다.", "to_dialect")
        self.assertTrue(hits)
        self.assertTrue(all({"kind", "from", "to"} <= set(h) for h in hits))

    def test_performance_is_acceptable_on_a_laptop(self):
        """CONTRACT §6 — 개발·운영 환경이 노트북이다. 문장 100개가 1초 안에 끝나야 한다."""
        text = "집 앞에 물이 안 빠지고 자꾸 고이가꼬 몬 살겠다"
        start = time.perf_counter()
        for _ in range(100):
            normalize(text)
        self.assertLess(time.perf_counter() - start, 1.0)


if __name__ == "__main__":
    unittest.main()
