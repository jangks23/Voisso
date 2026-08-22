"""라우팅 회귀 테스트 — 문장과 기대 결과를 표로 두고 통과율을 출력한다.

    python3 -m mcp_server.regression            # 통과율 요약
    python3 -m mcp_server.regression -v         # 실패 케이스 상세
    python3 -m mcp_server.regression --all      # 전 케이스 상세
    python3 -m mcp_server.regression --json     # 기계 판독용

케이스 출처
    1. 실제 음성 왕복 테스트에서 나온 실측 문장 (voice/STT 팀 보고)
    2. P5 의 voisso/dialect/demo_lines.md 기계 판독용 JSON
       (사투리 원문 / STT 예측 / 정규화 결과 3가지 입력을 각각 채점한다)
    3. 도청 소관이 아닌 질의 — "모르겠다"고 말해야 정답인 것들

기대 결과의 종류
    dept      : 이 부서(부분 문자열) 중 하나가 1순위여야 한다
    referral  : 도청 소관이 아니다. 시군 민원실 안내가 정답
    no_match  : 어떤 부서도 배정하면 안 된다

**억지 배정은 실패로 친다.** 정답이 없는 질의에 부서를 배정하면 감점이다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from voisso import routing

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_LINES = REPO_ROOT / "voisso" / "dialect" / "demo_lines.md"


# ---------------------------------------------------------------- 케이스 표
#
# expect 는 사람이 판단해 적은 값이다. 근거를 note 에 남긴다.

CASES: list[dict[str, Any]] = [
    # ── 실제 음성 왕복 테스트 실측 (구어체, 행정 용어 없음) ──────────────
    {
        "id": "voice-drain-symptom",
        "text": "집 앞에 물이 안 빠지고 자꾸 고여서 큰일이에요",
        "expect": ["맑은물정책과", "환경관리과", "수자원관리과"],
        "note": "어르신은 '하수구'라고 안 한다. 증상만 말한다. 배수/하수 소관으로 가야 한다",
        "tag": "실측",
    },
    {
        "id": "voice-farmroad",
        "text": "농로가 무너져서 트랙터가 못 지나간다고 하이",
        "expect": ["스마트농업혁신과", "농업대전환과", "자연재난과"],
        "note": "문장 끝 '하이'(카이)가 '하이테크'와 겹치면 안 된다",
        "tag": "실측",
    },
    {
        "id": "voice-streetlight",
        "text": "우리 동네 가로등이 며칠째 안 들어오는데 우째해야 되니?",
        "expect": "referral",
        "note": "가로등·보안등은 도청 사무분장에 0건. 시군 소관이다",
        "tag": "실측",
    },
    {
        "id": "voice-streetlight-2",
        "text": "우리 동네 가로등이 며칠째 안 들어와요",
        "expect": "referral",
        "note": "위와 같은 건, 어미만 다름",
        "tag": "실측",
    },

    # ── 구어체 증상 표현 (개념 사전이 다리를 놔야 하는 것들) ──────────────
    {
        "id": "sym-drain-pool",
        "text": "비만 오면 마당에 물이 고여서 못 살겠어요",
        "expect": ["맑은물정책과", "자연재난과", "수자원관리과"],
        "tag": "구어체",
    },
    {
        "id": "sym-drain-backflow",
        "text": "화장실에서 물이 역류해서 올라옵니다",
        "expect": ["맑은물정책과"],
        "tag": "구어체",
    },
    {
        "id": "sym-water-none",
        "text": "며칠째 수돗물이 안 나옵니다",
        "expect": ["맑은물정책과"],
        "tag": "구어체",
    },
    {
        "id": "sym-water-rust",
        "text": "수도에서 녹물이 나와요",
        "expect": ["맑은물정책과"],
        "tag": "구어체",
    },
    {
        "id": "sym-trash-dump",
        "text": "밤에 누가 길가에 쓰레기를 몰래 버리고 갑니다",
        "expect": ["환경관리과"],
        "tag": "구어체",
    },
    {
        "id": "sym-boar",
        "text": "멧돼지가 밭에 내려와서 농작물을 다 망쳐놨어요",
        "expect": ["기후환경정책과", "스마트농업혁신과", "농업대전환과"],
        "tag": "구어체",
    },
    {
        "id": "sym-bus",
        "text": "우리 마을에 버스가 하루에 두 번밖에 안 옵니다",
        "expect": ["교통정책과"],
        "tag": "구어체",
    },
    {
        "id": "sym-wildfire",
        "text": "산에 낙엽이 많이 쌓여서 불나면 어쩌나 걱정입니다",
        "expect": ["산림정책과", "산불피해재창조사업단"],
        "tag": "구어체",
    },

    # ── 도청 소관이 아니거나 존재하지 않는 것 ─────────────────────────
    {
        "id": "oos-glacier",
        "text": "빙하 탐사선 견인은 누가 담당하노?",
        "expect": "no_match",
        "note": "도청과 무관. 억지 배정하면 실패",
        "tag": "범위밖",
    },
    {
        "id": "oos-mars",
        "text": "화성 이주 신청은 어디서 하노?",
        "expect": "no_match",
        "tag": "범위밖",
    },
    {
        "id": "oos-resident-cert",
        "text": "주민등록등본 떼려면 어디로 가야 되나요?",
        "expect": "referral",
        "note": "주민등록 사무는 시군·읍면동 소관",
        "tag": "범위밖",
    },
    {
        "id": "oos-trash-bag",
        "text": "종량제 봉투는 어디서 사나요?",
        "expect": "referral",
        "note": "생활폐기물 수거·종량제 운영은 시군 소관",
        "tag": "범위밖",
    },
    {
        "id": "oos-parking",
        "text": "불법 주차 단속 좀 해주세요",
        "expect": "referral",
        "note": "주차 단속은 시군 소관",
        "tag": "범위밖",
    },
    {
        "id": "oos-stray-dog",
        "text": "유기견이 돌아다녀서 무섭습니다",
        "expect": "referral",
        "note": "유기동물 구조·보호는 시군 소관",
        "tag": "범위밖",
    },

    {
        "id": "oos-streetlight-andong",
        "text": "안동시 옥동인데 가로등이 며칠째 안 들어와요",
        "expect": "referral",
        "expect_region": "안동시",
        "note": "시군이 문장에 있으면 '안동시청 민원실'까지 짚어야 다음 행동이 된다",
        "tag": "범위밖",
    },
    {
        "id": "oos-streetlight-noregion",
        "text": "우리 동네 가로등이 며칠째 안 들어와요",
        "expect": "referral",
        "expect_region": "",
        "note": "시군을 모르면 먼저 확인하라고 안내해야 한다",
        "tag": "범위밖",
    },
    {
        "id": "oos-trashbag-ulleung",
        "text": "울릉도 사는데 종량제 봉투는 어디서 사나요?",
        "expect": "referral",
        "expect_region": "울릉군",
        "note": "울릉도 -> 울릉군",
        "tag": "범위밖",
    },

    # ── 홀드아웃 (파라미터 튜닝 후에 추가한 문장들) ────────────────────
    {
        "id": "hold-senior-center",
        "text": "보일러가 고장나서 경로당이 추워요",
        "expect": ["어르신복지과", "통합돌봄과"],
        "tag": "홀드아웃",
    },
    {
        "id": "hold-landslide",
        "text": "장마철에 축대가 무너질까 걱정입니다",
        "expect": ["자연재난과", "산림", "안전"],
        "tag": "홀드아웃",
    },
    {
        "id": "hold-childcare",
        "text": "우리 아이 어린이집 보조금 문의합니다",
        "expect": ["아이돌봄과", "보육", "여성가족"],
        "tag": "홀드아웃",
    },
    {
        "id": "hold-drought",
        "text": "농사지을 물이 없어서 논이 다 말라갑니다",
        "expect": ["스마트농업혁신과", "농업대전환과", "수자원관리과"],
        "tag": "홀드아웃",
    },
    {
        "id": "hold-tax",
        "text": "지방세 고지서가 잘못 나온 것 같은데예",
        "expect": ["세정담당관"],
        "tag": "홀드아웃",
    },
    {
        "id": "hold-odor",
        "text": "공장에서 나는 악취 때문에 못 살겠습니다",
        "expect": ["환경관리과", "기후환경정책과"],
        "tag": "홀드아웃",
    },
    {
        "id": "hold-return-farm",
        "text": "귀농하려는데 지원 사업이 있나요",
        "expect": ["농업대전환과", "농업유통과", "스마트농업혁신과"],
        "tag": "홀드아웃",
    },
    {
        "id": "hold-traffic-light",
        "text": "동네 신호등이 고장났어요",
        "expect": ["교통정책과"],
        "note": "도·시군 공동 소관. 배정하되 관할 안내 문구가 붙어야 한다",
        "tag": "홀드아웃",
    },
]


# ------------------------------------------------ P5 demo_lines.md 케이스

# demo_lines 각 시나리오의 기대 부서 (사람 판단). label 로 매칭한다.
DEMO_EXPECT: dict[str, Any] = {
    "하수구 막힘": ["맑은물정책과"],
    "상수도 누수": ["맑은물정책과"],
    "농로 유실": ["스마트농업혁신과", "농업대전환과", "자연재난과"],
    "버스 배차": ["교통정책과"],
    "경로당 지원": ["어르신복지과", "통합돌봄과"],
    "산불 예방": ["산림정책과", "산불피해재창조사업단"],
    "폐기물 무단투기": ["환경관리과"],
    "독거노인 돌봄": ["어르신복지과", "통합돌봄과"],
    "멧돼지 피해": ["기후환경정책과", "스마트농업혁신과", "농업대전환과"],
    "노인 일자리": ["어르신복지과", "경제정책노동과"],
}

# demo_lines 는 한 시나리오에 입력이 3가지다. 각각 따로 채점한다.
DEMO_VARIANTS = [
    ("dialect", "사투리 원문"),
    ("stt_predicted", "STT 예측"),
    ("normalized", "정규화 후"),
]


def load_demo_cases() -> list[dict[str, Any]]:
    """demo_lines.md 의 기계 판독용 JSON 블록에서 케이스를 뽑는다."""
    if not DEMO_LINES.is_file():
        return []
    text = DEMO_LINES.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\s*(\[.*?\])\s*```", text, re.S)
    if not blocks:
        return []
    try:
        entries = json.loads(blocks[-1])
    except json.JSONDecodeError:
        return []

    cases: list[dict[str, Any]] = []
    for entry in entries:
        label = entry.get("label", "")
        expect = DEMO_EXPECT.get(label)
        if expect is None:
            continue
        for key, korean in DEMO_VARIANTS:
            value = (entry.get(key) or "").strip()
            if not value:
                continue
            cases.append(
                {
                    "id": f"demo-{label}-{key}",
                    "text": value,
                    "expect": expect,
                    "tag": f"P5:{korean}",
                    "note": label,
                }
            )
    return cases


# ------------------------------------------------------------------ 채점

def judge(case: dict[str, Any]) -> dict[str, Any]:
    result = routing.route(case["text"], top_k=3)
    matches = result["matches"]
    top = matches[0] if matches else None
    outcome = result.get("outcome", "department" if matches else "no_match")
    expect = case["expect"]

    if expect == "no_match":
        ok = not matches and outcome != "municipal_referral"
        got = "매칭 0건" if not matches else f"{top['full_name']} ({top['score']:.2f})"
    elif expect == "referral":
        # 시군 안내이거나, 최소한 틀린 부서를 1순위로 올리지 않아야 한다
        ok = outcome == "municipal_referral" or not matches
        action = result.get("next_action", {})
        got = (
            "시군 안내"
            if outcome == "municipal_referral"
            else ("매칭 0건" if not matches else f"{top['full_name']} ({top['score']:.2f})")
        )
        if ok and outcome == "municipal_referral":
            # 안내만으로는 부족하다. "다음 행동"이 실제로 담겨야 한다.
            if not action.get("instruction"):
                ok, got = False, "안내 문구 없음"
            elif case.get("expect_region") is not None:
                if action.get("region") != case["expect_region"]:
                    ok = False
                got += f" / 시군={action.get('region') or '미확인'}"
            else:
                got += f" / {action.get('type')}"
    else:
        ok = bool(top) and any(k in top["full_name"] for k in expect)
        got = f"{top['full_name']} ({top['score']:.2f})" if top else "매칭 0건"

    return {
        "id": case["id"],
        "tag": case["tag"],
        "text": case["text"],
        "expect": expect if isinstance(expect, str) else " | ".join(expect),
        "got": got,
        "ok": ok,
        "confident": result["confident"],
        "outcome": outcome,
        "evidence": top["evidence"] if top else "",
        "note": case.get("note", ""),
    }


def needs_real_data(case: dict[str, Any]) -> bool:
    """수집된 실데이터가 있어야 채점 가능한 케이스인가.

    ``referral`` 만 데이터에 독립이다 — 개념 사전의 관할 판단으로 결정되고
    점수를 보지 않기 때문이다. 부서명 기대값은 물론이고 ``no_match`` 도
    코퍼스 크기에 좌우된다(9개 부서짜리 합성 샘플에서는 "신청" 하나로도
    후보가 뜬다). 그래서 실데이터에서만 채점한다.
    """
    return case["expect"] != "referral"


def all_cases() -> list[dict[str, Any]]:
    return CASES + load_demo_cases()


def run(dataset: str = "real") -> tuple[int, int, list[dict[str, Any]]]:
    """(통과, 전체, 행) — selftest 가 이 함수로 회귀를 끌어다 쓴다.

    dataset="sample" 이면 데이터셋에 의존하지 않는 케이스만 채점한다.
    """
    cases = all_cases()
    if dataset != "real":
        cases = [c for c in cases if not needs_real_data(c)]
    rows = [judge(c) for c in cases]
    return sum(1 for r in rows if r["ok"]), len(rows), rows


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in argv or "--verbose" in argv
    show_all = "--all" in argv
    as_json = "--json" in argv

    dataset = "sample" if routing.is_sample() else "real"
    _passed, _total, rows = run(dataset)

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0 if all(r["ok"] for r in rows) else 1

    print("라우팅 회귀 테스트")
    print(f"  데이터 : {routing.data_source()}")
    if dataset == "sample":
        print("  주의   : 합성 샘플로 동작 중 — 부서명 기대값 케이스는 제외했다")
    print(f"  케이스 : {len(rows)}건")

    by_tag: dict[str, list[dict]] = {}
    for row in rows:
        by_tag.setdefault(row["tag"], []).append(row)

    print()
    for tag, group in by_tag.items():
        passed = sum(1 for r in group if r["ok"])
        print(f"── {tag:<14} {passed}/{len(group)}")
        for r in group:
            if r["ok"] and not show_all:
                continue
            mark = "ok  " if r["ok"] else "FAIL"
            print(f"   {mark} {r['text'][:44]}")
            print(f"        기대: {r['expect']}")
            print(f"        실제: {r['got']}  (confident={r['confident']}, outcome={r['outcome']})")
            if (verbose or show_all) and r["evidence"]:
                print(f"        근거: {r['evidence'][:70]}")
            if (verbose or show_all) and r["note"]:
                print(f"        메모: {r['note']}")

    total = len(rows)
    passed = sum(1 for r in rows if r["ok"])
    rate = passed / total * 100 if total else 0.0
    print("\n" + "=" * 64)
    print(f"통과율: {passed}/{total} = {rate:.1f}%")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
