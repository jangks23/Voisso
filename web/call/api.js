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
  /* API 주소 결정 — 하드코딩 금지. 지자체가 어느 호스트·포트에 올리든 그대로 동작해야 한다.
     우선순위: ?api= > API_BASE 가 명시된 절대주소 > 같은 오리진 > (file:// 일 때만) FILE_API_BASE */
  function resolveBase() {
    const q = qs.get('api');
    if (q != null && q !== '') return q.replace(/\/+$/, '');
    const cfg = CFG.API_BASE;
    if (typeof cfg === 'string' && /^https?:\/\//i.test(cfg)) return cfg.replace(/\/+$/, '');
    if (cfg === '') return '';                                   // 명시적으로 같은 오리진
    // 'auto' 또는 미설정
    if (location.protocol === 'http:' || location.protocol === 'https:') return '';
    return String(CFG.FILE_API_BASE || 'http://localhost:8000').replace(/\/+$/, '');
  }

  const base = resolveBase();
  // 화면에 보여줄 주소. 같은 오리진이면 빈 문자열이라 실제 주소로 바꿔 준다.
  const baseLabel = () => base || location.origin;

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

  async function get(path) {
    const res = await fetch(base + path, { method: 'GET' });
    if (!res.ok) {
      const err = new Error(`${path} 실패 (HTTP ${res.status})`);
      err.status = res.status; err.path = path;
      throw err;
    }
    return res.json();
  }

  /* ── 계약 5-B. 담당자 핸드오프 ─────────────────────────
     어르신 화면은 '조회'와 '메시지 보내기(role: caller)'만 쓴다.
     start 는 대시보드(담당자)가 호출한다. */
  async function handoffGet(complaintId) {
    const id = encodeURIComponent(complaintId);
    return useMock ? mock.handoffGet(id) : get('/api/handoff/' + id);
  }

  async function handoffSay(complaintId, text) {
    const id = encodeURIComponent(complaintId);
    const body = { role: 'caller', text: text };
    return useMock ? mock.handoffSay(id, body) : post('/api/handoff/' + id + '/message', body);
  }

  async function handoffClose(complaintId) {
    const id = encodeURIComponent(complaintId);
    return useMock ? mock.handoffClose(id) : post('/api/handoff/' + id + '/close', {});
  }

  /* ── 실서버 상태 확인 ──────────────────────────────────
     연결 여부뿐 아니라 **서버가 어떤 능력을 켰는지**도 함께 읽는다.
     프론트가 서버 설정을 하드코딩하면 서버가 STT 를 켜도 화면은 모른다. */
  async function probe() {
    if (useMock) return { mode: 'mock', ok: true, base: baseLabel(), stt: null };
    try {
      const res = await fetch(base + '/api/health', { method: 'GET' });
      if (res.ok) {
        const j = await res.json().catch(() => null);
        const rt = (j && j.runtime) || {};
        return {
          mode: 'server', ok: true, base: baseLabel(),
          stt: rt.stt || null, sttLabel: rt.stt_label || null,
          tts: rt.tts || null, engine: rt.engine || null,
          degraded: !!rt.degraded,
        };
      }
    } catch (e) { /* 아래 폴백으로 */ }
    // /api/health 가 없는 서버(계약 5절만 구현한 경우)도 지원한다.
    try {
      const res = await fetch(base + '/api/complaints', { method: 'GET' });
      return { mode: 'server', ok: res.ok, base: baseLabel(), stt: null };
    } catch (e) {
      return { mode: 'server', ok: false, base: baseLabel(), stt: null, error: String(e.message || e) };
    }
  }

  return { start, turn, end, probe, handoffGet, handoffSay, handoffClose,
           isMock: () => useMock, base: () => base, baseLabel };
})();
