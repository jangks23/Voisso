/**
 * Voisso 민원 담당자 대시보드
 *
 * - 의존성 없음(빌드 스텝 없음). 브라우저에서 index.html 을 바로 열면 동작한다.
 * - 데이터 출처: docs/CONTRACT.md 5절 HTTP API
 *     GET /api/complaints        -> {"complaints":[<민원카드>...]}
 *     GET /api/complaints/{id}   -> {"complaint": <민원카드>}
 *   서버(server/, P6)가 아직 없으면 mock-data.js 의 샘플 카드로 자동 폴백한다.
 *   API 주소를 직접 지정하려면 ?api=http://localhost:8000 형태로 붙인다.
 * - 재배정은 서버 계약에 쓰기 API가 없으므로 브라우저 localStorage 에만 기록한다.
 *   (실제 이관 시 POST /api/complaints/{id}/assign 로 교체하면 되도록 한 곳에 모아 둠)
 */
(function () {
  "use strict";

  // ---------- 상수 ----------
  var API_CANDIDATES = buildApiCandidates();
  var LS_REASSIGN = "voisso.dashboard.reassign.v1";
  var LS_THEME = "voisso.dashboard.theme";
  var LS_TRMODE = "voisso.dashboard.trmode";
  var FALLBACK_PHONE = "1522-0120"; // 계약서 3절: 매핑 없으면 경북도청 대표번호

  var STATUS = {
    assigned:   { label: "배정완료", cls: "badge--assigned" },
    reassigned: { label: "재배정",   cls: "badge--reassigned" },
    unassigned: { label: "미배정",   cls: "badge--unassigned" }
  };

  // ---------- 상태 ----------
  var state = {
    complaints: [],
    source: "loading",   // live | mock | loading
    apiBase: null,
    selectedId: null,
    overrides: readJSON(LS_REASSIGN, {}),
    trMode: localStorage.getItem(LS_TRMODE) || "both",
    filter: { q: "", dept: "", status: "" }
  };

  var el = {};

  // ---------- 부팅 ----------
  document.addEventListener("DOMContentLoaded", function () {
    cacheEls();
    applyTheme(new URLSearchParams(location.search).get("theme") ||
               localStorage.getItem(LS_THEME) || "auto");
    bindEvents();
    loadComplaints();
  });

  function cacheEls() {
    ["source-badge","refresh-btn","theme-btn","stat-today","stat-today-sub","stat-unassigned",
     "stat-reassigned","stat-duration","stat-dist","q","f-dept","f-status","reset-btn",
     "list","list-count","detail","detail-empty"].forEach(function (id) {
      el[camel(id)] = document.getElementById(id);
    });
  }

  function bindEvents() {
    el.refreshBtn.addEventListener("click", loadComplaints);
    el.themeBtn.addEventListener("click", cycleTheme);
    el.q.addEventListener("input", function () { state.filter.q = this.value.trim(); render(); });
    el.fDept.addEventListener("change", function () { state.filter.dept = this.value; render(); });
    el.fStatus.addEventListener("change", function () { state.filter.status = this.value; render(); });
    el.resetBtn.addEventListener("click", function () {
      state.filter = { q: "", dept: "", status: "" };
      el.q.value = ""; el.fDept.value = ""; el.fStatus.value = "";
      render();
    });

    el.list.addEventListener("click", function (e) {
      var card = e.target.closest(".card");
      if (card) select(card.dataset.id);
    });

    document.addEventListener("keydown", function (e) {
      var typing = /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);
      if (e.key === "/" && !typing) { e.preventDefault(); el.q.focus(); return; }
      if (typing) return;
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); move(-1); }
      else if (e.key === "r" || e.key === "R") { loadComplaints(); }
    });
  }

  // ---------- 데이터 로딩 ----------
  function buildApiCandidates() {
    var out = [];
    var q = new URLSearchParams(location.search).get("api");
    if (q) out.push(q.replace(/\/+$/, ""));
    if (location.protocol === "http:" || location.protocol === "https:") out.push("");
    out.push("http://localhost:8000", "http://127.0.0.1:8000");
    return out.filter(function (v, i, a) { return a.indexOf(v) === i; });
  }

  function loadComplaints() {
    setSource("loading");
    tryNext(0);

    function tryNext(i) {
      if (i >= API_CANDIDATES.length) return useMock();
      var base = API_CANDIDATES[i];
      fetchJSON(base + "/api/complaints", 2000).then(function (data) {
        var list = data && Array.isArray(data.complaints) ? data.complaints : null;
        if (!list) throw new Error("bad payload");
        state.apiBase = base;
        state.complaints = list;
        setSource("live");
        afterLoad();
      }).catch(function () { tryNext(i + 1); });
    }

    function useMock() {
      state.apiBase = null;
      state.complaints = (window.VOISSO_MOCK_COMPLAINTS || []).slice();
      setSource("mock");
      afterLoad();
    }
  }

  function afterLoad() {
    state.complaints.sort(function (a, b) {
      return String(b.created_at || "").localeCompare(String(a.created_at || ""));
    });
    fillDeptFilter();
    render();
    if (state.selectedId && !byId(state.selectedId)) state.selectedId = null;
    if (!state.selectedId) {
      var first = visible()[0];
      if (first) select(first.id, { silent: true });
    } else {
      renderDetail();
    }
  }

  function fetchJSON(url, timeoutMs) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, timeoutMs || 4000);
    return fetch(url, { signal: ctrl ? ctrl.signal : undefined, headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .finally(function () { clearTimeout(t); });
  }

  function setSource(kind) {
    state.source = kind;
    var b = el.sourceBadge;
    b.className = "src-badge src-badge--" + (kind === "live" ? "live" : kind === "mock" ? "mock" : "loading");
    if (kind === "live") {
      b.textContent = "● 실시간 연결됨";
      b.title = "GET " + (state.apiBase || location.origin) + "/api/complaints";
    } else if (kind === "mock") {
      b.textContent = "● 샘플 데이터";
      b.title = "민원 서버(GET /api/complaints)에 연결되지 않아 mock-data.js 샘플을 표시합니다.";
    } else {
      b.textContent = "연결 확인 중…";
      b.title = "";
    }
  }

  // ---------- 민원카드 파생값 ----------
  // 재배정 결과를 얹은 "실효 카드"를 만든다. 원본(AI 배정)은 _ai 에 보존한다.
  function effective(c) {
    var ov = state.overrides[c.id];
    if (!ov) return c;
    var copy = Object.assign({}, c);
    copy.assigned = ov.assigned;
    copy.alternatives = ov.alternatives || [];
    copy._reassigned = { at: ov.at, from: ov.from };
    copy._ai = { assigned: c.assigned, alternatives: c.alternatives || [] };
    return copy;
  }

  function statusOf(c) {
    if (state.overrides[c.id]) return "reassigned";
    if (c.status && STATUS[c.status]) return c.status;
    var a = c.assigned;
    if (!a || !(a.full_name || a.department_id)) return "unassigned";
    return "assigned";
  }

  function deptOf(c) {
    var a = effective(c).assigned;
    return (a && a.full_name) || "";
  }

  function phoneOf(a) {
    // 계약서 3절: 공개 데이터셋에는 토큰만 존재. 서버가 실번호를 해석해 주면 그 값을 쓴다.
    if (!a) return { text: FALLBACK_PHONE, token: null, resolved: false };
    var real = a.phone || a.phone_resolved || null;
    return { text: real || FALLBACK_PHONE, token: a.phone_token || null, resolved: !!real };
  }

  function byId(id) {
    for (var i = 0; i < state.complaints.length; i++) if (state.complaints[i].id === id) return state.complaints[i];
    return null;
  }

  function visible() {
    var q = state.filter.q.toLowerCase();
    return state.complaints.filter(function (c) {
      if (state.filter.dept && deptOf(c) !== state.filter.dept) return false;
      if (state.filter.status && statusOf(c) !== state.filter.status) return false;
      if (!q) return true;
      return haystack(c).indexOf(q) !== -1;
    });
  }

  function haystack(c) {
    if (c._hay) return c._hay;
    var e = effective(c);
    var parts = [c.id, c.summary, c.category, deptOf(c),
                 e.assigned && e.assigned.evidence,
                 c.caller && c.caller.name_masked];
    (c.alternatives || []).forEach(function (a) { parts.push(a.full_name, a.evidence); });
    (c.transcript || []).forEach(function (t) { parts.push(t.dialect, t.standard); });
    var s = parts.filter(Boolean).join(" ").toLowerCase();
    c._hay = s;
    return s;
  }

  // ---------- 렌더 ----------
  function render() { renderStats(); renderList(); renderDetail(); }

  function renderStats() {
    var all = state.complaints;
    var today = new Date().toDateString();
    var todayCount = all.filter(function (c) {
      var d = new Date(c.created_at);
      return !isNaN(d) && d.toDateString() === today;
    }).length;

    el.statToday.textContent = todayCount;
    el.statTodaySub.textContent = "전체 " + all.length + "건";
    el.statUnassigned.textContent = all.filter(function (c) { return statusOf(c) === "unassigned"; }).length;
    el.statReassigned.textContent = all.filter(function (c) { return statusOf(c) === "reassigned"; }).length;

    var durs = all.map(function (c) { return Number(c.duration_sec) || 0; }).filter(function (v) { return v > 0; });
    var avg = durs.length ? Math.round(durs.reduce(function (a, b) { return a + b; }, 0) / durs.length) : 0;
    el.statDuration.textContent = avg ? fmtDuration(avg) : "–";

    var counts = {};
    all.forEach(function (c) {
      var d = deptOf(c) || "미배정";
      counts[d] = (counts[d] || 0) + 1;
    });
    var rows = Object.keys(counts).map(function (k) { return { name: k, n: counts[k] }; })
      .sort(function (a, b) { return b.n - a.n; });
    var total = all.length || 1;
    var shown = rows.slice(0, 4);
    var rest = rows.slice(4).reduce(function (s, r) { return s + r.n; }, 0);

    el.statDist.innerHTML = rows.length
      ? shown.map(function (r) {
          return '<li class="dist-row"><div><div class="dist-name" title="' + esc(r.name) + '">' + esc(r.name) +
            '</div><div class="dist-track"><span class="dist-fill" style="width:' +
            Math.max(6, Math.round(r.n / total * 100)) + '%"></span></div></div>' +
            '<div class="dist-count">' + r.n + '건</div></li>';
        }).join("") + (rest ? '<li class="dist-empty">기타 ' + rows.slice(4).length + '개 부서 · ' + rest + '건</li>' : "")
      : '<li class="dist-empty">데이터 없음</li>';
  }

  function fillDeptFilter() {
    var set = {};
    state.complaints.forEach(function (c) { var d = deptOf(c); if (d) set[d] = 1; });
    var names = Object.keys(set).sort(function (a, b) { return a.localeCompare(b, "ko"); });
    var cur = state.filter.dept;
    el.fDept.innerHTML = '<option value="">전체 부서</option>' +
      names.map(function (n) { return '<option value="' + esc(n) + '">' + esc(n) + "</option>"; }).join("");
    el.fDept.value = names.indexOf(cur) !== -1 ? cur : "";
    state.filter.dept = el.fDept.value;
  }

  function renderList() {
    var rows = visible();
    el.listCount.textContent = rows.length + "건";

    if (!rows.length) {
      el.list.innerHTML = '<li class="empty-sub" style="padding:18px 8px">' +
        (state.source === "loading" ? "불러오는 중…" : "조건에 맞는 민원이 없습니다.") + "</li>";
      return;
    }

    el.list.innerHTML = rows.map(function (c) {
      var e = effective(c);
      var st = statusOf(c);
      var dept = deptOf(c);
      return '<li class="card' + (c.id === state.selectedId ? " is-selected" : "") + '" data-id="' + esc(c.id) + '">' +
        '<div class="card-top">' +
          '<span class="card-id">#' + esc(c.id) + "</span>" +
          '<span class="card-time">' + esc(fmtTime(c.created_at)) + "</span>" +
          '<span class="card-dur">통화 ' + esc(fmtDuration(c.duration_sec)) + "</span>" +
        "</div>" +
        '<p class="card-summary">' + esc(c.summary || "(요약 없음)") + "</p>" +
        '<div class="card-bottom">' +
          '<span class="badge ' + STATUS[st].cls + '">' + STATUS[st].label + "</span>" +
          '<span class="card-dept' + (dept ? "" : " is-none") + '">' + esc(dept || "담당 부서 미확인") + "</span>" +
          (c.category ? '<span class="tag">' + esc(c.category) + "</span>" : "") +
        "</div></li>";
    }).join("");
  }

  function select(id, opts) {
    state.selectedId = id;
    renderList();
    renderDetail();
    if (!(opts && opts.silent)) {
      var node = el.list.querySelector('.card[data-id="' + cssEsc(id) + '"]');
      if (node) node.scrollIntoView({ block: "nearest" });
      el.detail.scrollTop = 0;
      el.detail.parentElement.scrollTop = 0;
    }
    // 서버가 살아 있으면 상세는 계약서의 단건 API로 다시 받아 최신값을 쓴다.
    if (state.source === "live") {
      fetchJSON(state.apiBase + "/api/complaints/" + encodeURIComponent(id), 3000)
        .then(function (data) {
          var full = data && data.complaint;
          if (!full || full.id !== state.selectedId) return;
          for (var i = 0; i < state.complaints.length; i++) {
            if (state.complaints[i].id === full.id) { state.complaints[i] = full; break; }
          }
          renderDetail();
        })
        .catch(function () { /* 목록 데이터로 계속 표시 */ });
    }
  }

  function move(delta) {
    var rows = visible();
    if (!rows.length) return;
    var i = rows.findIndex(function (c) { return c.id === state.selectedId; });
    var next = rows[Math.min(rows.length - 1, Math.max(0, (i === -1 ? 0 : i + delta)))];
    if (next) select(next.id);
  }

  function renderDetail() {
    var raw = state.selectedId ? byId(state.selectedId) : null;
    if (!raw) {
      el.detail.hidden = true;
      el.detailEmpty.hidden = false;
      return;
    }
    el.detailEmpty.hidden = true;
    el.detail.hidden = false;

    var c = effective(raw);
    var st = statusOf(raw);
    var a = c.assigned || null;
    var ph = phoneOf(a);
    var alts = (c.alternatives || []).filter(function (x) { return x && x.full_name; });

    var html = "";

    // 헤더
    html += '<div class="d-head"><div style="min-width:0">' +
      '<span class="d-id">접수번호 ' + esc(c.id) + "</span> " +
      '<span class="badge ' + STATUS[st].cls + '">' + STATUS[st].label + "</span>" +
      '<h1 class="d-summary">' + esc(c.summary || "(요약 없음)") + "</h1>" +
      '<div class="d-meta">' +
        "<span>접수 <b>" + esc(fmtDateTime(c.created_at)) + "</b></span>" +
        "<span>통화시간 <b>" + esc(fmtDuration(c.duration_sec)) + "</b></span>" +
        (c.category ? "<span>분류 <b>" + esc(c.category) + "</b></span>" : "") +
        "<span>발화 <b>" + ((c.transcript || []).length) + "턴</b></span>" +
      "</div></div></div>";

    // 배정 + 근거 (화면의 1급 요소)
    html += '<div class="section"><h3>배정 부서와 배정 근거</h3>';
    if (a) {
      html += '<div class="assign">' +
        '<div class="assign-top">' +
          '<span class="assign-name">' + esc(a.full_name || "(부서명 없음)") + "</span>" +
          '<span class="assign-pos">' + esc(a.position || "직위 정보 없음") + "</span>" +
          '<span class="assign-phone">☎ ' + esc(ph.text) +
            (ph.resolved ? "" : ' <span class="tag">대표번호 안내</span>') +
            (ph.token ? ' <span class="tag">' + esc(ph.token) + "</span>" : "") +
          "</span>" +
        "</div>" +
        '<div class="assign-body">' +
          '<div class="assign-why">▍이 부서로 배정된 근거 — 경상북도청 사무분장 원문</div>' +
          '<blockquote class="evidence">' + esc(a.evidence || "근거 없음 — 담당자 확인이 필요합니다.") + "</blockquote>" +
          '<p class="evidence-src">' +
            (c._reassigned
              ? "담당자가 " + esc(fmtDateTime(c._reassigned.at)) + "에 <b>" + esc(c._reassigned.from || "AI 배정 부서") + "</b> → 위 부서로 재배정했습니다."
              : "AI가 통화 내용과 위 담당업무 원문을 대조해 자동 배정했습니다.") +
            (a.department_id ? " · 부서코드 <code>" + esc(a.department_id) + "</code>" : "") +
          "</p>" +
          (c._reassigned ? '<p style="margin:10px 0 0"><button class="btn btn-ghost" data-act="undo">↩ AI 배정으로 되돌리기</button></p>' : "") +
        "</div></div>";
    } else {
      html += '<div class="assign assign--none"><div class="assign-top">' +
        '<span class="assign-name">미배정</span>' +
        '<span class="assign-pos">담당 부서를 확인해 주세요</span></div>' +
        '<div class="assign-body"><p class="evidence-src">AI가 담당 부서를 특정하지 못했습니다. 아래 후보 부서에서 선택해 배정하세요.</p></div></div>';
    }
    html += "</div>";

    // 후보 부서
    html += '<div class="section"><h3>다른 후보 부서 · 한 번 클릭으로 재배정</h3><div class="alts">';
    if (alts.length) {
      html += alts.map(function (x, i) {
        var s = typeof x.score === "number" ? x.score : null;
        return '<div class="alt">' +
          '<div class="alt-main"><div class="alt-name">' + esc(x.full_name) +
            (x.position ? ' <span class="tag">' + esc(x.position) + "</span>" : "") + "</div>" +
            '<div class="alt-ev">근거: ' + esc(x.evidence || "근거 원문 없음") + "</div></div>" +
          '<div class="alt-right">' +
            '<div class="score"><div class="score-top"><span>매칭 점수</span><span class="score-num">' +
              (s === null ? "–" : s.toFixed(2)) + '</span></div>' +
              '<div class="score-track"><span class="score-fill" style="width:' +
              (s === null ? 0 : Math.round(Math.max(0, Math.min(1, s)) * 100)) + '%"></span></div></div>' +
            '<button class="btn btn-primary" data-act="reassign" data-i="' + i + '">이 부서로 재배정</button>' +
          "</div></div>";
      }).join("");
    } else {
      html += '<p class="alt-empty">후보 부서가 없습니다.</p>';
    }
    html += "</div></div>";

    // 전사
    var turns = c.transcript || [];
    html += '<div class="section"><h3>통화 전문 · 사투리 원문과 표준어 대조</h3>' +
      '<div class="tr-toolbar"><div class="seg">' +
        seg("both", "대조 보기") + seg("dialect", "사투리 원문") + seg("standard", "표준어") +
      "</div>" +
      '<span class="pane-hint">사투리 정규화: voisso/dialect (STT 교정 결과)</span></div>';
    if (turns.length) {
      html += '<div class="transcript mode-' + esc(state.trMode) + '" id="transcript">' +
        '<div class="tr-head"><span>화자</span><span>사투리 원문</span><span>표준어</span></div>' +
        turns.map(function (t) {
          var caller = t.role === "caller";
          return '<div class="tr-row ' + (caller ? "is-caller" : "is-agent") + '">' +
            '<div class="tr-who">' + (caller ? "신고자" : "AI 상담") + "</div>" +
            '<div class="tr-cell tr-cell--dialect">' + esc(t.dialect || t.standard || "") + "</div>" +
            '<div class="tr-cell tr-cell--standard">' + esc(t.standard || t.dialect || "") + "</div>" +
          "</div>";
        }).join("") + "</div>";
    } else {
      html += '<p class="alt-empty">전사 데이터가 없습니다.</p>';
    }
    html += "</div>";

    // 신고자
    var caller = c.caller || {};
    html += '<div class="section"><h3>신고자 정보 (마스킹)</h3>' +
      '<dl class="kv">' +
        "<dt>성명</dt><dd>" + esc(caller.name_masked || "미확인") + "</dd>" +
        "<dt>연락처</dt><dd>" + esc(caller.phone_masked || "미확인") + "</dd>" +
      "</dl>" +
      '<p class="note">개인정보 보호를 위해 대시보드에는 마스킹된 값만 표시됩니다. 회신이 필요하면 통화 시스템의 콜백 기능을 이용하세요.</p></div>';

    el.detail.innerHTML = html;
    bindDetail(raw, alts);
  }

  function seg(mode, label) {
    return '<button type="button" data-act="trmode" data-mode="' + mode + '"' +
      (state.trMode === mode ? ' class="is-on"' : "") + ">" + label + "</button>";
  }

  function bindDetail(raw, alts) {
    el.detail.querySelectorAll('[data-act="trmode"]').forEach(function (b) {
      b.addEventListener("click", function () {
        state.trMode = b.dataset.mode;
        localStorage.setItem(LS_TRMODE, state.trMode);
        renderDetail();
      });
    });
    el.detail.querySelectorAll('[data-act="reassign"]').forEach(function (b) {
      b.addEventListener("click", function () { reassign(raw, alts[Number(b.dataset.i)]); });
    });
    var undo = el.detail.querySelector('[data-act="undo"]');
    if (undo) undo.addEventListener("click", function () { undoReassign(raw); });
  }

  // ---------- 재배정 ----------
  // 서버 쓰기 API가 생기면 이 함수 안에서 POST 를 호출하도록 바꾸면 된다.
  function reassign(raw, alt) {
    if (!alt) return;
    var cur = effective(raw);
    var prev = cur.assigned;
    var nextAlts = (cur.alternatives || []).filter(function (x) { return x !== alt; });
    if (prev && prev.full_name) {
      nextAlts.unshift({
        full_name: prev.full_name,
        department_id: prev.department_id,
        position: prev.position,
        phone_token: prev.phone_token,
        score: typeof prev.score === "number" ? prev.score : null,
        evidence: prev.evidence
      });
    }
    state.overrides[raw.id] = {
      assigned: {
        department_id: alt.department_id || null,
        full_name: alt.full_name,
        position: alt.position || null,
        phone_token: alt.phone_token || null,
        evidence: alt.evidence || "",
        score: typeof alt.score === "number" ? alt.score : null
      },
      alternatives: nextAlts,
      from: prev && prev.full_name ? prev.full_name : "미배정",
      at: new Date().toISOString()
    };
    saveOverrides();
    delete raw._hay;
    fillDeptFilter();
    render();
    toast(alt.full_name + " 로 재배정했습니다.");
  }

  function undoReassign(raw) {
    delete state.overrides[raw.id];
    saveOverrides();
    delete raw._hay;
    fillDeptFilter();
    render();
    toast("AI 배정으로 되돌렸습니다.");
  }

  function saveOverrides() {
    try { localStorage.setItem(LS_REASSIGN, JSON.stringify(state.overrides)); } catch (e) {}
  }

  // ---------- 테마 ----------
  function cycleTheme() {
    var order = ["auto", "light", "dark"];
    var cur = document.documentElement.getAttribute("data-theme") || "auto";
    applyTheme(order[(order.indexOf(cur) + 1) % order.length]);
  }

  function applyTheme(mode) {
    if (["auto", "light", "dark"].indexOf(mode) === -1) mode = "auto";
    document.documentElement.setAttribute("data-theme", mode);
    try { localStorage.setItem(LS_THEME, mode); } catch (e) {}
    el.themeBtn.textContent = mode === "light" ? "☀ 라이트" : mode === "dark" ? "☾ 다크" : "◐ 시스템";
  }

  // ---------- 유틸 ----------
  function fmtTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "-";
    var today = new Date().toDateString() === d.toDateString();
    var hm = d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
    return today ? hm : d.toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit" }) + " " + hm;
  }

  function fmtDateTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "-";
    return d.toLocaleString("ko-KR", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false
    });
  }

  function fmtDuration(sec) {
    sec = Number(sec) || 0;
    var m = Math.floor(sec / 60), s = sec % 60;
    return m ? m + "분 " + String(s).padStart(2, "0") + "초" : s + "초";
  }

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function cssEsc(v) { return String(v).replace(/["\\]/g, "\\$&"); }

  function camel(id) { return id.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); }); }

  function readJSON(key, dflt) {
    try { return JSON.parse(localStorage.getItem(key)) || dflt; } catch (e) { return dflt; }
  }

  var toastTimer = null;
  function toast(msg) {
    var old = document.querySelector(".toast");
    if (old) old.remove();
    var n = document.createElement("div");
    n.className = "toast";
    n.textContent = msg;
    document.body.appendChild(n);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { n.remove(); }, 2200);
  }
})();
