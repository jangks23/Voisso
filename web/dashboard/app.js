/**
 * Voisso 민원 담당자 대시보드
 *
 * - 의존성 없음(빌드 스텝 없음). 브라우저에서 index.html 을 바로 열어도 동작한다.
 * - 데이터 출처: docs/CONTRACT.md 5절 HTTP API
 *     GET /api/complaints        -> {"complaints":[<민원카드>...]}
 *     GET /api/complaints/{id}   -> {"complaint": <민원카드>}
 *   실행 설정은 config.js (USE_MOCK / API_BASE / POLL_INTERVAL_MS).
 *   서버에 못 붙으면 mock-data.js 샘플로 자동 폴백한다. 데모 중 서버가 죽어도 화면은 남는다.
 * - 폴링으로 자동 갱신한다. 통화가 끝나면 새로고침 없이 목록에 뜨고, NEW 뱃지가 붙는다.
 * - 재배정은 서버 계약에 쓰기 API가 없으므로 브라우저 localStorage 에만 기록한다.
 *   (실제 이관 시 reassign()/undoReassign() 안에서 POST 를 호출하도록 바꾸면 된다.)
 */
(function () {
  "use strict";

  // ---------- 설정 ----------
  var CFG = window.VOISSO_DASHBOARD_CONFIG || {};
  var POLL_MS = CFG.POLL_INTERVAL_MS || 4000;
  var POLL_IDLE_MS = CFG.POLL_IDLE_MS || 15000;
  var POLL_IDLE_AFTER_MS = CFG.POLL_IDLE_AFTER_MS || 120000;
  var NEW_TTL = CFG.NEW_BADGE_TTL_MS || 300000;

  // 담당자가 화면에서 만든 값(처리 상태·재배정·이력)을 모아 두는 단일 저장소.
  // TODO(P6): 서버에 쓰기 API(PATCH /api/complaints/{id})가 생기면 이 자리를 서버로 옮긴다.
  //           지금은 브라우저 localStorage 에만 남는다 — README 에 명시.
  var LS_BOOK = "voisso.dashboard.casebook.v1";
  var LS_REASSIGN_V1 = "voisso.dashboard.reassign.v1"; // 이전 버전 마이그레이션용
  var LS_THEME = "voisso.dashboard.theme";
  var LS_TRMODE = "voisso.dashboard.trmode";
  var FALLBACK_PHONE = "1522-0120"; // 계약서 3절: 매핑 없으면 경북도청 대표번호

  // 근거 원문이 이보다 길면 접어 둔다. 첫 줄(또는 첫 항목)은 항상 보인다.
  var EVIDENCE_COLLAPSE_CHARS = 110;

  // 배정 상태 — 데이터에서 파생된다(담당자가 고르는 값이 아니다).
  var ASSIGN_STATE = {
    assigned:   { label: "배정완료", cls: "badge--assigned" },
    reassigned: { label: "재배정",   cls: "badge--reassigned" },
    unassigned: { label: "미배정",   cls: "badge--unassigned" }
  };

  // 처리 상태 — 담당자가 직접 옮기는 값. 접수됨 → 확인함 → 처리중 → 완료(또는 반려).
  var WORKFLOW = [
    { key: "received", label: "접수됨", cls: "wf--received", hint: "아직 열어보지 않음" },
    { key: "ack",      label: "확인함", cls: "wf--ack",      hint: "담당자가 내용을 확인함" },
    { key: "progress", label: "처리중", cls: "wf--progress", hint: "현장 확인·조치 진행 중" },
    { key: "done",     label: "완료",   cls: "wf--done",     hint: "조치 완료, 민원인 회신됨" },
    { key: "rejected", label: "반려",   cls: "wf--rejected", hint: "타 기관 이관 등으로 종결" }
  ];
  var WF = {};
  WORKFLOW.forEach(function (w) { WF[w.key] = w; });

  // ---------- 상태 ----------
  var state = {
    complaints: [],
    source: "loading",   // live | mock | loading
    apiBase: null,
    selectedId: null,
    book: loadBook(),     // id -> { workflow, assignment, history }
    trMode: localStorage.getItem(LS_TRMODE) || "both",
    filter: { q: "", dept: "", status: "" },
    seen: null,          // 최초 로드 이후에 들어온 건만 NEW 로 본다
    fresh: {},           // id -> 도착 시각(ms)
    animated: {},        // 하이라이트를 이미 재생한 id
    expanded: {},        // 상세에서 펼쳐 둔 근거 블록
    lastSync: null,
    lastChange: Date.now(),  // 마지막으로 뭔가 달라진 시각 (폴링 주기 결정용)
    etag: null,              // 서버가 ETag 를 주면 조건부 요청으로 바꾼다
    polling: null,
    inFlight: false,
    stats: { requests: 0, notModified: 0, bytes: 0 }
  };

  var el = {};

  // ---------- 부팅 ----------
  document.addEventListener("DOMContentLoaded", function () {
    cacheEls();
    applyTheme(new URLSearchParams(location.search).get("theme") ||
               localStorage.getItem(LS_THEME) || "auto");
    bindEvents();
    loadComplaints();
    startPolling();
  });

  function cacheEls() {
    ["source-badge","last-sync","live-region","refresh-btn","theme-btn","stat-today","stat-today-sub",
     "stat-unread","stat-progress","stat-progress-sub","stat-unassigned",
     "stat-rate","stat-rate-sub","stat-rate-fill","stat-dist",
     "q","f-dept","f-status","reset-btn","export-btn","export-menu",
     "export-n-filtered","export-n-all","list","list-count","detail","detail-empty"].forEach(function (id) {
      el[camel(id)] = document.getElementById(id);
    });
  }

  function bindEvents() {
    el.refreshBtn.addEventListener("click", function () { loadComplaints({ manual: true }); });
    el.themeBtn.addEventListener("click", cycleTheme);
    el.q.addEventListener("input", function () { state.filter.q = this.value.trim(); render(); });
    el.fDept.addEventListener("change", function () { state.filter.dept = this.value; render(); });
    el.fStatus.addEventListener("change", function () { state.filter.status = this.value; render(); });
    el.resetBtn.addEventListener("click", function () {
      state.filter = { q: "", dept: "", status: "" };
      el.q.value = ""; el.fDept.value = ""; el.fStatus.value = "";
      render();
    });

    el.exportBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleExportMenu(el.exportMenu.hidden);
    });
    el.exportMenu.addEventListener("click", function (e) {
      var b = e.target.closest("[data-scope]");
      if (!b) return;
      exportCSV(b.dataset.scope);
      toggleExportMenu(false);
    });
    document.addEventListener("click", function () { toggleExportMenu(false); });

    el.list.addEventListener("click", function (e) {
      var card = e.target.closest(".card");
      if (card) { markActive(); select(card.dataset.id, { user: true }); }
    });

    document.addEventListener("keydown", function (e) {
      var typing = /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);
      if (e.key === "Escape") { toggleExportMenu(false); }
      if (e.key === "/" && !typing) { e.preventDefault(); el.q.focus(); return; }
      if (typing) return;
      markActive();
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); move(-1); }
      else if (e.key === "r" || e.key === "R") { loadComplaints({ manual: true }); }
    });

    // 탭이 보이지 않는 동안은 폴링을 멈춘다. 돌아오면 즉시 한 번 당겨온다.
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { stopPolling(); }
      else { state.lastChange = Date.now(); loadComplaints(); startPolling(); }
    });
  }

  // ---------- 폴링 ----------
  /**
   * 적응형 폴링.
   * 기본은 POLL_INTERVAL_MS(4초)지만, 아무 변화 없이 조용한 시간이 이어지면
   * POLL_IDLE_MS(15초)로 늦춘다. 담당자가 화면을 만지거나 새 민원이 오면 즉시 되돌린다.
   * 하루 8시간 열어 두는 화면이라, 조용한 구간의 요청 수를 줄이는 것이 그대로 서버 부하다.
   */
  function nextDelay() {
    var quietFor = Date.now() - state.lastChange;
    return quietFor > POLL_IDLE_AFTER_MS ? POLL_IDLE_MS : POLL_MS;
  }

  function startPolling() {
    stopPolling();
    if (POLL_MS <= 0) return;
    var tick = function () {
      state.polling = setTimeout(function () {
        loadComplaints();
        tick();
      }, nextDelay());
    };
    tick();
  }

  function stopPolling() {
    if (state.polling) { clearTimeout(state.polling); state.polling = null; }
  }

  /** 담당자가 화면을 만졌다 — 빠른 주기로 되돌린다. */
  function markActive() {
    var wasIdle = Date.now() - state.lastChange > POLL_IDLE_AFTER_MS;
    state.lastChange = Date.now();
    if (wasIdle) { startPolling(); }
  }

  // ---------- 데이터 로딩 ----------
  function apiCandidates() {
    var out = [];
    if (state.apiBase !== null) return [state.apiBase]; // 이미 붙은 서버를 계속 쓴다
    if (typeof CFG.API_BASE === "string") out.push(CFG.API_BASE.replace(/\/+$/, ""));
    // ?api= 로 못박은 경우에는 다른 서버를 기웃거리지 않는다. 지정한 곳이 죽었으면 샘플로 간다.
    if (!CFG.API_PINNED) {
      (CFG.API_FALLBACKS || []).forEach(function (b) { out.push(String(b).replace(/\/+$/, "")); });
    }
    // file:// 로 열었을 때 상대경로 fetch 는 의미가 없다.
    if (location.protocol === "file:") out = out.filter(function (b) { return b !== ""; });
    return out.filter(function (v, i, a) { return a.indexOf(v) === i; });
  }

  function loadComplaints(opts) {
    opts = opts || {};
    if (state.inFlight) return;

    if (CFG.USE_MOCK) { useMock(); return; }

    state.inFlight = true;
    if (state.source === "loading") setSource("loading");
    tryNext(0);

    function tryNext(i) {
      var bases = apiCandidates();
      if (i >= bases.length) { state.inFlight = false; useMock(); return; }
      var base = bases[i];
      fetchJSON(base + "/api/complaints", 2500, { conditional: true }).then(function (data) {
        if (data && data.__notModified) {   // 서버가 "그대로다" 라고 답한 경우
          state.inFlight = false;
          state.apiBase = base;
          setSource("live");
          state.lastSync = Date.now();
          renderLastSync();
          if (opts.manual) toast("최신 상태입니다.");
          return;
        }
        var list = data && Array.isArray(data.complaints) ? data.complaints : null;
        if (!list) throw new Error("bad payload");
        state.inFlight = false;
        state.apiBase = base;
        setSource("live");
        apply(list, opts);
      }).catch(function () {
        if (state.apiBase !== null && !opts.manual) {
          // 붙어 있던 서버가 잠깐 끊긴 경우 — 화면은 그대로 두고 다음 폴링에서 재시도한다.
          state.inFlight = false;
          setSource("stale");
          return;
        }
        tryNext(i + 1);
      });
    }

    function useMock() {
      var wasLive = state.source === "live";
      state.apiBase = null;
      setSource("mock");
      if (!wasLive || CFG.USE_MOCK) apply((window.VOISSO_MOCK_COMPLAINTS || []).slice(), opts);
    }
  }

  /** 새로 받은 목록을 반영한다. 선택/스크롤/필터는 건드리지 않는다. */
  function apply(list, opts) {
    list.sort(function (a, b) {
      return String(b.created_at || "").localeCompare(String(a.created_at || ""));
    });

    var arrived = [];
    if (state.seen === null) {
      // 최초 로드 — 기존 민원은 NEW 로 보지 않는다.
      state.seen = {};
      list.forEach(function (c) { state.seen[c.id] = 1; });
    } else {
      list.forEach(function (c) {
        if (!state.seen[c.id]) {
          state.seen[c.id] = 1;
          state.fresh[c.id] = Date.now();
          arrived.push(c);
        }
      });
    }

    var changed = signature(list) !== signature(state.complaints);
    state.complaints = list;
    state.lastSync = Date.now();
    renderLastSync();

    if (changed || arrived.length) {
      state.lastChange = Date.now();   // 변화가 있었으니 빠른 주기를 유지한다
      fillDeptFilter();
      render();
    }

    if (state.selectedId && !byId(state.selectedId)) state.selectedId = null;
    if (!state.selectedId) {
      var first = visible()[0];
      if (first) select(first.id, { silent: true });
    }

    if (arrived.length) {
      var msg = arrived.length === 1
        ? "새 민원 접수 — #" + arrived[0].id + " " + truncate(arrived[0].summary, 26)
        : "새 민원 " + arrived.length + "건 접수";
      toast(msg);
      announce(msg + ". 목록 " + state.complaints.length + "건.");
    }
    if (opts && opts.manual && !arrived.length) toast("최신 상태입니다.");
  }

  function signature(list) {
    return list.map(function (c) {
      return c.id + ":" + (c.created_at || "") + ":" +
             ((c.assigned && c.assigned.full_name) || "") + ":" + (c.summary || "").length;
    }).join("|");
  }

  function fetchJSON(url, timeoutMs, opts) {
    opts = opts || {};
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, timeoutMs || 4000);
    var headers = { Accept: "application/json" };
    // 서버가 ETag 를 주면 조건부 요청으로 바꾼다. 변경이 없으면 304 + 본문 0바이트.
    // 서버가 아직 ETag 를 안 주면 이 헤더는 그냥 무시되므로 지금 넣어도 안전하다.
    if (opts.conditional && state.etag) headers["If-None-Match"] = state.etag;

    return fetch(url, { signal: ctrl ? ctrl.signal : undefined, headers: headers })
      .then(function (r) {
        state.stats.requests++;
        if (r.status === 304) {          // 변경 없음 — 파싱도 렌더도 하지 않는다
          state.stats.notModified++;
          return { __notModified: true };
        }
        if (!r.ok) throw new Error("HTTP " + r.status);
        var tag = r.headers.get("ETag");
        if (opts.conditional && tag) state.etag = tag;
        return r.json();
      })
      .finally(function () { clearTimeout(t); });
  }

  function setSource(kind) {
    state.source = kind;
    var b = el.sourceBadge;
    var cls = kind === "live" ? "live" : kind === "mock" ? "mock" : kind === "stale" ? "stale" : "loading";
    b.className = "src-badge src-badge--" + cls;
    if (kind === "live") {
      b.textContent = "● 실시간 연결됨";
      b.title = "GET " + (state.apiBase || location.origin) + "/api/complaints · " +
                Math.round(POLL_MS / 1000) + "초마다 자동 갱신";
    } else if (kind === "mock") {
      b.textContent = "● 샘플 데이터";
      b.title = CFG.USE_MOCK
        ? "config.js 의 USE_MOCK 이 true 입니다."
        : "민원 서버에 연결되지 않아 mock-data.js 샘플을 표시합니다.";
    } else if (kind === "stale") {
      b.textContent = "● 연결 끊김 — 재시도 중";
      b.title = "마지막으로 받은 목록을 그대로 표시하고 있습니다.";
    } else {
      b.textContent = "연결 확인 중…";
      b.title = "";
    }
  }

  function renderLastSync() {
    if (!el.lastSync) return;
    el.lastSync.textContent = state.lastSync
      ? "갱신 " + new Date(state.lastSync).toLocaleTimeString("ko-KR", {
          hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
      : "";
  }

  // ---------- 민원카드 파생값 ----------
  function effective(c) {
    var e = state.book[c.id];
    var ov = e && e.assignment;
    if (!ov) return c;
    var copy = Object.assign({}, c);
    copy.assigned = ov.assigned;
    copy.alternatives = ov.alternatives || [];
    copy._reassigned = true;
    return copy;
  }

  /** 배정 상태 — 데이터 + 담당자 재배정 여부에서 파생. */
  function statusOf(c) {
    var e = state.book[c.id];
    if (e && e.assignment) return "reassigned";
    if (c.status && ASSIGN_STATE[c.status]) return c.status;
    var a = c.assigned;
    var name = a && String(a.full_name || "").trim();
    if (!a || !name || name === "미배정") return "unassigned";
    return "assigned";
  }

  /** 처리 상태 — 담당자가 옮기는 값. 기본은 접수됨(미확인). */
  function workflowOf(c) {
    var e = state.book[c.id];
    var key = e && e.workflow && e.workflow.status;
    return WF[key] ? key : "received";
  }

  function setWorkflow(id, key, opts) {
    if (!WF[key]) return;
    var cur = workflowOf({ id: id });
    if (cur === key) return;
    var e = entry(id);
    e.workflow = { status: key, at: new Date().toISOString(), by: "담당자" };
    pushHistory(id, {
      type: "status", at: e.workflow.at, by: "담당자",
      from: WF[cur].label, to: WF[key].label,
      auto: !!(opts && opts.auto)
    });
    saveBook();
    if (!(opts && opts.silent)) {
      toast("처리 상태를 '" + WF[key].label + "' 로 변경했습니다.");
      announce("접수번호 " + id + " 처리 상태 " + WF[key].label + ".");
    }
  }

  function deptOf(c) {
    var a = effective(c).assigned;
    var name = (a && String(a.full_name || "").trim()) || "";
    return name === "미배정" ? "" : name;
  }

  /**
   * 담당 연락처.
   * 계약서 3절: 공개 카드에는 PHONE_xxxx 토큰만 들어온다. 실번호 해석은 서버(resolve_phone)
   * 몫이고, 서버가 풀어 준 값이 있으면 그것을 쓴다. 토큰 자체는 화면에 노출하지 않는다.
   */
  function phoneOf(a) {
    if (!a) return { text: FALLBACK_PHONE, resolved: false };
    var real = String(a.phone || a.phone_resolved || "").trim();
    return { text: real || FALLBACK_PHONE, resolved: !!real };
  }

  function byId(id) {
    for (var i = 0; i < state.complaints.length; i++) if (state.complaints[i].id === id) return state.complaints[i];
    return null;
  }

  function isFresh(id) {
    var t = state.fresh[id];
    return !!t && (Date.now() - t) < NEW_TTL;
  }

  function visible() {
    var q = state.filter.q.toLowerCase();
    return state.complaints.filter(function (c) {
      if (state.filter.dept && deptOf(c) !== state.filter.dept) return false;
      if (state.filter.status) {
        var f = state.filter.status;
        if (f.indexOf("wf:") === 0) { if (workflowOf(c) !== f.slice(3)) return false; }
        else if (f.indexOf("as:") === 0) { if (statusOf(c) !== f.slice(3)) return false; }
      }
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

  // ---------- 근거 원문 ----------
  /**
   * 실데이터의 근거는 "◦ 항목 ◦ 항목 ◦ 항목 등" 형태로 길다.
   * 항목으로 쪼갤 수 있으면 목록으로, 아니면 통짜 문장으로 렌더한다.
   * 어느 쪽이든 첫 줄은 접힌 상태에서도 항상 보인다.
   */
  function parseEvidence(text) {
    var raw = String(text == null ? "" : text).trim();
    if (!raw) return { items: [], text: "", long: false };
    var items = raw.split(/\s*(?:[◦•∙·▪○]|(?:^|\s)-\s)\s*/)
                   .map(function (s) { return s.trim(); })
                   .filter(Boolean);
    if (items.length < 2) items = [];
    return { items: items, text: raw, long: items.length > 1 || raw.length > EVIDENCE_COLLAPSE_CHARS };
  }

  function evidenceHTML(text, key, opts) {
    opts = opts || {};
    var ev = parseEvidence(text);
    if (!ev.text) return '<p class="ev-empty">근거 없음 — 담당자 확인이 필요합니다.</p>';

    var open = !!state.expanded[key];
    var collapsible = ev.long && !opts.noCollapse;
    var body;

    if (ev.items.length) {
      var shown = (collapsible && !open) ? ev.items.slice(0, 1) : ev.items;
      body = '<ul class="ev-list">' + shown.map(function (s) {
        return "<li>" + esc(s) + "</li>";
      }).join("") + "</ul>";
    } else {
      body = '<p class="ev-text' + (collapsible && !open ? " is-clamped" : "") + '">' + esc(ev.text) + "</p>";
    }

    var more = "";
    if (collapsible) {
      var hidden = ev.items.length ? ev.items.length - 1 : 0;
      more = '<button type="button" class="ev-toggle" data-act="ev-toggle" data-key="' + esc(key) + '">' +
             (open ? "접기 ▲" : (hidden ? "근거 " + hidden + "줄 더 보기 ▼" : "전체 보기 ▼")) + "</button>";
    }
    return body + more;
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

    var durs = all.map(function (c) { return Number(c.duration_sec) || 0; }).filter(function (v) { return v > 0; });
    var avg = durs.length ? Math.round(durs.reduce(function (a, b) { return a + b; }, 0) / durs.length) : 0;

    el.statToday.textContent = todayCount;
    el.statTodaySub.textContent = "전체 " + all.length + "건" + (avg ? " · 평균 통화 " + fmtDuration(avg) : "");

    var wfCount = {};
    all.forEach(function (c) { var k = workflowOf(c); wfCount[k] = (wfCount[k] || 0) + 1; });
    el.statUnread.textContent = wfCount.received || 0;
    el.statProgress.textContent = wfCount.progress || 0;
    el.statProgressSub.textContent = "완료 " + (wfCount.done || 0) + "건" +
      (wfCount.rejected ? " · 반려 " + wfCount.rejected + "건" : "");
    el.statUnassigned.textContent = all.filter(function (c) { return statusOf(c) === "unassigned"; }).length;

    renderReassignRate(all);
    renderDist(all);
  }

  /**
   * AI 배정 대비 재배정 비율.
   * 우리 라우팅 품질의 정직한 자기 평가 지표다(GOAL.md H3: 20% 미만).
   * 분모는 AI 가 실제로 부서를 배정한 건수, 분자는 담당자가 그 배정을 뒤집은 건수.
   */
  function reassignRate(all) {
    var aiAssigned = 0, flipped = 0;
    all.forEach(function (c) {
      var name = c.assigned && String(c.assigned.full_name || "").trim();
      if (!name || name === "미배정") return;   // AI 가 배정 못 한 건은 분모에서 뺀다
      aiAssigned++;
      var e = state.book[c.id];
      if (e && e.assignment) flipped++;
    });
    return { aiAssigned: aiAssigned, flipped: flipped,
             pct: aiAssigned ? (flipped / aiAssigned * 100) : null };
  }

  function renderReassignRate(all) {
    var r = reassignRate(all);
    var over = r.pct !== null && r.pct >= 20;
    el.statRate.textContent = r.pct === null ? "–" : (Math.round(r.pct * 10) / 10) + "%";
    el.statRate.className = "stat-value " + (r.pct === null ? "" : over ? "stat-value--warn" : "stat-value--ok");
    el.statRateSub.textContent = r.pct === null
      ? "AI 배정 건 없음"
      : r.flipped + " / " + r.aiAssigned + "건 · 목표 20% 미만" + (over ? " (초과)" : "");
    el.statRateFill.style.width = Math.min(100, r.pct === null ? 0 : r.pct) + "%";
    el.statRateFill.className = "gauge-fill" + (over ? " is-over" : "");
  }

  function renderDist(all) {
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

    el.list.setAttribute("aria-activedescendant",
      state.selectedId ? "card-" + state.selectedId : "");
    el.list.innerHTML = rows.map(function (c) {
      var st = statusOf(c);
      var wf = workflowOf(c);
      var dept = deptOf(c);
      var fresh = isFresh(c.id);
      // 하이라이트는 도착 직후 한 번만 재생한다. 폴링·필터로 다시 튀지 않게.
      var animate = fresh && !state.animated[c.id];
      if (animate) state.animated[c.id] = 1;
      var selected = c.id === state.selectedId;
      return '<li class="card' + (selected ? " is-selected" : "") +
          (animate ? " is-arriving" : "") + '" data-id="' + esc(c.id) + '"' +
          ' id="card-' + esc(c.id) + '" role="option" aria-selected="' + (selected ? "true" : "false") + '">' +
        '<div class="card-top">' +
          '<span class="card-id">#' + esc(c.id) + "</span>" +
          (fresh ? '<span class="badge badge--new">NEW</span>' : "") +
          '<span class="card-time">' + esc(fmtTime(c.created_at)) + "</span>" +
          '<span class="card-dur">통화 ' + esc(fmtDuration(c.duration_sec)) + "</span>" +
        "</div>" +
        '<p class="card-summary">' + esc(c.summary || "(요약 없음)") + "</p>" +
        '<div class="card-bottom">' +
          '<span class="badge ' + WF[wf].cls + '">' + WF[wf].label + "</span>" +
          (st !== "assigned" ? '<span class="badge ' + ASSIGN_STATE[st].cls + '">' + ASSIGN_STATE[st].label + "</span>" : "") +
          '<span class="card-dept' + (dept ? "" : " is-none") + '">' + esc(dept || "담당 부서 미확인") + "</span>" +
          (c.category ? '<span class="tag">' + esc(c.category) + "</span>" : "") +
        "</div></li>";
    }).join("");
  }

  function select(id, opts) {
    var wasFresh = isFresh(id);
    state.selectedId = id;
    delete state.fresh[id]; // 열어 본 민원은 더 이상 NEW 가 아니다
    // 담당자가 직접 연 민원만 '확인함' 으로 올린다.
    // 화면 진입 시의 자동 선택까지 확인 처리하면 '미확인 건수' 가 거짓말을 한다.
    var acked = false;
    if (opts && opts.user && workflowOf({ id: id }) === "received") {
      setWorkflow(id, "ack", { auto: true, silent: true });
      acked = true;
    }
    if (wasFresh || acked) renderStats();
    renderList();
    renderDetail();
    if (!(opts && opts.silent)) {
      var node = el.list.querySelector('.card[data-id="' + cssEsc(id) + '"]');
      if (node) node.scrollIntoView({ block: "nearest" });
      el.detail.parentElement.scrollTop = 0;
    }
    // 서버가 살아 있으면 상세는 계약서의 단건 API로 다시 받아 최신값을 쓴다.
    if (state.apiBase !== null) {
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
    if (next) select(next.id, { user: true });
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
    var wf = workflowOf(raw);
    var a = c.assigned && String(c.assigned.full_name || "").trim() &&
            String(c.assigned.full_name).trim() !== "미배정" ? c.assigned : null;
    var unassignedBlock = !a && c.assigned ? c.assigned : null; // 미배정도 근거(사유)를 갖는다
    var ph = phoneOf(a);
    var alts = (c.alternatives || []).filter(function (x) { return x && x.full_name; });
    var aiName = (raw.assigned && String(raw.assigned.full_name || "").trim()) || "";
    var restoredLabel = function (x) {
      if (!x.restored) return null;
      return x.full_name === aiName ? "AI 최초 배정" : "담당자 이전 배정";
    };

    var html = "";

    html += '<div class="d-head"><div style="min-width:0">' +
      '<span class="d-id">접수번호 ' + esc(c.id) + "</span> " +
      '<span class="badge ' + WF[wf].cls + '">' + WF[wf].label + "</span> " +
      '<span class="badge ' + ASSIGN_STATE[st].cls + '">' + ASSIGN_STATE[st].label + "</span>" +
      '<h1 class="d-summary">' + esc(c.summary || "(요약 없음)") + "</h1>" +
      '<div class="d-meta">' +
        "<span>접수 <b>" + esc(fmtDateTime(c.created_at)) + "</b></span>" +
        "<span>통화시간 <b>" + esc(fmtDuration(c.duration_sec)) + "</b></span>" +
        (c.category ? "<span>분류 <b>" + esc(c.category) + "</b></span>" : "") +
        "<span>발화 <b>" + ((c.transcript || []).length) + "턴</b></span>" +
      "</div></div></div>";

    // 처리 상태 — 담당자가 실제로 일을 굴리는 줄
    var wfEntry = state.book[c.id] && state.book[c.id].workflow;
    html += '<div class="wfbar"><span class="wfbar-label">처리 상태</span>' +
      '<div class="wfbar-steps">' + WORKFLOW.map(function (w) {
        return '<button type="button" class="wfbtn ' + w.cls + (w.key === wf ? " is-on" : "") +
          '" data-act="wf" data-key="' + w.key + '" title="' + esc(w.hint) + '"' +
          (w.key === wf ? ' aria-current="true"' : "") + ">" + w.label + "</button>";
      }).join("") + "</div>" +
      '<span class="wfbar-at">' + (wfEntry ? esc(fmtDateTime(wfEntry.at)) + " 변경" : "변경 이력 없음") + "</span>" +
      "</div>";

    // 배정 + 근거 (화면의 1급 요소)
    html += '<div class="section"><h3>배정 부서와 배정 근거</h3>';
    if (a) {
      html += '<div class="assign">' +
        '<div class="assign-top">' +
          '<span class="assign-name">' + esc(a.full_name) + "</span>" +
          '<span class="assign-pos">' + esc(a.position || "직위 정보 없음") + "</span>" +
          '<span class="assign-phone">☎ ' + esc(ph.text) +
            (ph.resolved ? "" : ' <span class="tag">대표번호 안내</span>') +
          "</span>" +
        "</div>" +
        '<div class="assign-body">' +
          '<div class="assign-why">▍이 부서로 배정된 근거 — 경상북도청 사무분장 원문</div>' +
          '<blockquote class="evidence">' + evidenceHTML(a.evidence, "main") + "</blockquote>" +
          '<p class="evidence-src">' +
            (c._reassigned
              ? "담당자가 재배정한 부서입니다. AI 최초 배정과 그 근거는 아래 <b>처리 이력</b>에 남아 있습니다."
              : "AI가 통화 내용과 위 담당업무 원문을 대조해 자동 배정했습니다.") +
            (a.department_id ? " · 부서코드 <code>" + esc(a.department_id) + "</code>" : "") +
          "</p>" +
          (c._reassigned ? '<p style="margin:10px 0 0"><button class="btn btn-ghost" data-act="undo">↩ AI 배정으로 되돌리기</button></p>' : "") +
        "</div></div>";
    } else {
      html += '<div class="assign assign--none"><div class="assign-top">' +
        '<span class="assign-name">미배정</span>' +
        '<span class="assign-pos">담당 부서를 확인해 주세요</span></div>' +
        '<div class="assign-body">' +
          '<div class="assign-why">▍자동 배정이 보류된 사유</div>' +
          '<blockquote class="evidence">' +
            evidenceHTML(unassignedBlock ? unassignedBlock.evidence : "", "main") + "</blockquote>" +
          '<p class="evidence-src">아래 후보 부서에서 선택하면 즉시 배정됩니다.</p>' +
        "</div></div>";
    }
    html += "</div>";

    // 후보 부서
    html += '<div class="section"><h3>다른 후보 부서 · 한 번 클릭으로 재배정</h3><div class="alts">';
    if (alts.length) {
      html += alts.map(function (x, i) {
        var s = typeof x.score === "number" ? x.score : null;
        return '<div class="alt">' +
          '<div class="alt-main"><div class="alt-name">' + esc(x.full_name) +
            (x.position ? ' <span class="tag">' + esc(x.position) + "</span>" : "") +
            (restoredLabel(x) ? ' <span class="tag tag--prev">' + esc(restoredLabel(x)) + "</span>" : "") + "</div>" +
            '<div class="alt-ev"><span class="alt-ev-label">근거</span>' +
              evidenceHTML(x.evidence, "alt" + i) + "</div></div>" +
          '<div class="alt-right">' +
            (s === null
              ? '<div class="score score--none">' +
                  (x.restored ? "배정돼 있던 부서<br>민원카드에 점수 없음" : "매칭 점수 없음") + "</div>"
              : '<div class="score"><div class="score-top"><span>매칭 점수</span><span class="score-num">' +
                s.toFixed(2) + '</span></div>' +
                '<div class="score-track"><span class="score-fill" style="width:' +
                Math.round(Math.max(0, Math.min(1, s)) * 100) + '%"></span></div></div>') +
            '<button class="btn btn-primary" data-act="reassign" data-i="' + i + '">이 부서로 재배정</button>' +
          "</div></div>";
      }).join("");
    } else {
      html += '<p class="alt-empty">후보 부서가 없습니다.</p>';
    }
    html += "</div></div>";

    // 처리 이력 — AI 최초 배정과 담당자의 개입이 모두 남는다
    html += renderHistory(raw);

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

  /**
   * 처리 이력.
   * AI 최초 배정(근거 포함)을 항상 맨 아래 기준선으로 깔고, 그 위에 담당자의 개입을 쌓는다.
   * 담당자가 AI 배정을 얼마나 자주 뒤집는지가 라우팅 품질 지표이므로 근거까지 함께 남긴다.
   */
  function renderHistory(raw) {
    var events = historyOf(raw.id).slice().sort(function (a, b) {
      return String(a.at || "").localeCompare(String(b.at || ""));
    });
    var ai = raw.assigned || {};
    var aiName = String(ai.full_name || "").trim() || "미배정";

    var rows = [
      '<li class="hist-row hist-row--ai">' +
        '<span class="hist-when">' + esc(fmtDateTime(raw.created_at)) + "</span>" +
        '<span class="hist-who">AI</span>' +
        '<div class="hist-what"><b>최초 배정 — ' + esc(aiName) + "</b>" +
          '<div class="hist-ev">근거: ' + esc(truncate(String(ai.evidence || "근거 없음"), 90)) + "</div></div></li>"
    ];

    events.forEach(function (ev) {
      var isAssign = ev.type === "assign";
      rows.push('<li class="hist-row">' +
        '<span class="hist-when">' + esc(fmtDateTime(ev.at)) + "</span>" +
        '<span class="hist-who">' + esc(ev.by || "담당자") + (ev.auto ? " · 자동" : "") + "</span>" +
        '<div class="hist-what">' +
          (isAssign
            ? "<b>재배정 — " + esc(ev.from || "미배정") + " → " + esc(ev.to || "") + "</b>" +
              (ev.to_evidence ? '<div class="hist-ev">새 근거: ' + esc(truncate(String(ev.to_evidence), 90)) + "</div>" : "")
            : "처리 상태 " + esc(ev.from || "") + " → <b>" + esc(ev.to || "") + "</b>") +
        "</div></li>");
    });

    var flips = events.filter(function (e) { return e.type === "assign"; }).length;
    return '<div class="section"><h3>처리 이력' +
      (flips ? ' <span class="hist-flag">담당자 재배정 ' + flips + "회</span>" : "") + "</h3>" +
      '<ol class="hist">' + rows.reverse().join("") + "</ol>" +
      '<p class="note">담당자가 AI 배정을 뒤집은 기록은 라우팅 품질 측정에 쓰입니다(목표: 재배정 20% 미만).</p></div>';
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
    el.detail.querySelectorAll('[data-act="ev-toggle"]').forEach(function (b) {
      b.addEventListener("click", function () {
        var k = b.dataset.key;
        if (state.expanded[k]) delete state.expanded[k]; else state.expanded[k] = 1;
        renderDetail();
      });
    });
    el.detail.querySelectorAll('[data-act="wf"]').forEach(function (b) {
      b.addEventListener("click", function () {
        setWorkflow(raw.id, b.dataset.key);
        render();
      });
    });
    el.detail.querySelectorAll('[data-act="reassign"]').forEach(function (b) {
      b.addEventListener("click", function () { reassign(raw, alts[Number(b.dataset.i)]); });
    });
    var undo = el.detail.querySelector('[data-act="undo"]');
    if (undo) undo.addEventListener("click", function () { undoReassign(raw); });
  }

  // ---------- 재배정 ----------
  // 서버 쓰기 API가 생기면 이 두 함수 안에서 POST 를 호출하도록 바꾸면 된다.
  function reassign(raw, alt) {
    if (!alt) return;
    var cur = effective(raw);
    var prev = cur.assigned;
    var nextAlts = (cur.alternatives || []).filter(function (x) { return x !== alt; });
    var prevName = prev && String(prev.full_name || "").trim();
    if (prevName && prevName !== "미배정") {
      nextAlts.unshift({
        full_name: prev.full_name,
        department_id: prev.department_id,
        position: prev.position,
        phone_token: prev.phone_token,
        score: typeof prev.score === "number" ? prev.score : null,
        evidence: prev.evidence,
        // 배정돼 있다가 후보로 내려온 것. 민원카드의 assigned 에는 점수가 없으므로
        // 빈 점수 대신 출처를 밝힌다. AI 최초인지 담당자 이전 배정인지는 렌더 시점에 가린다.
        restored: true
      });
    }

    var e = entry(raw.id);
    e.assignment = {
      assigned: {
        department_id: alt.department_id || null,
        full_name: alt.full_name,
        position: alt.position || null,
        phone_token: alt.phone_token || null,
        phone: alt.phone || null,
        evidence: alt.evidence || "",
        score: typeof alt.score === "number" ? alt.score : null
      },
      alternatives: nextAlts
    };
    pushHistory(raw.id, {
      type: "assign", at: new Date().toISOString(), by: "담당자",
      from: prevName || "미배정",
      to: alt.full_name,
      from_evidence: (prev && prev.evidence) || "",
      to_evidence: alt.evidence || ""
    });
    saveBook();

    delete raw._hay;
    state.expanded = {};
    fillDeptFilter();
    render();
    toast(alt.full_name + " 로 재배정했습니다. 이력에 남습니다.");
    announce("접수번호 " + raw.id + " 를 " + alt.full_name + " 로 재배정했습니다.");
  }

  /** AI 최초 배정으로 되돌린다. 되돌린 사실 자체도 이력으로 남는다. */
  function undoReassign(raw) {
    var cur = effective(raw);
    var from = (cur.assigned && cur.assigned.full_name) || "";
    var aiName = (raw.assigned && raw.assigned.full_name) || "미배정";
    var e = entry(raw.id);
    delete e.assignment;
    pushHistory(raw.id, {
      type: "assign", at: new Date().toISOString(), by: "담당자",
      from: from, to: aiName,
      to_evidence: (raw.assigned && raw.assigned.evidence) || "",
      revert: true
    });
    saveBook();

    delete raw._hay;
    state.expanded = {};
    fillDeptFilter();
    render();
    toast("AI 배정으로 되돌렸습니다.");
  }

  function saveBook() {
    try { localStorage.setItem(LS_BOOK, JSON.stringify(state.book)); } catch (e) {}
  }

  /** 담당자 작업 기록을 읽는다. 이전 버전(v1 재배정 전용) 기록이 있으면 옮겨 담는다. */
  function loadBook() {
    var book = readJSON(LS_BOOK, null);
    if (book) return book;

    book = {};
    var legacy = readJSON(LS_REASSIGN_V1, {});
    Object.keys(legacy).forEach(function (id) {
      var v = legacy[id];
      book[id] = {
        assignment: { assigned: v.assigned, alternatives: v.alternatives || [] },
        history: [{
          type: "assign", at: v.at, by: "담당자",
          from: v.from || "미배정",
          to: (v.assigned && v.assigned.full_name) || "",
          to_evidence: (v.assigned && v.assigned.evidence) || ""
        }]
      };
    });
    return book;
  }

  function entry(id) {
    if (!state.book[id]) state.book[id] = {};
    return state.book[id];
  }

  function historyOf(id) {
    var e = state.book[id];
    return (e && e.history) || [];
  }

  function pushHistory(id, event) {
    var e = entry(id);
    if (!e.history) e.history = [];
    e.history.push(event);
  }

  // ---------- CSV 내보내기 ----------
  // 공무원은 결국 엑셀로 본다. 엑셀이 한글을 깨뜨리지 않게 UTF-8 BOM 을 붙이고
  // 줄바꿈은 CRLF 로 낸다. 외부 라이브러리 없이 Blob + createObjectURL 로 저장한다.
  function toggleExportMenu(open) {
    if (!el.exportMenu) return;
    if (open) {
      el.exportNFiltered.textContent = "(" + visible().length + "건)";
      el.exportNAll.textContent = "(" + state.complaints.length + "건)";
    }
    el.exportMenu.hidden = !open;
    el.exportBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  var CSV_COLUMNS = [
    ["접수번호",           function (c) { return c.id; }],
    ["접수일시",           function (c) { return fmtDateTime(c.created_at); }],
    ["통화시간",           function (c) { return fmtDuration(c.duration_sec); }],
    ["요약",               function (c) { return c.summary || ""; }],
    ["분류",               function (c) { return c.category || ""; }],
    ["배정부서",           function (c) { return deptOf(c) || "미배정"; }],
    ["배정근거",           function (c) { return (effective(c).assigned || {}).evidence || ""; }],
    ["상태",               function (c) { return WF[workflowOf(c)].label; }],
    // 신고자 연락처는 마스킹된 값만 내보낸다. 원본은 카드에도 없고, CSV 로도 절대 나가지 않는다.
    ["신고자연락처(마스킹)", function (c) { return (c.caller && c.caller.phone_masked) || ""; }],
    // 아래 두 칸은 재배정 비율(GOAL.md H3)을 엑셀에서 직접 검산하기 위한 추가 열이다.
    ["재배정여부",         function (c) { return statusOf(c) === "reassigned" ? "Y" : "N"; }],
    ["AI최초배정부서",     function (c) {
      var n = c.assigned && String(c.assigned.full_name || "").trim();
      return n || "미배정";
    }]
  ];

  function csvCell(value) {
    var v = String(value == null ? "" : value).replace(/\r?\n/g, " ").trim();
    return /[",]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  function buildCSV(rows) {
    var lines = [CSV_COLUMNS.map(function (col) { return csvCell(col[0]); }).join(",")];
    rows.forEach(function (c) {
      lines.push(CSV_COLUMNS.map(function (col) { return csvCell(col[1](c)); }).join(","));
    });
    return "\uFEFF" + lines.join("\r\n") + "\r\n"; // BOM — 엑셀 한글 깨짐 방지
  }

  function exportCSV(scope) {
    var rows = scope === "all" ? state.complaints.slice() : visible();
    if (!rows.length) { toast("내보낼 민원이 없습니다."); return; }

    var blob = new Blob([buildCSV(rows)], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "voisso_민원목록_" + stampNow() + (scope === "all" ? "_전체" : "_필터") + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    toast(rows.length + "건을 CSV 로 내보냈습니다.");
  }

  function stampNow() {
    var d = new Date(), p = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "_" + p(d.getHours()) + p(d.getMinutes());
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

  function truncate(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n) + "…" : s;
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

  /**
   * 테스트 훅.
   * 브라우저 자동화 없이 순수 로직(CSV 생성, 지표 계산, 상태 파생)을 Node 에서 검증하기 위한 창구다.
   * 화면 동작에는 관여하지 않는다.
   */
  window.__voissoDashboard = {
    state: state,
    buildCSV: function (rows) { return buildCSV(rows); },
    csvColumns: function () { return CSV_COLUMNS.map(function (c) { return c[0]; }); },
    reassignRate: function () { return reassignRate(state.complaints); },
    workflowOf: workflowOf,
    statusOf: statusOf,
    effective: effective,
    historyOf: historyOf,
    reassign: reassign,
    undoReassign: undoReassign,
    setWorkflow: setWorkflow,
    nextDelay: nextDelay,
    visible: visible
  };

  /** 스크린리더에 알린다. 화면에는 보이지 않는다. */
  function announce(msg) {
    if (!el.liveRegion) return;
    el.liveRegion.textContent = msg;
  }

  var toastTimer = null;
  function toast(msg) {
    var old = document.querySelector(".toast");
    if (old) old.remove();
    var n = document.createElement("div");
    n.className = "toast";
    n.setAttribute("role", "status");
    n.setAttribute("aria-live", "polite");
    n.textContent = msg;
    document.body.appendChild(n);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { n.remove(); }, 2600);
  }
})();
