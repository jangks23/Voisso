/* Voisso 통화 데모 UI — 설정
 * ---------------------------------------------------------------------------
 * 서버(server/, P6)가 뜨면 아래 USE_MOCK 한 줄만 false 로 바꾸면 실서버로 붙는다.
 * 코드 수정 없이 쿼리스트링으로도 전환된다:
 *   index.html?mock=0                     -> 실서버 사용
 *   index.html?mock=0&api=http://localhost:8000
 * --------------------------------------------------------------------------- */
window.VOISSO_CONFIG = {
  // 'auto' : file:// 로 열면 목, http(s) 로 열면 실서버. (권장)
  // true    : 항상 목    /  false : 항상 실서버
  USE_MOCK: 'auto',

  /* API 주소.
   *   'auto'       : (권장) http(s) 로 서빙되면 **같은 오리진** — 호스트·포트가 무엇이든 따라간다.
   *                  file:// 로 열었을 때만 아래 FILE_API_BASE 를 쓴다.
   *   ''           : 항상 같은 오리진
   *   'http://...' : 주소 고정 (다른 호스트의 API 를 볼 때만)
   * 포트를 바꿔 띄우거나 다른 서버로 이관해도 코드를 고칠 필요가 없어야 한다. */
  API_BASE: 'auto',

  // file:// 로 파일을 직접 열었을 때만 쓰는 주소. http(s) 로 서빙되면 무시된다.
  FILE_API_BASE: 'http://localhost:8000',

  AUTO_PLAY_AUDIO: true,               // 응답에 audio_b64 가 있으면 자동 재생
  GREETING_ON_START: true,             // 통화 시작 직후 빈 turn 을 보내 첫 인사를 받아온다

  /* ── 음성 입력 경로 ───────────────────────────────────────────────────────
   * 'auto'  : 1) 브라우저 내장 음성인식(Web Speech, Chrome/Edge)
   *           2) 서버 STT (SERVER_STT=true 일 때만. MediaRecorder -> audio_b64)
   *           3) 텍스트 입력 (항상 가능)
   * 'web' | 'server' | 'text' 로 고정할 수도 있다. URL 로도 바꾼다: ?stt=web
   * ---------------------------------------------------------------------- */
  STT_MODE: 'auto',

  /* 서버 STT(Whisper 계열) 사용 여부.
   *   'auto'  : (권장) /api/health 의 runtime.stt 를 읽어 서버가 켜져 있으면 사용한다.
   *             하드코딩하지 않는다 — 서버가 켰는데 프론트가 모르면 그게 버그다.
   *   true    : 강제 사용 (health 를 못 읽어도)
   *   false   : 강제 미사용 (브라우저 음성인식 또는 텍스트만)
   *
   * ── 'auto' 일 때 서버 STT 를 브라우저 음성인식보다 앞에 두는 이유 ──
   *   실측(gpt-4o-transcribe, 경북 사투리 문장 10개):
   *     · 10/10 인식 성공, 발화당 평균 1.1초
   *     · **사투리 어미를 그대로 받아쓴다** — "옵니더 / 주이소 / 심더 / 마카 / 그라는데"
   *   브라우저 음성인식(Web Speech)은 표준어 기준이라 사투리를 표준어로 바꿔 적는 경향이 있다.
   *   우리 제품의 핵심은 "사투리를 받아서 → 정규화한다" 이므로,
   *   **입력 단계에서 사투리가 이미 지워지면 방언 레이어가 할 일이 없어진다.**
   *   그래서 정확도보다 '사투리 원문 보존'을 기준으로 서버 STT 를 기본으로 둔다.
   *   대신 지연이 약 +1초 늘고 비용이 발생하므로, 화면의 칩을 눌러 즉시 전환할 수 있게 했다.
   *   (브라우저 음성인식의 장점인 실시간 중간결과는 전환 한 번으로 바로 볼 수 있다) */
  SERVER_STT: 'auto',

  /* 브라우저 음성인식 세부 (Web Speech) */
  SPEECH_LANG: 'ko-KR',
  SPEECH_CONTINUOUS: true,             // 천천히 말하다 쉬어도 끊기지 않게
  SPEECH_SILENCE_MS: 1800,             // 이만큼 조용하면 한 턴이 끝난 것으로 본다
  SPEECH_ALTERNATIVES: 4,              // 후보 개수 — 많을수록 재점수화 여지가 커진다

  /* 방언 사전 재점수화: 표준어 기준 1순위 대신 '경북 사투리 민원처럼 들리는' 후보를 고른다.
     사전은 dialect-hints.js (voisso/dialect/lexicon.json 에서 생성). */
  HANDOFF_POLL_MS: 3000,               // 통화 종료 후 담당자 연결을 확인하는 주기 (계약 5-B)
  RESCORE_WITH_DIALECT: true,
  VOICE_REVEAL_MS: 700,                // 음성 발화의 정규화 결과를 보여주고 나서 상담원 답변을 띄우는 간격
  SEND_ALTERNATIVES: true,             // /api/call/turn 에 alternatives 도 함께 보낸다(추가 필드)
};
