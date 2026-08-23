# 폴백 경로 검증 보고서

> **최초 검증:** 2026-08-21 · **재검증:** 2026-08-22 · **검증자:** P5 dialect
> 이 프로젝트의 성공 기준은 "완벽"이 아니라 **"끊기지 않음"** 이다.
> 이 문서는 폴백이 코드에 있다는 것이 아니라 **실제로 재현해서 확인한** 결과다.
>
> **재검증 사유:** 대화 엔진 rule → OpenAI 전환(`voisso/agent/providers.py` 신설), STT 활성화
> (gpt-4o-transcribe), TTS tempo/LUFS 추가, 라우팅 개념 사전 도입.
>
> 표기: **[실측]** 재현해서 측정 · **[코드]** 코드로 확인, 실행 못 함 · **[미검증]** 확인 못 함
>
> **브라우저 자동화는 쓰지 않았다.** Chrome은 P7 단독 사용이다. 전부 CLI/HTTP로 검증했고,
> 브라우저에서만 확인 가능한 항목은 **미검증으로 남겼다. 추측으로 통과 처리하지 않았다.**

---

## 재검증 요약 (2026-08-22)

**결론: 기능적 폴백은 전부 살아 있다. 단 하나 남은 치명적 문제는 「대기 시간」이다.**

키가 없어도, 키가 틀려도, 부서 데이터가 없어도, **네트워크가 완전히 죽어도**
통화는 끝까지 진행되고 민원카드가 근거와 함께 나온다 **[실측]**.
문제는 네트워크가 **무응답**일 때 4턴 통화가 **375초** 걸린다는 것이다.

### 이번에 확인된 변화

| 항목 | 이전(08-21) | 재검증(08-22) |
|---|---|---|
| 대화 엔진 폴백 | rule 고정이라 해당 없음 | ✅ **openai → rule 폴백 동작** (401에서 0.65초) |
| `meta.engine` | 없음 | ✅ 턴 응답에 실림 (`'rule'`) |
| `meta.timings` | 없음 | ✅ 구간별 ms 계측이 실려 온다 — 진단이 매우 쉬워졌다 |
| 시연 대비책 C·D·E·F | ❌ 4건 오류 | ✅ **P1이 전부 수정. 문서의 폴백 명령을 실제로 돌려 검증했다** |
| 타임아웃 A | 60/45/30초 | ❌ **그대로** |
| UI가 `meta` 읽기 B | 안 읽음 | ❌ **그대로** (`grep` 0건) |
| 클라이언트 타임아웃 I | 없음 | ❌ **그대로** |
| health `routing` G | 데이터 없어도 true | ❌ **그대로** |

### 발표 전 조치 우선순위

| # | 문제 | 심각도 | 소유자 |
|---|---|---|---|
| **A** | **무응답 네트워크에서 4턴 통화가 375초.** start 30초 + 턴당 75초 + end 45초 | 🔴 | P6 |
| **B** | **오류가 화면에 전혀 안 뜬다.** 백엔드는 다 알려주는데 UI가 `meta` 를 안 읽는다 | 🔴 | P7 |
| **J** | 엔진이 rule로 떨어진 **사유**가 턴 응답에 없다. `meta.engine` 만 바뀐다 | 🟠 | P6 |
| **K** | **health가 지연 반영.** 잘못된 키로 기동해도 첫 통화 전까지 `degraded=false` | 🟠 | P6 |
| **I** | `web/call/api.js` 에 요청 타임아웃 없음. 서버가 멈춘 만큼 브라우저도 멈춘다 | 🟠 | P7 |
| **L** | health의 `tts` 가 실패를 반영하지 않는다. 401을 두 번 맞아도 "음성 출력 (typecast)" | 🟡 | P6 |
| **G** | health의 `routing` 이 부서 데이터 없이도 `true` | 🟡 | P6 |
| **M** | `tts_error` 만 영어 원문. 나머지는 한국어 안내 | 🟡 | P6 |
| **H** | 통화 UI가 `/api/health` 를 호출하지 않아 저하 상태를 알 수 없다 | 🟡 | P7 |

---

## 시나리오별 재검증 결과

전부 **2026-08-22** 관측값이다.

| # | 장애 | 재현 방법 | 실제 동작 (관측값) | 사용자에게 보이는 것 | 데모 지속? | 조치 |
|---|---|---|---|---|---|---|
| **1** | **키 전부 없음** | `OPENAI_API_KEY= ANTHROPIC_API_KEY= TYPECAST_API_KEY= ELEVENLABS_API_KEY= python -m server` | **[실측]** `engine='rule'` `stt='none'` `tts='none'` `degraded=True`<br>`missing_keys=['OPENAI_API_KEY 또는 ANTHROPIC_API_KEY','OPENAI_API_KEY']`<br>4턴 **합계 0.01초** 완주 → 카드 `기후환경국 맑은물정책과` evidence **54자** | 서버 로그에 저하 상태. `meta.tts_error="TYPECAST_API_KEY 가 없어 텍스트 모드로 강등했습니다."` 매 턴 전달<br>**통화 화면에는 아무것도 안 뜸**(B) | ✅ 전 구간 | — |
| **2** | **OpenAI 키만 401** | `OPENAI_API_KEY=sk-proj-INVALIDKEY...` | **[실측]** 첫 턴 **0.65초**에 `meta.engine='rule'` 로 폴백, 통화 지속<br>통화 후 health: `engine='rule'`, `engine_label="규칙 기반 폴백 · OPENAI_API_KEY 가 거부되었습니다(401)..."`, `missing_keys=['openai 키(무효)']`, `agent.engine.llm_error` 에 사유 | **턴 응답에 사유가 없다.** `meta` 키 = `engine, rescored, stt_error, timings, tts, tts_error, turn` — **`engine_error`/`llm_error` 없음**<br>UI는 `meta` 자체를 안 읽음 | ⚠️ 진행되나 **조용히 떨어진다** | **J, B** |
| **3** | **Typecast 키만 401** | `TYPECAST_API_KEY=tc-INVALID... VOISSO_TTS_PROVIDER=typecast` | **[실측]** **0.15초 / 0.44초**에 폴백. `audio_b64=null`, 텍스트로 대화 지속<br>`meta.tts_error="HTTP 401 from https://api.typecast.ai/v1/text-to-speech: {"error_code":"AUTH_TOKEN_INVALID"...}"` | 텍스트만 나옴. **health는 실패를 반영 안 함** — 401을 두 번 맞은 뒤에도 `tts='typecast'`, `tts_label='음성 출력 (typecast)'`, `missing_keys` 에 typecast 없음 | ✅ 지연 없음 | **L, M, B** |
| **4** | **타임아웃 — API 호스트 전면 차단** | 무응답 블랙홀 프록시를 `HTTPS_PROXY` 로 물리고 실제 키 형식 유지 | **[실측] 서버 자체 계측(`meta.timings`)**<br>`{"normalize_ms":16.3, "llm_ms":45003.9, "dialect_ms":0.0, "tts_ms":30006.1, "total_ms":75026.4}`<br>`/api/call/start` **30.02초** (인사말 TTS)<br>턴 1~4 각 **75.0초**<br>`/api/call/end` **45.08초** (요약 LLM)<br>**→ 4턴 통화 총 375.1초 = 6분 15초** | **매 구간 화면이 멈춘 것처럼 보인다.** `api.js` 에 타임아웃이 없어 브라우저도 같이 멈춘다 | ❌ **데모 대본이 2분 30초다. 2.5배 초과** | **A, I** |
| **5** | **부서 데이터 없음** | `VOISSO_DATA_DIR=<빈 폴더>` | **[실측]** 정상 기동, 4턴 **0.01초** 완주<br>카드 `assigned.full_name='미배정 (수동 배정 필요)'`, evidence **67자** = `"자동 배정 보류(검색어 '하수도 정비 배수시설' 에 대한 후보 없음). 접수 내용: ..."` — **계약 §5의 "evidence 비면 안 된다" 준수**<br>서버 로그에 P4의 크롤러 실행 안내 출력 | 카드에 "미배정" 명시 | ⚠️ 데모 ③단계(사무분장 근거)는 못 보여준다 | **G** |
| **6** | **동시 실패 — 네트워크 전면 차단** | 위 블랙홀 + 모든 키 유효 형식 | **[실측] 기능적으로 완주한다.** `engine='rule'` 폴백, 4턴 전부 `done` 진행, `end` 에서 카드 `기후환경국 맑은물정책과` evidence **54자**. 라우팅은 로컬이라 무영향(`voisso/routing/` 네트워크 호출 **0건**)<br>**단 총 375초** | 위와 동일 | ⚠️ **기능 ✅ / 시간 ❌** | **A** |
| **6b** | **동시 실패 + 권장 대응** | 위 블랙홀 + `VOISSO_AGENT_PROVIDER=rule VOISSO_STT_PROVIDER=none VOISSO_TTS_PROVIDER=none` (**`.env` 의 실제 키는 그대로 둔 채**) | **[실측] `health: engine='rule' stt='none' tts='none' degraded=True`**<br>start 0.00초 / 턴 1~4 각 0.00초 / end 0.00초<br>**통화 전체 0.00초**, 카드 `기후환경국 맑은물정책과` evidence 54자 | 정상 | ✅ **완전 정상** | — |
| **7** | **마이크 권한 거부** | **[미검증]** 브라우저 자동화 금지 | **[코드]** `app.js:680` `getUserMedia` catch → 힌트 교체 + 토스트. `speech.js` 의 `not-allowed`/`service-not-allowed` 별도 처리 | **[코드]** "마이크를 쓸 수 없니더. 아래 칸에 글로 적어도 됩니더." + 토스트 4.5초 | **미검증** | **P7 E2E 대기** |
| **8** | **미지원 브라우저(Safari)** | **[미검증]** 동일 사유 | **[코드]** `speech.js:20` 에서 `SpeechRecognition \|\| webkitSpeechRecognition` 를 모듈 로드 시 캡처, `start()` 초입(`:84`)에서 없으면 `onError('이 브라우저는 음성 입력을 지원하지 않습니다.','unsupported')` 후 `false` | **[코드]** 힌트 영역에 위 문구. `STT_MODE:'auto'` 가 서버 STT → 텍스트 순으로 강등 | **미검증** | **P7 E2E 대기** |

---

## 시연 「실패 대비책」 재검증 — **이전 지적 4건 모두 수정 확인**

| 이전 지적 | 상태 | 확인 |
|---|---|---|
| **C** 목 모드 주소가 `localhost:8080/web/call/` | ✅ **수정됨** | 현재 `http://localhost:8000/call/?mock=1`. 실제 기본 포트 8000(`server/config.py:59`), 마운트 `/call`(`server/main.py:399`)과 일치 **[실측]** |
| **D** "아무것도 안 해도 된다" | ✅ **수정됨** | "⚠️ 아무것도 하면 안 된다" 로 바뀌고 폴백 명령이 명시됐다. **그 명령을 그대로 돌려 검증했다 → 통화 전체 0.00초** (시나리오 6b) **[실측]** |
| **E** `VOISO_TTS_PROVIDER` (S 하나) | ✅ **수정됨** | `VOISSO_TTS_PROVIDER` 로 정정 + "접두사는 `VOISSO_` 다" 경고 추가. 저장소에 `VOISO_` 잔재 **0건** **[실측]** |
| **F** 서버 사망 시 `?mock=1` 불가 | ✅ **수정됨** | `open web/call/index.html` (file:// 자동 목 모드) 안내 추가. 게다가 **"마이크는 보안 컨텍스트를 요구하니 평소엔 file:// 로 열지 마라"** 는 정확한 단서까지 붙었다 |

나머지 대비책도 재확인했다.

- **라우팅·MCP는 네트워크 불필요** → `voisso/routing/` 네트워크 호출 **0건**, 전면 차단 상태에서 `기후환경국 맑은물정책과` 를 evidence와 함께 반환 **[실측]**
- **STT 오인식 → "오히려 기회다"** → 유효. `voisso/dialect/demo_lines.md` 참조
- **전부 실패 → 녹화 영상** → **[미검증]** 영상 아직 없음

---

## 소유자별 요청

> 나는 `voisso/dialect/` 만 소유한다. 아래는 **직접 고치지 않고** 넘기는 항목이다.

### P6 — `server/`, `voisso/voice/`, `voisso/agent/`

**A. 타임아웃 단축 (최우선).** 현재 값은 배치 처리 기준이지 실시간 통화 기준이 아니다. 값이 이전 검증 이후 그대로다.

| 위치 | 현재 | 관측된 실제 대기 | 제안 |
|---|---|---|---|
| `voisso/agent/providers.py:125,140` | `timeout=45.0` | **45.00초** (`llm_ms=45003.9`) | **12초** |
| `voisso/agent/providers.py:223` | `timeout=30.0, max_retries=1` | — | **12초, `max_retries=0`** (재시도가 대기를 두 배로 만든다) |
| `voisso/voice/tts.py:319,368,432` | `timeout=30.0` | **30.01초** (`tts_ms=30006.1`) | **6초** — TTS는 없어도 텍스트로 진행된다 |
| `voisso/voice/tts.py:346` | `timeout=60.0` | — | **6초** |
| `voisso/voice/stt.py:220` | `timeout=60.0` | 60.01초(08-21 실측) | **8초** |

**턴 전체 상한도 함께 걸어 달라.** `server/main.py` 에 턴 단위 타임아웃이 없다 **[실측: grep 0건]**.
`asyncio.wait_for(..., 15)` 로 감싸고 초과 시 텍스트 모드로 즉시 반환하면, 개별 타임아웃이 어긋나도
화면은 15초 안에 반드시 응답한다.

**`/api/call/start` 도 30초 걸린다** — 인사말 TTS 때문이다 **[실측]**. 통화 시작 자체가 막히는 건
데모에서 가장 나쁜 그림이다. 인사말 오디오는 비동기로 빼거나 타임아웃을 더 짧게 잡아 달라.

**J. 엔진 폴백 사유를 턴 응답에 실어 달라.** 현재 `meta` 키는
`engine, rescored, stt_error, timings, tts, tts_error, turn` 이다. `engine` 이 `'openai'` → `'rule'` 로
바뀌지만 **왜 바뀌었는지가 없다.** `engine_status().llm_error` 에 이미 문구가 있으니
`meta.engine_error` 로 한 줄 실어 주면 P7이 그대로 띄울 수 있다.

```json
"meta": { "engine": "rule",
          "engine_error": "OPENAI_API_KEY 가 거부되었습니다(401). 키가 올바른지 확인하세요." }
```

**K. health가 지연 반영된다.** 잘못된 키로 기동한 직후에는 `engine='openai'`, `degraded=false`, `missing_keys=[]`
로 **정상처럼 보인다**. 첫 통화가 실패한 **뒤에야** `degraded=true` 로 바뀐다 **[실측]**.
→ **시연 30분 전 health 점검으로 잘못된 키를 못 잡는다.** 기동 시 가벼운 검증 호출을 한 번
돌리거나, health에 "아직 검증 안 됨(unverified)" 상태를 따로 표시해 달라.

**L. health의 `tts` 가 실패를 반영하지 않는다.** Typecast 401을 두 번 맞은 뒤에도
`tts='typecast'`, `tts_label='음성 출력 (typecast)'` 이고 `missing_keys` 에도 없다 **[실측]**.
엔진 쪽은 `engine_label="규칙 기반 폴백 · ..."` 로 잘 되어 있으니 같은 방식이면 된다.

**M. `tts_error` 만 영어 원문이다.** `"HTTP 401 from https://api.typecast.ai/... AUTH_TOKEN_INVALID"`.
STT는 `"OPENAI_API_KEY 가 거부되었습니다(401). 키가 올바른지 확인하세요."` 로 친절하다. 통일해 달라.

**G. health의 `routing` 플래그.** 부서 데이터가 없어도 `runtime.routing: true` 로 보고한다 **[실측]**.
같은 순간 `voisso.routing.data_available()` 은 `False` 다. 모듈 임포트 가능 여부와 데이터 준비 여부를
분리해 달라. P4의 `data_status()` 가 `available`/`next_step`/`message` 를 다 준다.

### P7 — `web/call/`

**B. `meta` 를 화면에 띄워 달라 (최우선).** `web/call/*.js` 어디에도 `meta` 를 읽는 코드가 없다
**[실측: grep 0건, 08-21·08-22 두 번 확인]**. 서버는 이미 이렇게 보낸다:

```json
{ "reply_dialect": "죄송합니더, 잘 안 들렸어예…",
  "meta": { "stt_error": "OPENAI_API_KEY 가 거부되었습니다(401). 키가 올바른지 확인하세요.",
            "tts_error": "TYPECAST_API_KEY 가 없어 텍스트 모드로 강등했습니다.",
            "engine": "rule",
            "timings": { "llm_ms": 45003.9, "tts_ms": 30006.1, "total_ms": 75026.4 } } }
```

`stt_error`/`tts_error` 를 토스트에 그대로 띄우고, `meta.engine === 'rule'` 이면 작은 배지를 보여 주면
**시연자가 무슨 일이 일어났는지 즉시 안다.** 지금은 "죄송합니더, 잘 안 들렸어예" 만 보여서 원인을
알 수 없다.

**I. `api.js` 에 요청 타임아웃.** `AbortController`/`AbortSignal` 이 없다 **[실측: grep 0건]**.
서버가 75초 멈추면 브라우저도 75초 멈춘다. 12~15초 `AbortSignal.timeout()` 을 걸고 중단 시
"응답이 늦습니다. 텍스트로 진행해 주세요" 를 띄우면 **P6의 서버 수정과 무관하게 화면이 먼저 살아난다.**

**H. 저하 상태 배지.** `app.js` 가 `/api/health` 를 한 번도 부르지 않는다 **[실측]**. 시작 시 한 번 불러
`degraded`/`missing_keys`/`engine_label` 을 작게 표시하면 시연 직전에 무엇이 꺼져 있는지 눈으로 확인된다.

**E2E 요청.** 시나리오 7(마이크 권한 거부)·8(Safari)은 **미검증으로 남겼다.** 브라우저 자동화를
쓰지 않았기 때문이다. Chrome에서 마이크를 차단하고, Safari로 한 번 열어 본 결과를 알려주면
이 표를 채우겠다. 코드상으로는 두 경로 모두 처리와 한국어 안내가 준비돼 있다.

### P1 — `docs/`

**이전 지적 4건이 전부 반영됐다. 추가 요청 없음.** 다만 시나리오 4 실측값이 갱신됐으니
시연 대본 네트워크 끊김 항목의 "STT 60초 + LLM 45초 + TTS 30초" 옆에
**"통화 시작에도 30초, 종료에도 45초 — 4턴 통화 총 375초"** 를 덧붙이면 위기감이 정확해진다.

---

## 발표 당일 체크리스트 (재검증 완료된 것만)

시연 30분 전:

```bash
# 1) 저하 상태 확인
curl -s localhost:8000/api/health | python3 -m json.tool | head -25
#    ⚠️ 주의: 잘못된 키는 첫 통화 전까지 잡히지 않는다(K). 아래 2번을 반드시 같이 돌려라.

# 2) 실제로 한 통화 돌려 본다 — 키 검증은 이것만 믿어라
python3 -m server.selftest

# 3) 부서 데이터 확인 — 없으면 카드가 "미배정" 으로 나온다
python3 -c "import voisso.routing as r; print(r.data_status())"
```

무대에서 문제가 생기면 **순서대로**:

| 증상 | 조치 | 근거 |
|---|---|---|
| 음성이 안 먹힘 | 화면 하단 텍스트 입력창에 타이핑 | 시나리오 1·5·6b 전부 텍스트로 완주 **[실측]** |
| **응답이 5초 넘게 안 옴** | 아래 명령으로 재기동 | **시나리오 6b 실측 — 통화 전체 0.00초** |
| 서버가 죽음 | `open web/call/index.html` (자동 목 모드, 텍스트 입력) | 시연 대본 반영됨 |
| 전부 실패 | 녹화 영상 | **아직 없음 — 촬영 필요** |

```bash
env VOISSO_AGENT_PROVIDER=rule VOISSO_STT_PROVIDER=none VOISSO_TTS_PROVIDER=none python3 -m server
```

> 이 명령은 **`.env` 의 실제 키를 그대로 둔 채** 네트워크 전면 차단 상태에서 검증했다.
> `health: engine='rule' stt='none' tts='none' degraded=True`, 통화 전체 **0.00초**,
> 카드 `기후환경국 맑은물정책과` evidence 54자 **[실측 2026-08-22]**.

---

## 검증 방법 재현

**브라우저 자동화 없음. 전부 CLI/HTTP.**

```bash
# 시나리오 1 — 키 0개
OPENAI_API_KEY= ANTHROPIC_API_KEY= TYPECAST_API_KEY= ELEVENLABS_API_KEY= python3 -m server

# 시나리오 2 — OpenAI 키만 무효
OPENAI_API_KEY=sk-proj-INVALIDKEY000... ANTHROPIC_API_KEY= VOISSO_TTS_PROVIDER=none python3 -m server

# 시나리오 3 — Typecast 키만 무효
TYPECAST_API_KEY=tc-INVALID-000... VOISSO_TTS_PROVIDER=typecast python3 -m server

# 시나리오 5 — 부서 데이터 없음
VOISSO_DATA_DIR=/tmp/empty python3 -m server
```

**시나리오 4·6(전면 차단)** 은 로컬 블랙홀 프록시로 서버의 아웃바운드를 통째로 막아 측정했다.
남의 코드는 고치지 않았다 — `HTTPS_PROXY`/`HTTP_PROXY` 환경변수만 썼다
(`voisso/voice/_http.py` 가 `urllib.request.urlopen` 기본 오프너를 쓰므로 프록시 설정을 따른다).

```python
# 연결은 받아 주고 응답은 절대 안 준다 — 캡티브 포털/패킷 드롭 재현
s = socket.socket(); s.bind(("127.0.0.1", 18111)); s.listen(64)
while True: held.append(s.accept()[0])
```

```bash
env HTTPS_PROXY=http://127.0.0.1:18111 HTTP_PROXY=http://127.0.0.1:18111 \
    NO_PROXY=127.0.0.1,localhost \
    OPENAI_API_KEY=sk-proj-... TYPECAST_API_KEY=tc-... python3 -m server
```

지연 수치는 추정이 아니라 **서버가 스스로 계측해 `meta.timings` 로 돌려준 값**이다.

| 구간 | 관측값 |
|---|---|
| `/api/call/start` | 30.02초 |
| 턴 1~4 (각각) | 75.0초 (`llm_ms` 45003.9 + `tts_ms` 30006.1) |
| `/api/call/end` | 45.08초 |
| **4턴 통화 합계** | **375.1초** |

**미검증으로 남은 것:** 시나리오 7(마이크 권한 거부), 8(미지원 브라우저), 목 모드의 실제 화면 동작.
브라우저 자동화를 쓰지 않기로 했으므로 **P7의 E2E 보고서를 기다린다. 추측으로 통과 처리하지 않았다.**
