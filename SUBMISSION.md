# Voisso (보이소) — 제출 폼

프로젝트명: **Voisso** · 한글명 **보이소**
이름 유래: "들어**보이소**"의 보이소 + **voice**

> 이 문서의 모든 수치는 실측값이다. 갱신 시 반드시 다시 측정해서 고칠 것.
> 대조 문서: [`README.md`](README.md) · [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) ·
> [`mcp_server/DEMO.md`](mcp_server/DEMO.md) · [`docs/DATA_LICENSE.md`](docs/DATA_LICENSE.md)

---

## Punchline (200자 제한)

### 영문안 (권장) — 175자
```
Gyeongbuk's elderly hang up on ARS menus. Voisso picks up the phone in their own dialect, understands the complaint, and routes it to the right desk at the provincial office.
```

### 국문안 — 74자
```
경북 어르신은 ARS 앞에서 전화를 끊습니다. Voisso는 사투리로 전화를 받고, 민원을 알아듣고, 경북도청의 담당 부서까지 연결합니다.
```

### 대안 (더 공격적) — 90자
```
ARS makes the elderly learn the system's menu. Voisso makes the system learn their dialect.
```

---

## Description (5000자 제한)

### 영문안 — 4,997자

```markdown
## The Problem

Press 1 for civil affairs, press 2 for taxation, press 3 to hear these options again.
Mildly annoying if you're under 50. A wall if you're an 80-year-old farmer in Uiseong.

Gyeongsangbuk-do has one of Korea's oldest populations. Those who most need their
government — a blocked culvert, a washed-out farm road — are least able to navigate a
nine-branch IVR tree. They give up, or drive to the county office. The tech isn't hard;
it just won't speak their language.

## What We Built

**Voisso (보이소)** — from *deureo-boiso*, "give it a listen," plus *voice* — answers in
Gyeongbuk dialect, holds a real conversation, and delivers a structured, routed complaint
to the right department. No menu to learn. They just talk.

> **Caller:** 집 앞에 물이 안 빠지고 자꾸 고이가꼬…
> **Voisso:** 물이 고인다 카시는 거네예. 어느 동네신지 여쭤봐도 될까예?

## The Infrastructure We Had to Build First

"Route the complaint to the right person" sounds like an LLM classification task. It
isn't. It's a data problem, and the data didn't exist in usable form.

Gyeongsangbuk-do publishes its full duty assignment — who handles what, the officer
responsible, their line — as HTML for human eyes. No API. Nothing an agent can query. We
scraped and normalized it (**96 departments, 1,866 duty entries**), then built an **MCP
server** exposing it to any agent:

`find_department` returns the department, officer, and duty text justifying the match;
`get_department`/`list_departments` expose the structure; `normalize_dialect`/
`to_dialect` convert dialect ↔ standard Korean; `submit_complaint` files the result.

Ask Claude Desktop, in dialect, "하수구가 막혔는데 어데 전화하믄 되노?" — you get 기후환경국
맑은물정책과 and the duty line making it their job: *"하수도 재난재해대책 수립 및 시행."*
Not hallucinated: it reads the province's own record.
**The server is useful without our service.** That's deliberate.

## We Ship the Scraper, Not the Dataset

The province's data is KOGL Type 3 — attribution, **no derivatives** — so rather than
redistribute a processed copy, we ship the scraper and let users generate it from the
rights holder's own site. **A bundled snapshot starts rotting the day it ships**, and
agencies reorganize constantly — routing to a department that no longer exists is worse
than not routing at all. We open-source not data but the method for making it.

## The Dialect Layer — Stated Honestly

**We did not train a dialect TTS model.** That claim appears nowhere in our repository —
fine-tuning an acoustic model in 48 hours isn't possible, and we didn't. What we built is
a **deterministic lexicon**: 367 vocabulary entries and 70 ending rules, **every one
source-tagged**. **Zero come from the AI Hub dialect corpus** — we reviewed it, found its
terms prohibit redistribution, and excluded it rather than ship a repo we couldn't
license cleanly.

Inbound, `normalize_dialect` repairs what standard-Korean STT mistranscribes; outbound,
the LLM answers in standard Korean and `to_dialect` rewrites it: "확인해 드리겠습니다"
→ "확인해 드릴게예." Accent depends entirely on the TTS voice selected: **the Typecast API
exposes no accent metadata, so we cannot verify how Gyeongbuk a voice sounds** — reported
as unverified rather than claimed.

**Stack:** Python · FastAPI · MCP SDK · `gpt-4o-transcribe` (STT) · Typecast `ssfm-v30`
(TTS). The conversation engine swaps provider in one env var — OpenAI, Anthropic, or a
rule engine needing no key. No local weights, no GPU; it runs on a laptop.

## For the Civil Servant

Intake is half the job; the other half is an official trusting what lands on the desk.
Every assignment shows **why** — the duty line that made it theirs — with transcript
and reassign button beside it.

When unsure, it says so. Below a measured confidence threshold, or when the caller's
words appear nowhere in the duty text, it returns ranked candidates instead of a verdict
— or just the province's main line.

It also knows what isn't its job. Streetlights and waste pickup are **city/county**
functions, absent from provincial duty text; our concept dictionary tags jurisdiction, so
"the streetlight is flickering" returns **zero departments** and a referral.

An AI that routes without justification is a liability in a public office; one that cites
its source is a tool.

## Limits

The demo runs over a browser microphone, not the PSTN; telephony is integration work,
not research. Our STT figure — 94–97% on dialect transcription — was measured by
round-tripping synthesized speech, **not real elderly speakers**; it is an upper bound.

We ported to Andong City to test this: **91 departments, 1,677 entries, ~75 minutes.**
URL swapping alone yields zero — each agency needs a ~150-line adapter — but the shared
collection layer is reused, and that adapter covered two more cities unchanged.

MIT licensed, on GitHub, runnable from the README alone; CI runs on every push, no
secrets.

We'd rather ship a system that says "I'm not sure which desk this belongs to" than one
that confidently sends a flooded street to the tourism division.
```

---

### 국문안

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

실제로 만든 건 **결정론적 사전**이다. 어휘 **367건**, 어미 규칙 **70건**, **전 항목 출처 표기**.
**AI Hub 방언 코퍼스에서 가져온 항목은 0건이다** — 검토했고, 이용정책이 제3자 재배포를
금지한다는 걸 확인했고, 라이선스가 깨끗하지 않은 저장소를 내놓느니 통째로 제외했다.

- **인바운드** — `gpt-4o-transcribe` 가 받아쓰고, `normalize_dialect`가 표준어 STT가 놓치는
  방언 어휘와 어미를 교정한다.
- **아웃바운드** — LLM이 표준어로 답하면 `to_dialect`가 다시 쓴다:
  "확인해 드리겠습니다" → "확인해 드릴게예."

억양과 운율은 전적으로 선택한 TTS 보이스에 달려 있다. **타입캐스트 API는 억양 메타데이터를
제공하지 않으므로, 특정 보이스가 얼마나 경북스러운지 우리는 검증할 수 없다.**
주장하지 않고 미검증으로 남긴다.

**스택:** Python · FastAPI · MCP SDK · `gpt-4o-transcribe`(STT) · Typecast `ssfm-v30`(TTS).
대화 엔진은 환경변수 하나로 제공자를 바꾼다 — OpenAI, Anthropic, 또는 키가 아예 필요 없는
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

근거 없이 배정하는 AI는 공공기관에서 부담이고, 출처를 대는 AI는 도구다.

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
- [ ] 🚧 **담당자 핸드오프 (양방향 통역)** — 계약 `docs/CONTRACT.md` 5-B절 고정, P6/P7/P8 구현 중.
      **완성 전까지 위 Description 본문에 넣지 않는다.** 완성되면 아래 「핸드오프 문구」 절의
      문단을 그대로 붙여넣는다
- [ ] 데모 영상 (통화 + 대시보드 왕복 + 담당자 핸드오프) — `docs/DEMO_SCRIPT.md` 대본대로 촬영
- [ ] 스크린샷 4종 → `docs/images/`
- [ ] 경북도청/주최측에 데이터 가공·공개 가능 여부 문의

---

## 🚧 핸드오프 문구 (완성되면 본문에 넣는다)

> **지금은 넣지 마라.** `docs/CONTRACT.md` 5-B절의 API 가 실제로 동작하고
> `docs/DEMO_SCRIPT.md` 5단계 촬영이 끝난 뒤에 아래를 본문으로 옮긴다.
> 판정 기준은 하나다 — **영상에 찍혔는가.** 찍히지 않았으면 넣지 않는다.

### 국문안에 추가할 문단 (여유 1,745자 중 약 400자 사용)

`## 담당 공무원 입장에서` 절의 마지막 문장 **앞**에 넣는다.

```markdown
**그리고 접수가 끝이 아니다.** 담당자가 민원카드에서 '통화 잇기'를 누르면 어르신과 직접
연결된다. 이때 **담당자는 표준어로 입력하고 어르신은 사투리로 듣는다.** 반대도 마찬가지다 —
"낼 오신다 캅니꺼?" 는 담당자 화면에 "내일 오신다 합니까?" 로 뜬다. 방언 레이어가 AI 응답을
만드는 부품에서 **사람과 사람 사이의 통역기**로 확장된다. 담당자가 경상도 사람이 아니어도
어르신과 대화할 수 있다.

핸드오프가 열리면 **AI 는 발화를 멈춘다.** 이 경계가 이 시스템의 핵심 설계다.
"AI 가 민원을 처리한다"는 공공기관이 받아들이지 않는다. "AI 가 접수를 돕고 담당자가
처리한다"는 받아들인다. **전권을 주는 게 아니라 접수까지만 맡기고 사람이 책임진다.**
```

### 영문안에 추가할 문단 (**514자 — 넣기 전에 같은 분량을 먼저 잘라야 한다**)

영문 Description 은 4,997/5,000자로 꽉 찼다. 아래 문단은 **514자**다. 절 크기를 재 보면
이렇고(합계 4,991자 + 절 사이 공백), 잘라낼 곳은 큰 절에서 찾는 게 맞다.

| 절 | 분량 | 잘라도 되는가 |
|---|---|---|
| `The Dialect Layer` | 1,121자 | ✅ 가장 크다. 아래 3번으로 46자, 문단 압축으로 200자 더 |
| `The Infrastructure…` | 1,011자 | ⚠️ 인프라 트랙의 핵심 주장이다. 건드리지 마라 |
| `For the Civil Servant` | 805자 | ⚠️ 핸드오프 문단이 **여기에 들어간다**. 늘어날 곳이다 |
| `Limits` | 767자 | ✅ 2번으로 51자. 정직성 서사라 더는 줄이지 마라 |
| `The Problem` | 482자 | ✅ 두 번째 문단을 한 문장으로 (약 200자 확보) |
| `We Ship the Scraper…` | 466자 | ✅ 1번으로 53자 |

**잘라낼 것 — 우선순위 순. 1~4를 다 하면 약 550자가 나온다(514자 필요).**

1. `We Ship the Scraper, Not the Dataset` 마지막 문장
   *"We open-source not data but the method for making it."* — **53자.** 닫는 문단과 중복
2. `Limits` 의 *"and that adapter covered two more cities unchanged."* — **51자.**
   `docs/PORTABILITY.md` 에 있고 심사에 결정적이지 않다
3. `The Dialect Layer` 의 *"— reported as unverified rather than claimed."* — **46자.**
   바로 앞 문장이 이미 같은 말을 한다
4. `The Problem` 두 번째 문단을 한 문장으로 압축 — **약 200자.**
   *"Gyeongsangbuk-do has one of Korea's oldest populations, and those who most need
   their government are least able to navigate a nine-branch IVR tree."* 정도면 된다
5. 그래도 모자라면 `The Dialect Layer` 의 AI Hub 제외 경위를 한 문장으로 줄인다 (약 150자)

**5,000자를 넘긴 채 제출하면 잘려 나간다. 넣은 뒤 반드시 다시 세라.**

넣을 문단 — `## For the Civil Servant` 절의 마지막 문장 **앞**:

```markdown
Intake isn't the end. The officer clicks "take the call" and speaks to the caller —
**typing standard Korean while the caller hears dialect,** and reading standard Korean
back. The dialect layer stops being a component the AI uses and becomes an interpreter
between two people; the officer need not be from Gyeongsang.

When the handoff opens, **the AI stops speaking.** That boundary is the design. "AI
handles the complaint" is not something a public office adopts. "AI takes the intake, a
person handles it" is.
```

**넣은 뒤 반드시 다시 세라.**

```bash
python3 - <<'EOF'
import re, pathlib
s = pathlib.Path("SUBMISSION.md").read_text(encoding="utf-8")
for i, b in enumerate(re.findall(r"```markdown\n(.*?)\n```", s, re.S), 1):
    print(f"블록 {i}: {len(b)}자 / 5000")
EOF
```

---

## 실측 수치 출처

| 수치 | 값 | 측정 방법 |
|---|---|---|
| 부서 수 | 96 | `scripts/scrape_gb_departments.py` 실행 결과 |
| 담당업무 건수 | 1,866 | 동일 |
| 방언 어휘 | 367 | `voisso/dialect/lexicon.json` → `entries` |
| 어미 규칙 | 70 | 동일 → `rules` |
| AI Hub 유래 항목 | **0** | 전 항목 `source` 태그 확인 (`curated:*`, `wikipedia:*`) |
| MCP 첫 응답 | 0.4초 (이후 밀리초) | `mcp_server/DEMO.md` 측정 |
| 스크레이퍼 소요 | 약 35초 | 데이터 없는 신규 클론에서 실측 (2회 재현) |
| 안동시 이식 | 91개 부서 / 1,677건 / 약 75분 | `docs/PORTABILITY.md` 실측 |
| STT 모델 | `gpt-4o-transcribe` | `voisso/voice/stt.py` `DEFAULT_MODEL` |
| TTS | Typecast `ssfm-v30` / Yongsik / tempo 0.85 / -14 LUFS | `voisso/voice/tts.py` |
| 담당자 핸드오프 | 🚧 **미구현** | 계약만 고정(`docs/CONTRACT.md` 5-B). **동작 확인 전까지 어떤 수치도 적지 마라** |
| STT 정확도 | 94~97% | **타입캐스트 합성음 왕복 측정. 실제 어르신 음성 아님.** ⚠️ 측정 산출물이 저장소에 없다 — 커밋 권장 |
