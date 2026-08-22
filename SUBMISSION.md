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

### 영문안 — 4,999자

```markdown
## The Problem

Press 1 for civil affairs, press 2 for taxation, press 3 to hear these options again.
Mildly annoying if you're under 50. A wall if you're an 80-year-old farmer in Uiseong.

Gyeongsangbuk-do has one of Korea's oldest populations. The people who most need to
reach their government — a blocked culvert, a washed-out farm road — are least able to
navigate a nine-branch IVR tree. They give up, or drive to the county office. The tech
isn't too hard; it just refuses to speak their language.

## What We Built

**Voisso (보이소)** — from *deureo-boiso*, "give it a listen," plus *voice* — answers in
Gyeongbuk dialect, holds a real conversation, and delivers a structured, routed
complaint to the right department. The caller doesn't learn a menu. They just talk.

> **Voisso:** 어떤 일로 전화 주셨는교?
> **Caller:** 집 앞에 물이 안 빠지고 자꾸 고이가꼬…
> **Voisso:** 물이 고인다 카시는 거네예. 어느 동네신지 여쭤봐도 될까예?
> **Caller:** 안동 옥동인데.
> **Voisso:** 예, 안동 옥동 배수 문제로 접수해 드릴게예.

## The Infrastructure We Had to Build First

"Route the complaint to the right person" sounds like an LLM classification task. It
isn't. It's a data problem, and the data didn't exist in usable form.

Gyeongsangbuk-do publishes its full duty assignment — which team handles what, the
officer responsible, their line — as HTML for human eyes. No API. Nothing an agent can
query. We scraped and normalized it: **96 departments, 1,866 duty entries.**

So we built an **MCP server** exposing it as tools any agent can call:

| Tool | What it does |
|---|---|
| `find_department(text)` | Complaint → department, officer, duty text justifying it |
| `get_department` / `list_departments` | The full 96-department duty structure |
| `normalize_dialect` / `to_dialect` | Dialect ↔ standard Korean |
| `submit_complaint(summary)` | File a routed complaint |

Ask Claude Desktop, in dialect, "하수구가 막혔는데 어데 전화하믄 되노?" — you get 기후환경국
맑은물정책과 and the duty line making it their job: *"하수도 재난재해대책 수립 및 시행."*
Not hallucinated: it reads the province's own record. First answer in 0.4s, then
milliseconds. **The server is useful without our service.** That's deliberate.

## We Ship the Scraper, Not the Dataset

The province's data is published under KOGL Type 3 — attribution, **no derivatives**.
Rather than redistribute a processed copy, we ship the scraper and let each user
generate it from the rights holder's own site. One command, ~35 seconds.

This is not a compromise. **A bundled snapshot starts rotting the day it ships**, and
agencies reorganize constantly — routing to a department that no longer exists is worse
than not routing at all. The scraper always produces today's org chart. What we
open-source is not data; it's the method for making it and the interface for using it.

## The Dialect Layer — Stated Honestly

**We did not train a dialect TTS model.** That claim appears nowhere in our repository.
Fine-tuning an acoustic model in 48 hours isn't possible, and we didn't.

What we built is a **deterministic lexicon**: 367 vocabulary entries and 70 ending
rules, **every one source-tagged**. **Zero entries come from the AI Hub dialect
corpus** — we reviewed it, found its terms prohibit redistribution, and excluded it
rather than ship a repository we couldn't license cleanly.

- **Inbound** — Whisper transcribes, then `normalize_dialect` repairs the dialect
  vocabulary and endings standard-Korean STT mistranscribes.
- **Outbound** — the LLM answers in standard Korean, then `to_dialect` rewrites it:
  "확인해 드리겠습니다" → "확인해 드릴게예."

Accent and prosody depend entirely on the TTS voice selected. **The Typecast API exposes
no accent metadata, so we cannot verify how Gyeongbuk a voice sounds.** We report that
as unverified rather than claim it.

**Stack:** Python · FastAPI · MCP SDK · Claude · Whisper API (STT) · Typecast ssfm-v30
(TTS). No local weights, no GPU, no checkpoint downloads — it runs on a laptop.

## For the Civil Servant

Intake is half the job; the other half is an official trusting what lands on the desk.
Every assignment shows **why** — the exact duty line that made it this department's
responsibility, transcript one click away, reassignment always available.

When the system isn't sure, it says so. Below a measured confidence threshold, or when
the caller's words appear nowhere in the duty text, it returns ranked candidates instead
of a verdict — or just the province's main line, 1522-0120. An AI that routes without
justification is a liability in a public office; one that cites its source is a tool.

## Limits

The demo runs over a browser microphone, not the PSTN; telephony is an integration task,
not a research one. Our STT figure — 94–97% on dialect transcription — was measured by
round-tripping Typecast-synthesized speech, **not real elderly speakers**; treat it as
an upper bound.

MIT licensed, on GitHub, runnable from the README alone.

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

- **인바운드** — Whisper가 받아쓰고, `normalize_dialect`가 표준어 STT가 놓치는 방언 어휘와
  어미를 교정한다.
- **아웃바운드** — LLM이 표준어로 답하면 `to_dialect`가 다시 쓴다:
  "확인해 드리겠습니다" → "확인해 드릴게예."

억양과 운율은 전적으로 선택한 TTS 보이스에 달려 있다. **타입캐스트 API는 억양 메타데이터를
제공하지 않으므로, 특정 보이스가 얼마나 경북스러운지 우리는 검증할 수 없다.**
주장하지 않고 미검증으로 남긴다.

**스택:** Python · FastAPI · MCP SDK · Claude · Whisper API(STT) · Typecast ssfm-v30(TTS).
로컬 가중치도, GPU도, 체크포인트 다운로드도 없다 — 노트북에서 그대로 돈다.

## 담당 공무원 입장에서

접수는 절반이다. 나머지 절반은 책상에 올라온 것을 담당자가 믿을 수 있느냐다.
모든 배정에는 **왜**가 붙는다 — 그 부서 소관으로 만든 사무분장 원문, 클릭 한 번의 전사 기록,
언제든 가능한 재배정.

확신이 없으면 없다고 말한다. 측정된 임계값 아래이거나, 민원인이 쓴 단어가 사무분장 원문에
아예 없으면, 단정 대신 후보를 순위로 제시한다 — 그것도 아니면 도청 대표번호 1522-0120만
안내한다. 근거 없이 배정하는 AI는 공공기관에서 부담이고, 출처를 대는 AI는 도구다.

## 한계

데모는 실제 전화망(PSTN)이 아니라 **브라우저 마이크**로 돈다. 전화망 연동은 연구 과제가
아니라 통합 과제다. STT 정확도 94~97%는 **타입캐스트 합성음 왕복 측정**이며,
**실제 어르신 음성이 아니다.** 상한선으로 보아야 한다.

MIT 라이선스, GitHub 공개, README만으로 실행 가능.

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
- [ ] 데모 영상 (통화 + 대시보드 왕복) — `docs/DEMO_SCRIPT.md` 대본대로 촬영
- [ ] 스크린샷 4종 → `docs/images/`
- [ ] 경북도청/주최측에 데이터 가공·공개 가능 여부 문의

---

## 실측 수치 출처

| 수치 | 값 | 측정 방법 |
|---|---|---|
| 부서 수 | 96 | `scripts/scrape_gb_departments.py` 실행 결과 |
| 담당업무 건수 | 1,866 | 동일 |
| 방언 어휘 | 367 | `voisso/dialect/lexicon.json` → `entries` |
| 어미 규칙 | 70 | 동일 → `rules` |
| AI Hub 유래 항목 | **0** | 전 항목 `source` 태그 확인 (`curated:*`, `wikipedia:*`) |
| MCP 첫 응답 | 0.4초 | `mcp_server/DEMO.md` 측정 |
| 스크레이퍼 소요 | 약 35초 | 신규 클론에서 실측 |
| STT 정확도 | 94~97% | **타입캐스트 합성음 왕복 측정. 실제 어르신 음성 아님.** |
