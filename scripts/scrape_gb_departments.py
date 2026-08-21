#!/usr/bin/env python3
"""경상북도청 본청 부서 사무분장·직원 담당업무 크롤러.

출처: 경상북도청 홈페이지 조직도 > 부서별 직원안내
      https://www.gb.go.kr/Main/programs/organizationChart/organizationPartInfo.do

파이썬 표준 라이브러리만 사용한다 (pip 의존성 0).

    python3 scripts/scrape_gb_departments.py            # 캐시 사용
    python3 scripts/scrape_gb_departments.py --refresh  # 캐시 무시하고 재수집

산출물
    data/gb_departments.json    공개 데이터셋 (전화번호는 PHONE_0001 토큰)
    data/gb_departments.csv     부서·직위·담당업무·전화토큰 평면화
    data/private/phone_map.json 토큰 -> 실제 전화번호 (gitignore 대상)
    data/raw/*.html             원본 HTML 캐시

개인정보 처리: docs/CONTRACT.md 3절 참조.
원문에 담당자 실명 컬럼은 없다. 전화번호는 공개 산출물에 넣지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# 설정
# --------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:                      # 스크립트로 직접 실행해도 voisso 를 찾게 한다
    sys.path.insert(0, ROOT)

try:
    # 살균 로직은 P4 의 voisso/routing/privacy.py 하나만 쓴다. 여기서 다시 만들면
    # 두 구현이 갈라지면서 한쪽에만 뚫린 구멍이 생긴다. (표준 라이브러리만 사용)
    from voisso.routing.privacy import contains_phone, scrub
except ImportError as exc:                    # pragma: no cover
    raise SystemExit(
        f"voisso.routing.privacy 를 불러오지 못했다: {exc}\n"
        "전화번호 살균 없이 공개 데이터셋을 만들 수 없다. 저장소 루트에서 실행해라."
    )
DATA_DIR = os.environ.get("VOISSO_DATA_DIR") or os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
PRIVATE_DIR = os.path.join(DATA_DIR, "private")

BASE = "https://www.gb.go.kr"
LIST_URL = (
    BASE + "/Main/page.do?mnu_uid=8843&LARGE_CODE=720&MEDIUM_CODE=60"
    "&SMALL_CODE=40&SMALL_CODE2=20&SMALL_CODE3=70&vdept_code=V000010&tabNum=7"
)
DETAIL_URL = (
    BASE + "/Main/programs/organizationChart/organizationPartInfo.do"
    "?mnu_uid=2153&site_uid=0&dept_code={dept_code}&dept_code1={dept_code1}"
    "&listType=2&tabNum=1"
)
SOURCE_URL = BASE + "/Main/programs/organizationChart/organizationPartInfo.do"

USER_AGENT = (
    "Voisso-GB-OpenData-Crawler/1.0 (JunctionX Korea; public data collection; "
    "contact via project repository) Python-urllib"
)
WORKERS = 4
DELAY_SEC = 0.3          # 요청 간 최소 간격 (예의 있는 크롤링)
TIMEOUT_SEC = 20
MAX_RETRY = 3

FALLBACK_PHONE = "1522-0120"   # 경상북도청 대표번호

# 라이선스: docs/DATA_LICENSE.md 2절 (경상북도청 저작권정책 실제 확인 결과).
# 제3유형은 출처표시가 핵심 의무이므로 표기 문구를 meta 에 직접 박아 둔다.
# 이용자가 README 를 안 읽어도 데이터셋만 보면 표기 방법을 알 수 있어야 한다.
LICENSE = "공공누리 제3유형 (출처표시 + 변경금지)"
SOURCE_ORG = "경상북도청"
ATTRIBUTION = "출처: 경상북도청 (https://www.gb.go.kr)"
MIN_DEPARTMENTS = 90           # 이보다 적으면 수집 실패로 간주
ROBOTS_URL = BASE + "/robots.txt"

PHONE_RE = re.compile(r"\d{2,3}-\d{3,4}-\d{4}")
DIGIT_RE = re.compile(r"\D")
# 담당업무 본문에 섞여 들어온 연락처(해외주재관 휴대전화 등)를 찾기 위한 패턴
INLINE_PHONE_RE = re.compile(r"\+?\d[\d\-\s]{7,}\d")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.I)

_rate_lock = threading.Lock()
_last_request = [0.0]


# --------------------------------------------------------------------------
# 유틸
# --------------------------------------------------------------------------

def clean_text(fragment: str) -> str:
    """HTML 조각 -> 사람이 읽는 한 줄 텍스트."""
    text = COMMENT_RE.sub("", fragment)
    text = BR_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_phone(cell: str) -> str:
    """전화번호 셀을 정규화한다. 없는 번호를 만들어내지 않는다.

    원문에는 하이픈이 빠진 셀(``0548803942``)과 해외사무소 국제번호가 섞여 있다.
    자릿수를 근거로 구분자만 붙이거나, 판단이 서지 않으면 원문을 그대로 둔다.
    """
    cell = cell.strip()
    if not cell:
        return ""
    match = PHONE_RE.search(cell)
    if match:
        return match.group(0)

    digits = DIGIT_RE.sub("", cell)
    if 9 <= len(digits) <= 11 and digits.startswith("0"):
        area = 2 if digits.startswith("02") else 3
        rest = digits[area:]
        return f"{digits[:area]}-{rest[:-4]}-{rest[-4:]}"
    if len(digits) >= 9:
        return re.sub(r"\s+", "", cell)   # 국제전화 등은 원문 유지
    return ""


def fetch(url: str) -> str:
    """지수 백오프 재시도 + 전역 레이트리밋이 걸린 GET."""
    last_error: Exception | None = None
    for attempt in range(MAX_RETRY):
        with _rate_lock:
            wait = DELAY_SEC - (time.monotonic() - _last_request[0])
            if wait > 0:
                time.sleep(wait)
            _last_request[0] = time.monotonic()
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}
            )
            with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            last_error = exc
            if attempt < MAX_RETRY - 1:
                time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"요청 실패: {url} ({last_error})")


def cached_fetch(path: str, url: str, refresh: bool) -> str:
    if not refresh and os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    body = fetch(url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return body


def check_robots() -> bool:
    """크롤링 전에 robots.txt 를 직접 읽어 우리 경로가 허용되는지 확인한다.

    2026-08-21 현재 gb.go.kr 은 ``User-agent: * / Allow: /`` 이라 제약이 없다.
    다만 정책은 언제든 바뀔 수 있으므로 실행 시마다 확인한다. 금지로 바뀌면
    수집을 중단한다. 공공기관에 이관될 코드이므로 이 확인 자체가 신뢰 요소다.

    허용이면 True, 금지면 False. robots.txt 를 못 읽으면 경고 후 진행한다
    (파일이 없거나 응답하지 않는 것은 금지 의사 표시가 아니다).
    """
    try:
        body = fetch(ROBOTS_URL)
    except RuntimeError as exc:
        print(f"      경고: robots.txt 를 읽지 못했다 ({exc}). 확인 없이 진행한다.")
        return True

    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, "_robots.txt"), "w", encoding="utf-8") as handle:
        handle.write(body)

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.splitlines())

    targets = [
        LIST_URL,
        DETAIL_URL.format(dept_code="6470783", dept_code1="6470793"),
    ]
    blocked = [url for url in targets if not parser.can_fetch(USER_AGENT, url)]
    if blocked:
        print("      robots.txt 가 다음 경로의 수집을 금지한다:")
        for url in blocked:
            print(f"        - {url.split('?')[0]}")
        return False

    # Crawl-delay 가 지정돼 있으면 우리 기본 지연보다 우선한다.
    global DELAY_SEC
    delay = parser.crawl_delay(USER_AGENT)
    if delay and float(delay) > DELAY_SEC:
        DELAY_SEC = float(delay)
        print(f"      robots.txt 의 Crawl-delay {DELAY_SEC}s 를 따른다.")

    print("      허용됨 (User-agent 규칙상 수집 가능)")
    return True


# --------------------------------------------------------------------------
# 1단계: 부서 목록
# --------------------------------------------------------------------------

ANCHOR_RE = re.compile(
    r'<a\s[^>]*href="([^"]*mnu_uid=7332[^"]*dept_code=\d+[^"]*)"[^>]*>(.*?)</a>', re.S
)
SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S)


def parse_department_list(page: str) -> list[dict]:
    """조직도 페이지에서 (dept_code, dept_code1, 부서명) 목록을 뽑는다."""
    found: dict[tuple[str, str], str] = {}
    order: list[tuple[str, str]] = []

    for href, label in ANCHOR_RE.findall(page):
        href = html.unescape(href)
        code = re.search(r"[?&]dept_code=(\d+)", href)
        if not code:
            continue
        code1 = re.search(r"[?&]dept_code1=(\d*)", href)
        key = (code.group(1), code1.group(1) if code1 else "")

        # 대부분의 링크는 텍스트만 담고 있으나, 도지사 링크처럼 <span>으로
        # 감싼 뒤 하위 조직을 이어 붙인 경우가 있어 첫 span을 우선한다.
        body = COMMENT_RE.sub("", label)
        span = SPAN_RE.search(body)
        name = clean_text(span.group(1) if span else body)
        if not name:
            continue
        if key not in found:
            order.append(key)
        found.setdefault(key, name)

    return [
        {"dept_code": code, "dept_code1": code1, "name": found[(code, code1)]}
        for code, code1 in order
    ]


# --------------------------------------------------------------------------
# 2단계: 부서 상세
# --------------------------------------------------------------------------

WORK_RE = re.compile(r'<p\s[^>]*class="[^"]*silguk_work[^"]*"[^>]*>(.*?)</p>', re.S)
TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<(th|td)[^>]*>(.*?)</\1>", re.S)


def parse_duties(page: str) -> list[str]:
    """<p class="silguk_work"> 의 '1. 항목<br/>2. 항목' 을 배열로."""
    match = WORK_RE.search(page)
    if not match:
        return []
    duties = []
    for chunk in BR_RE.split(match.group(1)):
        item = clean_text(chunk)
        item = re.sub(r"^\d+\s*[.)]\s*", "", item)   # 앞의 "N. " 제거
        if item:
            duties.append(item)
    return duties


def parse_staff(page: str) -> list[dict]:
    """직원표를 파싱한다. 헤더 이름으로 컬럼을 찾으므로 순서 변경에 안전하다."""
    table = TABLE_RE.search(page)
    if not table:
        return []
    rows = ROW_RE.findall(table.group(1))
    if not rows:
        return []

    header: list[str] = []
    staff: list[dict] = []

    for row in rows:
        cells = CELL_RE.findall(row)
        if not cells:
            continue
        values = [clean_text(body) for _, body in cells]

        if not header:
            # 첫 행이 헤더(소속부서/직책/전화번호/담당업무)인지 확인
            if any("소속" in value for value in values):
                header = values
                continue
            header = ["소속부서", "직책", "전화번호", "담당업무"]

        def column(*keywords: str) -> str:
            for index, name in enumerate(header):
                if any(keyword in name for keyword in keywords) and index < len(values):
                    return values[index]
            return ""

        staff.append(
            {
                "unit": column("소속"),
                "position": column("직책", "직위", "직급"),
                "duty": column("담당업무", "업무"),
                "phone": normalize_phone(column("전화", "연락")),
            }
        )
    return staff


def scrape_department(entry: dict, refresh: bool) -> dict:
    url = DETAIL_URL.format(
        dept_code=entry["dept_code"], dept_code1=entry["dept_code1"]
    )
    cache_path = os.path.join(
        RAW_DIR, f"{entry['dept_code']}_{entry['dept_code1'] or 'none'}.html"
    )
    page = cached_fetch(cache_path, url, refresh)
    return {
        **entry,
        "source_url": url,
        "duties": parse_duties(page),
        "staff": parse_staff(page),
    }


# --------------------------------------------------------------------------
# 3단계: 조립 + 전화번호 마스킹
# --------------------------------------------------------------------------

def department_id(dept_code: str, dept_code1: str) -> str:
    return f"gb-{dept_code}-{dept_code1}" if dept_code1 else f"gb-{dept_code}"


def is_phone_like(candidate: str) -> bool:
    """담당업무 본문 속 문자열이 연락처인지 판단한다 (연도 범위 등은 제외)."""
    digits = DIGIT_RE.sub("", candidate)
    if not 9 <= len(digits) <= 15:
        return False
    return "-" in candidate or "+" in candidate or len(digits) >= 10


def build_dataset(scraped: list[dict]) -> tuple[dict, dict]:
    """공개 JSON과 전화번호 매핑을 만든다.

    토큰은 (dept_code, dept_code1, 행 순서) 정렬 기준으로 결정적으로 부여하므로
    재실행해도 같은 번호에 같은 토큰이 붙는다.
    """
    parents = {
        item["dept_code"]: item["name"]
        for item in scraped
        if not item["dept_code1"]
    }

    ordered = sorted(
        scraped, key=lambda item: (item["dept_code"], item["dept_code1"])
    )

    phone_map: dict[str, str] = {}
    token_of: dict[str, str] = {}

    departments = []
    for item in ordered:
        name = item["name"]
        parent = parents.get(item["dept_code"], "")
        if parent == name:
            parent = ""

        def tokenize(number: str) -> str:
            token = token_of.get(number)
            if token is None:
                token = f"PHONE_{len(phone_map) + 1:04d}"
                token_of[number] = token
                phone_map[token] = number
            return token

        staff = []
        for member in item["staff"]:
            token = tokenize(member["phone"]) if member["phone"] else ""

            # 담당업무 본문에 연락처가 직접 적힌 행이 있다. 공개 데이터셋에는
            # 번호를 남기지 않는다는 원칙(계약서 3절)에 따라 여기서도 토큰화한다.
            duty = member["duty"]
            for candidate in INLINE_PHONE_RE.findall(duty):
                if is_phone_like(candidate):
                    duty = duty.replace(candidate.strip(), tokenize(candidate.strip()))

            # 마지막 관문: 원문에 남은 내선번호("[행정☎ (소방) 880-XXXX]")를 떼어낸다.
            # 위 토큰화는 9자리 이상만 잡으므로 짧은 내선번호는 여기서 걸린다.
            # 번호만 제거하고 업무 문장은 원문 그대로 둔다(공공누리 제3유형 대응).
            staff.append(
                {
                    "position": member["position"],
                    "duty": scrub(duty),
                    "phone_token": token,
                }
            )

        departments.append(
            {
                "id": department_id(item["dept_code"], item["dept_code1"]),
                "name": name,
                "parent": parent,
                "full_name": f"{parent} {name}".strip(),
                "dept_code": item["dept_code"],
                "dept_code1": item["dept_code1"],
                "source_url": item["source_url"],
                "duties": [
                    scrubbed
                    for scrubbed in (scrub(d) for d in item["duties"])
                    if scrubbed
                ],
                "staff": staff,
            }
        )

    dataset = {
        "meta": {
            "source_url": SOURCE_URL,
            "org": "경상북도청 본청",
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "department_count": len(departments),
            "staff_count": sum(len(d["staff"]) for d in departments),
            "phone_masked": True,
            "license": LICENSE,
            "source_org": SOURCE_ORG,
            "attribution": ATTRIBUTION,
        },
        "departments": departments,
    }
    return dataset, phone_map


def write_outputs(dataset: dict, phone_map: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PRIVATE_DIR, exist_ok=True)

    json_path = os.path.join(DATA_DIR, "gb_departments.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(dataset, handle, ensure_ascii=False, indent=2)

    csv_path = os.path.join(DATA_DIR, "gb_departments.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "department_id", "full_name", "parent", "department",
                "dept_code", "dept_code1", "position", "duty",
                "phone_token", "source_url",
            ]
        )
        for dept in dataset["departments"]:
            for member in dept["staff"]:
                writer.writerow(
                    [
                        dept["id"], dept["full_name"], dept["parent"], dept["name"],
                        dept["dept_code"], dept["dept_code1"],
                        member["position"], member["duty"],
                        member["phone_token"], dept["source_url"],
                    ]
                )

    map_path = os.path.join(PRIVATE_DIR, "phone_map.json")
    with open(map_path, "w", encoding="utf-8") as handle:
        json.dump(phone_map, handle, ensure_ascii=False, indent=2)

    print(f"  {json_path}")
    print(f"  {csv_path}")
    print(f"  {map_path}  (공개 금지 · gitignore 대상)")


# --------------------------------------------------------------------------
# 실행
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="경상북도청 본청 부서 크롤러")
    parser.add_argument(
        "--refresh", action="store_true", help="HTML 캐시를 무시하고 다시 내려받는다"
    )
    args = parser.parse_args()

    print("[0/3] robots.txt 확인 …")
    if not check_robots():
        print(
            "\n중단: 경상북도청 robots.txt 가 이 경로의 수집을 금지하고 있다.\n"
            "정책이 변경된 것으로 보인다. 수집을 진행하지 않는다.\n"
            "docs/DATA_LICENSE.md 2절을 갱신하고 경상북도청에 문의해라.",
            file=sys.stderr,
        )
        return 2

    print("[1/3] 부서 목록 수집 …")
    list_page = cached_fetch(
        os.path.join(RAW_DIR, "_department_list.html"), LIST_URL, args.refresh
    )
    entries = parse_department_list(list_page)
    print(f"      부서 링크 {len(entries)}개")

    print(f"[2/3] 부서 상세 수집 … (워커 {WORKERS}, 요청 간 {DELAY_SEC}s)")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        scraped = list(
            pool.map(lambda entry: scrape_department(entry, args.refresh), entries)
        )

    print("[3/3] 데이터셋 생성 …")
    dataset, phone_map = build_dataset(scraped)
    write_outputs(dataset, phone_map)

    departments = dataset["departments"]
    staff_rows = dataset["meta"]["staff_count"]
    duty_total = sum(len(d["duties"]) for d in departments)
    empty_duty = sum(
        1 for d in departments for m in d["staff"] if not m["duty"]
    )
    leaked = sum(
        1
        for d in departments
        for text in list(d["duties"]) + [m["duty"] for m in d["staff"]]
        if contains_phone(text)
    )

    print()
    print("=== 검증 ===")
    print(f"부서 수          : {len(departments)}")
    print(f"직원 행 수       : {staff_rows}")
    print(f"사무분장 총 개수 : {duty_total}")
    print(f"전화토큰 수      : {len(phone_map)}")
    print(f"담당업무 빈 행   : {empty_duty}")
    print(f"본문 전화번호 잔존: {leaked}  (0이어야 한다)")

    sample = next(
        (d for d in departments if d["id"] == "gb-6470783-6470793"), None
    )
    if sample:
        with_phone = sum(1 for m in sample["staff"] if m["phone_token"])
        print(
            f"검증용 정책기획관 : 사무분장 {len(sample['duties'])}개 "
            f"/ 전화번호 있는 행 {with_phone}개 (기대값 29 / 31)"
        )

    if leaked:
        print(
            f"\n오류: 담당업무 본문에 전화번호가 {leaked}건 남아 있다. "
            "공개 데이터셋에 전화번호를 넣지 않는다는 계약서 3절 위반이므로 "
            "산출물을 배포하지 마라. voisso/routing/privacy.py 의 패턴을 확인해라.",
            file=sys.stderr,
        )
        return 3

    if len(departments) < MIN_DEPARTMENTS:
        print(
            f"\n오류: 부서 수가 {len(departments)}개로 기준({MIN_DEPARTMENTS})에 "
            "미달한다. 소스 페이지 구조가 바뀌었을 수 있다.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
