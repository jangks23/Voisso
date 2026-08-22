/**
 * Voisso 담당자 대시보드 — 실행 설정
 *
 * 데모 당일 서버가 안 뜨는 상황에서도 화면은 보여야 한다.
 * 그래서 연결 실패는 오류가 아니라 "샘플 데이터로 폴백"으로 처리한다.
 */
window.VOISSO_DASHBOARD_CONFIG = {
  // true 로 두면 서버를 아예 찾지 않고 mock-data.js 로만 돈다(오프라인 시연용).
  // false 면 실서버 우선, 실패 시 자동 폴백.
  USE_MOCK: false,

  // "" = 이 화면을 서빙하는 서버와 같은 오리진.
  // server/main.py 가 /dashboard 로 마운트하므로 운영 기본값은 이대로 둔다.
  API_BASE: "",

  // 대시보드만 따로(file:// 등) 열었을 때 찾아볼 주소.
  //
  // 기본값을 비워 둔 이유: 포트를 추측해서 찔러보지 않기 위해서다.
  // 팀 규칙상 8000 과 8111(사용자 미리보기)은 금지이고, 각 에이전트 테스트 서버는
  // 8020~8025 로 흩어져 있어 '어딘가에 있겠지' 식 탐색은 엉뚱한 서버에 4초마다 붙는다.
  // 서버가 대시보드를 함께 서빙하면(운영 기본값) API_BASE:"" 로 이미 붙으므로 필요 없고,
  // 따로 열어야 할 때는 ?api=http://127.0.0.1:8025 처럼 주소를 명시한다.
  API_FALLBACKS: [],

  // ?api= 로 주소를 못박았는지. 못박았으면 다른 서버로 새지 않는다.
  API_PINNED: false,

  // 자동 갱신 주기(ms). 통화가 끝나면 새로고침 없이 목록에 뜬다.
  POLL_INTERVAL_MS: 4000,

  // 변화 없이 조용한 시간이 이어지면 주기를 늘린다(하루 종일 열어 두는 화면이라 부하가 쌓인다).
  // 새 민원이 들어오거나 담당자가 화면을 만지면 즉시 기본 주기로 돌아온다.
  POLL_IDLE_MS: 15000,
  POLL_IDLE_AFTER_MS: 120000,

  // 새 민원 NEW 뱃지 유지 시간(ms). 카드를 열어보면 그 전에 사라진다.
  NEW_BADGE_TTL_MS: 300000
};

// URL 로도 덮어쓸 수 있다 (데모 중 손이 빠른 쪽이 이긴다).
//   ?mock=1                        -> 강제 샘플 데이터
//   ?api=http://127.0.0.1:8025     -> API 주소 지정 (지정하면 그 주소만 쓴다)
//   ?poll=2000                     -> 폴링 주기 변경
(function () {
  var p = new URLSearchParams(location.search);
  var c = window.VOISSO_DASHBOARD_CONFIG;
  if (p.get("mock") === "1") c.USE_MOCK = true;
  if (p.get("mock") === "0") c.USE_MOCK = false;
  if (p.get("api")) { c.API_BASE = p.get("api").replace(/\/+$/, ""); c.API_PINNED = true; }
  if (p.get("poll")) c.POLL_INTERVAL_MS = Math.max(1000, Number(p.get("poll")) || 4000);
})();
