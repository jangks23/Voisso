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
   * ── 'auto' 일 때 브라우저 음성인식을 앞에 두는 이유 (2026-08-23 조정) ──
   *   서버 STT(gpt-4o-transcribe)는 사투리 어미를 그대로 받아쓴다(실측 10/10, 발화당 1.1초).
   *   그래서 한동안 이쪽을 기본으로 뒀다. 그러나 서버 STT 는 **발화가 끝나야 업로드**하므로
   *   말하는 동안 화면에 아무것도 채워지지 않는다 — 어르신에게는 멈춘 화면으로 보인다.
   *   "말하면 글자가 따라 나오는 것" 이 이 화면이 주는 확신이라, 실시간 중간결과를 우선한다.
   *   서버 STT 는 미지원 브라우저이거나 ?stt=server 로 명시했을 때만 쓴다.
   *   (사투리 원문 보존은 화면 표시가 아니라 서버 정규화·라우팅에서 책임진다) */
  SERVER_STT: 'auto',

  /* 브라우저 음성인식 세부 (Web Speech) */
  SPEECH_LANG: 'ko-KR',
  SPEECH_CONTINUOUS: true,             // 천천히 말하다 쉬어도 끊기지 않게
  SPEECH_SILENCE_MS: 1800,             // 이만큼 조용하면 한 턴이 끝난 것으로 본다
  SPEECH_ALTERNATIVES: 4,              // 후보 개수 — 많을수록 재점수화 여지가 커진다

  /* 방언 사전 재점수화: 표준어 기준 1순위 대신 '경북 사투리 민원처럼 들리는' 후보를 고른다.
     사전은 dialect-hints.js (voisso/dialect/lexicon.json 에서 생성). */
  // 응급(안전 안내가 뜬 상태)에서 서버가 done 을 주면 이만큼 뒤에 자동으로 접수한다.
  // 위험한 사람을 마무리 질문 루프에 붙잡아 두지 않기 위한 것이다. 0 이면 끈다.
  EMERGENCY_AUTO_END_MS: 2000,
  // 서버가 done 을 주면 마무리 멘트가 끝나고 이만큼 뒤에 접수완료 화면으로 넘어간다.
  DONE_AUTO_END_MS: 1200,
  HANDOFF_POLL_MS: 3000,               // 통화 종료 후 담당자 연결을 확인하는 주기 (계약 5-B)
  RESCORE_WITH_DIALECT: true,
  VOICE_REVEAL_MS: 700,                // 음성 발화의 정규화 결과를 보여주고 나서 상담원 답변을 띄우는 간격
  SEND_ALTERNATIVES: true,             // /api/call/turn 에 alternatives 도 함께 보낸다(추가 필드)
};
