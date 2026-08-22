/* Voisso 통화 데모 UI — API 클라이언트
 * ---------------------------------------------------------------------------
 * 계약서 5절 그대로. 목/실서버를 같은 함수 시그니처로 감싼다.
 * 요청 본문에는 계약에 없는 필드를 절대 넣지 않는다(서버가 strict 일 수 있다).
 * 응답은 관대하게 읽는다(서버가 추가 필드를 보내도 UI 는 깨지지 않는다).
 * --------------------------------------------------------------------------- */
window.VoissoAPI = (function () {
  'use strict';

  const CFG = window.VOISSO_CONFIG || {};
  const qs = new URLSearchParams(location.search);

  // 쿼리스트링 오버라이드: ?mock=0 -> 실서버, ?api=http://... -> 주소 지정
  //  'auto' = file:// 로 열면 목(서버 없이 시연), http(s) 로 열면 실서버
  let useMock;
  if (CFG.USE_MOCK === 'auto' || CFG.USE_MOCK == null) useMock = location.protocol === 'file:';
  else useMock = CFG.USE_MOCK !== false;
  if (qs.has('mock')) useMock = !/^(0|false|no)$/i.test(qs.get('mock'));
  const base = (qs.get('api') || CFG.API_BASE || '').replace(/\/+$/, '');

  const mock = window.VoissoMockAPI;
  if (useMock && !mock) console.warn('[Voisso] mock-api.js 가 로드되지 않았습니다.');

  async function post(path, body) {
    const res = await fetch(base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) {
      let detail = '';
      try {
        const raw = await res.text();
        try { detail = (JSON.parse(raw).detail || raw).slice(0, 200); } catch (e) { detail = raw.slice(0, 200); }
      } catch (e) {}
      const err = new Error(`${path} 실패 (HTTP ${res.status}) ${detail}`);
      err.status = res.status;          // 상위에서 사람이 읽을 문구로 바꾼다
      err.detail = detail;
      err.path = path;
      throw err;
    }
    return res.json();
  }

  /* ── 계약 5절 ─────────────────────────────────────────── */
  async function start() {
    const r = useMock ? await mock.start() : await post('/api/call/start', {});
    if (!r || !r.session_id) throw new Error('session_id 를 받지 못했습니다.');
    return r;
  }

  // text 와 audio_b64 는 둘 중 하나만 보낸다.
  async function turn(sessionId, payload) {
    const body = { session_id: sessionId };
    if (payload.audio_b64) body.audio_b64 = payload.audio_b64;
    else body.text = payload.text || '';
    return useMock ? mock.turn(body) : post('/api/call/turn', body);
  }

  async function end(sessionId) {
    const body = { session_id: sessionId };
    const r = useMock ? await mock.end(body) : await post('/api/call/end', body);
    return (r && r.complaint) ? r.complaint : r;
  }

  /* ── 실서버 헬스 체크(대기 화면 표시용. 실패해도 무해) ── */
  async function probe() {
    if (useMock) return { mode: 'mock', ok: true };
    try {
      const res = await fetch(base + '/api/complaints', { method: 'GET' });
      return { mode: 'server', ok: res.ok, base: base || location.origin };
    } catch (e) {
      return { mode: 'server', ok: false, base: base || location.origin, error: String(e.message || e) };
    }
  }

  return { start, turn, end, probe, isMock: () => useMock, base: () => base };
})();
