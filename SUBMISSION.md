# Unbland — 제출 폼 초안

프로젝트명은 확정: **Unbland** (7/30)

---

## Punchline (200자 제한)

### 영문안 (권장)
```
Gyeongbuk's elderly hang up on ARS menus. Unbland picks up the phone in their own dialect, understands the complaint, and routes it to the right desk at the provincial office.
```
(172자)

### 국문안
```
경북 어르신은 ARS 앞에서 전화를 끊습니다. Unbland는 사투리로 전화를 받고, 민원을 알아듣고, 경북도청의 담당 부서까지 연결합니다.
```
(74자)

### 대안 (더 공격적)
```
ARS makes the elderly learn the system's menu. Unbland makes the system learn their dialect.
```
(92자)

---

## Description (5000자 제한)

### 영문안

```markdown
## The Problem

Press 1 for civil affairs, press 2 for taxation, press 3 to hear these options again.
Mildly annoying if you're under 50. A wall if you're an 80-year-old farmer in Uiseong.

Gyeongsangbuk-do has one of Korea's oldest populations. The people who most need to
reach their government — a leaking culvert, a collapsed farm road — are the least able
to navigate a nine-branch IVR tree. They give up, or drive to the county office. The
technology isn't too hard; it refuses to speak their language: flat standard Seoul
Korean, to people who speak Gyeongsang.

## What We Built

**Unbland** answers the phone in Gyeongsang dialect, holds a real conversation, and
delivers a structured, routed complaint to the right department. The caller doesn't
learn a menu. They just talk.

> **Unbland:** 예, 경상북도 민원실입니다. 어떤 일로 전화 주셨는교?
> **Caller:** 아 저기, 집 앞에 물이 안 빠지고 자꾸 고이가꼬…
> **Unbland:** 아이고, 물이 고인다 카시는 거네예. 어느 동네신지 여쭤봐도 될까예?
> **Caller:** 안동 옥동인데.
> **Unbland:** 예, 안동 옥동 배수 문제로 접수해 드릴게예. 연락처 하나만 남겨 주시믄
> 담당자가 전화드립니더.

## The Infrastructure We Had to Build First

"Route this to the right person" sounds like an LLM classification task. It isn't.
It's a data problem, and the data didn't exist in usable form.

Gyeongsangbuk-do publishes the full duty assignment of all **98 departments** — which
team handles what, the officer responsible, their direct line:

```
소속부서    직책    전화번호        담당업무
정책기획관  주무관  054-880-XXXX   도정 주요업무계획 수립, 도정질문 답변서 작성…
```

A complete routing table for a provincial government — existing only as HTML for human
eyes. No API. Nothing an AI agent can query.

So we built **`gb-civil-mcp`**, an MCP server exposing that structure and our dialect
resources as tools any AI agent can call:

| Tool | What it does |
|---|---|
| `find_department(text)` | Complaint → department, officer, direct line, and the duty text justifying it |
| `get_department` / `list_departments` | Full duty assignment; the 98-department structure |
| `normalize_dialect` / `to_dialect` | Dialect ↔ standard Korean, for STT correction and TTS input |
| `submit_complaint(summary)` | File a routed complaint |

Ask Claude Desktop, in dialect, "우리 동네 하수구가 막혔는데 어데 전화하믄 되노?" — you
get the department, the officer, the direct number, and the duty line that makes it
their job. Not hallucinated: it reads the province's own published record.
**The server is useful without our service.** That's deliberate.

## Public Data Used

1. **Gyeongsangbuk-do duty assignments & contact directory** (`gb.go.kr`) — all 98
   departments scraped, normalized, published as JSON/CSV. To our knowledge the first
   time it has been machine-readable.
2. **AI Hub — Korean Dialect Speech, Gyeongsang** (dataSetSn=119) — 2,000+ speakers and
   **500,000+ dialect↔standard-Korean aligned word pairs**, our lexicon source.
3. **AI Hub — Dialect Data, Middle-aged & Elderly Speakers** (dataSetSn=71517) —
   dialect as spoken by the demographic we're building for.

## How the Dialect Layer Works

We did not fine-tune an acoustic model in 48 hours. Instead:

- **Inbound** — STT, then `normalize_dialect` repairs the dialect vocabulary and
  endings that generic Korean STT mistranscribes, using the AI Hub pairs.
- **Outbound** — the LLM answers in standard Korean, then `to_dialect` rewrites it,
  lexicon-grounded: "확인해 드리겠습니다" → "지금 확인해 드릴게예."
- **Voice** — a cloned Gyeongsang-accented voice carries the prosody text can't.

Word choice and endings come from a real corpus, not an LLM's impression of Gyeongbuk.

## For the Civil Servant

Intake is half the job; the other half is an official trusting what lands on the desk.

```
민원 #0417  ·  접수 08-21 14:32  ·  통화 1분 48초
──────────────────────────────────────────────
요약   안동시 옥동 주택가 배수 불량, 강우 시 침수 반복
배정   건설도시국 도로과 · 054-880-XXXX
근거   담당업무: "우수관로 정비 및 배수시설 유지관리"
[원문 전사] [사투리→표준어 대조] [배정 변경]
```

Every assignment shows **why** — the exact duty line that made it this department's
responsibility, transcript one click away, reassignment always available. An AI that
routes without justification is a liability in a public office; one that cites its
source is a tool.

## Sustainability

MIT licensed, on GitHub, runnable from the README alone. The MCP server stands alone.
Reorganizations happen yearly; refresh is one command. The
scraper targets a standard Korean government CMS layout, so other provinces need a URL
change, not a rewrite — ready to transfer to a provincial government repository.

**Stack:** Python · FastAPI · MCP SDK · Claude · Whisper · cloned Korean TTS

## Limits, Stated Plainly

The demo runs over a browser microphone, not the PSTN; telephony is an integration
task, not a research one, and is documented in the README. Department matching is
retrieval over official duty text — ambiguous complaints surface several candidates
rather than guessing.

We'd rather ship a system that says "I'm not sure which desk this belongs to" than one
that confidently sends a flooded street to the tourism division.
```

### 국문 요약안 (국문 제출 시 사용)

핵심 골자는 위와 동일. 순서:
1. 문제 — 경북 고령 인구, ARS는 벽
2. 우리가 만든 것 — 사투리로 받는 음성 민원 접수
3. 먼저 푼 인프라 문제 — 도청 98개 부서 사무분장이 AI가 못 읽는 HTML로만 존재
4. gb-civil-mcp — MCP 서버 도구 목록
5. 사용 공공데이터 3종
6. 방언 레이어의 실제 동작 (학습이 아니라 코퍼스 기반 변환 + 클로닝, 정직하게)
7. 담당자 대시보드 — 배정 "근거" 표시
8. 왜 포털 조회 재탕이 아닌가
9. 지속가능성 — MCP 서버 단독 가치, 갱신 경로, 타 지자체 이식, MIT
10. 기술 스택
11. 한계 명시

---

## 제출 전 체크리스트

- [ ] GitHub 공개 저장소
- [ ] LICENSE 파일 (MIT)
- [ ] README만으로 실행 가능 — 처음 보는 사람 기준
- [ ] .env.example (API 키 절대 커밋 금지)
- [ ] 데모 영상 (통화 + 대시보드 왕복)
- [ ] 스크레이핑한 데이터셋 저장소에 포함
- [ ] AI Hub 데이터 출처·라이선스 표기
