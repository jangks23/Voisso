#!/usr/bin/env python3
"""안동시청 부서·직위·담당업무 크롤러 (타 지자체 이식 실증).

출처: 안동시 홈페이지 > 안동 소개 > 청사안내 > 조직안내 > 직원업무 검색
      https://www.andong.go.kr/portal/staff/list.do?mId=0308020200

이 파일이 존재하는 이유
----------------------
README/제출문의 "다른 지자체는 스크레이퍼의 URL 만 교체하면 이식된다"는 주장을
실제로 검증한 결과물이다. **결론부터 말하면 그 주장은 사실이 아니다.**
URL 상수만 바꿔 경상북도청 스크레이퍼를 돌리면 부서 0개가 나온다.
측정 결과와 근거는 docs/PORTABILITY.md 를 봐라.

그래서 이 스크립트는 안동시 전용 파서를 새로 쓰되, **공용 유틸은
scripts/scrape_gb_departments.py 에서 그대로 import 해 재사용한다.**
(fetch / cached_fetch / clean_text / normalize_phone / is_phone_like)
살균은 voisso/routing/privacy.scrub() 하나만 쓴다. 여기서 다시 만들지 않는다.

경상북도청과 무엇이 다른가 (요약)
--------------------------------
  경상북도청                          안동시
  목록 페이지 -> 부서 96개 상세 페이지   단일 평면 목록 168페이지 (부서 상세 없음)
  dept_code / dept_code1 쿼리          deptCode / mId 쿼리
  <p class="silguk_work"> 사무분장      부서 단위 사무분장 블록 없음
  페이지네이션 없음                     page=N 페이지네이션 (필수)
  헤더 "소속부서"                       헤더 "부서" (+ 주석 처리된 "이름" 컬럼)
  공공누리 제3유형 (변경금지)            공공누리 제1유형 (출처표시)

실행
    python3 scripts/scrape_andong_departments.py            # 캐시 사용
    python3 scripts/scrape_andong_departments.py --refresh  # 캐시 무시하고 재수집

산출물
    data/andong_departments.json     공개 데이터셋 (전화번호는 ADPHONE_0001 토큰)
    data/andong_departments.csv      부서·직위·담당업무·전화토큰 평면화
    data/private/andong_phone_map.json  토큰 -> 실제 전화번호 (gitignore 대상)
    data/raw/andong/*.html           원본 HTML 캐시

개인정보 처리: docs/CONTRACT.md 3절과 동일하게 적용한다.
원문에 담당자 실명 컬럼은 없다(HTML 상 주석 처리되어 렌더링되지 않는다).
전화번호는 공개 산출물에 넣지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import html
import http.client
import importlib.util
import json
import os
import re
import sys
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from voisso.routing.privacy import contains_phone, scrub
except ImportError as exc:                    # pragma: no cover
    raise SystemExit(
        f"voisso.routing.privacy 를 불러오지 못했다: {exc}\n"
        "전화번호 살균 없이 공개 데이터셋을 만들 수 없다. 저장소 루트에서 실행해라."
    )


def _load_gb_module():
    """경상북도청 스크레이퍼를 모듈로 불러와 공용 유틸을 재사용한다.

    파일명이 식별자로 쓰기 나쁘지 않지만(`scrape_gb_departments`), 이 스크립트가
    scripts/ 를 패키지로 만들지 않고도 돌아가야 하므로 경로 기반으로 로드한다.
    GB 모듈은 import 시 부작용이 없다(상수 정의뿐, main 은 __main__ 가드 안).
    """
    path = os.path.join(ROOT, "scripts", "scrape_gb_departments.py")
    spec = importlib.util.spec_from_file_location("voisso_scrape_gb", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_gb = _load_gb_module()

# 공용 유틸 재사용 — 여기서 다시 구현하지 않는다.
clean_text = _gb.clean_text
normalize_phone = _gb.normalize_phone
is_phone_like = _gb.is_phone_like
USER_AGENT = _gb.USER_AGENT
INLINE_PHONE_RE = _gb.INLINE_PHONE_RE


# --------------------------------------------------------------------------
# fetch 는 그대로 못 쓴다 — 이식 과정에서 발견한 실제 차이
# --------------------------------------------------------------------------
# 안동시는 응답을 chunked 로 내려주는데 간헐적으로 끊긴다.
#   http.client.IncompleteRead(679928 bytes read)   ← 실제로 겪음
# GB 쪽 fetch() 의 재시도는 (URLError, HTTPError, OSError) 만 잡는다.
# IncompleteRead 는 HTTPException 계열이라 그 그물에 안 걸리고 그대로 터진다.
# 게다가 더 위험한 경우가 있다: 끊긴 응답이 예외 없이 돌아오면 표 일부만 담긴
# HTML 을 정상으로 착각해 조용히 적은 행을 수집한다. 그래서 (1) 예외 그물을
# 넓히고 (2) 페이지가 끝까지 왔는지 표식으로 검증한 뒤에만 캐시에 쓴다.

PAGE_END_MARKER = "</html>"      # 문서 끝 표식. 여기까지 와야 완전한 페이지다.
                                 # (공공누리 블록 wrap_ccl 은 직원목록 페이지에만 있어 못 쓴다)


def fetch(url: str) -> str:
    """GB fetch() 에 IncompleteRead 재시도와 완전성 검증을 덧댄 버전."""
    last_error: Exception | None = None
    for attempt in range(_gb.MAX_RETRY + 2):
        try:
            body = _gb.fetch(url)
        except (RuntimeError, http.client.HTTPException) as exc:
            last_error = exc
        else:
            if url.endswith("robots.txt") or PAGE_END_MARKER in body:
                return body
            last_error = RuntimeError(
                f"응답이 도중에 끊겼다 ({len(body)} bytes, '{PAGE_END_MARKER}' 없음)"
            )
        if attempt < _gb.MAX_RETRY + 1:
            time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"요청 실패: {url} ({last_error})")


def cached_fetch(path: str, url: str, refresh: bool) -> str:
    """GB cached_fetch 와 같되 위의 검증된 fetch 를 쓴다."""
    if not refresh and os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
        if PAGE_END_MARKER in body:
            return body               # 잘린 캐시는 버리고 다시 받는다
    body = fetch(url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return body

# --------------------------------------------------------------------------
# 설정
# --------------------------------------------------------------------------

DATA_DIR = os.environ.get("VOISSO_DATA_DIR") or os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw", "andong")
PRIVATE_DIR = os.path.join(DATA_DIR, "private")

BASE = "https://www.andong.go.kr"
STAFF_URL = BASE + "/portal/staff/list.do?mId=0308020200&page={page}"
ORG_URL = BASE + "/portal/contents.do?mId=0308020100"
SOURCE_URL = BASE + "/portal/staff/list.do?mId=0308020200"
ROBOTS_URL = BASE + "/robots.txt"

WORKERS = 2                    # 안동시는 동시성 4에서 응답이 끊겼다. 2로 낮춘다.
DELAY_SEC = 0.3
MAX_PAGES = 400                # 폭주 방지 상한 (현재 실제 168페이지)

# 라이선스: 직원업무 검색 페이지 하단 wrap_ccl 블록에서 직접 확인했다.
#   <img src="/common/img/KOGL/new_img_opentype01.png" alt="출처표시 공공누리 …">
#   "본 공공저작물은 공공누리 "출처표시" 조건에 따라 이용할 수 있습니다."
# 경상북도청(제3유형·변경금지)과 달리 제1유형이라 가공·재배포 제약이 없다.
LICENSE = "공공누리 제1유형 (출처표시)"
SOURCE_ORG = "안동시"
ATTRIBUTION = "출처: 안동시 (https://www.andong.go.kr)"
MIN_DEPARTMENTS = 60           # 이보다 적으면 수집 실패로 간주
MIN_STAFF_ROWS = 1200

PAGE_INFO_RE = re.compile(r"전체 페이지\s*(\d+)")
# class 는 정확히 "bod_list" 가 아닐 수 있다. 문경시는 "bod_list staff" 를 쓴다.
# 같은 CMS 인데도 이 한 글자 차이로 파서가 조용히 0행을 반환한다.
TABLE_RE = re.compile(r'<table[^>]*class="[^"]*\bbod_list\b[^"]*"[^>]*>.*?</table>', re.S)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
# 본문 <td> 는 부서/직위/전화번호/업무 내용 4칸이다. 헤더 <th> 는 믿지 않는다 —
# 안동시는 '이름' th 를, 구미시는 '담당'·'이름' th 를 주석 처리해 두고 렌더링하지
# 않는다. 헤더 이름으로 컬럼을 찾으면 어긋난다.
EXPECTED_COLUMNS = 4
_anomalies: list[int] = []

ORG_LINK_RE = re.compile(r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>', re.S)
MAIN_DO_RE = re.compile(r"^/([a-z0-9]+(?:/[a-z0-9]+)?)/main\.do$")
STAFF_LINK_RE = re.compile(r"^/(.+?)/staff/(?:integration/)?list\.do")


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------

def check_robots() -> bool:
    """안동시 robots.txt 를 확인한다. GB 쪽과 같은 예의를 지킨다.

    2026-08-22 현재 안동시는 /sys*, /cmm/fms/*, */bbs/*, /saeol/, /search/* 를
    금지한다. 우리가 쓰는 /portal/staff/list.do 와 /portal/contents.do 는
    금지 목록에 없다. 정책이 바뀌면 수집을 중단한다.
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

    targets = [ORG_URL, STAFF_URL.format(page=1)]
    blocked = [url for url in targets if not parser.can_fetch(USER_AGENT, url)]
    if blocked:
        print("      robots.txt 가 다음 경로의 수집을 금지한다:")
        for url in blocked:
            print(f"        - {url.split('?')[0]}")
        return False

    delay = parser.crawl_delay(USER_AGENT)
    if delay and float(delay) > _gb.DELAY_SEC:
        _gb.DELAY_SEC = float(delay)   # fetch() 가 참조하는 전역을 갱신한다
        print(f"      robots.txt 의 Crawl-delay {_gb.DELAY_SEC}s 를 따른다.")

    print("      허용됨 (User-agent 규칙상 수집 가능)")
    return True


# --------------------------------------------------------------------------
# 1단계: 조직도에서 상위 조직(국/기관) 매핑을 만든다
# --------------------------------------------------------------------------

def parse_org_tree(page: str) -> dict[str, str]:
    """조직도 페이지에서 {부서명: 상위조직명} 을 만든다.

    안동시 조직도는 부서를 국/기관별 서브사이트 경로로 나눠 링크한다.
        /dept/city/main.do              -> 도시건설국
        /dept/city/staff/list.do?...    -> 건설과, 건축과, …
    즉 경로 앞부분이 상위 조직을 가리킨다. 이 규칙으로 계층을 복원한다.
    읍면동은 /csc/<이름>/main.do 로 붙어 있어 상위를 '읍면동'으로 둔다.
    """
    start = page.find("sub_body")
    end = page.find("wrap_ccl")
    body = page[start:end] if 0 <= start < end else page

    groups: dict[str, str] = {}
    members: list[tuple[str, str]] = []

    for href, label in ORG_LINK_RE.findall(body):
        href = html.unescape(href)
        name = clean_text(label)
        if not name:
            continue
        top = MAIN_DO_RE.match(href)
        if top:
            groups[top.group(1)] = name
            continue
        member = STAFF_LINK_RE.match(href)
        if member:
            members.append((member.group(1), name))

    parents: dict[str, str] = {}
    for segment, name in members:
        parent = groups.get(segment, "")
        if parent and parent != name:
            parents.setdefault(name, parent)

    # 읍면동: /csc/<slug>/main.do 로만 등장하고 staff 링크가 따로 없다.
    for segment, name in groups.items():
        if segment.startswith("csc/"):
            parents.setdefault(name, "읍면동")

    return parents


# --------------------------------------------------------------------------
# 2단계: 평면 직원 목록 168페이지
# --------------------------------------------------------------------------

def parse_total_pages(page: str) -> int:
    match = PAGE_INFO_RE.search(page)
    return int(match.group(1)) if match else 1


def parse_staff_rows(page: str) -> list[dict]:
    """직원 목록 표 한 페이지를 파싱한다.

    경상북도청 파서를 쓰지 못하는 이유가 여기 있다. 안동시 표의 헤더는
    '소속부서'가 아니라 '부서'이고, '이름' <th> 가 HTML 주석으로 남아 있어
    헤더 5칸 / 본문 4칸으로 어긋난다. 헤더 이름 기반 매핑이 통하지 않는다.
    본문 <td> 만 읽고 위치로 해석한다 (부서/직위/전화번호/업무 내용).
    """
    table = TABLE_RE.search(page)
    if not table:
        return []

    rows: list[dict] = []
    for row in ROW_RE.findall(table.group(0)):
        cells = [clean_text(cell) for cell in TD_RE.findall(row)]
        if len(cells) < EXPECTED_COLUMNS:
            continue                       # 헤더행(<th>)과 '자료 없음' 행을 건너뛴다
        if len(cells) > EXPECTED_COLUMNS:
            # 위치 기반 파싱이라 컬럼이 하나만 늘어도 전화번호 자리에 업무가 들어간다.
            # 조용히 앞 4칸을 잘라 쓰면 틀린 데이터를 정상인 척 내보내게 된다.
            # 세어 두었다가 실행 끝에 드러낸다. (이식 중 실제로 만난 함정이다)
            _anomalies.append(len(cells))
            continue
        department, position, phone, duty = cells
        if not department:
            continue
        rows.append(
            {
                "department": department,
                "position": position,
                "phone": normalize_phone(phone),
                "duty": duty,
            }
        )
    return rows


def scrape_page(page_no: int, refresh: bool) -> list[dict]:
    url = STAFF_URL.format(page=page_no)
    cache_path = os.path.join(RAW_DIR, f"staff_{page_no:04d}.html")
    return parse_staff_rows(cached_fetch(cache_path, url, refresh))


# --------------------------------------------------------------------------
# 3단계: 조립 + 전화번호 마스킹
# --------------------------------------------------------------------------

def slug(name: str) -> str:
    """부서명을 안정적인 id 조각으로 바꾼다 (deptCode 가 없는 부서가 많다)."""
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", name)


def build_dataset(rows: list[dict], parents: dict[str, str]) -> tuple[dict, dict]:
    """공개 JSON과 전화번호 매핑을 만든다.

    토큰은 (부서명, 등장 순서) 기준으로 결정적으로 부여하므로 재실행해도
    같은 번호에 같은 토큰이 붙는다. 가짜 번호를 만들지 않는다(계약서 3절).
    """
    phone_map: dict[str, str] = {}
    token_of: dict[str, str] = {}

    def tokenize(number: str) -> str:
        token = token_of.get(number)
        if token is None:
            token = f"ADPHONE_{len(phone_map) + 1:04d}"
            token_of[number] = token
            phone_map[token] = number
        return token

    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        if row["department"] not in grouped:
            order.append(row["department"])
        grouped.setdefault(row["department"], []).append(row)

    departments = []
    for name in sorted(order):
        parent = parents.get(name, "")
        staff = []
        for row in grouped[name]:
            token = tokenize(row["phone"]) if row["phone"] else ""

            # 업무 내용 본문에 연락처가 직접 적힌 행이 있다. 공개 데이터셋에는
            # 번호를 남기지 않는다는 원칙(계약서 3절)에 따라 토큰화한다.
            duty = row["duty"]
            for candidate in INLINE_PHONE_RE.findall(duty):
                if is_phone_like(candidate):
                    duty = duty.replace(candidate.strip(), tokenize(candidate.strip()))

            # 마지막 관문: 짧은 내선번호("880-XXXX")를 떼어낸다.
            # 경북도청 소방본부에서 실제로 겪은 사고라 안동에도 같은 방어를 건다.
            staff.append(
                {
                    "position": row["position"],
                    "duty": scrub(duty),
                    "phone_token": token,
                }
            )

        departments.append(
            {
                "id": f"ad-{slug(name)}",
                "name": name,
                "parent": parent,
                "full_name": f"{parent} {name}".strip(),
                "dept_code": "",
                "dept_code1": "",
                "source_url": SOURCE_URL,
                "duties": [],   # 안동시에는 부서 단위 사무분장 블록이 없다
                "staff": staff,
            }
        )

    dataset = {
        "meta": {
            "source_url": SOURCE_URL,
            "org": "안동시청",
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

    json_path = os.path.join(DATA_DIR, "andong_departments.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(dataset, handle, ensure_ascii=False, indent=2)

    csv_path = os.path.join(DATA_DIR, "andong_departments.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "department_id", "full_name", "parent", "department",
                "position", "duty", "phone_token", "source_url",
            ]
        )
        for dept in dataset["departments"]:
            for member in dept["staff"]:
                writer.writerow(
                    [
                        dept["id"], dept["full_name"], dept["parent"], dept["name"],
                        member["position"], member["duty"],
                        member["phone_token"], dept["source_url"],
                    ]
                )

    map_path = os.path.join(PRIVATE_DIR, "andong_phone_map.json")
    with open(map_path, "w", encoding="utf-8") as handle:
        json.dump(phone_map, handle, ensure_ascii=False, indent=2)

    print(f"  {json_path}")
    print(f"  {csv_path}")
    print(f"  {map_path}  (공개 금지 · gitignore 대상)")


# --------------------------------------------------------------------------
# 실행
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="안동시청 부서·담당업무 크롤러")
    parser.add_argument(
        "--refresh", action="store_true", help="HTML 캐시를 무시하고 다시 내려받는다"
    )
    args = parser.parse_args()

    print("[0/4] robots.txt 확인 …")
    if not check_robots():
        print(
            "\n중단: 안동시 robots.txt 가 이 경로의 수집을 금지하고 있다.\n"
            "정책이 변경된 것으로 보인다. 수집을 진행하지 않는다.\n"
            "docs/PORTABILITY.md 와 docs/DATA_LICENSE.md 를 갱신해라.",
            file=sys.stderr,
        )
        return 2

    print("[1/4] 조직도에서 상위 조직 매핑 …")
    org_page = cached_fetch(
        os.path.join(RAW_DIR, "_orgchart.html"), ORG_URL, args.refresh
    )
    parents = parse_org_tree(org_page)
    print(f"      상위 조직이 확인된 부서 {len(parents)}개")

    print("[2/4] 직원 목록 1페이지 …")
    first = cached_fetch(
        os.path.join(RAW_DIR, "staff_0001.html"), STAFF_URL.format(page=1), args.refresh
    )
    total_pages = min(parse_total_pages(first), MAX_PAGES)
    print(f"      전체 {total_pages}페이지")

    print(f"[3/4] 나머지 페이지 수집 … (워커 {WORKERS}, 요청 간 {_gb.DELAY_SEC}s)")
    rows = parse_staff_rows(first)
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for chunk in pool.map(
                lambda n: scrape_page(n, args.refresh), range(2, total_pages + 1)
            ):
                rows.extend(chunk)
    print(f"      직원 행 {len(rows)}개")

    print("[4/4] 데이터셋 생성 …")
    dataset, phone_map = build_dataset(rows, parents)
    write_outputs(dataset, phone_map)

    departments = dataset["departments"]
    leaked = sum(
        1
        for d in departments
        for text in [m["duty"] for m in d["staff"]]
        if contains_phone(text)
    )
    empty_duty = sum(1 for d in departments for m in d["staff"] if not m["duty"])
    # 상위조직이 빈 부서 중 상당수는 그 자체가 최상위 조직(국·실·사업소)이라
    # 비어 있는 게 정상이다. 다른 부서의 parent 로 등장하는 이름을 최상위로 보고,
    # 그렇지 않은 것만 '미분류'로 센다. 숫자를 부풀리지 않기 위한 구분이다.
    top_level = {d["parent"] for d in departments if d["parent"]}
    unclassified = [
        d["name"] for d in departments
        if not d["parent"] and d["name"] not in top_level
    ]

    print()
    print("=== 검증 ===")
    print(f"부서 수          : {len(departments)}")
    print(f"직원 행 수       : {dataset['meta']['staff_count']}")
    print(f"전화토큰 수      : {len(phone_map)}")
    print(f"담당업무 빈 행   : {empty_duty}")
    print(f"최상위 조직     : {len(top_level)}")
    print(f"상위조직 미분류  : {len(unclassified)}  {unclassified if unclassified else ''}")
    print(f"본문 전화번호 잔존: {leaked}  (0이어야 한다)")
    if _anomalies:
        print(
            f"컬럼수 이상 행    : {len(_anomalies)}건 "
            f"(기대 {EXPECTED_COLUMNS}칸, 실제 {sorted(set(_anomalies))}) — 건너뜀"
        )

    if leaked:
        print(
            f"\n오류: 담당업무 본문에 전화번호가 {leaked}건 남아 있다. "
            "공개 데이터셋에 전화번호를 넣지 않는다는 계약서 3절 위반이므로 "
            "산출물을 배포하지 마라. voisso/routing/privacy.py 의 패턴을 확인해라.",
            file=sys.stderr,
        )
        return 3

    if len(departments) < MIN_DEPARTMENTS or len(rows) < MIN_STAFF_ROWS:
        print(
            f"\n오류: 수집량이 기준(부서 {MIN_DEPARTMENTS} / 행 {MIN_STAFF_ROWS})에 "
            "미달한다. 소스 페이지 구조가 바뀌었을 수 있다.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
