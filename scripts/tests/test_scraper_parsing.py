"""크롤러 파싱 회귀 테스트.

    python3 -m unittest scripts.tests.test_scraper_parsing

네트워크도 ``data/raw`` 캐시도 쓰지 않는다. ``fixtures/`` 의 합성 HTML만 읽는다.
여기 있는 항목은 대부분 **실제로 한 번 겪은 버그**다. 다시 새지 않도록 못 박는다.

  - 표 컬럼 순서가 페이지마다 다르다 (전화번호와 담당업무가 뒤바뀐 페이지가 있다)
  - 담당업무 본문에 전화번호가 섞여 들어와 공개 데이터셋으로 111건 새어 나갔다
  - 하이픈이 빠진 전화번호(0540000003)를 놓쳤다
"""

from __future__ import annotations

import json
import os
import random
import re
import unittest

from scripts import scrape_gb_departments as scraper
from voisso.routing.privacy import contains_phone

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

#: 검증 명령이 쓰는 것과 같은 패턴. 공개 산출물에 이게 걸리면 실패다.
LEAK_RE = re.compile(r"[☎☏]|(?<!\d)\d{3,4}[-‑–]\d{4}(?!\d)")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


class DepartmentListTest(unittest.TestCase):
    """조직도 페이지 -> (dept_code, dept_code1, 부서명)"""

    def setUp(self) -> None:
        self.entries = scraper.parse_department_list(fixture("list_page.html"))

    def test_extracts_every_department_once(self) -> None:
        # 미끼 링크 2개는 제외, 중복 링크 1개는 합쳐져 4개여야 한다.
        self.assertEqual(len(self.entries), 4)
        self.assertEqual(
            [(e["dept_code"], e["dept_code1"]) for e in self.entries],
            [
                ("1000001", "1000001"),
                ("2000000", ""),
                ("2000000", "2000010"),
                ("2000000", "2000020"),
            ],
        )

    def test_strips_comments_and_whitespace_from_name(self) -> None:
        names = [e["name"] for e in self.entries]
        self.assertEqual(names, ["시험비서실", "테스트국", "가상수도과", "모의도로과"])
        for name in names:
            self.assertNotIn("<!--", name)
            self.assertEqual(name, name.strip())

    def test_ignores_links_without_dept_code(self) -> None:
        self.assertNotIn("직원/담당업무", [e["name"] for e in self.entries])

    def test_ignores_other_menu_ids(self) -> None:
        self.assertNotIn("9999999", [e["dept_code"] for e in self.entries])


class DutiesTest(unittest.TestCase):
    """<p class="silguk_work"> -> duties[]"""

    def test_splits_and_strips_numbering(self) -> None:
        duties = scraper.parse_duties(fixture("detail_with_duties.html"))
        self.assertEqual(
            duties,
            [
                "가상 상수도 시설의 설치・운영",
                "모의 급수구역 관리",
                "시험용 수질 검사",
                "그밖에 과내 다른 팀에 속하지 아니하는 사항",
            ],
        )

    def test_missing_block_is_empty_not_error(self) -> None:
        # 원본 96개 부서 중 92개에 업무안내가 없다. 없는 게 정상이다.
        self.assertEqual(scraper.parse_duties(fixture("detail_no_duties_swapped.html")), [])


class StaffTableTest(unittest.TestCase):
    """직원표 -> staff[]"""

    def test_parses_every_row(self) -> None:
        staff = scraper.parse_staff(fixture("detail_with_duties.html"))
        self.assertEqual(len(staff), 6)

    def test_blank_position_is_kept(self) -> None:
        # 부서장 행은 직책 칸이 비어 있다. 행 자체를 버리면 안 된다.
        head = scraper.parse_staff(fixture("detail_with_duties.html"))[0]
        self.assertEqual(head["position"], "")
        self.assertEqual(head["duty"], "가상수도과 업무 총괄")
        self.assertEqual(head["phone"], "054-000-0001")

    def test_hyphenless_phone_gets_separators(self) -> None:
        # 0540000003 -> 054-000-0003. 숫자를 지어내는 게 아니라 구분자만 붙인다.
        row = scraper.parse_staff(fixture("detail_with_duties.html"))[2]
        self.assertEqual(row["phone"], "054-000-0003")

    def test_vacant_row_has_no_phone(self) -> None:
        row = scraper.parse_staff(fixture("detail_with_duties.html"))[4]
        self.assertEqual(row["phone"], "")
        self.assertIn("육아휴직", row["duty"])

    def test_truncated_phone_is_discarded(self) -> None:
        row = scraper.parse_staff(fixture("detail_with_duties.html"))[5]
        self.assertEqual(row["phone"], "")

    def test_swapped_columns_are_mapped_by_header(self) -> None:
        """전화번호와 담당업무 순서가 뒤바뀐 페이지에서도 컬럼이 어긋나면 안 된다."""
        staff = scraper.parse_staff(fixture("detail_no_duties_swapped.html"))
        self.assertEqual(staff[0]["position"], "과장")
        self.assertEqual(staff[0]["duty"], "모의도로과 업무 총괄")
        self.assertEqual(staff[0]["phone"], "054-000-0010")

    def test_header_row_is_not_a_staff_row(self) -> None:
        for row in scraper.parse_staff(fixture("detail_no_duties_swapped.html")):
            self.assertNotEqual(row["position"], "직위・직급")


class PhoneNormalizeTest(unittest.TestCase):
    def test_cases(self) -> None:
        cases = {
            "054-000-0001": "054-000-0001",
            "0540000003": "054-000-0003",
            "054-0000003": "054-000-0003",
            "054-000-": "",
            "-": "",
            "": "",
            "내선": "",
            "+99-0-0000-0000": "+99-0-0000-0000",   # 국제번호는 원문 유지
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(scraper.normalize_phone(raw), expected)


def _scrape_fixtures() -> list[dict]:
    """네트워크 대신 픽스처로 scrape_department() 와 같은 모양의 결과를 만든다."""
    pages = [
        ("2000000", "2000010", "가상수도과", "detail_with_duties.html"),
        ("2000000", "2000020", "모의도로과", "detail_no_duties_swapped.html"),
        ("2000000", "", "테스트국", "detail_no_duties_swapped.html"),
    ]
    out = []
    for dept_code, dept_code1, name, page in pages:
        html = fixture(page)
        out.append(
            {
                "dept_code": dept_code,
                "dept_code1": dept_code1,
                "name": name,
                "source_url": f"https://example.invalid/{dept_code}/{dept_code1}",
                "duties": scraper.parse_duties(html),
                "staff": scraper.parse_staff(html),
            }
        )
    return out


class DatasetTest(unittest.TestCase):
    """parse -> build_dataset 까지의 조립 결과"""

    def setUp(self) -> None:
        self.dataset, self.phone_map = scraper.build_dataset(_scrape_fixtures())
        self.departments = self.dataset["departments"]

    def test_ids_and_parentage(self) -> None:
        by_id = {d["id"]: d for d in self.departments}
        self.assertIn("gb-2000000-2000010", by_id)
        self.assertIn("gb-2000000", by_id)              # 실/국 단위는 접미사가 없다
        self.assertEqual(by_id["gb-2000000-2000010"]["parent"], "테스트국")
        self.assertEqual(by_id["gb-2000000-2000010"]["full_name"], "테스트국 가상수도과")
        self.assertEqual(by_id["gb-2000000"]["parent"], "")   # 자기 자신이 부모일 수 없다

    def test_meta_counts_match_payload(self) -> None:
        meta = self.dataset["meta"]
        self.assertEqual(meta["department_count"], len(self.departments))
        self.assertEqual(
            meta["staff_count"], sum(len(d["staff"]) for d in self.departments)
        )
        self.assertTrue(meta["phone_masked"])
        self.assertIn("공공누리", meta["license"])
        self.assertIn("gb.go.kr", meta["attribution"])   # 제3유형의 핵심 의무

    def test_staff_schema_is_exactly_the_contract(self) -> None:
        for dept in self.departments:
            for member in dept["staff"]:
                self.assertEqual(set(member), {"position", "duty", "phone_token"})


class PhoneLeakRegressionTest(unittest.TestCase):
    """전화번호 살균 — 공개 데이터셋에 번호가 남으면 안 된다.

    실제로 111건이 새어 나갔던 버그다. 담당업무 컬럼은 토큰화했는데
    담당업무 **본문**에 섞여 들어간 번호를 놓쳤다.
    """

    def setUp(self) -> None:
        self.dataset, self.phone_map = scraper.build_dataset(_scrape_fixtures())

    def test_no_phone_anywhere_in_public_dataset(self) -> None:
        blob = json.dumps(self.dataset, ensure_ascii=False)
        self.assertEqual(LEAK_RE.findall(blob), [])

    def test_duty_body_is_scrubbed_but_sentence_survives(self) -> None:
        duties = {
            member["duty"]
            for dept in self.dataset["departments"]
            for member in dept["staff"]
        }
        # 번호 부기는 사라지고 업무 내용은 남는다 (라우팅 근거 evidence 로 쓰인다)
        self.assertIn("급수팀 업무 전반", duties)
        for duty in duties:
            self.assertFalse(contains_phone(duty), duty)

    def test_scrubbing_does_not_empty_the_duty(self) -> None:
        for dept in self.dataset["departments"]:
            for member in dept["staff"]:
                self.assertTrue(member["duty"].strip(), f"{dept['full_name']} 의 담당업무가 비었다")

    def test_phone_column_becomes_token(self) -> None:
        tokens = [
            member["phone_token"]
            for dept in self.dataset["departments"]
            for member in dept["staff"]
            if member["phone_token"]
        ]
        self.assertTrue(tokens)
        for token in tokens:
            self.assertRegex(token, r"^PHONE_\d{4}$")
            self.assertIn(token, self.phone_map)

    def test_real_numbers_live_only_in_the_private_map(self) -> None:
        self.assertIn("054-000-0001", self.phone_map.values())
        self.assertNotIn("054-000-0001", json.dumps(self.dataset, ensure_ascii=False))


class TokenDeterminismTest(unittest.TestCase):
    """같은 입력이면 언제나 같은 토큰이 나와야 한다.

    토큰이 실행마다 흔들리면 민원카드에 저장된 phone_token 이 다음 수집 후
    엉뚱한 부서를 가리키게 된다.
    """

    def test_same_input_same_tokens(self) -> None:
        first, first_map = scraper.build_dataset(_scrape_fixtures())
        second, second_map = scraper.build_dataset(_scrape_fixtures())
        self.assertEqual(first_map, second_map)
        self.assertEqual(
            json.dumps(first["departments"], ensure_ascii=False, sort_keys=True),
            json.dumps(second["departments"], ensure_ascii=False, sort_keys=True),
        )

    def test_input_order_does_not_matter(self) -> None:
        # 크롤링은 워커 4개로 병렬이라 도착 순서가 매번 다르다.
        shuffled = _scrape_fixtures()
        random.Random(20260822).shuffle(shuffled)
        ordered_map = scraper.build_dataset(_scrape_fixtures())[1]
        shuffled_map = scraper.build_dataset(shuffled)[1]
        self.assertEqual(ordered_map, shuffled_map)

    def test_identical_numbers_share_one_token(self) -> None:
        dataset, phone_map = scraper.build_dataset(_scrape_fixtures())
        self.assertEqual(len(set(phone_map.values())), len(phone_map))


if __name__ == "__main__":
    unittest.main()
