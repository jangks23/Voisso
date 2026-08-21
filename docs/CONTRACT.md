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
     응답 {"reply_text","reply_dialect","audio_b64","done":false,"slots":{...}}
POST /api/call/end     {"session_id"} -> {"complaint": <민원카드>}
GET  /api/complaints                  -> {"complaints": [<민원카드>...]}
GET  /api/complaints/{id}             -> {"complaint": <민원카드>}
```

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

```
ANTHROPIC_API_KEY=       # 대화·요약·방언 변환
VOISSO_TTS_PROVIDER=      # typecast | elevenlabs | none   (기본 none = 텍스트 모드)
TYPECAST_API_KEY=
TYPECAST_VOICE_ID=
ELEVENLABS_API_KEY=
VOISSO_STT_PROVIDER=      # openai | none
OPENAI_API_KEY=          # Whisper API (로컬 모델 아님)
VOISSO_DATA_DIR=./data
```

## 8. 막히면

- 상대 모듈이 아직 없으면 **스텁/픽스처로 진행**하고, 계약서 시그니처만 지켜라.
- 2일짜리 해커톤이다. 완벽보다 **동작하는 것**이 우선. 단, mock 데이터로 끝내지 마라.
