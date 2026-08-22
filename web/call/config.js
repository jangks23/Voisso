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

  // 실서버 주소. ""(빈 문자열)이면 같은 오리진(현재 페이지 호스트)으로 요청한다.
  // file:// 로 열어도 되게 기본값은 로컬 서버를 가리킨다.
  API_BASE: 'http://localhost:8000',

  AUTO_PLAY_AUDIO: true,               // 응답에 audio_b64 가 있으면 자동 재생
  GREETING_ON_START: true,             // 통화 시작 직후 빈 turn 을 보내 첫 인사를 받아온다

  /* ── 음성 입력 경로 ───────────────────────────────────────────────────────
   * 'auto'  : 1) 브라우저 내장 음성인식(Web Speech, Chrome/Edge)
   *           2) 서버 STT (SERVER_STT=true 일 때만. MediaRecorder -> audio_b64)
   *           3) 텍스트 입력 (항상 가능)
   * 'web' | 'server' | 'text' 로 고정할 수도 있다. URL 로도 바꾼다: ?stt=web
   * ---------------------------------------------------------------------- */
  STT_MODE: 'auto',
  SERVER_STT: false,                   // 서버가 VOISSO_STT_PROVIDER=openai 로 떠 있으면 true

  /* 브라우저 음성인식 세부 (Web Speech) */
  SPEECH_LANG: 'ko-KR',
  SPEECH_CONTINUOUS: true,             // 천천히 말하다 쉬어도 끊기지 않게
  SPEECH_SILENCE_MS: 1800,             // 이만큼 조용하면 한 턴이 끝난 것으로 본다
  SPEECH_ALTERNATIVES: 4,              // 후보 개수 — 많을수록 재점수화 여지가 커진다

  /* 방언 사전 재점수화: 표준어 기준 1순위 대신 '경북 사투리 민원처럼 들리는' 후보를 고른다.
     사전은 dialect-hints.js (voisso/dialect/lexicon.json 에서 생성). */
  RESCORE_WITH_DIALECT: true,
  VOICE_REVEAL_MS: 700,                // 음성 발화의 정규화 결과를 보여주고 나서 상담원 답변을 띄우는 간격
  SEND_ALTERNATIVES: true,             // /api/call/turn 에 alternatives 도 함께 보낸다(추가 필드)
};
