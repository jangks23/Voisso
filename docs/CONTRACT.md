# Voisso — 모듈 계약서 (읽고 시작할 것)

> 병렬 작업 중이다. **이 문서의 스키마와 함수 시그니처는 임의로 바꾸지 마라.**
> 변경이 꼭 필요하면 오케스트레이터(P3 / w1:p2)에게 먼저 알린다.

## 0. 프로젝트

**Voisso (보이소)** — 경북 어르신이 사투리로 전화하면, AI가 대화로 민원을 파악해
경상북도청 담당 부서로 라우팅하고, 담당자에게 요약 카드를 전달한다.

## 1. 절대 규칙

- **git 명령을 실행하지 마라.** 커밋/푸시는 오케스트레이터가 전담한다.
  (7개 에이전트가 동시에 git을 쓰면 index.lock 충돌로 저장소가 깨진다.)
- **자기 소유 디렉터리 밖의 파일을 수정하지 마라.** 필요하면 오케스트레이터에게 요청.
- **비밀키를 코드에 넣지 마라.** 전부 환경변수 + `.env.example` 문서화.
- **하드코딩된 절대경로 금지.** 경북도청으로 이관 가능한 품질이 기준이다.
- 작업이 끝나면 **무엇을 만들었고 어떻게 실행하는지** 한 문단으로 보고한다.

## 2. 디렉터리 소유권

| 담당 | 소유 경로 |
|---|---|
| P3 crawler   | `scripts/`, `data/` |
| P4 mcp       | `mcp_server/`, `voisso/routing/` |
| P5 dialect   | `voisso/dialect/` |
| P6 voice     | `voisso/voice/`, `voisso/agent/`, `server/` |
| P7 call-ui   | `web/call/` |
| P8 dashboard | `web/dashboard/` |
| P1 docs      | `README.md`, `.env.example`, `.gitignore`, `docs/` |

공용 파일 `voisso/__init__.py`, `voisso/data.py`는 **P3가 만들고 나머지는 읽기만** 한다.

## 3. 데이터 스키마 (고정)

`data/gb_departments.json`

```json
{
  "meta": {
    "source_url": "https://www.gb.go.kr/Main/programs/organizationChart/organizationPartInfo.do",
    "org": "경상북도청 본청",
    "fetched_at": "2026-08-21T13:40:00Z",
    "department_count": 96,
    "staff_count": 1234,
    "phone_masked": true,
    "license": "출처표시 (공공누리 제1유형 추정, README에 확인 결과 기재)"
  },
  "departments": [
    {
      "id": "gb-6470783-6470793",
      "name": "정책기획관",
      "parent": "기획조정실",
      "full_name": "기획조정실 정책기획관",
      "dept_code": "6470783",
      "dept_code1": "6470793",
      "source_url": "https://www.gb.go.kr/...",
      "duties": ["도정의 기획・조정", "주요업무 계획수립 및 심사・평가"],
      "staff": [
        {
          "position": "주무관",
          "duty": "도정 주요업무계획 수립, 도정질문 답변서 작성, 당정협의회개최 등",
          "phone_token": "PHONE_0042"
        }
      ]
    }
  ]
}
```

**개인정보 처리 규칙 (중요)**

- 원문에는 담당자 **실명 컬럼이 없다.** 공개되는 건 `소속부서 / 직위 / 담당업무 / 전화번호`뿐.
- **전화번호는 공개 데이터셋에 절대 넣지 않는다.** `PHONE_0042` 같은 토큰으로 치환한다.
- 가짜 전화번호를 생성하지 마라. 실존하는 타인의 번호와 충돌할 수 있다. 반드시 토큰 형식.
- 실제 번호 매핑은 `data/private/phone_map.json` (gitignore 대상)에만 둔다.
  형식: `{"PHONE_0042": "054-880-XXXX"}`
- 매핑이 없으면 런타임은 경북도청 대표번호 **1522-0120** 으로 폴백한다.

## 4. 파이썬 모듈 인터페이스 (고정)

```python
# voisso/data.py            (P3 제공)
load_departments() -> dict          # 위 JSON 그대로
resolve_phone(token: str) -> str    # 매핑 있으면 실번호, 없으면 "1522-0120"

# voisso/routing/           (P4)
find_department(query: str, top_k: int = 3) -> list[Match]
# Match = {"department_id","full_name","position","duty","phone_token","score","evidence"}
#   evidence = 매칭 근거가 된 담당업무/사무분장 원문 문자열 (필수. 대시보드에 그대로 노출된다.)
get_department(department_id: str) -> dict
list_departments() -> list[dict]

# voisso/dialect/           (P5)
normalize(text: str) -> str    # 사투리 -> 표준어 (STT 결과 교정)
to_dialect(text: str) -> str   # 표준어 -> 경북 사투리 (TTS 입력)
lexicon_size() -> int
```

## 5. HTTP API (고정) — P6이 `server/`에 구현, P7/P8이 소비

```
POST /api/call/start                  -> {"session_id": "..."}
POST /api/call/turn                   -> {"session_id","text"|"audio_b64"}
     응답 {"reply_text","reply_dialect","audio_b64","done":false,"slots":{...},
           "caller_turn":{"dialect":"...","standard":"...","source":"stt"|"text",
                          "stt_raw":"...","stt_provider":"openai"|"web"|null}}

**`caller_turn` 은 필수다.** 음성 입력일 때 화면이 "무엇을 받아썼는지" 를 표시할 근거다.
빠지면 통화 화면에 `(음성 발화)` 같은 자리표시자가 뜬다 — 실제로 그 버그가 있었다.
- `stt_raw` : STT 원본. 정규화 전.
- `dialect` : 화면에 보여줄 발화(사투리 원문). 보통 stt_raw 와 같다.
- `standard`: `normalize()` 통과 결과.
- 세 값이 **모두 같아도 셋 다 채워라.** 프론트가 분기하지 않게 한다.
POST /api/call/end     {"session_id"} -> {"complaint": <민원카드>}
GET  /api/complaints                  -> {"complaints": [<민원카드>...]}
GET  /api/complaints/{id}             -> {"complaint": <민원카드>}
```

**계약 외 추가 엔드포인트와 추가 필드 (있어도 계약 위반이 아니다. 없다고 가정해도 된다.)**

```
POST /api/call/turn/stream                       -> application/x-ndjson (아래 참조)
POST /api/tts/stream   {"text","previous_text?"} -> audio/wav 청크 스트림
GET  /api/health                                 -> 지금 어떤 엔진·STT·TTS 로 도는가
```

- `/api/call/start` 응답에는 첫 인사(`reply_text` 등)와 `status`(런타임 상태)가 함께 온다.
  왕복 한 번을 아끼고, 저하 상태를 화면에 표시하기 위한 것이다.
- `/api/call/turn` 요청은 두 필드를 더 받는다.
  `alternatives`(브라우저 음성인식 후보 배열)와 `want_audio`(기본 `true`).
  **둘 다 없어도 기존과 똑같이 동작한다.** `want_audio: false` 면 TTS 를 건너뛰고
  텍스트만 돌려주므로, 클라이언트가 `/api/tts/stream` 으로 따로 받아 재생할 때 쓴다.
- `turn`/`end` 응답의 `meta.timings` 에 구간별 소요(ms)가 실린다. STT 가 실패하면
  `meta.stt_error` 에 사유가 담긴다 — **실패해도 200 이고 통화는 이어진다.**
- `/api/tts/stream` 은 통짜 `audio_b64` 보다 첫 음성이 빠르다.
  **TTS 키는 서버 안에서만 쓰인다. 브라우저로 내려보내지 않는다.**

**`/api/call/turn/stream` (NDJSON)** — 요청 본문은 `/api/call/turn` 과 같다.
일괄 경로는 LLM 과 TTS 가 다 끝나야 응답이 나가지만, 이 경로는 LLM 이 첫 문장을
뱉는 즉시 합성을 시작해 두 시간이 겹쳐진다. 한 줄에 JSON 객체 하나가 온다.

```
{"type":"heard","dialect":…,"standard":…}                       받아쓴 어르신 발화
{"type":"sentence","index":0,"standard":…,"dialect":…}          응답 문장 하나
{"type":"audio_start","index":0,"mime":"audio/wav",
 "sample_rate":32000,"bits":16,"channels":1}
{"type":"audio_chunk","index":0,"seq":0,"b64":…}                 첫 청크에 WAV 헤더
{"type":"audio_chunk","index":0,"seq":1,"b64":…}                 이후는 raw PCM
{"type":"audio_end","index":0,"chunks":49}
{"type":"final","reply_text":…,"reply_dialect":…,"slots":{…},"done":…,"meta":{…}}
{"type":"error","message":…}                                     스트림 도중 실패
```

- 클라이언트는 `audio_chunk` 를 **`seq` 순서대로 이어 붙여** 재생한다.
- TTS 가 꺼져 있으면(`VOISSO_TTS_PROVIDER=none`) `audio_*` 이벤트가 아예 없다.
  `sentence` 와 `final` 은 그대로 온다.
- 합성이 깨져도 통화는 끊지 않는다. **`final` 은 어떤 경로로든 반드시 나간다**,
  그리고 그 `slots`/`done` 은 `/api/call/turn` 과 같은 값이다.
- 실측 효과와 구간별 수치는 [`docs/E2E_SERVER.md`](./E2E_SERVER.md) 에 자동 기록된다.

**민원카드 스키마 (고정)**

```json
{
  "id": "0417",
  "created_at": "2026-08-21T14:32:00Z",
  "duration_sec": 108,
  "summary": "안동시 옥동 주택가 배수 불량, 강우 시 침수 반복",
  "category": "도로·하수 유지관리",
  "assigned": {
    "department_id": "gb-...",
    "full_name": "건설도시국 도로과",
    "phone_token": "PHONE_0421",
    "evidence": "우수관로 정비 및 배수시설 유지관리"
  },
  "alternatives": [{"full_name": "...", "score": 0.71, "evidence": "..."}],
  "caller": {"name_masked": "김○○", "phone_masked": "010-****-1234"},
  "transcript": [{"role":"caller","dialect":"...","standard":"..."},
                 {"role":"agent","standard":"...","dialect":"..."}]
}
```

`assigned.evidence`는 **비워두면 안 된다.** "AI가 왜 나한테 보냈는지"를 담당자에게
보여주는 값이고, 심사 기준(공공부문 활용 가능성 25%)의 핵심이다.

## 5-A. 긴급도 판정 (신규 · 고정)

민원카드에 **긴급도**를 넣는다. 담당자는 하루에 수십 건을 받는다. 무엇을 먼저 볼지
정해 주지 않으면 접수 순서대로 처리되고, 급한 민원이 뒤에 묻힌다.

```json
"urgency": {
  "level": "응급" | "중요" | "보통" | "낮음",
  "reason": "판정 근거 한 문장",
  "signals": ["침수 진행 중", "고령 1인 거주"],
  "decided_by": "rule" | "llm",
  "safety_referral": null | {"number": "119", "label": "소방·구조"}
}
```

### 단계 정의

| 단계 | 뜻 | 예 |
|---|---|---|
| **응급** | **사람이 다칠 수 있다. 지금.** | 침수 진행 중, 가스 냄새, 축대·건물 붕괴 조짐, 도로 함몰, 화재, 고립 |
| **중요** | 방치하면 피해가 커진다. 오늘~내일 | 상수도 단수, 하수 역류, 가로등 전면 소등, 농작물 침수 우려 |
| **보통** | 정상 처리 일정 | 도로 파임, 잡초, 표지판 파손, 일반 문의 |
| **낮음** | 급하지 않다 | 제도 문의, 건의, 칭찬, 단순 확인 |

### 판정 방식 — 규칙 먼저, LLM 은 보완

1. **규칙(rule)이 우선한다.** 명백한 위험 신호는 결정적으로 잡는다.
   가스/불/붕괴/함몰/고립/감전/떠내려/사람이 갇혔다 등. 규칙이 걸리면 LLM 판단으로 낮추지 마라.
2. **LLM 은 규칙이 안 걸릴 때만** 문맥으로 판정한다. 결과는 규칙 결과를 **올릴 수만 있고
   내릴 수 없다.** 안전 쪽으로 치우치는 것이 옳다.
3. **`reason` 을 반드시 채워라.** 라우팅 근거와 같은 원칙이다.
   담당자가 "왜 응급인가" 를 납득하지 못하면 그 표시는 무시된다.

### 🚨 응급은 접수하고 끝내면 안 된다

**사람이 위험한 상황을 민원으로 접수하고 통화를 끝내는 것은 이 시스템의 가장 큰 위험이다.**

- 응급으로 판정되면 **즉시 119·112 안내를 먼저 한다.**
  "지금 위험하시믄 먼저 119에 전화해 주이소. 민원은 제가 접수해 둘게예."
- 민원 접수는 그 다음이다. **접수가 신고를 대체한다고 오해하게 만들지 마라.**
- `safety_referral` 에 안내한 번호를 기록해 담당자가 확인할 수 있게 한다.
- 어르신 모드에서도 이 안내는 **크게, 명확히** 보여야 한다. 유일하게 시각적으로 강조하는 예외다.

### 응급 판정 후에는 대화 모드가 바뀐다 (필수)

**실사용에서 실패가 확인됐다.** 집에 물이 차오르는 민원인이 "빨리 와요!!!" 를 세 번 반복했는데
시스템은 "위험하면 바로 119에 신고하시고, 더 하실 말씀 있으신가예?" 를 반복했다.
**응급 상황에서 마무리 질문 루프를 도는 것은 그 자체로 실패다.**

응급으로 판정되면:

1. **화면에 119·112 버튼을 띄운다.** 말로만 안내하지 마라.
   어르신이 번호를 외워 다시 걸게 하면 안 된다. `tel:` 링크로 **누르면 바로 걸려야** 한다.
   어르신 모드에서 가장 크게, 화면 상단에 고정한다.
2. **슬롯 채우기를 중단한다.** 연락처·시점을 더 묻지 마라. 확보된 것만으로 접수한다.
   위치는 예외다 — 출동에 필요하므로 계속 확보하되, **한 번에 하나만** 묻는다.
3. **마무리 질문("더 하실 말씀?")을 하지 마라.** 응급에서는 이 루프에 들어가지 않는다.
   접수를 즉시 확정하고 담당자에게 넘긴다.
4. **재촉에는 상태로 답한다.** "빨리 와요" 에는 질문이 아니라 **지금 무엇이 되어 있는지**를 알린다.
   "접수됐습니더. 담당자한테 바로 넘겼어예. 위험하시믄 지금 119 눌러 주이소."

### 다급함 반복은 긴급도를 올린다

같은 화자가 재촉·다급함 표현을 **반복**하면 상황이 악화되고 있다는 신호다.
- "빨리", "빨리요", "지금", "당장", "우짜노", "야단났다", "큰일났다" 등이 **2회 이상** 나오면
  긴급도를 한 단계 올린다. 느낌표 반복(`!!!`)과 대문자·반복 입력도 신호다.
- 이미 응급이면 더 올릴 곳이 없으므로 **119 안내를 다시, 더 강하게** 표시한다.
- 단발성 강조("큰일이라예")는 경북에서 흔한 표현이므로 1회로는 올리지 않는다. 반복이 신호다.

### 표시 규칙

- **대시보드**: 긴급도로 정렬·필터. 응급은 상단 고정과 시각적 강조. 색만으로 구분하지 마라
  (색각 이상 고려). 반드시 글자를 함께 쓴다.
- **어르신 화면**: 긴급도를 어르신에게 보여주지 마라. 불안만 준다.
  예외는 위 안전 안내뿐이다.
- 담당자는 긴급도를 **수정할 수 있어야 한다.** AI 판정은 제안이고 최종 판단은 사람이 한다.
  수정 시 원래 판정과 근거는 이력으로 남긴다.

## 5-B. 담당자 핸드오프 (신규 · 고정)

AI 가 접수하고 **사람이 이어받는다.** 공공기관은 AI 에 전권을 주지 않는다.
접수까지는 AI, 그 다음은 담당자가 책임진다. 이 구조가 실제로 채택 가능한 형태다.

```
POST /api/handoff/{complaint_id}/start
     body {"officer_name": "홍길동", "department": "기후환경국 맑은물정책과"}
     -> {"channel_id": "...", "status": "open", "started_at": "..."}

POST /api/handoff/{complaint_id}/message
     body {"role": "officer" | "caller", "text": "..."}
     -> {"ok": true, "message": {...}}

GET  /api/handoff/{complaint_id}
     -> {"status": "none" | "open" | "closed",
         "officer": {"name": "...", "department": "..."},
         "messages": [{"role","text","dialect","standard","at"}]}

POST /api/handoff/{complaint_id}/close  -> {"status": "closed"}
```

**양방향 통역이 이 기능의 핵심이다.**

- 담당자는 **표준어로 입력**한다. 어르신 화면에는 `to_dialect()` 를 거친 **사투리**로 보인다.
- 어르신은 **사투리로 말한다.** 담당자 화면에는 `normalize()` 를 거친 **표준어**로 보인다.
- 각 메시지는 `dialect` 와 `standard` 를 **둘 다** 담는다. 양쪽 화면에서 원문 대조가 가능해야 한다.

방언 레이어가 AI 응답 생성용 장치에서 **사람과 사람 사이의 통역기**로 확장된다.
이게 우리 기술의 가장 강한 서사다. 담당자가 경상도 사람이 아니어도 어르신과 대화할 수 있다.

**규칙**

- 핸드오프는 민원카드가 생성된 뒤에만 시작된다. `complaint_id` 가 없으면 400.
- 담당자 이름·부서는 대시보드에서 입력받는다. **실명을 저장하지 마라.** 표시용으로만 쓰고
  민원카드에는 남기지 않는다. (도청 데이터에 담당자 실명이 없다는 원칙과 일관되게)
- 통화 화면은 `end` 이후에도 `GET /api/handoff/{id}` 를 폴링해 담당자 연결을 기다린다.
- **AI 가 담당자를 연기하지 마라.** 핸드오프가 열리면 AI 는 발화를 멈춘다.
  화면에도 "지금부터 담당자가 직접 응대합니더" 를 명확히 표시한다.
  누가 말하는지 헷갈리면 그 자체로 신뢰 문제가 된다.

## 5-C. 진행 안내 콜백 (신규 · 고정)

**시스템이 먼저 전화를 건다.** 지금 어르신이 민원 진행 상황을 알려면 다시 전화해서
ARS 를 또 뚫어야 한다. 우리가 없애려던 벽을 어르신이 다시 만난다. 그래서 방향을 뒤집는다.

```
POST /api/callback/{complaint_id}/schedule
     body {"briefing": "현장 확인 완료. 이번 주 내 배수관 준설 예정입니다.",
           "officer_name": "홍길동", "department": "기후환경국 맑은물정책과"}
     -> {"callback_id": "...", "status": "pending"}

GET  /api/callback/{complaint_id}
     -> {"status": "none"|"pending"|"answered"|"closed",
         "briefing": {"standard": "...", "dialect": "..."},
         "officer": {...},
         "messages": [{"role","text","dialect","standard","at"}]}

POST /api/callback/{complaint_id}/answer   -> 어르신이 전화를 받음. status: answered
POST /api/callback/{complaint_id}/message  body {"role":"caller"|"agent","text":"..."}
POST /api/callback/{complaint_id}/close
```

**흐름**

1. 담당자가 대시보드에서 **진행 상황을 표준어로 작성**하고 "안내 전화 걸기" 를 누른다.
2. 어르신 화면에 **수신 전화**가 뜬다. 벨 표시와 "경상북도청에서 전화가 왔습니더" 안내.
   받기 버튼 하나뿐이다. (어르신 모드 원칙)
3. 받으면 AI 가 **사투리로 브리핑**한다. 담당자가 쓴 내용을 `to_dialect()` 로 변환한 것이다.
4. 어르신이 추가로 물으면 받아 적어 담당자에게 전달한다. 통화 종료 시 민원카드에 쌓인다.

**절대 규칙 — 이걸 어기면 기능 자체가 위험해진다**

- **AI 는 담당자가 쓴 내용만 전달한다.** 처리 결과·일정·가능 여부를 AI 가 생성하지 마라.
  "언제 됩니꺼?" 라는 질문에 브리핑에 없는 답을 지어내면 그것은 행정 약속이 된다.
  모르는 것은 "담당자에게 여쭤보고 다시 연락드릴게예" 로 넘긴다.
- 어르신의 추가 질문은 **받아 적어 담당자에게 전달**한다. AI 가 답하지 않는다.
  단순 확인(접수번호, 담당 부서명 같은 이미 확정된 사실)은 답해도 된다.
- 브리핑 원문(`standard`)과 사투리 변환(`dialect`)을 **둘 다** 보관한다.
  담당자가 "내가 쓴 대로 전달됐는가" 를 확인할 수 있어야 한다.
- **실제 전화망(PSTN) 연동은 H3 다.** 지금은 브라우저에서 수신 화면을 띄우는 시뮬레이션이다.
  문서와 발표에서 이 점을 정직하게 밝혀라. 숨기면 질문 하나에 무너진다.

## 6. 개발 환경 제약 (필독)

**개발 환경은 노트북이다. 디스크·메모리·연산이 제한적이다.**

- 대용량 모델 가중치를 로컬에 내려받지 마라. Whisper large, 로컬 TTS 음향 모델 등 금지.
  STT/TTS는 **클라우드 API**로 해결한다.
- 대용량 데이터셋 통짜 다운로드 금지. AI Hub 방언 음성 3,000시간 같은 것은 받지 않는다.
  필요한 것은 텍스트 대응쌍 등 경량 자산뿐이다.
- 한국어 TTS는 **타입캐스트(Typecast, https://typecast.ai)** 를 우선 검토한다.
  대안: ElevenLabs, Google Cloud TTS.
- 프론트엔드는 빌드 스텝 없는 순수 HTML/CSS/JS. `node_modules` 금지.
- 파이썬 의존성 최소화. 표준 라이브러리로 되는 일은 표준 라이브러리로.
- 디스크를 크게 쓰는 작업 전에 오케스트레이터에게 먼저 알려라.

## 7. 환경변수

**전체 목록과 각 변수의 기본값·없을 때의 동작은 [`.env.example`](../.env.example) 에 있다.**
아래는 자주 쓰는 것만 추린 것이다. 새 변수를 추가하면 `.env.example` 을 같은 커밋에서 갱신하라
(README 만으로 실행 가능해야 한다는 것이 이 프로젝트의 탈락 조건이다).

```
# 대화 엔진
VOISSO_AGENT_PROVIDER=    # openai | anthropic | rule  (비우면 키 있는 쪽 자동, OpenAI 우선)
VOISSO_AGENT_MODEL=       # 비우면 gpt-5.6-terra / claude-sonnet-5
VOISSO_SUMMARY_MODEL=     # 비우면 gpt-5.6-terra / claude-opus-5
OPENAI_API_KEY=           # 대화 LLM 과 음성 인식이 같이 쓴다
ANTHROPIC_API_KEY=        # anthropic 경로 · 선택적 방언 다듬기

# 음성
VOISSO_TTS_PROVIDER=none  # typecast | elevenlabs | none  (기본 none = 텍스트 모드)
TYPECAST_API_KEY=
TYPECAST_VOICE_ID=
VOISSO_TTS_TEMPO=0.85     # 어르신 청취용으로 표준보다 느리게
ELEVENLABS_API_KEY=
VOISSO_STT_PROVIDER=none  # openai | none
VOISSO_STT_MODEL=         # 비우면 gpt-4o-transcribe (로컬 모델 아님)

# 데이터·서버
VOISSO_DATA_DIR=./data
VOISSO_DATA_FILE=         # 데이터 파일 직접 지정 (합성 샘플용)
VOISSO_HOST= / VOISSO_PORT=      # 비우면 127.0.0.1:8000
VOISSO_CORS_ORIGINS=             # 비우면 *
```

## 8. 막히면

- 상대 모듈이 아직 없으면 **스텁/픽스처로 진행**하고, 계약서 시그니처만 지켜라.
- 2일짜리 해커톤이다. 완벽보다 **동작하는 것**이 우선. 단, mock 데이터로 끝내지 마라.
