/**
 * 담당자 핸드오프 — 목(mock) 계층
 *
 * docs/CONTRACT.md 5-B 절의 엔드포인트를 브라우저 안에서 그대로 흉내낸다.
 * 서버(P6)가 /api/handoff/* 를 올리면 app.js 가 실제 API 로 자동 전환하고
 * 이 파일은 쓰이지 않는다. (전환 판정: app.js > detectHandoffApi)
 *
 * 저장 위치는 localStorage 라 브라우저를 넘어가지 않는다. 서버가 붙기 전까지의
 * UI 완성·시연용이며, 실제 운영에서는 서버가 상태를 들고 있어야 한다.
 *
 * ── 방언 변환에 대하여 ────────────────────────────────────────────
 * 진짜 변환은 `voisso/dialect/` (P5) 의 normalize() / to_dialect() 가 한다.
 * 여기 있는 것은 **서버가 없을 때 화면을 보여 주기 위한 축약판**이다.
 * 규칙 수십 개짜리 근사치이므로, 서버가 붙으면 즉시 그쪽 결과를 쓴다.
 */
(function () {
  "use strict";

  var LS_KEY = "voisso.dashboard.handoff.mock.v1";

  // ── 표준어 -> 경북 사투리 (담당자 입력이 어르신에게 보이는 형태)
  var TO_DIALECT = [
    [/감사합니다/g, "고맙심더"],
    [/죄송합니다/g, "죄송합니더"],
    [/알겠습니다/g, "알겠심더"],
    [/그렇습니다/g, "그렇심더"],
    [/하겠습니다/g, "하겠심더"],
    [/했습니다/g, "했심더"],
    [/합니다/g, "합니더"],
    [/입니다/g, "입니더"],
    [/습니다/g, "심더"],
    [/하세요/g, "하이소"],
    [/주세요/g, "주이소"],
    [/보세요/g, "보이소"],
    [/세요/g, "시이소"],
    [/할까요/g, "할까예"],
    [/인가요/g, "인교"],
    [/나요\?/g, "는교?"],
    [/어요/g, "어예"],
    [/아요/g, "아예"],
    [/네요/g, "네예"],
    [/지요/g, "지예"],
    [/어디/g, "어데"],
    [/무엇/g, "머"],
    [/빨리/g, "퍼뜩"],
    [/많이/g, "마이"],
    [/그런데/g, "근데예"],
    [/조금만/g, "쪼매만"]
  ];

  // ── 경북 사투리 -> 표준어 (어르신 발화가 담당자에게 보이는 형태)
  var TO_STANDARD = [
    [/고맙심더/g, "감사합니다"],
    [/알겠심더/g, "알겠습니다"],
    [/그렇심더/g, "그렇습니다"],
    [/하겠심더/g, "하겠습니다"],
    [/했심더/g, "했습니다"],
    [/합니더/g, "합니다"],
    [/입니더/g, "입니다"],
    [/심더/g, "습니다"],
    [/하이소/g, "하세요"],
    [/주이소/g, "주세요"],
    [/보이소/g, "보세요"],
    [/니껴\?/g, "니까?"],
    [/니껴/g, "니까"],
    [/는교\?/g, "나요?"],
    [/인교\?/g, "인가요?"],
    [/카이/g, "니까"],
    [/가꼬/g, "가지고"],
    [/어예/g, "어요"],
    [/아예/g, "아요"],
    [/라예/g, "라고요"],
    [/어데/g, "어디"],
    [/퍼뜩/g, "빨리"],
    [/마이/g, "많이"],
    [/쪼매/g, "조금"],
    [/억수로/g, "매우"],
    [/우얄/g, "어떻게 할"],
    [/겁나가/g, "무서워서"]
  ];

  function convert(text, rules) {
    var s = String(text == null ? "" : text);
    rules.forEach(function (r) { s = s.replace(r[0], r[1]); });
    return s;
  }

  function read() {
    try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; }
  }
  function write(all) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(all)); } catch (e) {}
  }

  function now() { return new Date().toISOString(); }

  window.VOISSO_HANDOFF_MOCK = {
    /** 방언 변환기 — 서버가 없을 때만 쓰이는 근사치 */
    toDialect: function (t) { return convert(t, TO_DIALECT); },
    toStandard: function (t) { return convert(t, TO_STANDARD); },

    /** POST /api/handoff/{id}/start */
    start: function (id, officerName, department) {
      var all = read();
      all[id] = {
        channel_id: "mock-" + id + "-" + Date.now().toString(36),
        status: "open",
        started_at: now(),
        // 계약: 담당자 실명을 저장하지 않는다. 목에서도 지킨다 —
        // 이름은 이 세션의 화면 표시용으로만 app.js 가 들고 있고 여기 남기지 않는다.
        officer: { name: "", department: department || "" },
        messages: []
      };
      write(all);
      return { channel_id: all[id].channel_id, status: "open", started_at: all[id].started_at };
    },

    /** POST /api/handoff/{id}/message */
    message: function (id, role, text) {
      var all = read();
      var h = all[id];
      if (!h || h.status !== "open") return { ok: false };
      var m = role === "officer"
        // 담당자는 표준어로 친다 -> 어르신 화면에는 사투리로 간다
        ? { role: "officer", standard: text, dialect: convert(text, TO_DIALECT), at: now() }
        // 어르신은 사투리로 말한다 -> 담당자 화면에는 표준어로 보인다
        : { role: "caller", dialect: text, standard: convert(text, TO_STANDARD), at: now() };
      m.text = m.standard;
      h.messages.push(m);
      write(all);
      return { ok: true, message: m };
    },

    /** GET /api/handoff/{id} — 서버(voisso/agent/handoff.py)의 as_dict 와 같은 형태 */
    get: function (id) {
      var h = read()[id];
      if (!h) {
        return {
          status: "none", channel_id: null, complaint_id: id,
          officer: { name: "", department: "" },
          started_at: null, closed_at: null, notice: "", messages: []
        };
      }
      return {
        status: h.status,
        channel_id: h.channel_id,
        complaint_id: id,
        officer: h.officer,
        started_at: h.started_at,
        closed_at: h.closed_at || null,
        notice: "지금부터 담당자가 직접 응대합니다.",
        messages: h.messages
      };
    },

    /** POST /api/handoff/{id}/close */
    close: function (id) {
      var all = read();
      if (all[id]) { all[id].status = "closed"; all[id].closed_at = now(); write(all); }
      return { status: "closed" };
    },

    /** 어떤 민원에 핸드오프가 열려 있는지 (목 전용 편의 — 실서버에는 이 조회가 없다) */
    openIds: function () {
      var all = read(), out = [];
      Object.keys(all).forEach(function (id) { if (all[id].status === "open") out.push(id); });
      return out;
    }
  };
})();
