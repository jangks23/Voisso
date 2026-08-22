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

    # ── 응급 민원 — 긴급도 판정과 라우팅이 충돌하면 안 된다 ──────────────
    #
    # 119 안내는 P6 의 긴급도 모듈이 한다. 라우팅은 그와 **별개로** 민원 자체를
    # 담당 부서로 보내야 한다. 단, 도청에 소관이 아예 없는 건은 억지 배정 대신
    # 제 기관으로 안내한다.
    {
        "id": "emg-gas",
        "text": "집에 가스 냄새가 나예",
        "expect": "external",
        "note": "도청 96개 부서에 가스 누출 소관이 없다. '가스'는 전부 온실가스·배출가스다. "
                "환경관리과 배출업소 점검으로 보내면 담당자가 가스 누출임을 놓친다",
        "tag": "응급",
    },
    {
        "id": "emg-wall",
        "text": "축대가 무너질 것 같습니더",
        "expect": ["자연재난과"],
        "note": "급경사지정비사업이 안전행정실 자연재난과 소관",
        "tag": "응급",
    },
    {
        "id": "emg-flood-now",
        "text": "물이 차올라예",
        "expect": ["맑은물정책과"],
        "note": "진행 중 침수. 119 안내와 별개로 배수 소관으로 가야 한다",
        "tag": "응급",
    },
    {
        "id": "emg-wall-normal",
        "text": "축대가 오래돼서 정비가 필요합니다",
        "expect": ["자연재난과"],
        "note": "응급이 아니어도 같은 부서 — 긴급도가 배정을 바꾸면 안 된다",
        "tag": "응급",
    },
    {
        "id": "emg-gas-mixed",
        "text": "가스 냄새도 나고 하수구도 막혔어요",
        "expect": ["맑은물정책과"],
        "note": "섞인 민원은 하수구를 배정하되 가스 안내(external_referral)를 함께 실어야 한다",
        "tag": "응급",
    },

    # ── 119 소관 응급 — 억지 배정 대신 119 안내 ────────────────────
    #
    # 실사용에서 나온 오배정이다.
    #   "안동시 옥동 주택 내 가스 냄새 발생" -> 안전행정실 사회재난과
    #        근거 "승강기 시설 및 사업자 관리, 승강기 안전관리 지도/점검…"
    #   "가스 냄새 및 인명 고립"             -> 기후환경국 환경관리과
    #        근거 "배출업소 통합지도점검계획 수립…"
    # 근거가 민원과 무관하다. 도청 사무분장에 화재·가스·붕괴·고립을 맡는 부서가
    # 없으므로 **부서를 배정하지 않고** 119 를 안내하는 것이 정답이다.
    # (접수 자체는 막지 않는다 — outcome 만 external_referral 이고 민원카드는 남는다.)
    {
        "id": "e119-gas-summary",
        "text": "안동시 옥동 주택 내 가스 냄새 발생",
        "expect": "external",
        "note": "실사용 오배정 #0178 — 승강기 관리 근거로 배정됐던 건",
        "tag": "119소관",
    },
    {
        "id": "e119-gas-trapped",
        "text": "가스 냄새 및 인명 고립",
        "expect": "external",
        "note": "실사용 오배정 #0145/0147/0151/0153/0155 — 배출업소 지도점검 근거",
        "tag": "119소관",
    },
    {
        "id": "e119-fire",
        "text": "주택 화재 발생 및 인명 대피",
        "expect": "external",
        "note": "'대피'가 storm_damage 를 깨워 자연재난과로 0.89 가던 건",
        "tag": "119소관",
    },
    {
        "id": "e119-collapse",
        "text": "건물 붕괴 위험으로 주민 대피",
        "expect": "external",
        "note": "'건물'의 물이 storm_damage 물 패턴에 걸리던 건",
        "tag": "119소관",
    },
    {
        "id": "e119-electric",
        "text": "전선 단선으로 감전 위험 발생",
        "expect": "external",
        "tag": "119소관",
    },
    {
        "id": "e119-sinkhole",
        "text": "도로 지반 함몰 발생",
        "expect": "external",
        "tag": "119소관",
    },
    # 활용형 구멍으로 놓쳤던 것들 (발표 전 최종 점검에서 발견)
    {
        "id": "e119-smoke-formal",
        "text": "옆집에서 연기가 납니다",
        "expect": "external",
        "note": "'납니다' 활용형이 빠져 no_match 였다",
        "tag": "119소관",
    },
    {
        "id": "e119-fire-past",
        "text": "불이 났어요",
        "expect": "external",
        "note": "'불이 났' 사이의 조사 '이' 때문에 안 걸렸다",
        "tag": "119소관",
    },
    {
        "id": "e119-tilt",
        "text": "건물이 기울었습니다",
        "expect": "external",
        "note": "붕괴 조짐에 '기울' 이 빠져 있었다",
        "tag": "119소관",
    },
    {
        "id": "e119-cannot-exit",
        "text": "못 나오고 있어요",
        "expect": "external",
        "note": "'나오' 활용형 누락",
        "tag": "119소관",
    },

    # ── 119 소관과 헷갈리면 안 되는 것들 (도청 소관이 맞다) ──────────────
    {
        "id": "e119-not-wall",
        "text": "축대가 무너질 것 같습니더",
        "expect": ["자연재난과"],
        "note": "축대·옹벽·비탈면은 도청 급경사지정비 소관. 건물 붕괴(119)와 구분돼야 한다",
        "tag": "119소관",
    },
    {
        "id": "e119-not-storm",
        "text": "태풍으로 침수돼 주민이 대피했습니다",
        "expect": ["자연재난과"],
        "note": "비·물 맥락이 있는 대피는 자연재난 소관이 맞다",
        "tag": "119소관",
    },
    {
        "id": "e119-not-drain",
        "text": "안동시 옥동 주택가 배수 불량, 장마철부터 반복",
        "expect": ["맑은물정책과"],
        "require_confident": True,
        "note": "민원카드 요약은 공문체다. '배수 불량' 같은 행정 문체도 잡아야 한다",
        "tag": "119소관",
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
        # 처음엔 농업 부서만 적었는데, 사무분장을 확인하니 '가뭄'을 문자 그대로
        # 명시한 곳은 안전행정실 자연재난과("재해영향평가, 한파, 가뭄")였다.
        # 농사용 물 부족은 농촌용수 소관과도 겹치므로 둘 다 정답으로 인정한다.
        "expect": ["스마트농업혁신과", "농업대전환과", "수자원관리과", "자연재난과"],
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


# ─────────────────────────────────────────── 일관성 쌍 (같은 성격 = 같은 부서)
#
# 실사용에서 #0074("물이 안 빠진다" -> 맑은물정책과)와
# #0075("집이 물에 잠겼어요" -> 자연재난과)가 갈렸다. 둘 다 주택 침수인데
# 배정이 달랐다. 일관성 없는 배정은 담당자 신뢰를 깎는다.
#
# 침수는 **원인**에 따라 소관이 갈리는 게 맞다. 그래서 세 갈래로 고정한다.
#   상시·반복 배수 불량 -> 하수도 (맑은물정책과)
#   태풍·호우 재난 피해 -> 자연재난과
#   원인 불명           -> 단정 금지, 후보 두 갈래를 함께
CONSISTENCY_GROUPS: list[dict[str, Any]] = [
    {
        "id": "flood-chronic",
        "label": "상시 배수 불량 (원인이 상시임이 드러난 문장)",
        "expect": ["맑은물정책과"],
        "require_confident": True,
        "texts": [
            "집 앞에 물이 안 빠지고 자꾸 고여서 큰일이에요",
            "집 앞에 물이 안 빠지고 자꾸 고여서 큰일이라예",
            "비만 오면 마당에 물이 고여서 못 살겠어요",
            "비만 오모 집 앞에 물이 안 빠지가 마당이 모두 잠기뿌니더",
            "장마철부터 집 앞에 물이 안 빠집니다",
            "상습 침수 구역이라 비만 오면 잠깁니다",
        ],
    },
    {
        "id": "drain-variants",
        "label": "같은 배수 민원의 표현 변형 (전부 같은 부서로 가야 한다)",
        "expect": ["맑은물정책과"],
        "require_confident": True,
        "texts": [
            "비만 오면 마당에 물이 찬다",
            "마당에 물이 찹니다",
            "집 앞에 물이 안 빠져요",
            "빗물이 안 내려가요",
            "지하실에 물이 차올라요",
            "골목에 물이 고여서 못 지나갑니다",
            "배수구가 막혔어요",
            "하수구가 막혀서 물이 넘칩니다",
            "도랑이 막혀서 물이 안 빠집니다",
            "소나기만 와도 마당이 잠겨요",
            # 아래 10개는 위 파라미터/패턴을 고친 **뒤에** 새로 만든 홀드아웃이다.
            "대문 앞에 물이 그득 차서 못 나갑니다",
            "맨홀에서 물이 역류합니다",
            "장마 때마다 반지하에 물이 들어옵니다",
            "우수관이 막힌 것 같아요",
            "길바닥에 물이 고여서 차가 못 다닙니다",
            "집 앞 도랑을 좀 쳐 주세요",
            "화장실 변기에서 물이 거꾸로 올라옵니다",
            "논밭에 물이 안 빠져서 벼가 썩습니다",
        ],
    },
    {
        "id": "water-supply-variants",
        "label": "상수도 민원의 표현 변형",
        "expect": ["맑은물정책과"],
        "require_confident": True,
        "texts": [
            "상수도가 터져서 물이 샙니다",
            "며칠째 수돗물이 안 나옵니다",
            "수도에서 녹물이 나와요",
            "물이 안 나와서 밥을 못 합니다",
            "수도관이 터졌어요",
        ],
    },
    {
        "id": "road-variants",
        "label": "도로 파손의 표현 변형",
        "expect": ["도로철도과"],
        "require_confident": True,
        "texts": [
            "도로가 파여서 차가 덜컹거려요",
            "길에 구멍이 났어요",
            "아스팔트가 깨져서 위험합니다",
            "포트홀 때문에 타이어가 터졌어요",
            "길이 울퉁불퉁해서 못 다닙니다",
        ],
    },
    {
        "id": "streetlight-variants",
        "label": "가로등 (시군 소관) 의 표현 변형",
        "expect": "referral",
        "texts": [
            "가로등이 안 들어와요",
            "밤에 골목이 캄캄해요",
            "보안등이 나갔습니다",
            "가로등 불이 깜빡거려요",
            "동네가 어두워서 무서워요",
        ],
    },
    {
        "id": "waste-variants",
        "label": "폐기물 무단투기·소각의 표현 변형",
        "expect": ["환경관리과"],
        "require_confident": True,
        "texts": [
            "쓰레기를 아무데나 버려요",
            "길가에 쓰레기가 쌓였습니다",
            "밤에 몰래 쓰레기를 버리고 갑니다",
            "폐기물 불법투기 신고합니다",
            "쓰레기 태우는 냄새가 납니다",
        ],
    },
    {
        "id": "farm-infra-variants",
        "label": "농업기반 시설의 표현 변형",
        "expect": ["스마트농업혁신과", "농업대전환과"],
        "require_confident": True,
        "texts": [
            "농로가 무너졌어요",
            "논둑이 터졌습니다",
            "밭에 가는 길이 유실됐어요",
            "수로가 막혀서 물이 안 갑니다",
            "저수지 둑이 위험해 보입니다",
        ],
    },
    {
        "id": "senior-variants",
        "label": "어르신 복지의 표현 변형",
        "expect": ["어르신복지과"],
        "require_confident": True,
        "texts": [
            "혼자 사시는 어르신이 걱정됩니다",
            "경로당 보일러가 고장났어요",
            "노인 일자리 알아보고 싶어요",
            "요양 서비스를 못 받고 있어요",
            "독거노인 돌봄이 필요합니다",
        ],
    },
    {
        "id": "livelihood-variants",
        # 기초생활보장·긴급복지는 어르신복지과가 아니라 사회복지과 소관이다.
        # 처음에 '복지'로 뭉쳐 놨다가 사무분장을 확인하고 그룹을 갈랐다.
        "label": "저소득 생계 지원의 표현 변형",
        "expect": ["사회복지과"],
        "require_confident": True,
        "texts": [
            "기초생활 신청하려면요",
            "생계가 어려워서 도움이 필요합니다",
            "긴급복지 지원을 받고 싶습니다",
            "먹고 살기가 너무 힘듭니다",
        ],
    },
    {
        "id": "bus-variants",
        "label": "버스 운행의 표현 변형",
        "expect": ["교통정책과"],
        "require_confident": True,
        "texts": [
            "버스가 하루에 두 번밖에 안 와요",
            "우리 마을에 버스가 안 들어옵니다",
            "버스 노선을 늘려주세요",
            "정류장에 지붕이 없어요",
            "막차가 너무 일찍 끊깁니다",
        ],
    },
    {
        "id": "wildlife-variants",
        "label": "야생동물 피해의 표현 변형",
        "expect": ["기후환경정책과"],
        "require_confident": True,
        "texts": [
            "멧돼지가 밭을 다 망쳐놨어요",
            "고라니가 농작물을 먹어치웁니다",
            "산돼지가 내려와서 무섭습니다",
            "들짐승 때문에 농사를 못 짓겠어요",
        ],
    },
    {
        "id": "flood-disaster",
        "label": "태풍·호우 재난 피해",
        "expect": ["자연재난과"],
        "require_confident": True,
        "texts": [
            "지난 호우로 마을이 침수됐습니다",
            "태풍 때문에 집이 물에 잠기고 세간이 다 떠내려갔어요",
            "집중호우로 침수 피해를 입었는데 지원을 받을 수 있나요",
        ],
    },
    {
        "id": "flood-unclear",
        "label": "원인 불명 침수 — 단정하면 안 된다",
        "expect": "ambiguous",
        "expect_both": ["맑은물정책과", "자연재난과"],
        "texts": [
            "집이 물에 잠겼어요",
            "물이 차서 집이 잠겼습니다",
            "주택 침수 발생",
        ],
    },
]


def consistency_cases() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in CONSISTENCY_GROUPS:
        for text in group["texts"]:
            case = {
                "id": f"{group['id']}::{text[:14]}",
                "text": text,
                "expect": group["expect"],
                "tag": f"일관성:{group['label'][:14]}",
                "note": group["label"],
            }
            if group.get("require_confident"):
                case["require_confident"] = True
            if group.get("expect_both"):
                case["expect_both"] = group["expect_both"]
            out.append(case)
    return out


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
    elif expect == "external":
        # 지자체 소관이 아니다. 부서를 배정하지 않고 제 기관으로 안내해야 한다.
        action = result.get("next_action", {})
        # 부서를 배정하지 않았고(무관한 근거가 붙을 수 없다), 다음 행동이 있어야 한다.
        ok = outcome == "external_referral" and not matches and bool(action.get("instruction"))
        if ok and "119" not in (action.get("instruction", "") + action.get("phone", "")):
            ok = False
        got = ("관할밖 안내" if outcome == "external_referral"
               else (f"{top['full_name']} ({top['score']:.2f})" if top else "매칭 0건"))
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
    elif expect == "ambiguous":
        # 단정하면 안 되고, 두 갈래가 후보에 다 보여야 한다.
        names = " ".join(m["full_name"] for m in matches)
        both = all(k in names for k in case.get("expect_both", []))
        ok = (not result["confident"]) and both
        got = f"{'후보제시' if not result['confident'] else '단독배정(실패)'} / " + (
            ", ".join(m["full_name"] for m in matches[:3]) or "매칭 0건"
        )
    else:
        ok = bool(top) and any(k in top["full_name"] for k in expect)
        got = f"{top['full_name']} ({top['score']:.2f})" if top else "매칭 0건"
        if ok and case.get("id") == "emg-gas-mixed" and not result.get("external_referral"):
            ok = False
            got += " (external_referral 누락 — 안전 안내가 빠졌다)"
        if ok and case.get("require_confident") and not result["confident"]:
            ok = False
            got += " (confident=False — 같은 성격 민원은 일관되게 단독 배정돼야 한다)"

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
    return CASES + consistency_cases() + load_demo_cases()


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
