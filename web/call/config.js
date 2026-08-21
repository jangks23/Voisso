/* Voisso 통화 데모 UI — 설정
 * ---------------------------------------------------------------------------
 * 서버(server/, P6)가 뜨면 아래 USE_MOCK 한 줄만 false 로 바꾸면 실서버로 붙는다.
 * 코드 수정 없이 쿼리스트링으로도 전환된다:
 *   index.html?mock=0                     -> 실서버 사용
 *   index.html?mock=0&api=http://localhost:8000
 * --------------------------------------------------------------------------- */
window.VOISSO_CONFIG = {
  USE_MOCK: true,                      // ← 서버 준비되면 false

  // 실서버 주소. ""(빈 문자열)이면 같은 오리진(현재 페이지 호스트)으로 요청한다.
  // file:// 로 열어도 되게 기본값은 로컬 서버를 가리킨다.
  API_BASE: 'http://localhost:8000',

  AUTO_PLAY_AUDIO: true,               // 응답에 audio_b64 가 있으면 자동 재생
  GREETING_ON_START: true,             // 통화 시작 직후 빈 turn 을 보내 첫 인사를 받아온다
};
