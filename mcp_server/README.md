# Voisso MCP 서버 — 경상북도청 사무분장 검색

경상북도청 본청 **96개 부서 / 직원 1,866명의 직위·담당업무**를 AI 에이전트가
질의할 수 있는 MCP 툴로 노출한다.

같은 자료가 [경북도청 조직도](https://www.gb.go.kr/Main/programs/organizationChart/organizationPartInfo.do)에
공개돼 있지만 **사람이 눈으로 읽는 HTML 표**로만 존재한다. 부서를 하나씩 눌러
담당업무를 훑어야 "내 민원을 어디로 보내야 하는지"를 알 수 있다. 이 서버는 그
자료를 기계가 질의 가능한 형태로 바꾼다.

핵심은 **evidence** 다. 모든 라우팅 결과에는 배정 근거가 된 담당업무 원문이
그대로 붙는다. 담당자가 "AI가 왜 나한테 보냈나"를 근거 문장 하나로 확인할 수 있다.

```
질의:  "집 앞 하수구가 막혀서 물이 안 빠진다"
1위:   기후환경국 맑은물정책과 / 주무관  (0.637)
근거:  ◦ 하수도분야 국도비 보조사업 예산 및 추진 ◦ 하수도사업 재원협의 및
       총사업비변경 관련 업무 ◦ 하수도 재난재해대책(호우, 태풍 등) 수립 및 시행 …
```

> 시연용 질의 세트와 대본은 **[DEMO.md](./DEMO.md)** 에 있다.

---

## 빠른 시작

### 0. 데이터 수집 (최초 1회, 필수)

**부서 데이터는 저장소에 들어 있지 않다.** 경상북도청 조직도 파생 데이터는
재배포 라이선스 리스크 때문에 커밋하지 않는다. 클론 직후 한 번 수집해야 한다.

```bash
python3 scripts/scrape_gb_departments.py     # → data/gb_departments.json
```

수집 전에 서버를 띄우면 조용히 빈 결과를 주는 대신 무엇을 해야 하는지 알려준다.

```
$ python3 -m mcp_server --check
경상북도청 부서 데이터가 없습니다. 먼저 크롤러를 실행하세요:

    python3 scripts/scrape_gb_departments.py

탐색한 경로:
    - data/gb_departments.json
...
```

MCP 툴을 호출해도 마찬가지로 `{"error": "data_unavailable", "next_step": "..."}`
가 `isError: true` 로 돌아오므로, 붙어 있는 AI 에이전트가 사용자에게 그대로
안내할 수 있다.

### 1. 실행

```bash
python3 -m mcp_server.selftest      # 자체 점검 47개 항목 (데이터 없이도 통과)
python3 -m mcp_server --check       # 데이터 상태만 확인
python3 -m mcp_server               # MCP 서버 실행 (stdio)
```

**의존성은 선택이다.** `pip install mcp` 로 공식 SDK를 넣으면 SDK로 뜨고,
없으면 표준 라이브러리만으로 같은 JSON-RPC를 처리하는 내장 구현(`_fallback.py`)으로
자동 전환된다. 파이썬 3.10+ 만 있으면 동작한다.

```bash
pip install -r mcp_server/requirements.txt   # 선택 — 공식 SDK 사용 시
python3 -m mcp_server --no-sdk               # SDK가 있어도 내장 구현으로 강제
```

### 2. 데이터 없이 기능만 보기 — 합성 샘플

수집 없이 라우팅 동작만 확인하려면 합성 샘플을 물릴 수 있다.

```bash
VOISSO_DATA_FILE=mcp_server/fixtures/sample_departments.json python3 -m mcp_server
```

`mcp_server/fixtures/sample_departments.json` 은 이 프로젝트가 직접 작성한
**가상 조직**(테스트국 가상수도과, 예시국 가상재난과 …)이다. 어떤 공공데이터에서도
파생되지 않았으므로 저장소에 커밋된다. 부서명·담당업무가 전부 가상이라
**실제 민원 라우팅에는 쓸 수 없고**, 서버는 기동 시 stderr 로 그 사실을 알린다.

## Claude Desktop 연결

설정 파일 위치

| OS | 경로 |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

아래를 넣고 Claude Desktop을 재시작한다. `/absolute/path/to/junctionX` 는
**이 저장소를 클론한 실제 경로**로 바꾼다.

```json
{
  "mcpServers": {
    "voisso-gb": {
      "command": "python3",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/junctionX",
        "VOISSO_DATA_DIR": "/absolute/path/to/junctionX/data"
      }
    }
  }
}
```

Windows 는 `"command": "python"` 과 백슬래시 경로(`C:\\path\\to\\junctionX`)를 쓴다.

**연결 확인** — 앱을 완전히 종료(⌘Q)했다가 재시작한 뒤 로그를 본다.

```bash
grep "connected successfully" ~/Library/Logs/Claude/mcp.log
tail -5 ~/Library/Logs/Claude/mcp-server-voisso-gb.log
#   → [voisso-gb] 데이터 96개 부서 로드 (source=voisso.data.load_departments())
```

위 스니펫은 macOS + Claude Desktop 에서 실제로 붙여 확인했다. 기동+initialize 0.4초,
첫 질의 0.07초, 이후 질의 1~5밀리초.

`spawn python3 ENOENT` 가 나오면 GUI 앱이 `python3` 를 못 찾은 것이다.
`which python3` 결과를 `command` 에 절대경로로 넣는다 (pyenv·conda 환경이면 이쪽이 안전하다).

```json
"command": "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
```

연결되면 Claude에게 이렇게 물어볼 수 있다.

> 안동에 사는데 집 앞 하수구가 막혀서 물이 안 빠져요. 경북도청 어디에 전화해야 하나요?

> 경상북도청에서 버스 노선 신설을 담당하는 부서와 그 근거 사무분장을 알려줘.

### Claude Code 에 붙이기

```bash
claude mcp add voisso-gb --env PYTHONPATH=$(pwd) -- python3 -m mcp_server
```

---

## 노출 툴

| 툴 | 설명 |
|---|---|
| `find_department` | 민원 문장 → 담당 부서 후보 + **evidence 원문**. `top_k` 기본 3 |
| `get_department` | 부서 id → 사무분장·직위·담당업무 전체 |
| `list_departments` | 부서 목록(요약). `contains` 로 이름 필터 |
| `normalize_dialect` | 경북 사투리 → 표준어 (`voisso.dialect` 위임) |
| `to_dialect` | 표준어 → 경북 사투리 (`voisso.dialect` 위임) |
| `submit_complaint` | 민원카드를 `data/complaints/<id>.json` 으로 저장 |

### `find_department` 응답

```json
{
  "query": "버스 노선을 늘려달라",
  "confident": true,
  "reason": "1순위 점수 0.57, 2순위와 격차 0.57 — 단독 배정 가능",
  "grounded": true,
  "matched_terms": [
    "버스"
  ],
  "fallback_phone": "1522-0120",
  "matches": [
    {
      "department_id": "gb-6471597-6471622",
      "full_name": "경제통상국 교통정책과",
      "position": "주무관",
      "duty": "◦ 시외버스 인․면허 업무관리 ◦ 공항버스 등 한정면허 운영관리 등 ◦ 시외버스 …",
      "phone_token": "PHONE_1040",
      "score": 0.5679,
      "evidence": "◦ 시외버스 인․면허 업무관리 ◦ 공항버스 등 한정면허 운영관리 등 ◦ 시외버스 불편신고 민원처리"
    }
  ],
  "data_source": "voisso.data.load_departments()",
  "is_sample": false
}
```

`duty` / `position` / `phone_token` 은 **evidence 를 만든 바로 그 담당자**의 값이다.
배정 사유가 된 담당업무와 연결되는 사람이 어긋나면 "왜 나한테 보냈나"에 답할 수 없기 때문이다.

`confident` 가 `false` 면 **단정하지 말고 후보를 함께 제시**해야 한다는 신호다.
네 가지 경우에 그렇게 된다.

| 조건 | 의미 |
|---|---|
| 1순위 점수 < 0.48 | 어느 부서도 충분히 안 맞는다 |
| 1·2순위 격차 < 0.10 | 두 부서가 비등하다 — 사람이 골라야 한다 |
| `grounded: false` | 민원인이 쓴 단어가 사무분장 원문에 아예 없다 (유사어로만 찾은 결과) |
| 맥락 부족 | 같은 말이 맥락에 따라 소관이 갈린다 |

**맥락에 따라 소관이 갈리는 민원.** "집이 물에 잠겼어요"는 상시 배수 불량일 수도,
호우 재난 피해일 수도 있다. 전자는 하수도(맑은물정책과), 후자는 자연재난과 소관이다.
개념 사전이 이런 개념에 `needs_context` 를 달아 두고, 원인을 가리는 신호
(상시·반복 / 태풍·호우)가 함께 잡히지 않으면 **단정하지 않고 양쪽 후보를 함께** 낸다.
`next_action.type` 은 `need_context` 가 되어 무엇을 더 물어야 하는지 알려준다.

```
"집 앞에 물이 안 빠지고 자꾸 고여서"   → 맑은물정책과 0.73  단독 배정
"지난 호우로 마을이 침수됐습니다"       → 자연재난과   0.92  단독 배정
"집이 물에 잠겼어요"                  → 두 부서를 함께 제시, 단정 안 함
```

점수 임계값 0.48 은 실데이터에서 측정해 잡았다. 정상 민원 질의 10건은 0.653~1.000,
도청 소관이 아닌 질의 5건("심해 잠수정 도색", "화성 이주 신청" 등)은 0.000~0.312 로
두 분포 사이가 비어 있다. 확신 없이 오배정하는 것보다 후보를 보여주는 편이 낫다 —
공공 서비스에서 오배정은 민원인이 두 번 전화하게 만든다.

임계선을 넘는 후보가 하나도 없으면 `matches` 는 빈 목록이고 대표번호(`fallback_phone`)를
안내한다. 없는 부서를 지어내지 않는다.

---

## 라우팅 엔진 (`voisso/routing/`)

외부 의존성 없이 한국어에 맞춘 랭킹을 직접 구현했다. 형태소 분석기(konlpy/mecab)는
JVM·사전 설치가 필요해 "README만으로 실행"을 깨뜨리므로 쓰지 않았다.

| 파일 | 역할 |
|---|---|
| `tokenizer.py` | 정규화 → 조사·어미 꼬리 제거 → 불용어 제거 → 문자 2·3-gram |
| `concepts.py` | **민원 개념 사전 56개.** 구어 증상 표현 → 행정 용어, 관할(도/시군) 표시 |
| `regions.py` | 경상북도 22개 시·군 감지 — 시군 소관 민원의 다음 행동을 구체화 |
| `lexicon.py` | 어절 단위 유사어 확장 (보조 역할) |
| `engine.py` | TF-IDF 코사인 + BM25 하이브리드, 부서 단위 집계 |
| `privacy.py` | 사무분장 원문에 섞인 전화번호 제거 |
| `dataaccess.py` | 데이터 소스 해석 + 데이터 부재 시 안내 (`MissingDataError`) |

**동작 방식**

1. **문장 단위 색인.** 부서가 아니라 담당업무 문장 하나하나를 색인한다.
   그래야 evidence 로 쓸 원문을 정확히 특정할 수 있다.
2. **문자 n-gram.** 한국어는 한자어 명사가 겹치므로 `하수구`↔`하수도`,
   `재난지원금`↔`자연재난 피해조사` 가 부분 문자열로 이어진다.
3. **코사인 + BM25 혼합.** 코사인만 쓰면 "업무 전반" 같은 짧은 문장이 과대평가되고,
   BM25만 쓰면 점수 스케일이 질의마다 달라져 임계값을 못 잡는다.
4. **부서 커버리지 가산.** 한 부서 안에서 여러 문장이 걸리면 가점을 준다.
   "메타버스" 하나만 걸린 인공지능산업과보다, 시외버스·공항버스·저상버스가
   두루 걸린 교통정책과가 위로 올라온다.
5. **개념 사전이 구어와 행정 용어 사이에 다리를 놓는다.** "물이 안 빠진다"에는
   도청 사무분장에 나오는 단어가 하나도 없다. 문자 매칭만으로는 못 잡는다.
   사람이 작성한 55개 개념이 이를 `하수도·하수관로·배수·우수·준설` 로 번역한다.
   각 개념에는 관할이 붙어 있어, 시군 소관이면 부서를 배정하지 않고 안내로 돌린다.
6. **2글자 겹침만으로 걸린 유닛은 감점한다.** "가로등"과 "가로수"가 겹치는 건
   `가로` 뿐이고, 사투리 "카이"와 "하이테크"가 겹치는 건 `하이` 뿐이다.
   3글자 이상이 걸렸거나 개념 사전이 확인해 준 용어가 걸린 경우만 실질 매칭으로 본다.
7. **구어체·사투리 어미를 걷어낸다.** "어데 전화하믄 되노", "유실됐다 카는데" 같은
   경북 사투리 의문·인용 어미와 민원 군더더기("동네", "전화", "소관")를 검색어에서 뺀다.
   STT 결과를 표준어로 고치지 않고 그대로 넣어도 같은 부서로 간다.
8. **원어절 접지(grounding) 확인.** 민원인이 쓴 어절이 사무분장 원문에 하나도 없으면
   확장 사전(유사어)만으로 찾은 결과다. 그런 결과는 단정하지 않고 후보로만 제시한다.
9. **evidence 는 점수와 다른 기준으로 고른다.** 담당자가 납득하려면 민원인이
   말한 단어가 실제로 그 담당업무에 적혀 있어야 한다. 그래서 질의 어절이
   원문에 그대로 등장하는 문장을 우대하고, 부서명이나 "업무 전반" 류는 뒤로 민다.

### 검증된 라우팅 결과

수집된 실데이터(96개 부서)로 확인한 결과다.
회귀 테스트는 `python3 -m mcp_server.regression` 로 재현한다 (**132케이스 100% 통과**).
그중 13개가 *같은 민원의 표현 변형이 전부 같은 부서로 가는지* 보는 일관성 그룹이다 —
"표현이 달라도 결과가 같다"가 이 엔진의 품질 기준이다.
`./scripts/test.sh` 통합 러너에 물려 있어 라우팅이 퇴행하면 러너가 실패한다.

| 질의 | 종류 | 1순위 | 점수 | 판정 |
|---|---|---|---|---|
| 집 앞 하수구가 막혀서 물이 안 빠진다 | 표준어 | 기후환경국 맑은물정책과 | 0.744 | 단독 배정 |
| 집 앞에 물이 안 빠지고 자꾸 고여서 큰일이에요 | 구어체(행정용어 없음) | 기후환경국 맑은물정책과 | 0.704 | 단독 배정 |
| 비만 오면 마당에 물이 찬다 | 구어체(표현 변형) | 기후환경국 맑은물정책과 | 0.679 | 단독 배정 |
| 도로가 파여서 차가 덜컹거려요 | 구어체 | 건설도시국 도로철도과 | 0.894 | 단독 배정 |
| 쓰레기를 아무데나 버려요 | 구어체 | 기후환경국 환경관리과 | 0.860 | 단독 배정 |
| 막차가 너무 일찍 끊깁니다 | 구어체 | 경제통상국 교통정책과 | 0.733 | 단독 배정 |
| 농로가 유실됐다 카는데 어느 과 소관이고? | 사투리 | 농축산유통국 스마트농업혁신과 | 0.698 | 단독 배정 |
| 경로당 지원 사업은 누가 담당하노? | 사투리 | 복지건강국 어르신복지과 | 0.894 | 단독 배정 |
| 산불 예방 관련해서 물어볼 데가 어디고? | 사투리 | 산림자원국 산림정책과 | 1.000 | 단독 배정 |
| 집이 물에 잠겼어요 | 맥락 부족 | 안전행정실 자연재난과 | 0.762 | 후보 제시 |
| 밤에 골목이 캄캄해요 | 시군 소관 | — | — | **시군 민원실 안내** |
| 빙하 탐사선 견인은 누가 담당하노? | 범위 밖 | — | — | **후보 없음 → 대표번호 안내** |

사투리·구어체 질의는 표준어로 고치지 않고 **원문 그대로** 넣은 결과다.
시연 대본과 근거 원문 전문은 [DEMO.md](./DEMO.md) 에 있다.

## 개인정보 처리

계약서 3절을 서버 단에서 한 번 더 강제한다.

- 응답에는 **`phone_token`(예: `PHONE_1046`)만** 나간다.
- 실번호는 `data/private/phone_map.json` (gitignore 대상)에서만 해석하며,
  `get_department` 의 `resolve_phone: true` 로 명시적으로 요청할 때만 붙는다.
- 매핑이 없으면 경북도청 대표번호 **1522-0120** 으로 폴백한다. 가짜 번호를
  만들지 않는다.
- 경북도청 원문 사무분장에는 내선번호가 본문에 섞인 항목이 있다
  (예: `행사, 의전 [행정☎ (소방) 880-6110]`). `privacy.py` 가 색인 단계에서
  이를 떼어내므로 evidence 로 새어 나가지 않는다. 셀프테스트 3절이 이를 검사한다.

---

## 데이터 소스 우선순위

`dataaccess.py` 가 다음 순서로 찾는다. 앞의 것이 생기면 재시작 없이 승격된다.

1. `voisso.data.load_departments()` — P3 공용 모듈
2. `$VOISSO_DATA_FILE` — 데이터 파일 직접 지정 (합성 샘플을 물릴 때)
3. `$VOISSO_DATA_DIR/gb_departments.json` (기본 `<repo>/data`)

어디에도 없으면 `MissingDataError` 를 던진다. **빈 결과를 조용히 돌려주지 않는다.**
"담당 부서를 못 찾음"과 "데이터가 아예 없음"은 전혀 다른 상황이고, 처음 실행하는
담당자는 그 차이를 즉시 알아야 하기 때문이다. 예외 없이 상태만 보려면
`routing.data_available()` / `routing.data_status()` 를 쓴다.

## 방언 모듈 연동

`normalize_dialect` / `to_dialect` 는 `voisso.dialect` 에 위임한다. 모듈이 아직
없어도 서버는 죽지 않고 원문을 그대로 돌려주며 `available: false` 와 안내 문구를
싣는다. 모듈이 생기면 매 호출마다 import를 재시도하므로 재시작 없이 붙는다.

## 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `VOISSO_DATA_DIR` | `<repo>/data` | 부서 데이터 및 `private/phone_map.json` 위치 |
| `VOISSO_DATA_FILE` | (없음) | 데이터 **파일**을 직접 지정. `VOISSO_DATA_DIR` 보다 우선한다 |
| `VOISSO_COMPLAINTS_DIR` | `$VOISSO_DATA_DIR/complaints` | 민원카드 저장 위치 |

전체 환경변수는 저장소 루트의 [`.env.example`](../.env.example) 에 있다.
