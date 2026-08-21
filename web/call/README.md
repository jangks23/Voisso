# Voisso 통화 데모 UI (`web/call/`)

경북 어르신이 사투리로 민원을 말하면, AI가 대화로 정보를 모아 담당 부서로 넘기는 과정을
한 화면에서 보여주는 데모다. **빌드 스텝 없음. 의존성 없음. 파일을 열면 바로 뜬다.**

## 여는 법

```bash
# 1) 가장 간단 — 파일을 그대로 연다 (목 API로 전 과정 시연 가능)
open web/call/index.html            # macOS
xdg-open web/call/index.html        # Linux

# 2) 마이크를 쓰려면 로컬 서버로 여는 편이 안전하다
python3 -m http.server 8080         # 저장소 루트에서
# → http://localhost:8080/web/call/
```

브라우저 마이크(`getUserMedia`)는 보안 컨텍스트를 요구한다. `file://` 에서 막히면
위 2번처럼 `http://localhost` 로 열면 된다. 마이크가 없어도 **텍스트 입력만으로 전 과정이 동작한다.**

## 실서버로 전환

`config.js` 의 한 줄만 바꾼다.

```js
USE_MOCK: false,                     // ← 서버 준비되면 false
API_BASE: 'http://localhost:8000',   // "" 이면 같은 오리진
```

코드를 안 고치고 URL 로도 전환된다.

| URL | 동작 |
|---|---|
| `index.html` | 설정값 그대로 |
| `index.html?mock=0` | 실서버 (`API_BASE`) |
| `index.html?mock=0&api=http://localhost:8000` | 서버 주소 지정 |
| `index.html?mock=1` | **강제로 목 모드** — 데모 당일 서버·네트워크가 죽었을 때의 탈출구 |

대기 화면 하단에 현재 모드("데모 모드" / "서버 연결됨" / "서버 응답 없음")가 표시된다.

## 화면 구성

1. **대기** — 큰 통화 버튼(168px) → 누르면 "경상북도 민원실"로 발신
2. **통화 중**
   - 말풍선이 실시간 누적. 각 말풍선에 **[사투리 원문] / [표준어 변환] 토글**
     (표준어 문장에서 원문과 달라진 단어를 하이라이트해 변환 결과가 눈에 보인다)
   - 상단에 "표준어 변환 함께 보기" 전체 토글
   - 하단에 슬롯 4칸(**무슨 일 / 어디서 / 언제부터 / 연락처**)이 대화에 따라 실시간으로 채워짐
   - 입력: 텍스트(항상 제공) + 마이크(옵션, `MediaRecorder` → base64 → `audio_b64`)
   - 예시 답변 칩 — 시연 속도용. 누르면 바로 전송된다
3. **결과** — 민원카드 + "담당자에게 전달됨" 상태 전환.
   담당 부서, **연결 근거(사무분장 원문)**, 다음 후보와 점수, 발신자 마스킹 정보를 표시

접근성: 글자 크기 3단계(보통/크게/아주 크게), 밝기 3단계(시스템/밝게/어둡게) — 설정은 저장된다.
모든 조작 버튼은 최소 46~62px 높이. `prefers-reduced-motion` 존중.

## 파일

| 파일 | 역할 |
|---|---|
| `index.html` | 화면 3개(대기/통화/결과) 마크업 |
| `styles.css` | 디자인 토큰 + 라이트/다크 팔레트 |
| `config.js` | **전환 플래그**(USE_MOCK / API_BASE) |
| `api.js` | 계약서 5절 HTTP 클라이언트. 목/실서버를 같은 시그니처로 감쌈 |
| `mock-api.js` | 서버가 없을 때 쓰는 목. 계약 스키마 그대로 |
| `app.js` | 통화 흐름, 말풍선, 슬롯, 녹음/재생, 민원카드 |

## 서버(P6)와의 약속

**요청**은 계약서 그대로만 보낸다. 추가 필드를 넣지 않는다.

- `POST /api/call/start` → `{"session_id"}`
- `POST /api/call/turn` → `{"session_id","text"}` 또는 `{"session_id","audio_b64"}`
- `POST /api/call/end` → `{"session_id"}`

**응답**은 관대하게 읽는다. 아래는 서버가 주면 UI가 더 잘 보여주는 값들이다(없어도 동작한다).

| 필드 | 쓰임 |
|---|---|
| `reply_dialect`, `reply_text` | 상담원 말풍선의 사투리 원문 / 표준어. 하나만 와도 됨 |
| `slots` | 하단 슬롯 4칸. 키는 `what/where/when/contact` 권장 (`location`, `phone`, `연락처` 등 별칭도 매핑) |
| `audio_b64` | 있으면 재생, 없으면 조용히 텍스트만 표시(= 텍스트 모드 정상 동작) |
| `done` | true 면 "통화 끝내고 민원 접수" 버튼이 강조된다 |
| `caller_text` (또는 `stt_text`) | **음성 입력일 때 발신자 말풍선에 넣을 STT 결과.** 없으면 "(음성 발화)"로만 표시된다 |
| `caller_standard` (또는 `normalized_text`) | 발신자 발화의 표준어 변환. 없으면 원문을 그대로 표준어 자리에 넣는다 |

두 가지 부탁:

1. **통화 시작 직후 UI가 `turn` 을 `text: ""` 로 한 번 호출한다.** 이때 첫 인사를 돌려주면 된다.
   (원치 않으면 `config.js` 의 `GREETING_ON_START: false`)
2. `file://` 또는 다른 포트에서 열므로 **CORS 허용**이 필요하다.

## 목(mock)의 한계

`mock-api.js` 의 부서·근거·사투리 사전은 **데모용 픽스처**다.
실제 라우팅은 P4(`voisso/routing`) + `data/gb_departments.json`, 실제 사투리 변환은
P5(`voisso/dialect`)가 담당한다. 서버가 붙으면 목은 경로에서 완전히 빠진다.
