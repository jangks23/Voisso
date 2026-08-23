<p align="center">
  <img src="docs/images/logo.png" alt="Voisso" width="380">
</p>

<p align="center">
  <a href="https://github.com/jangks23/Voisso/actions/workflows/ci.yml"><img src="https://github.com/jangks23/Voisso/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
</p>

<p align="center">
  <b>경북 어르신이 사투리로 전화하면, AI가 알아듣고 담당 부서로 연결한다.</b>
</p>

<p align="center">
  프로젝트 소개는 <a href="ABOUT.md"><b>ABOUT.md</b></a> 를 보세요.
</p>

---

## 파이프라인

```
어르신                     Voisso                        담당 공무원
  │                          │                                │
  │  "물이 안 빠져가          │                                │
  │   큰일이라예"    ──────▶  ① 음성 인식 (Whisper)            │
  │                          │  ② 방언 정규화                  │
  │                          │     "안 빠져가" → "안 빠져서"    │
  │                          │        ↓                        │
  │                          │  ③ 대화로 정보 수집              │
  │  ◀────  "지금 어데        │     무엇 / 어디 / 언제 / 연락처  │
  │          계신가예?"       │        ↓                        │
  │                          │  ④ 부서 라우팅                   │
  │                          │     경상북도청 96개 부서          │
  │                          │     사무분장에서 검색             │
  │                          │        ↓                        │
  │                          │  ⑤ 긴급도 판정                   │
  │                          │     응급 / 중요 / 보통 / 낮음     │
  │                          │        ↓                        │
  │                          │  ⑥ 민원 카드  ────────────────▶ 실시간 도착
  │                          │     요약 · 배정 부서 · 배정 근거   │
  │                          │                                │
  │  ◀───────  담당자 직접 대화 (사투리로 전달)  ◀──────────────┤
  │                          │                                │
  │  ◀───────  진행 안내 콜백 (시스템이 먼저 연락)  ◀────────────┤
```

**배정 근거**는 AI가 지어낸 설명이 아니라, 경상북도청이 공개한 그 부서의 담당업무 문장을
그대로 가져온 것이다.

```
민원 #0175   ·   [중요]   ·   통화 1분 12초
────────────────────────────────────────────────
요약    안동시 옥동 주택가 도랑 막힘으로 장마철부터 배수 불량
배정    기후환경국 맑은물정책과
근거    "하수도 재난재해대책(호우, 태풍 등) 수립 및 시행"
신고자  010-****-5678
```

---

## 빠른 시작

**API 키 없이도 전 과정이 동작한다.** 음성 입출력만 꺼지고 나머지는 그대로다.

### 준비물

- **Python 3.10 이상** (`python3 --version`)
- 그게 전부다. Node.js, Docker, GPU 모두 필요 없다.

### 한 번에 실행

```bash
git clone https://github.com/jangks23/Voisso.git && cd Voisso
./scripts/demo.sh
```

데이터 수집 → 서버 기동 → 브라우저 열기까지 한 번에 처리한다.

### 단계별로

```bash
# 1. 가상환경
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 환경변수 (비워 두면 텍스트 모드로 동작한다)
cp .env.example .env

# 3. 경상북도청 부서 데이터 수집 (1~2분)
python3 scripts/scrape_gb_departments.py

# 4. 서버 기동
python3 -m server --port 8000
```

브라우저에서 열기:

| 주소 | 화면 |
|---|---|
| `http://127.0.0.1:8000/call/` | 민원인 통화 화면 |
| `http://127.0.0.1:8000/dashboard/` | 담당 공무원 대시보드 |
| `http://127.0.0.1:8000/demo/` | 좌우 분할 (시연용) |

### 동작 확인

```bash
./scripts/test.sh                  # 전체 자체 점검
python3 scripts/rehearsal.py       # 통화 시작부터 끝까지 자동 재현
```

라우팅만 따로 확인:

```bash
python3 -c "
from voisso.routing import route
r = route('비가 오면 집앞에 물이 안 빠져가 큰일이라예')
m = r['matches'][0]
print(m['full_name'], '|', m['evidence'][:40])
"
```

---

## 환경변수

`.env` 를 비워 두면 텍스트 모드로 동작한다. 키를 넣으면 해당 기능이 켜진다.

| 변수 | 용도 | 없으면 |
|---|---|---|
| `OPENAI_API_KEY` | 음성 인식(Whisper) · 대화 | 규칙 기반 대화, 텍스트 입력만 |
| `TYPECAST_API_KEY` | 음성 합성 | 텍스트로만 응답 |
| `VOISSO_STT_PROVIDER` | `openai` \| `none` | `none` |
| `VOISSO_TTS_PROVIDER` | `typecast` \| `none` | `none` |
| `VOISSO_TTS_TEMPO` | 말하기 속도 (0.5~2.0) | `0.85` |

전체 목록과 설명은 [`.env.example`](.env.example) 에 있다.

---

## MCP 서버

경상북도청 부서 정보를 **어떤 AI 에이전트든 질의할 수 있는 형태**로 제공한다.
Voisso 를 쓰지 않아도 이 부분만 따로 가져다 쓸 수 있다.

Claude Desktop 설정 (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "voisso": {
      "command": "/절대경로/Voisso/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "env": { "VOISSO_DATA_DIR": "/절대경로/Voisso/data" }
    }
  }
}
```

저장 후 Claude Desktop 을 완전히 종료했다가 다시 실행하면 사투리로 물어볼 수 있다.

> "우리 동네 하수구가 막혔는데 어데 전화하믄 되노?"

제공 도구: `find_department` · `get_department` · `list_departments` ·
`normalize_dialect` · `to_dialect` · `submit_complaint`

연결 검증:

```bash
python3 -m mcp_server.verify_connection
```

자세한 내용은 [`mcp_server/README.md`](mcp_server/README.md).

---

## 데이터

| 항목 | 값 |
|---|---|
| 출처 | 경상북도청 조직도 / 부서별 직원안내 |
| 주소 | https://www.gb.go.kr/Main/programs/organizationChart/organizationPartInfo.do |
| 규모 | 96개 부서 · 담당업무 1,866건 |
| 이용조건 | 공공누리 제3유형 (출처표시 + 변경금지) |

> **출처: 경상북도청** (https://www.gb.go.kr)

**데이터 파일은 저장소에 포함하지 않는다.** 대신 수집 스크립트를 제공한다.
이용조건 문제가 없고, 조직 개편이 있어도 항상 최신 조직도가 나온다.

```bash
python3 scripts/scrape_gb_departments.py            # 캐시 사용
python3 scripts/scrape_gb_departments.py --refresh  # 처음부터 다시
```

**전화번호는 공개 데이터에 넣지 않는다.** `PHONE_0042` 형태 토큰으로 치환하고
실제 매핑은 `data/private/` (gitignore) 에만 둔다. 담당업무 문장 속에 섞인 번호도 제거한다.
자세한 근거는 [`docs/DATA_LICENSE.md`](docs/DATA_LICENSE.md).

---

## 다른 지자체로 이식

공용 수집 계층(요청·robots·캐시·전화번호 살균·출력)은 그대로 재사용하고,
기관마다 **파서 어댑터 100~150줄**을 작성한다.
같은 CMS 를 쓰는 지자체끼리는 URL 교체만으로 이식된다.

안동시로 실증했다 — 91개 부서 / 담당업무 1,677건 수집.
안동시용 어댑터는 문경시에도 URL 교체만으로 통했다.

자세한 결과는 [`docs/PORTABILITY.md`](docs/PORTABILITY.md).

---

## 프로젝트 구조

```
voisso/          핵심 모듈
  routing/       부서 라우팅 (사무분장 검색 + 개념 사전)
  dialect/       방언 사전과 양방향 변환
  agent/         대화 오케스트레이션 · 긴급도 · 민원 카드
  voice/         음성 인식 / 합성 어댑터
server/          HTTP API (FastAPI)
mcp_server/      MCP 서버
web/             화면 (빌드 스텝 없는 HTML/CSS/JS)
  call/          민원인 통화 화면
  dashboard/     담당 공무원 대시보드
  demo/          좌우 분할 시연 화면
scripts/         데이터 수집 · 테스트 · 리허설
docs/            설계 계약 · 데이터 라이선스 · 검증 보고서
```

---

## 기여

이슈와 PR 을 환영한다. 다음 두 가지를 지켜 주세요.

- **전화번호·개인정보를 커밋하지 마세요.** 수집 데이터와 통화 기록은 gitignore 대상입니다.
- **새 의존성을 추가하면 README 를 같은 커밋에서 갱신하세요.**

작업 전에 [`docs/CONTRACT.md`](docs/CONTRACT.md) 의 모듈 계약을 읽어 주세요.

---

## 라이선스

소스코드는 **MIT** ([`LICENSE`](LICENSE)).

데이터에는 각각의 이용조건이 별도로 적용됩니다.

> **출처: 경상북도청** (https://www.gb.go.kr)
> 본 프로젝트는 경상북도청이 공개한 조직 및 담당업무 정보를 수집·재구성하여 이용합니다.
> 공공누리 제3유형(출처표시 + 변경금지) 조건을 따릅니다.

경상도 방언 참고: AI Hub (한국지능정보사회진흥원).
해당 데이터는 이용약관에 따라 본 저장소에 포함하지 않았습니다.
