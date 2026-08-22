# 폴백 경로 검증 보고서

> **검증일:** 2026-08-22 · **검증자:** P5 dialect
> GOAL.md H1의 성공 기준은 "완벽"이 아니라 **"끊기지 않음"** 이다.
> 이 문서는 폴백이 코드에 있다는 것이 아니라 **실제로 동작하는지** 재현해서 확인한 결과다.
>
> 표기: **[실측]** 재현해서 측정함 · **[코드]** 코드로 확인, 실행은 못 함 · **[미검증]** 확인 못 함

---

## 요약 — 발표 전에 반드시 조치할 것

| # | 문제 | 심각도 | 소유자 |
|---|---|---|---|
| A | **무응답 네트워크에서 한 턴이 최대 135초 멈춘다** (STT 60초 + LLM 45초 + TTS 30초) | 🔴 데모 실패 | P6 |
| B | **STT/TTS 오류가 화면에 전혀 안 뜬다.** 백엔드는 401을 정확히 알려주는데 UI가 안 읽는다 | 🔴 시연자가 당황 | P7 |
| C | **DEMO_SCRIPT의 목 모드 주소가 틀렸다.** `localhost:8080/web/call/` → 실제는 `localhost:8000/call/` | 🔴 대비책 무효 | P1 |
| D | **DEMO_SCRIPT의 "네트워크 끊김 → 아무것도 안 해도 된다"는 틀렸다.** 키가 살아 있으면 매 턴 멈춘다 | 🔴 대비책 무효 | P1 |
| E | **DEMO_SCRIPT의 `VOISO_TTS_PROVIDER=none` 은 이제 아무 효과가 없다.** 이름이 `VOISSO_` 로 바뀌었다 | 🟠 대비책 무효 | P1 |
| F | 서버가 죽으면 `?mock=1` 페이지 자체를 못 받는다. `file://` 로 여는 경로가 문서에 없다 | 🟠 대비책 공백 | P1 |
| G | `/api/health` 가 부서 데이터가 없어도 `routing: true` 라고 보고한다 | 🟡 오해 유발 | P6 |
| H | 통화 UI가 `/api/health` 를 한 번도 호출하지 않는다. 저하 상태를 시연자가 알 수 없다 | 🟡 | P7 |
| I | `web/call/api.js` 에 요청 타임아웃이 없다. 서버가 멈춘 만큼 브라우저도 멈춘다 | 🟠 | P7 |

**좋은 소식:** 키가 0개여도, 부서 데이터가 없어도, API가 401/429/500을 줘도 **서버는 죽지 않고 통화가 끝까지 진행되며 민원카드가 나온다.** 폴백의 뼈대는 실제로 동작한다. 문제는 **무응답 네트워크의 대기 시간**과 **화면에 아무 설명이 없다는 것** 둘이다.

---

## 장애 시나리오별 검증 결과

| # | 장애 | 재현 방법 | 실제 동작 | 사용자에게 보이는 것 | 데모 지속? | 조치 필요 |
|---|---|---|---|---|---|---|
| 1 | **키 전부 없음** | `OPENAI_API_KEY= ANTHROPIC_API_KEY= TYPECAST_API_KEY= VOISSO_TTS_PROVIDER=none VOISSO_STT_PROVIDER=none python -m server` | **[실측]** 정상 기동. `engine=rule`, `degraded=true`, `missing_keys=["OPENAI_API_KEY 또는 ANTHROPIC_API_KEY"]`. 4턴 대화 → 슬롯 4개 충족 → 민원카드 `기후환경국 맑은물정책과`, evidence 54자 | 서버 로그에 저하 상태 표시. **통화 화면에는 표시 없음**(H) | ✅ 전 구간 | — |
| 2 | **키가 잘못됨(401)** | `OPENAI_API_KEY=sk-proj-INVALID...` 로 기동 후 `audio_b64` 전송 | **[실측] 0.38초**에 HTTP 200. `meta.stt_error="OPENAI_API_KEY 가 거부되었습니다(401). 키가 올바른지 확인하세요."` `/api/health` 의 `stt.last_error` 에도 남는다. 서버 생존 | **"죄송합니더, 잘 안 들렸어예. 한 번만 더 말씀해 주시겠어예?"** 만 보인다. **401이라는 사실은 화면 어디에도 없다** | ⚠️ 진행은 되나 시연자가 원인을 모르고 계속 재시도하게 된다 | **B (P7)** |
| 3a | **네트워크 끊김 — 연결 거부** | 죽은 포트로 STT 요청 | **[실측] 0.00초** 즉시 실패. `error="연결 실패 ... [Errno 61] Connection refused"` | 즉시 텍스트 모드 안내 | ✅ | — |
| 3b | **네트워크 끊김 — 무응답(블랙홀)** | 연결은 받고 응답 안 하는 소켓으로 STT/TTS 요청 | **[실측] STT 60.01초 / TTS 30.00초** 뒤 폴백. 예외는 안 던짐 | **그 시간 동안 화면이 완전히 멈춘 것처럼 보인다.** `api.js` 에 타임아웃이 없어 브라우저도 같이 멈춘다 | ❌ **60~135초 정지는 데모 실패** | **A (P6), I (P7)** |
| 3c | **네트워크 끊김 — LLM** | 코드 확인 | **[코드]** OpenAI `timeout=45.0`, Anthropic `timeout=30.0, max_retries=1`(≈60초) | 위와 동일 | ❌ | **A (P6)** |
| 4 | **API 한도 초과(429)** | 로컬 429 응답 서버로 STT 요청 | **[실측] 0.00초** 즉시. `error="OpenAI 사용 한도에 걸렸습니다(429). 잠시 후 다시 시도하세요."` (500도 동일하게 즉시 폴백) | 401과 같다 — **화면에는 안 뜬다** | ✅ 지연 없음 | **B (P7)** |
| 5 | **부서 데이터 없음** | `VOISSO_DATA_DIR=<빈 폴더>` 로 기동 | **[실측]** 서버 정상 기동. 통화 완주. 민원카드 `assigned.full_name="미배정 (수동 배정 필요)"`, `evidence="자동 배정 보류(검색어 '하수도 정비 배수시설' 에 대한 후보 없음). 접수 내용: ..."` — **evidence 가 비지 않는다**(계약 §5 준수). P4의 안내가 서버 로그에 크롤러 실행법까지 출력 | 카드에 "미배정"이 명시된다 | ⚠️ 데모 ③단계(사무분장 근거)는 못 보여준다 | **G (P6)** |
| 6 | **마이크 권한 거부** | **[미검증]** — 브라우저 확장 미연결로 실행 불가 | **[코드]** `app.js:680` `getUserMedia` catch → 힌트 문구 교체 + 토스트. `speech.js` 의 `not-allowed`/`service-not-allowed` 도 별도 처리 | **[코드]** 힌트: "마이크를 쓸 수 없니더. 아래 칸에 글로 적어도 됩니더." + 토스트 "마이크 권한이 없습니다. 텍스트로 진행하세요." (4.5초) | ✅ 텍스트 입력으로 이어짐 | 브라우저 실측 필요 |
| 7 | **미지원 브라우저(Safari 등)** | **[미검증]** — 동일 사유 | **[코드]** `speech.js:20` 에서 `SpeechRecognition \|\| webkitSpeechRecognition` 를 모듈 로드 시점에 잡고, `start()` 초입(`:84`)에서 없으면 `onError('이 브라우저는 음성 입력을 지원하지 않습니다.', 'unsupported')` 후 `false` 반환 | **[코드]** 힌트 영역에 위 문구. `config.js` 의 `STT_MODE:'auto'` 가 서버 STT → 텍스트 순으로 내려간다 | ✅ 텍스트 입력은 항상 가능 | 브라우저 실측 필요 |

---

## DEMO_SCRIPT.md 「실패 대비책」 검증 — 6개 중 3개가 실제로는 안 된다

가장 위험한 것은 **문서에만 있고 실제로는 안 되는 폴백**이다. 한 줄씩 확인했다.

| 문서의 대비책 | 검증 결과 |
|---|---|
| 네트워크 끊김 → "**아무것도 안 해도 된다.** 라우팅과 MCP는 네트워크가 필요 없다" | **❌ 절반만 맞다.** 라우팅은 확인했다 — `voisso/routing/` 에 네트워크 호출 **0건**, 오프라인에서 `기후환경국 맑은물정책과` 를 evidence와 함께 반환 **[실측]**. 그러나 **키가 `.env` 에 살아 있으면 STT·LLM·TTS가 매 턴 죽은 API를 부른다.** 무응답 네트워크에서 턴당 최대 135초 정지 **[실측/코드]**. "아무것도 안 해도 된다"는 틀렸다 → **D** |
| API 서버 다운 → `http://localhost:8080/web/call/?mock=1` | **❌ 주소가 틀렸다.** 8080에는 아무것도 없고(`curl` 연결 실패 **[실측]**), 경로도 `/web/call/` 이 아니라 `/call/` 이다(`/web/call/?mock=1` → **404**, `/call/?mock=1` → **200** **[실측]**). 기본 포트는 `server/config.py:59` 기준 **8000**. 올바른 주소는 `http://localhost:8000/call/?mock=1` → **C** |
| API 서버 다운 → 목 모드 | **❌ 전제가 깨진다.** 통화 페이지를 **서버가 서빙한다.** 서버 프로세스가 죽으면 `?mock=1` 을 붙여도 페이지 자체를 못 받는다. 올바른 대비책은 **`web/call/index.html` 을 `file://` 로 직접 여는 것**이다. `config.js` 의 `USE_MOCK:'auto'` 가 `file:` 프로토콜을 감지해 자동으로 목으로 간다. `index.html` 에 `type="module"` 도 로컬 `fetch` 도 없어 `file://` 에서 깨지지 않는다 **[실측/코드]**. `mock-api.js` 는 네트워크 호출 **0건**이라 완전 오프라인 동작 **[실측]** → **F** |
| 마이크 불통 → 텍스트 입력 모드 | **✅ 코드상 성립.** 위 시나리오 6. 브라우저 실측만 남았다 |
| 타입캐스트 한도 초과 → `.env` 에서 `VOISO_TTS_PROVIDER=none` | **❌ 변수명이 죽었다.** 이름 변경 후 코드가 읽는 것은 `VOISSO_TTS_PROVIDER` 다. `VOISO_TTS_PROVIDER` 를 읽는 코드는 저장소에 **0건 [실측]**. 문서대로 하면 아무 효과 없이 재기동만 하게 된다 → **E**<br>(폴백 자체는 동작한다: 실제 Typecast가 401을 준 상황에서 **0.14초**에 텍스트 모드로 넘어가고 `meta.tts_error` 에 사유가 남았다 **[실측]**) |
| STT가 엉뚱하게 받아씀 → "오히려 기회다" | **✅ 그대로 유효.** 방언 레이어가 정확히 그 지점을 증명한다. `voisso/dialect/demo_lines.md` 참조 |
| 전부 실패 → 녹화 영상 | **[미검증]** 영상이 아직 없다. 촬영 후 로컬 저장 확인 필요 |

---

## 소유자별 요청 사항

> 나는 `voisso/dialect/` 만 소유한다. 아래는 **직접 고치지 않고** 넘기는 항목이다.

### P6 — `server/`, `voisso/voice/`, `voisso/agent/`

**A. 타임아웃 단축 (최우선).** 현재 값은 배치 처리 기준이지 실시간 통화 기준이 아니다.

| 위치 | 현재 | 제안 |
|---|---|---|
| `voisso/voice/stt.py:220` | `timeout=60.0` | **8초** — 8초 안에 안 오면 어차피 통화가 끊긴 것과 같다 |
| `voisso/voice/tts.py:319,346,354,368,432` | `30.0 / 60.0` | **6초** — TTS는 없어도 텍스트로 진행된다 |
| `voisso/agent/providers.py:125,140` | `timeout=45.0` | **12초** |
| `voisso/agent/providers.py:223` | `timeout=30.0, max_retries=1` | **12초, `max_retries=0`** — 재시도가 대기시간을 두 배로 만든다 |

추가로 **턴 전체에 상한**을 두는 편이 안전하다. `server/main.py` 의 turn 핸들러에 `asyncio.wait_for(..., 15)` 를 걸고 초과 시 텍스트 모드로 즉시 반환하면, 개별 타임아웃이 어긋나도 화면은 15초 안에 반드시 응답한다. (현재 `server/main.py` 에 턴 단위 타임아웃 없음 **[실측: grep 0건]**)

**G. `/api/health` 의 `routing` 플래그.** 부서 데이터가 없는데도 `runtime.routing: true` 로 보고한다 **[실측]**. `voisso.routing.data_available()` 이 `False` 인 상태였다. 모듈 임포트 가능 여부와 데이터 준비 여부를 분리해 주면 좋겠다. P4의 `data_status()` 가 이미 `available`/`next_step`/`message` 를 다 준다.

### P7 — `web/call/`

**B. `meta.stt_error` / `meta.tts_error` 를 화면에 띄워 달라 (최우선).**
`web/call/*.js` 어디에도 `meta` 를 읽는 코드가 없다 **[실측: grep 0건]**. 서버는 이미 이렇게 보낸다:

```json
{ "reply_dialect": "죄송합니더, 잘 안 들렸어예…",
  "meta": { "stt_error": "OPENAI_API_KEY 가 거부되었습니다(401). 키가 올바른지 확인하세요.",
            "tts_error": null, "tts": "none" } }
```

이 문구를 토스트나 힌트 영역에 그대로 띄우기만 하면 된다. **사용자가 실제로 겪은 그 상황**(잘린 키로 401이 났는데 화면에 설명이 없어 당황)이 이 한 줄로 해결된다.

**I. `api.js` 에 요청 타임아웃.** `fetch` 에 `AbortController` 가 없다 **[실측: grep 0건]**. 서버가 60초 멈추면 브라우저도 60초 멈춘다. 12~15초 `AbortSignal.timeout()` 을 걸고, 중단되면 "응답이 늦습니다. 텍스트로 진행해 주세요" 를 띄우면 P6의 서버 수정과 무관하게 화면이 먼저 살아난다.

**H. 저하 상태 배지.** `app.js` 가 `/api/health` 를 한 번도 부르지 않는다 **[실측]**. 시작 시 한 번 불러서 `degraded`/`missing_keys` 를 작게 표시하면, 시연 직전에 무엇이 꺼져 있는지 눈으로 확인할 수 있다.

### P1 — `docs/`

**C.** `DEMO_SCRIPT.md:268` — `http://localhost:8080/web/call/?mock=1` → **`http://localhost:8000/call/?mock=1`**
(`DEMO_SCRIPT.md:235` 의 `http://localhost:8080/web/call/` 도 같은 오류)

**D.** `DEMO_SCRIPT.md:267` 네트워크 끊김 행의 "아무것도 안 해도 된다" 를 아래로:
> **`.env` 의 키를 비우고 재기동한다.** 키가 남아 있으면 매 턴 죽은 API를 부르느라 최대 135초씩 멈춘다.
> ```
> OPENAI_API_KEY= ANTHROPIC_API_KEY= TYPECAST_API_KEY= \
> VOISSO_STT_PROVIDER=none VOISSO_TTS_PROVIDER=none python -m server
> ```
> 이 상태로 전 구간이 돈다(검증됨). 라우팅·MCP·방언 사전은 원래 네트워크가 필요 없다.

**E.** `DEMO_SCRIPT.md:270` — `VOISO_TTS_PROVIDER=none` → **`VOISSO_TTS_PROVIDER=none`** (S 두 개)

**F.** API 서버 다운 행에 한 줄 추가:
> **서버 프로세스가 죽었으면** `?mock=1` 로도 페이지를 못 받는다(페이지를 서버가 서빙하므로).
> 이때는 `web/call/index.html` 을 **파인더에서 더블클릭해 `file://` 로 연다.** 자동으로 목 모드가 된다. 완전 오프라인으로 동작한다.

---

## 발표 당일 체크리스트 (검증된 것만)

시연 30분 전:

```bash
# 1) 저하 상태 확인 — degraded 가 true 면 무엇이 꺼졌는지 missing_keys 로 보인다
curl -s localhost:8000/api/health | python3 -m json.tool | head -20

# 2) 키 없이도 도는지 확인 (10초)
python3 -m server.selftest

# 3) 부서 데이터가 있는지 확인 — 없으면 카드가 "미배정" 으로 나온다
python3 -c "import voisso.routing as r; print(r.data_status())"
```

무대에서 문제가 생기면 **순서대로**:

| 증상 | 조치 | 소요 |
|---|---|---|
| 음성이 안 먹힘 | 화면 하단 텍스트 입력창에 타이핑. 정규화·라우팅·카드 전부 동일하게 동작 **[실측]** | 0초 |
| 응답이 5초 넘게 안 옴 | 키를 비우고 재기동 (위 D의 명령) | 15초 |
| 서버가 죽음 | `web/call/index.html` 을 **더블클릭**해서 연다 (오프라인 목 모드) | 10초 |
| 전부 실패 | 녹화 영상 (아직 없음 — 촬영 필요) | — |

---

## 검증 방법 재현

이 보고서의 **[실측]** 항목은 아래로 재현된다.

```bash
# 시나리오 1 — 키 0개
OPENAI_API_KEY= ANTHROPIC_API_KEY= TYPECAST_API_KEY= \
VOISSO_TTS_PROVIDER=none VOISSO_STT_PROVIDER=none VOISSO_PORT=8099 python3 -m server

# 시나리오 2 — 잘못된 키 (audio_b64 로 턴 전송)
OPENAI_API_KEY=sk-proj-INVALIDKEY... VOISSO_STT_PROVIDER=openai VOISSO_PORT=8099 python3 -m server

# 시나리오 5 — 부서 데이터 없음
VOISSO_DATA_DIR=/tmp/empty VOISSO_PORT=8099 python3 -m server
```

시나리오 3·4(블랙홀·429·500)는 로컬 소켓으로 API 호스트를 흉내 내 측정했다. 남의 코드는 고치지 않고 모듈의 URL 상수만 테스트 프로세스 안에서 바꿔, `voisso.voice.stt.transcribe()` / `voisso.voice.tts.synthesize()` 를 **같은 경로로** 태워 잰 값이다.

| 조건 | STT | TTS |
|---|---|---|
| 무응답(블랙홀) | **60.01초** | **30.00초** |
| 연결 거부 | 0.00초 | — |
| 429 | 0.00초 | — |
| 500 | 0.00초 | — |

**미검증으로 남은 것:** 시나리오 6(마이크 권한 거부), 7(미지원 브라우저), 그리고 목 모드의 화면 동작. 브라우저 확장이 연결되지 않아 실행하지 못했다. 코드상으로는 세 가지 모두 처리 경로가 있고 한국어 안내 문구도 준비돼 있다. **P7이 Chrome에서 마이크를 차단하고, Safari로 한 번 열어 보면 10분 안에 확인된다.**
