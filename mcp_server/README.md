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

---

## 빠른 시작

```bash
# 저장소 루트에서
python3 -m mcp_server.selftest       # 자체 점검 (35개 항목)
python3 -m mcp_server                # MCP 서버 실행 (stdio)
```

**의존성은 선택이다.** `pip install mcp` 로 공식 SDK를 넣으면 SDK로 뜨고,
없으면 표준 라이브러리만으로 같은 JSON-RPC를 처리하는 내장 구현(`_fallback.py`)으로
자동 전환된다. 파이썬 3.10+ 만 있으면 동작한다.

```bash
pip install -r mcp_server/requirements.txt   # 선택 — 공식 SDK 사용 시
python3 -m mcp_server --no-sdk               # SDK가 있어도 내장 구현으로 강제
```

---

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
  "reason": "1순위 점수 0.57, 2순위와 격차 0.27 — 단독 배정 가능",
  "fallback_phone": "1522-0120",
  "matches": [
    {
      "department_id": "gb-6471597-6471622",
      "full_name": "경제통상국 교통정책과",
      "position": "주무관",
      "duty": "◦ 시외버스 인․면허 업무관리 ◦ 공항버스 등 한정면허 운영관리 등 …",
      "phone_token": "PHONE_1040",
      "score": 0.568,
      "evidence": "◦ 시외버스 인․면허 업무관리 ◦ 공항버스 등 한정면허 운영관리 등 ◦ 시외버스 불편신고 민원처리"
    }
  ]
}
```

`duty` / `position` / `phone_token` 은 **evidence 를 만든 바로 그 담당자**의 값이다.
배정 사유가 된 담당업무와 연결되는 사람이 어긋나면 "왜 나한테 보냈나"에 답할 수 없기 때문이다.

`confident` 가 `false` 면 **단정하지 말고 후보를 함께 제시**해야 한다는 신호다.
1순위 점수가 낮거나 1·2위 격차가 좁을 때 그렇게 된다. 확신 없이 오배정하는 것보다
후보 세 곳을 담당자에게 보여주는 편이 낫다는 판단이다.

---

## 라우팅 엔진 (`voisso/routing/`)

외부 의존성 없이 한국어에 맞춘 랭킹을 직접 구현했다. 형태소 분석기(konlpy/mecab)는
JVM·사전 설치가 필요해 "README만으로 실행"을 깨뜨리므로 쓰지 않았다.

| 파일 | 역할 |
|---|---|
| `tokenizer.py` | 정규화 → 조사·어미 꼬리 제거 → 불용어 제거 → 문자 2·3-gram |
| `lexicon.py` | 민원 구어체 ↔ 행정 용어 사전 (`하수구` → `하수도·배수·우수·준설`) |
| `engine.py` | TF-IDF 코사인 + BM25 하이브리드, 부서 단위 집계 |
| `privacy.py` | 사무분장 원문에 섞인 전화번호 제거 |
| `dataaccess.py` | 데이터 소스 해석 (`voisso.data` → `data/` → 픽스처) |

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
5. **evidence 는 점수와 다른 기준으로 고른다.** 담당자가 납득하려면 민원인이
   말한 단어가 실제로 그 담당업무에 적혀 있어야 한다. 그래서 질의 어절이
   원문에 그대로 등장하는 문장을 우대하고, 부서명이나 "업무 전반" 류는 뒤로 민다.

### 검증된 라우팅 결과

`python3 -m mcp_server.selftest -v` 로 재현할 수 있다.

| 질의 | 1순위 | 점수 | 판정 |
|---|---|---|---|
| 집 앞 하수구가 막혀서 물이 안 빠진다 | 기후환경국 맑은물정책과 | 0.637 | 단독 배정 |
| 농로가 무너졌다 | 농축산유통국 스마트농업혁신과 | 0.488 | 후보 제시 |
| 버스 노선을 늘려달라 | 경제통상국 교통정책과 | 0.568 | 단독 배정 |
| 일자리 지원 사업 문의 | 경제통상국 경제정책노동과 | 0.747 | 후보 제시 |
| 재난지원금 신청 방법 | 안전행정실 자연재난과 | 0.497 | 단독 배정 |

---

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
2. `$VOISSO_DATA_DIR/gb_departments.json` (기본 `<repo>/data`)
3. `mcp_server/fixtures/gb_departments.json` — 개발용 소규모 픽스처

3번 픽스처는 `meta.fixture: true` 로 표시되며, `list_departments` 응답과
셀프테스트가 픽스처로 동작 중임을 알려준다.

## 방언 모듈 연동

`normalize_dialect` / `to_dialect` 는 `voisso.dialect` 에 위임한다. 모듈이 아직
없어도 서버는 죽지 않고 원문을 그대로 돌려주며 `available: false` 와 안내 문구를
싣는다. 모듈이 생기면 매 호출마다 import를 재시도하므로 재시작 없이 붙는다.

## 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `VOISSO_DATA_DIR` | `<repo>/data` | 부서 데이터 및 `private/phone_map.json` 위치 |
| `VOISSO_COMPLAINTS_DIR` | `$VOISSO_DATA_DIR/complaints` | 민원카드 저장 위치 |
