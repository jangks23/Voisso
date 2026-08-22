# 경북 방언 레이어

Voisso(보이소)에서 **경북 어르신이 사투리로 말해도 시스템이 알아듣고, 시스템도
사투리로 답하게** 만드는 레이어다.

```
어르신 발화 ──STT──▶ normalize() ──▶ 라우팅·요약 (표준어 전제)
                                            │
경북 말투 ◀──TTS── to_dialect() ◀───────────┘
```

표준어만 아는 ARS는 80대 어르신에게 벽이다. 이 레이어는 그 벽의 양쪽을 다 헐어야 한다.
들어오는 쪽에서는 STT가 사투리를 잘못 받아적은 것을 교정하고, 나가는 쪽에서는
표준어 응답을 정중한 경북 말투로 바꾼다.

## 정직성 고지 — 읽고 인용할 것

**방언 음향 모델을 학습시키지 않았다.** 48시간 해커톤에서 음향 모델 파인튜닝은
불가능하고, 시도하지도 않았다. "사투리 TTS를 학습시켰다"는 주장은 하지 않는다.

여기서 하는 일은 두 가지다.

1. 출처가 기록된 어휘·어미 사전(`lexicon.json`) 기반 **결정론적 문자열 변환**
2. `VOISSO_DIALECT_LLM=1` 일 때만 켜지는 **선택적** LLM 다듬기 (기본 꺼짐)

사전에는 AI Hub 방언 코퍼스에서 온 항목이 **0개**다. 이용정책 제5항이 승인 없는
제3자 제공을 금지해 공개 저장소에 올릴 수 없기 때문이다. 배경과 대안은
[`SOURCES.md`](SOURCES.md) 참조.

## 빠른 확인

```bash
python -c "from voisso.dialect import normalize, to_dialect, lexicon_size; \
           print(lexicon_size()); \
           print(to_dialect('확인해 드리겠습니다. 담당자가 연락드릴 예정입니다.')); \
           print(normalize('물이 안 빠져가 큰일이라예'))"
```

```
382
확인해 드리겠습니더. 담당자가 연락드릴 예정입니더.
물이 안 빠져서 큰일이에요
```

의존성은 **없다.** 코어는 파이썬 표준 라이브러리만 쓴다. `anthropic` 은
선택적 import라 설치돼 있지 않아도 규칙 경로로 정상 동작한다.

## API (`docs/CONTRACT.md` §4)

```python
from voisso.dialect import normalize, to_dialect, lexicon_size

normalize(text: str) -> str     # 사투리 → 표준어 (STT 결과 교정)
to_dialect(text: str) -> str    # 표준어 → 경북 사투리 (TTS 입력)
lexicon_size() -> int           # 어휘 대응쌍 개수
```

계약 시그니처는 그대로 두고, 확장은 **키워드 전용 인자**로만 했다.

```python
to_dialect(text, strength="light")    # 종결어미만 (가장 보수적)
to_dialect(text, strength="polite")   # 기본값
to_dialect(text, strength="strong")   # 어휘까지, 데모용
normalize(text, use_llm=True)         # LLM 다듬기 강제 (키 필요)
```

부가 함수:

| 함수 | 용도 |
|---|---|
| `rule_count()` | 어미·문법 규칙 개수 |
| `explain(text, direction)` | 이 문장에 **실제로 적용된** 항목 목록. 대시보드 "사투리/표준어 대조 보기"용 |
| `source_counts()` | 출처별 항목 수 |
| `restricted_entries()` | 재배포 금지 출처 항목 (**항상 비어 있어야 한다**) |
| `closing_cues()` | 통화 마무리 신호 목록 — 종료/계속 판정용 (P6) |
| `soften(text)` | 행정 문체를 쉬운 말로. **`to_dialect()` 앞에 쓴다** |
| `admin_plain()` | 행정용어 → 쉬운 말 대응표 |
| `officer_to_dialect(text)` | **핸드오프(5-B)** — 담당자 채팅을 어르신 말투로 |
| `briefing_to_dialect(text)` | **진행 안내 콜백(5-C)** — AI 가 읽어 줄 브리핑으로 |
| `callback_question(text)` | 어르신 추가 질문을 AI 가 답해도 되는지 판정 |
| `deflection_line()` | 브리핑에 없는 것을 물었을 때 쓸 문장 |
| `detect_risk(text, history=[...])` | **긴급도(5-A)** — 위험 신호 탐지 |
| `detect_pressure(turns)` | 재촉·다급함 **반복** 탐지 |

### 긴급도 — 반복이 신호다 (5-A, P6 연동)

```python
from voisso.dialect import detect_risk

risk = detect_risk(caller_text, history=previous_caller_turns)
#  history 를 주면 통화 전체를 본다. 안 주면 단발 문장만 본다.
```

**`history` 를 반드시 넘겨라.** 실사용에서 이런 결함이 났다 — 집에 물이 차오르는
민원인이 "빨리와요!!!" 를 세 번 반복했는데 긴급도가 올라가지 않았다. 원인이 둘이었다.

1. `"빨리 좀 와 주이소"` 같은 어순 고정 패턴이라 구어 축약형 `"빨리와요"` 를 놓쳤다
2. 단발 문장만 봐서 **반복**이라는 정보가 들어갈 자리가 없었다.
   위험 표현("물이 차올라예")은 1턴에 나오고 재촉은 그 뒤에 반복되는데,
   현재 문장만 보면 위험이 사라진 것처럼 보인다

이제 위험 표현도 재촉도 **통화 전체**에서 찾는다.

#### 강도 설계가 전부다

"큰일이라예"는 경북에서 아주 흔한 일상 강조다. 1회로 올리면 오탐이 쏟아지고,
**오탐이 쏟아지면 진짜 응급이 묻힌다.** 그래서 표현마다 단독 강도를 두고 반복으로 판정한다.

| 강도 | 임계 | 예 |
|---|---|---|
| **강** | 1회 | 사람 살리 주이소 / 119 / 지금 당장 / 빨리와요 / 급합니더 |
| **중** | 2회 | 빨리 · 퍼뜩 · 언능 / 와 주이소 / 우짜노 / 야단났다 / 몬 살겠다 / 죽겠다 |
| **약** | 3회 | 큰일이라예 / 미치겠다 / 아이고 / 좀 해 주이소 |

느낌표 반복(`!!!`), 글자 늘임(`빨리이이`), 같은 말 되풀이는 **1회분으로 가산**된다.
임계값은 `risk_signals.json` 의 `pressure.thresholds` 에 있어 P6 이 조절할 수 있다.

#### 진행 중인가, 지나간 일인가

같은 "물이 들어온다" 라도 위험도가 다르다. `detect_risk()` 결과의 `tense` 에 실린다.

| 발화 | 판정 | 등급 |
|---|---|---|
| 지금 물이 들어와요 | 진행 | 응급 |
| 자꾸 물이 들어와예 | 진행 | 응급 |
| **어제** 물이 들어**왔어예** | 과거 | 중요 (한 단계 내림) |
| **어제부터** 물이 들어**옵니더** | 불명 | 응급 (서술어가 현재형이라 안 내린다) |

**내리는 조건은 아주 좁다.** 과거 수식어와 과거 서술어가 **둘 다** 있고, 진행 수식어가
없고, 다급함 반복도 없을 때만이다. 그리고 **침수 계열에만 적용한다** — 불·가스·붕괴·부상은
과거형이어도 현장이 그대로일 수 있어 내리지 않는다.

### 진행 안내 콜백 (5-C, P6 연동)

```python
from voisso.dialect import briefing_to_dialect, callback_question

dialect = briefing_to_dialect(briefing_text)   # 어르신이 들을 브리핑
# standard 는 원문 그대로 저장 (계약서 5-C: 둘 다 보관)

verdict = callback_question(caller_text)
if verdict["verdict"] == "relay":
    say(verdict["suggested_reply"])            # AI 가 답하지 않는다
    relay_to_officer(caller_text)
```

**핸드오프와 한 단계 다르다.** 브리핑은 **소리 내어 읽는다.** 공문은 "현장 확인 완료."
처럼 명사로 끝나는데, 그대로 읽으면 전화가 아니라 공문 낭독이 된다.

```
현장 확인 완료.
  → officer_to_dialect  : 현장 확인 완료.          (그대로 — 채팅이니 문제없다)
  → briefing_to_dialect : 현장 확인 다 했습니더.    (낭독용으로 폈다)
```

**절대 규칙을 코드로 지킨다.** `callback_question()` 은 "언제 됩니꺼?" 처럼 새 정보를
요구하는 질문을 `relay` 로 판정한다. **애매하면 항상 `relay` 다** — 지어내는 것보다
넘기는 편이 낫다. 브리핑에 없는 답을 AI 가 만들면 그것은 행정 약속이 된다.

변환 예시는 [`callback_samples.md`](callback_samples.md), 핸드오프는
[`handoff_samples.md`](handoff_samples.md) 참조. 둘 다 실행 결과에서 생성된다.

### 통화 마무리 (P6 연동)

슬롯이 다 찬 뒤 "더 하실 말씀 있으십니꺼?" 를 묻고, 대답이 종료인지 계속인지 가른다.
어르신이 "없다"를 말하는 방식은 아주 다양해서(없어예 / 됐어예 / 괘안타 / 그기 다라예 /
끝이라예 …) **이걸 못 알아들으면 통화가 끝나지 않는다.**

```python
from voisso.dialect import closing_cues, normalize

cues = closing_cues()          # {"closing_negative": [...64개], "closing_positive": [...31개]}
said = normalize(caller_text)

# 긍정을 먼저 본다 — 놓치면 민원을 잃는다
if any(c in said or c in caller_text for c in cues["closing_positive"]):
    ...   # 계속 듣는다
elif any(c in said or c in caller_text for c in cues["closing_negative"]):
    ...   # 담당자 연결로 넘어간다
```

목록에는 사투리형과 표준어형이 **둘 다** 들어 있다. `normalize()` 전후 어느 쪽에
매칭해도 걸리게 하려는 것이다.

### 담당자 핸드오프 — `soften()` 을 먼저 거쳐라

담당자는 공문체로 입력하는데 어르신은 그걸 사투리로 듣는다. `to_dialect()` 는 어미만
바꾸므로 그대로 넣으면 이렇게 된다.

```
관련 부서에 이첩하여 처리하도록 하겠습니다.
  → 관련 부서에 이첩하여 처리하도록 하겠습니더.     ← 표준어일 때보다 나쁘다
```

공무원이 사투리를 흉내 내는 소리가 된다. **낱말 난이도를 먼저 낮춰야 한다.**

```python
from voisso.dialect import soften, to_dialect
to_dialect(soften(staff_text))
```

```
해당 건은 검토 후 회신드리겠습니다.
  → 말씀하신 건은 살펴보고 연락드리겠습니더.        ← soften() 을 거친 결과
```

`soften()` 은 되돌릴 수 없는 의역이라 **`to_dialect()` 안에서 자동으로 불리지 않는다.**
부르는 쪽이 명시적으로 선택한다. 왕복 검증 대상도 아니다.

`explain()` 반환 예:

```python
>>> explain("접수해 드리겠습니다.", "to_dialect")
[{'kind': '어미', 'from': '습니다.', 'to': '습니더.', 'desc': '합쇼체 평서 -습니다 → -습니더'}]
```

## CLI

```bash
python -m voisso.dialect --demo              # 민원 상황 변환 예시 실행
python -m voisso.dialect --stats             # 사전 규모·도메인·출처 분포
python -m voisso.dialect --roundtrip-report  # 왕복 보존 통과율
python -m voisso.dialect --samples           # samples.md 내용 생성
python -m voisso.dialect --demo-lines        # demo_lines.md 내용 생성 (데모 1단계 대사)
python -m voisso.dialect --handoff           # handoff_samples.md (5-B 핸드오프)
python -m voisso.dialect --callback          # callback_samples.md (5-C 콜백)
python -m voisso.dialect -d "접수해 드리겠습니다" -v   # 표준어 → 경북 (적용 규칙 표시)
python -m voisso.dialect -n "어데서 물이 새노" -v      # 사투리 → 표준어
```

## 무엇이 어떻게 바뀌나

**어미가 체감 차이의 대부분이다.** 어휘를 많이 바꿀수록 좋아지는 게 아니다.

| 표준어 | 경북 (정중) |
|---|---|
| -습니다 / -ㅂ니다 | -습니더 / -ㅂ니더 |
| -습니까? / -ㅂ니까? | -습니꺼? / -ㅂ니꺼? |
| -아요 / -어요 / -할게요 | -아예 / -어예 / -할게예 |
| -세요 / -십시오 (명령) | -이소 (하세요 → 하이소) |
| -읍시다 / -ㅂ시다 | -입시더 / -ㅂ시더 |
| -죠 / -네요 / -거든요 | -지예 / -네예 / -거든예 |
| -인가요? | -인교? |

목표 화계는 **정중한 경북 말투**다. 어르신 대상 공공 서비스이므로
`억수로`, `-구마`, `-카이`, `가시나` 같은 표현은 `to_dialect` 에서 **의도적으로 뺐다.**
희화화된 사투리는 역효과다. (알아듣기는 해야 하므로 `normalize` 방향으로는 남아 있다.)

변환 예시 30개는 [`samples.md`](samples.md), 데모 1단계용 사투리 대사 10개와
라우팅 실측은 [`demo_lines.md`](demo_lines.md) — 둘 다 손으로 지어낸 기대값이 아니라
실제 실행 결과다. (`demo_lines.md` 의 STT 열만 예측이고, 파일 안에 그렇게 표시돼 있다.)

## 설계상 지킨 것

**부서명·전화번호는 보존된다.** 숫자·영문·대괄호 토큰은 변환 전에 마스킹된다.

```
건설도시국 도로과로 접수했습니다. 대표번호는 1522-0120입니다.
  → 건설도시국 도로과로 접수했습니더. 대표번호는 1522-0120입니더.
```

**어휘를 바꾸면 조사도 따라간다.** "차부가" → "버스터미널**이**" (받침이 생겼으므로).
단, 치환이 실제로 일어난 자리에서만 손댄다. 문장 전체에 돌리면 "마을"의 끝 글자
'을'을 조사로 착각해 "마를"로 망가뜨린다.

**어떤 실패도 통화를 끊지 않는다.** 사전 로딩 실패, 정규식 오류, LLM 타임아웃 —
전부 원문 또는 규칙 결과를 그대로 돌려준다.

## 품질 근거 — 왕복 보존 검사

이 모듈의 품질 근거는 사전 규모가 아니라 **왕복 검사**다.
`to_dialect` 로 만든 사투리를 `normalize` 로 되돌렸을 때 의미가 보존되는지 본다.

```bash
python -m voisso.dialect --roundtrip-report
```

```
왕복 보존 검사 — 표준어 문장 108개
  글자까지 동일 (exact)   : 105  (97.2%)
  의미 보존   (semantic)  :   3  (2.8%)
  실패        (fail)      :   0
```

되돌렸을 때 깨지는 규칙은 `lexicon.json` 에서 `roundtrip: false` 로 내려
`to_dialect` 에서 제외한다. **양보다 자연스러움이 먼저다.**

## 테스트

```bash
python -m unittest discover -s voisso/dialect/tests -t .
```

`pytest` 없이 표준 라이브러리 `unittest` 로 돈다. 검사 항목:

- 계약 시그니처, 빈 입력·초장문 방어
- 왕복 보존, 멱등성, **높임 등급 유지** (존댓말이 반말로 떨어지지 않는가)
- 최장일치와 **짧은 표제어로의 폴백** ("맥히가꼬" → "막혀서")
- 부서명·전화번호 보존, 사투리 없는 문장 비파괴
- 사전 스키마: 모든 항목의 `source` 필수, 중복·동일쌍 금지
- **라이선스 가드**: `aihub:` 출처 항목이 섞이면 실패
- 성능: 노트북에서 문장 100개 변환 < 1초

## 사전 고치기

`lexicon.json` 이 원본이다. 직접 고쳐도 되고, 초기 시드를 다시 만들 수도 있다.

```bash
python -m voisso.dialect.tools.seed_lexicon --force   # 시드 재생성 (수정분이 날아간다)
python -m voisso.dialect.tools.filter_lexicon --stats # 출처별 집계
```

항목을 추가할 때 지킬 것:

1. **`source` 를 반드시 채운다.** `curated:` / `wikipedia:` / `nikl:` 접두사 필수
2. **방언형과 표준형이 같으면 넣지 않는다.** 변환에 아무 일도 안 하는 패딩이다
3. **표준어와 충돌하는 짧은 낱말은 넣지 않는다.** "질"(길)을 넣으면 "질문"이 "길문"이 된다
4. `to_dialect` 역변환은 `reverse: true` 화이트리스트에만 허용한다
5. 고친 뒤 **왕복 검사와 테스트를 돌린다**

## 알려진 한계

- **연결어미 `-아/어 가`** (= -아/어서) 는 일반 규칙으로 만들지 않았다.
  "들어가·돌아가·걸어가" 같은 실제 동사와 구분할 방법이 없어서, 민원 통화에 자주
  나오는 어형만 항목으로 등록했다. 등록되지 않은 어형은 그대로 통과한다.
- **의문 종결 `-노/-나`** 는 앞 음절 화이트리스트로 판정한다. "피아노"를 "피아니"로
  만들지 않으려는 조치이고, 대신 드문 어형 일부가 변환되지 않는다.
- **`-라꼬` → `-려고`** 는 "갈라꼬"를 "갈려고"로 만든다. 표준형은 "가려고"지만
  정규식으로 한글 음절을 자모 분해할 수 없어 여기까지가 한계다. 뜻은 통한다.
- 사전은 **경북 기준**이다. 경남·부산 쪽 어형(`-능교` 등)은 `normalize` 로는
  알아듣지만 `to_dialect` 기본값으로는 생성하지 않는다.
- **STT가 방언 낱말을 다른 표준어 낱말로 바꿔 버리면 복구하지 못한다.** 예를 들어
  "수채구영"(하수구)이 "수채 구멍"으로 받아써지면 표제어가 사라져 사전이 걸리지 않는다.
  이 레이어의 전제는 "STT가 방언 음운을 소리 나는 대로 받아쓴다"이다.
  실제 사례는 [`demo_lines.md`](demo_lines.md) 의 «한계» 절에 있다.

## 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `VOISSO_DIALECT_LLM` | (꺼짐) | `1` 이면 LLM 다듬기 사용 |
| `ANTHROPIC_API_KEY` | — | LLM 다듬기에 필요 |
| `VOISSO_DIALECT_LLM_MODEL` | `claude-opus-5` | 다듬기 모델 |
| `VOISSO_OPENDICT_KEY` | — | (예약) 우리말샘 API 증강용 |

LLM 다듬기를 **기본으로 끈 이유**는 두 가지다. 전화 통화는 턴당 지연이 즉시
체감되고(규칙 변환은 수 ms), 호출마다 결과가 달라지면 민원 카드 문장이 매번
달라진다. LLM은 0→1이 아니라 1→1.2 역할만 한다 — 규칙 변환 결과를 받아
어색한 곳만 다듬고, 실패하면 조용히 규칙 결과로 돌아간다.

## 라이선스

코드는 저장소 루트의 MIT, **`lexicon.json` 은 CC BY-SA 4.0** 이다.
위키백과(CC BY-SA 4.0) 유래 항목이 있어 동일조건변경허락이 전파된다.
자세한 내용은 [`SOURCES.md`](SOURCES.md) §4.
