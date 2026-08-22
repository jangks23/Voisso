# Voisso (보이소) — 제출 폼

프로젝트명: **Voisso** · 한글명 **보이소**
이름 유래: "들어**보이소**"의 보이소 + **voice**

> 이 문서의 모든 수치는 실측값이다. 갱신 시 반드시 다시 측정해서 고칠 것.
> 대조 문서: [`README.md`](README.md) · [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) ·
> [`mcp_server/DEMO.md`](mcp_server/DEMO.md) · [`docs/DATA_LICENSE.md`](docs/DATA_LICENSE.md)

---

## Punchline (200자 제한)

### 영문안 (권장) — 174자
```
Gyeongbuk's elderly hang up on ARS menus. Voisso picks up the phone in their own dialect, understands the complaint, and routes it to the right desk at the provincial office.
```

### 국문안 — 4,984자
```
경북 어르신은 ARS 앞에서 전화를 끊습니다. Voisso는 사투리로 전화를 받고, 민원을 알아듣고, 경북도청의 담당 부서까지 연결합니다.
```

### 대안 (더 공격적) — 91자
```
ARS makes the elderly learn the system's menu. Voisso makes the system learn their dialect.
```

### 대안 (핸드오프 강조) — 영문 199자

접수까지는 AI, 그다음은 사람이 이어받는다. 방언 레이어가 그 사이에서 통역한다 —
**담당자는 표준어로 쓰고, 어르신은 사투리로 듣는다.**

```
Voisso answers Gyeongbuk's elderly in their dialect, routes the complaint citing the province's own duty text, then hands the call to a human who types standard Korean while the caller hears dialect.
```

---

## Description (5000자 제한)

### 영문안 — 4,989자

```markdown
## The Problem

Press 1 for civil affairs, press 2 for taxation, press 3 to hear these options again.
Mildly annoying if you're under 50. A wall if you're an 80-year-old farmer in Uiseong.

Gyeongsangbuk-do has one of Korea's oldest populations, and those who most need their
government are least able to navigate a nine-branch IVR tree. The tech isn't hard; it
just won't speak their language.

## What We Built

**Voisso (보이소)** — from *deureo-boiso*, "give it a listen," plus *voice* — answers in
Gyeongbuk dialect, holds a real conversation, and delivers a structured, routed complaint
to the right department. No menu to learn. Just talk.

> **Caller:** 집 앞에 물이 안 빠지고 자꾸 고이가꼬…
> **Voisso:** 물이 고인다 카시는 거네예. 어느 동네신지 여쭤봐도 될까예?

## The Infrastructure We Had to Build First

"Route the complaint to the right person" sounds like an LLM classification task. It
isn't. It's a data problem, and the data didn't exist in usable form.

Gyeongsangbuk-do publishes its full duty assignment — who handles what, the officer
responsible, their line — as HTML for human eyes. No API. Nothing an agent can query. We
scraped and normalized it (**96 departments, 1,866 duty entries**), then built an **MCP
server** exposing it to any agent: `find_department` returns the department, officer, and
the duty text justifying the match; `normalize_dialect`/`to_dialect` convert between
dialect and standard Korean.

Ask Claude Desktop, in dialect, "하수구가 막혔는데 어데 전화하믄 되노?" — you get 기후환경국
맑은물정책과 and the duty line making it their job: *"하수도 재난재해대책 수립 및 시행."*
Not hallucinated: it reads the province's own record.
**The server is useful without our service.** Deliberately so.

We ship the scraper, not the dataset: the province's data is KOGL Type 3, **no
derivatives**, so users generate it from the rights holder's own site. **A bundled
snapshot starts rotting the day it ships** — routing to a department that no longer exists
is worse than not routing.

## The Dialect Layer — Stated Honestly

**We did not train a dialect TTS model.** Fine-tuning an acoustic model in 48 hours isn't
possible, and we didn't. What we built is a **deterministic lexicon**: 382 vocabulary
entries and 71 ending rules, **every one source-tagged, zero from the AI Hub dialect
corpus** — its terms prohibit redistribution, so we excluded it entirely.

**Normalization is for the machine, not the listener.** Any Korean official understands
"물이 안 빠져가"; the retrieval layer does not — mistranscribed dialect becomes a bad search
string and routes to the wrong desk. We normalize, then match. Answering *in* dialect is a
smaller, separate claim: it keeps callers from freezing up. Accent depends on the TTS
voice, and **Typecast exposes no accent metadata — we cannot verify how Gyeongbuk a voice
sounds.** Unverified, not claimed.

## The Handoff — Where the AI Stops

Intake is half the job. The officer clicks "take the call" and speaks to the caller —
**typing standard Korean while the caller hears it in their own register.** Not because
the officer couldn't understand dialect, but so the caller keeps talking as they always
have — now to a person, not a machine.

When the handoff opens, **the AI stops speaking.** That boundary is the design. "AI
handles the complaint" is not something a public office adopts. "AI takes the intake, a
person handles it" is.

## Two Faces of One Screen

The caller's screen is a phone, not a chat log: one big button, a subtitle, 20px text,
status in words rather than color. Everything diagnostic lives
behind `?debug=1` — hidden, not deleted. Contrast 7.16:1 minimum, targets 44×44px:
accessibility by design, not assertion.

## For the Civil Servant

Every assignment shows **why** — the duty line that made it theirs — with transcript and
reassign button beside it. When unsure it says so, returning ranked candidates instead of a
verdict. It also knows what isn't its job: streetlights and waste pickup are
**city/county** functions, so "the streetlight is flickering" returns **zero departments**
and a referral.

An AI that routes without justification is a liability in a public office; one that cites
its source is a tool.

## Limits

The demo runs over a browser microphone, not the PSTN; telephony is integration work, not
research. Our STT figure — 94–97% — came from round-tripping synthesized speech, **not
real elderly speakers**; it is an upper bound.

We ported to Andong City to test portability: **91 departments, 1,677 entries, ~75
minutes.** URL swapping alone yields zero — each agency needs a ~150-line adapter — but
the collection layer is reused.

**Stack:** Python · FastAPI · MCP SDK · `gpt-4o-transcribe` (STT) · Typecast `ssfm-v30`
(TTS). The engine swaps provider in one env var — OpenAI, Anthropic, or a rule engine
needing no key. No GPU, no local weights. MIT licensed, runnable from the README alone.

We'd rather ship a system that says "I'm not sure which desk this belongs to" than one
that confidently sends a flooded street to the tourism division.
```

---

### 국문안 — 4,352자

```markdown
## 문제

1번 민원, 2번 세무, 3번 다시 듣기. 쉰 살 아래면 조금 성가신 정도다.
의성의 여든 살 농부에게는 벽이다.

경상북도는 전국에서 고령 인구 비율이 가장 높은 축에 든다. 행정을 가장 절실히 필요로 하는
사람들 — 막힌 배수로, 유실된 농로 — 이 아홉 갈래 ARS를 가장 못 넘는다. 포기하거나,
군청까지 직접 차를 몬다. 기술이 어려워서가 아니다. 그들의 말을 안 쓸 뿐이다.

## 우리가 만든 것

**Voisso(보이소)** — "들어보이소"의 보이소 + voice — 는 경북 사투리로 전화를 받고,
대화로 민원을 파악해, 담당 부서로 넘긴다. 어르신이 메뉴를 외울 필요가 없다. 말하면 된다.

> **Voisso:** 어떤 일로 전화 주셨는교?
> **어르신:** 집 앞에 물이 안 빠지고 자꾸 고이가꼬…
> **Voisso:** 물이 고인다 카시는 거네예. 어느 동네신지 여쭤봐도 될까예?

## 먼저 풀어야 했던 인프라 문제

"민원을 담당자에게 보낸다"는 건 LLM 분류 문제처럼 들린다. **아니다. 데이터 문제였고,
쓸 수 있는 형태의 데이터가 없었다.**

경상북도청은 전체 사무분장 — 어느 과가 무엇을 맡는지, 담당자와 연락처 — 을 공개한다.
단, **사람 눈으로 읽는 HTML로만** 존재한다. API도 없고 AI가 질의할 방법도 없다.
우리는 이걸 수집·정규화했다: **96개 부서, 담당업무 1,866건.**

그래서 **MCP 서버**를 만들었다. 어떤 AI 에이전트든 호출할 수 있는 도구다.

| 도구 | 하는 일 |
|---|---|
| `find_department(text)` | 민원 → 부서·담당자, 그리고 배정 근거가 된 사무분장 원문 |
| `get_department` / `list_departments` | 96개 부서 전체 구조 |
| `normalize_dialect` / `to_dialect` | 사투리 ↔ 표준어 |
| `submit_complaint(summary)` | 배정된 민원 접수 |

Claude Desktop에 사투리로 "하수구가 막혔는데 어데 전화하믄 되노?" 라고 물으면
**기후환경국 맑은물정책과**와 함께 그 근거가 나온다 — *"하수도 재난재해대책 수립 및 시행."*
지어낸 답이 아니라 도청이 공개한 원문을 읽은 것이다. 첫 응답 0.4초, 이후 밀리초 단위다.
**이 서버는 우리 서비스 없이도 쓸모가 있다.** 의도한 설계다.

## 데이터셋이 아니라 스크레이퍼를 공개한다

경북도청 자료는 **공공누리 제3유형**이다 — 출처표시 + **변경금지**. 가공본을 재배포하는
대신, 우리는 스크레이퍼를 공개하고 이용자가 **원본 권리자의 사이트에서 직접 생성**하게 했다.
명령 하나, 약 35초, 표준 라이브러리만 쓴다.

이건 타협이 아니다. **동봉된 스냅샷은 배포되는 날부터 낡기 시작한다.** 공공기관은 조직
개편이 잦고, 없어진 부서로 민원을 보내는 건 아예 안 보내는 것보다 나쁘다. 스크레이퍼는
언제나 **오늘의 조직도**를 만든다. 우리가 오픈소스로 내놓는 건 데이터가 아니라, 그것을
만드는 방법과 쓰는 인터페이스다.

## 방언 레이어 — 정직하게

**우리는 방언 TTS를 학습시키지 않았다.** 그런 주장은 저장소 어디에도 없다.
48시간에 음향 모델 파인튜닝은 불가능하고, 시도하지도 않았다.

실제로 만든 건 **결정론적 사전**이다. 어휘 **382건**, 어미 규칙 **71건**, **전 항목 출처 표기**.
**AI Hub 방언 코퍼스에서 가져온 항목은 0건이다** — 검토했고, 이용정책이 제3자 재배포를
금지한다는 걸 확인했고, 라이선스가 깨끗하지 않은 저장소를 내놓느니 통째로 제외했다.

**정규화는 사람이 아니라 기계를 위한 것이다.** 공무원은 "물이 안 빠져가"를 그냥 알아듣는다.
못 알아듣는 쪽은 **검색 계층**이다. 받아쓴 문장이 그대로 검색어가 되므로, 어긋나면
**사무분장 원문과 매칭되지 않아 엉뚱한 과로 간다.** 그래서 되돌린 다음 찾는다.

- **인바운드** — `gpt-4o-transcribe` 가 받아쓰고, `normalize_dialect`가 교정한다. **라우팅 정확도의 문제다.**
- **아웃바운드** — LLM이 표준어로 답하면 `to_dialect`가 다시 쓴다("확인해 드리겠습니다" →
  "확인해 드릴게예"). **이해가 아니라 편안함의 문제다** — 기계음성 앞에서 위축되지 않게 하는 것.

억양과 운율은 전적으로 선택한 TTS 보이스에 달려 있다. **타입캐스트 API는 억양 메타데이터를
제공하지 않으므로, 특정 보이스가 얼마나 경북스러운지 우리는 검증할 수 없다.**
주장하지 않고 미검증으로 남긴다.

**스택:** Python · FastAPI · MCP SDK · `gpt-4o-transcribe`(STT) · Typecast `ssfm-v30`(TTS).
대화 엔진은 환경변수 하나로 제공자를 바꾼다 — OpenAI, Anthropic, 또는 키가 필요 없는
규칙 엔진. 로컬 가중치도 GPU도 없다. 노트북에서 그대로 돈다.

## 담당 공무원 입장에서

접수는 절반이다. 나머지 절반은 책상에 올라온 것을 담당자가 믿을 수 있느냐다.
모든 배정에는 **왜**가 붙는다 — 그 부서 소관으로 만든 사무분장 원문, 클릭 한 번의 전사 기록,
언제든 가능한 재배정.

확신이 없으면 없다고 말한다. 측정된 임계값 아래이거나, 민원인이 쓴 단어가 사무분장 원문에
아예 없으면, 단정 대신 후보를 순위로 제시한다 — 그것도 아니면 도청 대표번호 1522-0120만
안내한다.

**소관이 아닌 것도 안다.** 가로등·보안등 유지관리와 생활폐기물 수거는 **시·군 소관**이라
도청 사무분장에 아예 없다. 개념 사전에 관할을 표시해 두어서, "가로등이 깜빡깜빡한다"는
**부서 0건**과 시·군 안내를 돌려준다. 그럴듯한 도청 부서를 억지로 붙이면 민원인은
헛걸음을 한다.

**급한 민원은 앞으로 보낸다.** 담당자는 하루에 수십 건을 받는다. 순서를 정해 주지 않으면
접수 순서대로 처리되고 급한 것이 뒤에 묻힌다. 그래서 카드에 **긴급도**(응급/중요/보통/낮음)와
**판정 근거 한 문장**을 함께 싣는다. 규칙이 먼저 판정하고 LLM은 **등급을 올릴 수만 있다** —
안전 쪽으로 치우치는 것이 옳기 때문이다.

**그리고 응급은 접수하고 끝내지 않는다.** 사람이 위험한 상황을 민원으로만 받고 통화를
끝내는 것이 이 시스템의 가장 큰 위험이다. "지금 집에 물이 차오르고 있어예"에는 접수보다
**119가 먼저**다. 다만 통보가 아니라 질문이다 — *"제가 119에 연결해 드릴까예?"* → "네" →
*"예, 119로 연결하겠습니더."* **어르신은 버튼보다 말이 편하다는 것이 이 서비스의 전제이므로,
안전 기능도 같은 원칙을 따른다.** 접수가 신고를 대체한다고 오해하게 만들지 않는다.

**그리고 접수가 끝이 아니다.** 담당자가 민원카드에서 '통화 잇기'를 누르면 어르신과 직접
연결되고, **담당자가 표준어로 입력하면 어르신에게는 익숙한 말투로 전달된다.**
담당자가 사투리를 못 알아들어서가 아니다 — 한국 사람은 다 알아듣는다.
**어르신이 하던 대로 말하게 두려는 것이다.** 기계 앞에서 말을 고르던 사람이,
이제 사람과 편하게 이야기한다.

핸드오프가 열리면 **AI는 발화를 멈춘다.** 이 경계가 이 시스템의 핵심 설계다.
"AI가 민원을 처리한다"는 공공기관이 받아들이지 않는다. "AI가 접수를 돕고 담당자가
처리한다"는 받아들인다. **전권을 주는 게 아니라 접수까지만 맡기고 사람이 책임진다.**

## 그리고 방향을 뒤집는다

접수가 끝난 뒤에도 문제가 하나 남는다. **어르신이 진행 상황을 알려면 다시 전화해서 ARS를
또 뚫어야 한다.** 우리가 없애려던 벽을 어르신이 다시 만나는 것이다.

그래서 **시스템이 먼저 건다.** 담당자가 진행 상황을 표준어로 쓰면 어르신에게 전화가 가고,
AI가 그 내용을 사투리로 읽어 준다. 어르신이 "그라믄 언제 옵니꺼?"라고 물으면 —
**AI는 답하지 않는다.** 담당자가 쓴 내용에 없기 때문이다. "담당자에게 여쭤보고 다시
연락드리겠습니더"로 넘기고, 질문은 받아 적어 담당자에게 전달한다.
**AI가 지어낸 일정은 행정 약속이 된다.** 그래서 AI는 담당자가 쓴 것만 전달한다.

(실제 전화망 연동은 아직이다. 지금은 브라우저 수신 화면 시뮬레이션이고, 문서에 그렇게 적었다.)

근거 없이 배정하는 AI는 공공기관에서 부담이고, 출처를 대는 AI는 도구다.

## 한 화면의 두 얼굴

어르신 화면에는 **큰 버튼 하나와 지금 오가는 말**만 있다. 본문 최소 20px, 통화 버튼 높이
200px, 상태는 색이나 아이콘이 아니라 **글자로** 알린다. 전사·슬롯·STT 경로·응답 지연 같은
진단 정보는 전부 `?debug=1` 시연 모드로 보냈다.

**지운 게 아니라 숨긴 것이다.** 어르신 모드에서 빠진 정보는 시연 모드에 그대로 다 있다.
접근성을 주장하지 않고 설계로 증명한다 — 명도 대비 최저 7.16:1, 조작 요소 44×44px 이상을
실제 브라우저에서 계산해 확인했다.

## 한계

데모는 실제 전화망(PSTN)이 아니라 **브라우저 마이크**로 돈다. 전화망 연동은 연구 과제가
아니라 통합 과제다. STT 정확도 94~97%는 **타입캐스트 합성음 왕복 측정**이며,
**실제 어르신 음성이 아니다.** 상한선으로 보아야 한다.

**이식을 실제로 해 봤다.** 안동시로 옮겨 **91개 부서 / 담당업무 1,677건**을 약 75분에
수집했다. 다만 "URL만 바꾸면 된다"는 사실이 아니다 — 기관마다 150줄짜리 파서 어댑터가
필요하다. 대신 공용 수집 계층은 그대로 재사용되고, 안동 어댑터는 문경·구미에 URL 교체만으로
통했다. 안동시는 **공공누리 제1유형**이라 도청(제3유형)보다 조건이 자유롭다.

MIT 라이선스, GitHub 공개, README만으로 실행 가능. CI는 시크릿 없이 매 푸시마다 돈다.

침수된 도로를 확신에 차서 관광과로 보내는 시스템보다,
"이건 어느 과 소관인지 잘 모르겠습니다" 라고 말하는 시스템을 내겠다.
```

---

## 제출 전 체크리스트

- [x] GitHub 공개 저장소
- [x] LICENSE 파일 (MIT)
- [x] README만으로 실행 가능 — 데이터 없는 신규 클론 기준 검증 완료
- [x] `.env.example` (API 키 절대 커밋 금지)
- [x] 데이터 라이선스 조사 문서화 (`docs/DATA_LICENSE.md`)
- [x] **데이터셋을 저장소에 포함하지 않음** — 스크레이퍼만 공개 (공공누리 제3유형 대응)
- [x] 방언 사전 전 항목 출처 표기 · AI Hub 유래 0건
- [x] MCP 서버 시연 대본 (`mcp_server/DEMO.md`)
- [x] CI (`.github/workflows/ci.yml`) — 시크릿 없이 Python 3.10/3.11/3.12 통과
- [x] 원터치 실행 (`./scripts/demo.sh`) · 통합 테스트 (`./scripts/test.sh`)
- [x] 타 지자체 이식 실증 (`docs/PORTABILITY.md`) — 안동시 91개 부서
- [x] **담당자 핸드오프 — 서버 API** (`docs/CONTRACT.md` 5-B) — 4개 엔드포인트 동작, 양쪽 말투 변환 확인
- [x] **어르신 모드 / 시연 모드 분리** — 기본 어르신 모드, `?debug=1` 로 진단 정보
- [x] **긴급도 판정** (`docs/CONTRACT.md` 5-A) — 응급 시 119 안내 우선까지 확인
- [x] **진행 안내 콜백 — 서버 API** (`docs/CONTRACT.md` 5-C) — 5개 엔드포인트 동작.
      브리핑 사투리 변환 + **AI가 일정을 지어내지 않는 것**까지 확인
- [ ] 🚧 **핸드오프 화면 · 콜백 수신 화면** (통화·대시보드) — P7/P8 구현 중. **화면이 안 되면 영상에서 뺀다**
- [ ] ⚠️ **타입캐스트 한도 초과로 현재 음성 꺼짐** — 촬영 전 계정 교체 필수
      (`docs/DEMO_SCRIPT.md` 촬영 체크리스트 0번)
- [ ] 데모 영상 (통화 + 대시보드 왕복 + 담당자 핸드오프) — `docs/DEMO_SCRIPT.md` 대본대로 촬영
- [ ] 스크린샷 4종 → `docs/images/`
- [ ] 경북도청/주최측에 데이터 가공·공개 가능 여부 문의

---

## 실측 수치 출처

| 수치 | 값 | 측정 방법 |
|---|---|---|
| 부서 수 | 96 | `scripts/scrape_gb_departments.py` 실행 결과 |
| 담당업무 건수 | 1,866 | 동일 |
| 방언 어휘 | **382** | `python3 -c "from voisso.dialect import lexicon_size; print(lexicon_size())"` |
| 어미 규칙 | **71** | `lexicon.json` → `rules` (표준어화 50 / 사투리화 21) |
| AI Hub 유래 항목 | **0** | 전 항목 `source` 태그 확인 (`curated:*`, `wikipedia:*`) |
| MCP 첫 응답 | 0.4초 (이후 밀리초) | `mcp_server/DEMO.md` 측정 |
| 스크레이퍼 소요 | 약 35초 | 데이터 없는 신규 클론에서 실측 (2회 재현) |
| 안동시 이식 | 91개 부서 / 1,677건 / 약 75분 | `docs/PORTABILITY.md` 실측 |
| STT 모델 | `gpt-4o-transcribe` | `voisso/voice/stt.py` `DEFAULT_MODEL` |
| TTS | Typecast `ssfm-v30` / Yongsik / tempo 0.85 / -14 LUFS | `voisso/voice/tts.py` |
| 라우팅 회귀 | **150/150 통과** | `python3 -m mcp_server.regression` — 실측·구어체·범위밖·응급·홀드아웃 + 일관성 13묶음. **사투리 표현이 달라도 같은 부서로 가는지**를 본다 |
| 긴급도 판정 | 규칙 우선 · LLM은 상향만 | "물이 차오르고 있어예" → `level: 응급`, `decided_by: rule`, `safety_referral: 119`. 접수보다 **119 연결 제안이 먼저** 나가는 것 확인 ("제가 119에 연결해 드릴까예?" → "네" → 연결) |
| 진행 안내 콜백 | 서버 API 동작 | `POST /api/callback/{id}/schedule·answer·message` 왕복 확인. "언제 옵니꺼?" → "담당자에게 여쭤보고 다시 연락드리겠습니더" (일정 생성 안 함) |
| 담당자 핸드오프 | 서버 API 동작 | `POST /api/handoff/{id}/start·message`, `GET /api/handoff/{id}` 로 왕복 확인. 화면은 작업 중 |
| 담당자 실명 | 저장 안 함 | 핸드오프 응답에서 `홍길동` → `홍○○` 로 마스킹 |
| 민원인 연락처 | 자릿수 보존 마스킹 | `010-1234-5678` → `010-****-5678`, `054-880-XXXX` → `054-***-1234` |
| 어르신 모드 | 본문 20px / 버튼 200px | `web/call/styles.css` `:root[data-mode="elder"]` |
| STT 정확도 | 94~97% | **타입캐스트 합성음 왕복 측정. 실제 어르신 음성 아님.** ⚠️ 측정 산출물이 저장소에 없다 — 커밋 권장 |
