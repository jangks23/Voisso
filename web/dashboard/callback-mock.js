/**
 * 진행 안내 콜백 — 목(mock) 계층
 *
 * docs/CONTRACT.md 5-C 절의 엔드포인트를 브라우저 안에서 흉내낸다.
 * 서버(P6)가 /api/callback/* 를 올리면 app.js 가 실제 API 로 자동 전환한다.
 * (전환 판정: app.js > callbackLive)
 *
 * ── 이 목이 하지 않는 일 ──────────────────────────────────
 * **어르신 질문에 대한 답을 만들어 내지 않는다.** 계약 5-C 의 절대 규칙이다.
 * 처리 결과·일정·가능 여부를 AI 가 지어내면 그건 행정 약속이 된다.
 * 브리핑은 담당자가 쓴 문장을 사투리로 바꾼 것뿐이고, 그 밖의 질문은
 * DEFLECTION 문구로 넘긴다. 실제 AI 응답 생성은 서버(P6)가 같은 규칙으로 한다.
 *
 * 방언 변환은 handoff-mock.js 의 축약판을 그대로 쓴다(진짜는 voisso/dialect).
 */
(function () {
  "use strict";

  var LS_KEY = "voisso.dashboard.callback.mock.v1";

  // 브리핑에 없는 것을 물으면 이 문장으로 넘긴다. AI 가 답을 만들지 않는다.
  var DEFLECTION = "그건 지가 모르는 기라예. 담당자에게 여쭤보고 다시 연락드릴게예.";

  function dial() {
    var m = window.VOISSO_HANDOFF_MOCK;
    return m ? m.toDialect : function (t) { return t; };
  }
  function std() {
    var m = window.VOISSO_HANDOFF_MOCK;
    return m ? m.toStandard : function (t) { return t; };
  }

  function read() {
    try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; }
  }
  function write(all) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(all)); } catch (e) {}
  }
  function now() { return new Date().toISOString(); }

  function empty(id) {
    return {
      status: "none", callback_id: null, complaint_id: id,
      briefing: { standard: "", dialect: "" },
      officer: { name: "", department: "" },
      scheduled_at: null, answered_at: null, closed_at: null,
      messages: []
    };
  }

  window.VOISSO_CALLBACK_MOCK = {
    DEFLECTION: DEFLECTION,

    /** POST /api/callback/{id}/schedule */
    schedule: function (id, briefing, officerName, department) {
      var all = read();
      var text = String(briefing || "").trim();
      all[id] = {
        callback_id: "mockcb-" + id + "-" + Date.now().toString(36),
        status: "pending",
        // 원문과 사투리를 둘 다 남긴다 — 담당자가 "내가 쓴 대로 갔는가" 를 봐야 한다.
        briefing: { standard: text, dialect: dial()(text) },
        // 계약: 담당자 실명은 저장하지 않는다.
        officer: { name: "", department: department || "" },
        scheduled_at: now(), answered_at: null, closed_at: null,
        messages: []
      };
      write(all);
      return { callback_id: all[id].callback_id, status: "pending" };
    },

    /** POST /api/callback/{id}/answer — 어르신이 전화를 받았다 */
    answer: function (id) {
      var all = read(), c = all[id];
      if (!c || c.status !== "pending") return { status: c ? c.status : "none" };
      c.status = "answered";
      c.answered_at = now();
      // 받자마자 AI 가 브리핑을 읽어 준다. 담당자가 쓴 문장의 사투리 변환일 뿐이다.
      c.messages.push({
        role: "agent", text: c.briefing.standard,
        standard: c.briefing.standard, dialect: c.briefing.dialect, at: now()
      });
      write(all);
      return { status: "answered" };
    },

    /** POST /api/callback/{id}/message */
    message: function (id, role, text) {
      var all = read(), c = all[id];
      if (!c || c.status === "closed" || c.status === "none") return { ok: false };
      var m = role === "caller"
        ? { role: "caller", dialect: text, standard: std()(text), at: now() }
        : { role: "agent", standard: text, dialect: dial()(text), at: now() };
      m.text = m.standard;
      c.messages.push(m);
      write(all);
      return { ok: true, message: m };
    },

    /** GET /api/callback/{id} */
    get: function (id) {
      var c = read()[id];
      return c ? c : empty(id);
    },

    /** POST /api/callback/{id}/close */
    close: function (id) {
      var all = read();
      if (all[id]) { all[id].status = "closed"; all[id].closed_at = now(); write(all); }
      return { status: "closed" };
    },

    /** 목 전용 편의 — 실서버에는 이 조회가 없다 */
    statuses: function () {
      var all = read(), out = {};
      Object.keys(all).forEach(function (id) { out[id] = all[id].status; });
      return out;
    }
  };
})();
