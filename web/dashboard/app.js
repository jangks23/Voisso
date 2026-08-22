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
  var WAIT_WINDOW = CFG.HANDOFF_WAIT_WINDOW_MS || 900000;

  // 담당자가 화면에서 만든 값(처리 상태·재배정·이력)을 모아 두는 단일 저장소.
  // TODO(P6): 서버에 쓰기 API(PATCH /api/complaints/{id})가 생기면 이 자리를 서버로 옮긴다.
  //           지금은 브라우저 localStorage 에만 남는다 — README 에 명시.
  var LS_BOOK = "voisso.dashboard.casebook.v1";
  // 담당자 이름·부서는 **이 브라우저에만** 남긴다. 급할 때 매번 입력하게 하면 못 쓴다.
  // 서버에는 계약 5-B 대로 start 요청에 실어 보내지만, 서버가 마스킹해서만 저장한다(홍○○).
  // 민원카드·CSV 어디에도 담당자 이름은 남지 않는다.
  var LS_OFFICER_DEPT = "voisso.dashboard.officer.department.v1";
  var LS_OFFICER_NAME = "voisso.dashboard.officer.name.v1";
  var LS_SORT = "voisso.dashboard.sort.v1";
  var LS_REASSIGN_V1 = "voisso.dashboard.reassign.v1"; // 이전 버전 마이그레이션용
  var LS_THEME = "voisso.dashboard.theme";
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

  /**
   * 긴급도 (계약 5-A).
   *
   * 색만으로 구분하지 않는다 — 색각 이상 담당자가 있다.
   * 모든 표시에 **라벨 글자**를 함께 쓰고, 응급은 테두리 두께·목록 상단 고정 같은
   * 색 아닌 단서를 겹쳐 준다. 깜빡이는 애니메이션은 넣지 않는다(하루 종일 보는 화면이다).
   */
  var URGENCY = [
    { key: "응급", rank: 0, cls: "urg--emergency", hint: "사람이 다칠 수 있다. 지금." },
    { key: "중요", rank: 1, cls: "urg--high",      hint: "방치하면 피해가 커진다. 오늘~내일" },
    { key: "보통", rank: 2, cls: "urg--normal",    hint: "정상 처리 일정" },
    { key: "낮음", rank: 3, cls: "urg--low",       hint: "급하지 않다" }
  ];
  var URG = {};
  URGENCY.forEach(function (u) { URG[u.key] = u; });

  // notes 출처 라벨. 서버가 영문 키를 주므로 화면에는 우리말로 바꿔 쓴다.
  var NOTE_SOURCE = {
    caller: "신고자",
    callback: "안내 전화 문의",
    handoff: "담당자 통화",
    agent: "AI 상담"
  };

  // 진행 안내 콜백 상태 (계약 5-C)
  var CALLBACK = {
    none:     { label: "안내 없음", cls: "cb--none" },
    pending:  { label: "안내 대기", cls: "cb--pending" },
    answered: { label: "안내 통화중", cls: "cb--answered" },
    closed:   { label: "안내 완료", cls: "cb--closed" }
  };

  // 핸드오프 상태 — 담당자가 '지금 나를 기다리는 민원'을 한눈에 알아야 한다.
  var HANDOFF = {
    none:   { label: "미연결", cls: "ho--none" },
    open:   { label: "통화중", cls: "ho--open" },
    closed: { label: "상담종료", cls: "ho--closed" }
  };

  // ---------- 상태 ----------
  var state = {
    complaints: [],
    source: "loading",   // live | mock | loading
    apiBase: null,
    selectedId: null,
    book: loadBook(),     // id -> { workflow, assignment, history }
    filter: { q: "", dept: "", status: "" },
    // 기본은 최신순 + 응급 상단 고정. 이유는 README '정렬을 이렇게 정한 이유' 참고.
    sortMode: localStorage.getItem(LS_SORT) || "recent",
    seen: null,          // 최초 로드 이후에 들어온 건만 NEW 로 본다
    fresh: {},           // id -> 도착 시각(ms)
    animated: {},        // 하이라이트를 이미 재생한 id
    expanded: {},        // 상세에서 펼쳐 둔 근거 블록
    handoff: {},           // id -> {status, officer, messages, ...} 마지막으로 받은 상태
    handoffApi: null,      // true=실서버, false=목, null=아직 판정 전
    officer: {
      name: localStorage.getItem(LS_OFFICER_NAME) || "",
      department: localStorage.getItem(LS_OFFICER_DEPT) || ""
    },
    handoffBusy: false,
    callback: {},          // id -> 마지막으로 받은 콜백 상태
    callbackApi: null,     // true=실서버, false=목
    callbackStatuses: {},  // 목록 뱃지용
    callbackForm: null,
    callbackDraft: "",
    callbackBusy: false,
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
     "stat-emergency","stat-urgency-sub","stat-urgency-dist","sort-btn","wait-band","back-btn","back-id",
     "stat-unread","stat-live","stat-live-sub","stat-unassigned",
     "stat-rate","stat-rate-sub","stat-rate-fill","stat-dist",
     "q","f-dept","f-status","reset-btn","export-btn","export-menu",
     "export-n-filtered","export-n-all","list","list-count","detail","detail-empty"].forEach(function (id) {
      el[camel(id)] = document.getElementById(id);
    });
  }

  /**
   * 좁은 폭(발표용 /demo iframe 등)에서는 목록과 상세를 좌우로 못 나눈다.
   * 한 번에 하나씩 보여 주고, 카드를 고르면 상세로 넘어간다.
   */
  var narrowMQ = window.matchMedia ? window.matchMedia("(max-width: 900px)") : null;
  function isNarrow() { return !!(narrowMQ && narrowMQ.matches); }
  function setView(v) {
    document.documentElement.setAttribute("data-view", v);
    if (v === "detail" && el.backId) {
      el.backId.textContent = state.selectedId ? "접수번호 " + state.selectedId : "";
    }
  }

  function bindEvents() {
    setView("list");
    if (narrowMQ) {
      var onChange = function () {
        // 넓어지면 두 칸이 함께 보이므로 전환 상태는 의미가 없다.
        setView(isNarrow() && state.selectedId ? "detail" : "list");
      };
      if (narrowMQ.addEventListener) narrowMQ.addEventListener("change", onChange);
      else if (narrowMQ.addListener) narrowMQ.addListener(onChange);
    }
    if (el.backBtn) el.backBtn.addEventListener("click", function () {
      setView("list");
      var node = el.list.querySelector('.card[data-id="' + cssEsc(state.selectedId || "") + '"]');
      if (node && node.scrollIntoView) node.scrollIntoView({ block: "nearest" });
      el.list.focus();
    });

    el.waitBand.addEventListener("click", function () {
      state.filter.status = state.filter.status === "ho:waiting" ? "" : "ho:waiting";
      el.fStatus.value = state.filter.status;
      markActive();
      render();
    });

    el.sortBtn.addEventListener("click", function () {
      state.sortMode = state.sortMode === "recent" ? "urgency" : "recent";
      try { localStorage.setItem(LS_SORT, state.sortMode); } catch (e) {}
      renderSortBtn();
      render();
      toast(state.sortMode === "urgency"
        ? "긴급도순으로 정렬합니다."
        : "최신순으로 정렬합니다. 응급은 계속 위에 고정됩니다.");
    });
    renderSortBtn();

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
      if (card) {
        markActive();
        select(card.dataset.id, { user: true });
        if (isNarrow()) setView("detail");   // 좁은 화면에서는 상세로 넘어간다
      }
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
        // 서버가 handoffs 맵을 실어 주면 /api/handoff/* 도 있다는 뜻이다(추가 요청 없이 판정).
        state.handoffApi = data.handoffs !== undefined && data.handoffs !== null;
        if (state.handoffApi) {
          var before = state.handoffStatuses || {};
          state.handoffStatuses = data.handoffs;
          Object.keys(data.handoffs).forEach(function (id) {
            if (before[id] !== data.handoffs[id]) state.lastChange = Date.now();
          });
        }
        // 서버가 callbacks 맵을 주면 콜백 API 도 있다는 뜻. (P6 에 추가 요청해 둔 필드)
        if (data.callbacks !== undefined && data.callbacks !== null) {
          state.callbackApi = true;
          state.callbackStatuses = data.callbacks;
        }
        setSource("live");
        apply(list, opts);
        refreshHandoff(state.selectedId);
        refreshCallback(state.selectedId);
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
      state.handoffApi = false;
      setSource("mock");
      state.callbackApi = false;
      if (!wasLive || CFG.USE_MOCK) apply((window.VOISSO_MOCK_COMPLAINTS || []).slice(), opts);
      refreshHandoff(state.selectedId);
      refreshCallback(state.selectedId);
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
      announce(msg + ". 어르신이 담당자 연결을 기다리고 있을 수 있습니다.");
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

  function renderSortBtn() {
    if (!el.sortBtn) return;
    var urg = state.sortMode === "urgency";
    el.sortBtn.textContent = urg ? "긴급도순" : "최신순";
    el.sortBtn.title = urg
      ? "긴급도순 — 응급 → 중요 → 보통 → 낮음 (누르면 최신순)"
      : "최신순 · 응급은 상단 고정 (누르면 긴급도순)";
    el.sortBtn.className = "sort-btn" + (urg ? " is-urgency" : "");
  }

  function renderLastSync() {
    if (!el.lastSync) return;
    el.lastSync.textContent = state.lastSync
      ? "갱신 " + new Date(state.lastSync).toLocaleTimeString("ko-KR", {
          hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
      : "";
  }

  // ---------- 핸드오프 (계약 5-B) ----------
  // 실서버에 /api/handoff/* 가 있으면 그쪽을, 없으면 handoff-mock.js 를 쓴다.
  // 판정은 GET /api/complaints 응답에 `handoffs` 맵이 실려 오는지로 한다(추가 요청 없음).
  function handoffLive() {
    return state.handoffApi === true && state.apiBase !== null;
  }

  function MOCK() { return window.VOISSO_HANDOFF_MOCK; }

  function hoGet(id) {
    if (!handoffLive()) return Promise.resolve(MOCK().get(id));
    return fetchJSON(state.apiBase + "/api/handoff/" + encodeURIComponent(id), 3000)
      .catch(function () { return null; });   // 일시적 실패 — 화면은 마지막 상태를 유지한다
  }

  function hoPost(id, path, body) {
    if (!handoffLive()) {
      if (path === "start") return Promise.resolve(MOCK().start(id, body.officer_name, body.department));
      if (path === "message") return Promise.resolve(MOCK().message(id, body.role, body.text));
      if (path === "close") return Promise.resolve(MOCK().close(id));
      return Promise.reject(new Error("unknown"));
    }
    return fetch(state.apiBase + "/api/handoff/" + encodeURIComponent(id) + "/" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data && data.detail ? data.detail : "HTTP " + r.status);
        return data;
      });
    });
  }

  /** 목록에서 쓰는 핸드오프 상태. 서버가 주면 그 값, 아니면 목에서 계산한다. */
  function handoffStatusOf(id) {
    if (handoffLive()) {
      return (state.handoffStatuses && state.handoffStatuses[id]) || "none";
    }
    var h = state.handoff[id];
    if (h) return h.status;
    return MOCK().get(id).status;
  }

  /** 선택된 민원의 대화를 다시 받아온다. 목록 폴링과 같은 주기로 돌린다. */
  function refreshHandoff(id, opts) {
    if (!id) return Promise.resolve();
    return hoGet(id).then(function (h) {
      if (!h || h.status === undefined) return;
      var prev = state.handoff[id];
      var grew = prev && h.messages && prev.messages && h.messages.length > prev.messages.length;
      state.handoff[id] = h;
      // 목록 뱃지는 handoffStatuses 를 보므로 여기서 같이 갱신한다.
      // 안 그러면 '통화 잇기' 직후 다음 목록 폴링(최대 4초)까지 '미연결' 로 보인다.
      if (!state.handoffStatuses) state.handoffStatuses = {};
      if (h.status === "none") delete state.handoffStatuses[id];
      else state.handoffStatuses[id] = h.status;
      if (h.status === "open") state.lastChange = Date.now();  // 상담 중에는 느려지지 않는다
      if (grew) {
        var last = h.messages[h.messages.length - 1];
        if (last && last.role === "caller") {
          announce("어르신 답변: " + (last.standard || last.text || ""));
          if (state.selectedId !== id) toast("#" + id + " 어르신 답변이 도착했습니다.");
        }
      }
      if ((grew || (opts && opts.render)) && state.selectedId === id) renderDetail();
    });
  }

  // ---------- 진행 안내 콜백 (계약 5-C) ----------
  // 핸드오프와 같은 구조다. 서버에 /api/callback/* 가 있으면 그쪽, 없으면 callback-mock.js.
  function CBMOCK() { return window.VOISSO_CALLBACK_MOCK; }

  function callbackLive() {
    return state.callbackApi === true && state.apiBase !== null;
  }

  function cbGet(id) {
    if (!callbackLive()) return Promise.resolve(CBMOCK().get(id));
    return fetchJSON(state.apiBase + "/api/callback/" + encodeURIComponent(id), 3000)
      .catch(function () { return null; });
  }

  function cbPost(id, path, body) {
    if (!callbackLive()) {
      var M = CBMOCK();
      if (path === "schedule") return Promise.resolve(M.schedule(id, body.briefing, body.officer_name, body.department));
      if (path === "answer") return Promise.resolve(M.answer(id));
      if (path === "message") return Promise.resolve(M.message(id, body.role, body.text));
      if (path === "close") return Promise.resolve(M.close(id));
      return Promise.reject(new Error("unknown"));
    }
    return fetch(state.apiBase + "/api/callback/" + encodeURIComponent(id) + "/" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data && data.detail ? data.detail : "HTTP " + r.status);
        return data;
      });
    });
  }

  function callbackStatusOf(id) {
    var c = state.callback[id];
    if (c && c.status) return c.status;
    if (callbackLive()) return (state.callbackStatuses && state.callbackStatuses[id]) || "none";
    return CBMOCK().get(id).status;
  }

  /**
   * 연결 대기 — **지금 나를 기다리는 사람이 있는가.**
   *
   * 어르신은 통화를 끝낸 뒤 화면 앞에서 담당자 연결을 기다린다.
   * 그런데 '미연결' 은 과거 민원 전부의 기본값이라 그것만으로는 신호가 되지 않는다.
   * 그래서 **접수된 지 얼마 안 됐고 아직 아무도 연결하지 않은 건**만 골라낸다.
   * (이미 완료·반려한 건은 기다릴 사람이 없으므로 뺀다.)
   */
  function isAwaitingHandoff(c) {
    if (handoffStatusOf(c.id) !== "none") return false;
    var wf = workflowOf(c);
    if (wf === "done" || wf === "rejected") return false;
    var t = new Date(c.created_at).getTime();
    if (isNaN(t)) return false;
    return (Date.now() - t) <= WAIT_WINDOW;
  }

  function awaitingList() {
    return state.complaints.filter(isAwaitingHandoff);
  }

  /** 어르신이 추가로 물은 것 — 담당자가 답해야 할 목록 */
  function callerQuestions(id) {
    var c = state.callback[id];
    if (!c || !c.messages) return [];
    return c.messages.filter(function (m) { return m.role === "caller"; });
  }

  function refreshCallback(id, opts) {
    if (!id) return Promise.resolve();
    return cbGet(id).then(function (c) {
      if (!c || c.status === undefined) return;
      var prev = state.callback[id];
      var grew = prev && c.messages && prev.messages && c.messages.length > prev.messages.length;
      state.callback[id] = c;
      if (!state.callbackStatuses) state.callbackStatuses = {};
      if (c.status === "none") delete state.callbackStatuses[id];
      else state.callbackStatuses[id] = c.status;
      if (c.status === "pending" || c.status === "answered") state.lastChange = Date.now();
      if (grew) {
        var last = c.messages[c.messages.length - 1];
        if (last && last.role === "caller") {
          var q = last.standard || last.text || "";
          announce("어르신 추가 질문: " + q);
          if (state.selectedId !== id) toast("#" + id + " 어르신이 추가로 물으셨습니다.");
        }
      }
      if ((grew || (opts && opts.render)) && state.selectedId === id) renderDetail();
    });
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

  /**
   * 긴급도. 담당자가 고쳤으면 그 값이 우선한다.
   * AI 판정 원본은 카드에 그대로 남아 있고 이력에서 확인된다.
   */
  function urgencyOf(c) {
    var e = state.book[c.id];
    if (e && e.urgency && URG[e.urgency.level]) {
      return {
        level: e.urgency.level,
        reason: e.urgency.reason || "담당자가 직접 조정했습니다.",
        signals: (c.urgency && c.urgency.signals) || [],
        decided_by: "officer",
        safety_referral: (c.urgency && c.urgency.safety_referral) || null,
        overridden: true,
        ai: c.urgency || null,
        history: (c.urgency && c.urgency.history) || []
      };
    }
    var u = c.urgency;
    if (!u || !URG[u.level]) return null;   // 서버가 아직 안 주는 카드
    // 서버에서 담당자가 이미 조정한 카드는 urgency.history 에 원래 판정이 들어 있다.
    var hist = Array.isArray(u.history) ? u.history : [];
    var byOfficer = u.decided_by === "officer";
    return {
      level: u.level,
      reason: u.reason || "",
      signals: Array.isArray(u.signals) ? u.signals : [],
      decided_by: u.decided_by || "rule",
      safety_referral: u.safety_referral || null,
      overridden: byOfficer,
      // 조정됐다면 이력의 첫 항목이 AI 최초 판정이다.
      ai: byOfficer && hist.length ? hist[0] : u,
      history: hist
    };
  }

  function urgencyRank(c) {
    var u = urgencyOf(c);
    return u ? URG[u.level].rank : 2.5;   // 판정 없는 카드는 보통과 낮음 사이
  }

  function isEmergency(c) {
    var u = urgencyOf(c);
    return !!u && u.level === "응급";
  }

  /**
   * 담당자가 긴급도를 조정한다. AI 판정과 그 근거는 이력에 남는다.
   *
   * 서버에 조정 엔드포인트가 있으면 그쪽에 쓴다(모두에게 반영된다).
   * 없으면 브라우저 casebook 에만 남긴다 — README 에 그 한계를 밝혀 두었다.
   */
  function setUrgency(id, level, reason) {
    if (!URG[level]) return;
    var card = byId(id);
    var cur = card ? urgencyOf(card) : null;
    if (cur && cur.level === level) return;
    var at = new Date().toISOString();
    var note = (reason || "").trim();

    // 이력은 어느 경로로 조정하든 대시보드 쪽에도 남긴다(처리 이력 한 곳에서 보이게).
    pushHistory(id, {
      type: "urgency", at: at, by: "담당자",
      from: cur ? cur.level : "판정 없음",
      to: level,
      from_reason: cur ? cur.reason : "",
      to_reason: note,
      ai_level: card && card.urgency ? card.urgency.level : null
    });

    var done = function () {
      saveBook();
      toast("긴급도를 '" + level + "' 로 조정했습니다. 이력에 남습니다.");
      announce("접수번호 " + id + " 긴급도 " + level + ".");
      render();
    };

    if (state.apiBase !== null) {
      fetch(state.apiBase + "/api/complaints/" + encodeURIComponent(id) + "/urgency", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ level: level, reason: note })
      }).then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data && data.detail ? data.detail : "HTTP " + r.status);
          if (card && data.urgency) card.urgency = data.urgency;   // 서버 판정으로 갱신
          delete (entry(id)).urgency;                              // 로컬 사본은 두지 않는다
          if (card) delete card._hay;
          done();
        });
      }).catch(function () {
        // 서버가 못 받으면 브라우저에만 남긴다. 화면이 멈추는 것보다 낫다.
        entry(id).urgency = { level: level, reason: note, at: at, by: "담당자" };
        done();
        toast("서버에 저장하지 못해 이 브라우저에만 반영했습니다.");
      });
      return;
    }

    entry(id).urgency = { level: level, reason: note, at: at, by: "담당자" };
    done();
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

  /**
   * 목록 정렬.
   *
   * 기본은 **최신순 + 응급 상단 고정**이다. 긴급도 전체 정렬을 기본으로 하지 않은 이유:
   *  - 담당자에게 목록은 작업 큐다. "위가 최신" 은 1초면 익히는 규칙이고,
   *    통화가 끝나자마자 새 민원이 맨 위에 뜨는 동작이 이 화면의 실시간성 그 자체다.
   *  - 긴급도로 전부 정렬하면 방금 들어온 '보통' 이 목록 중간에 끼어 보이지 않는다.
   *  - 그래서 예외는 하나만 둔다 — **응급**. "사람이 다칠 수 있다. 지금" 은
   *    스크롤해서 찾게 두면 안 되므로 무조건 위로 올린다.
   *  - 밀린 건을 훑을 때는 '긴급도순' 토글로 바꾸면 된다. 중요 건만 보려면 필터가 더 빠르다.
   */
  function sortRows(rows) {
    var byRecent = function (a, b) {
      return String(b.created_at || "").localeCompare(String(a.created_at || ""));
    };
    if (state.sortMode === "urgency") {
      return rows.slice().sort(function (a, b) {
        var d = urgencyRank(a) - urgencyRank(b);
        return d !== 0 ? d : byRecent(a, b);
      });
    }
    return rows.slice().sort(function (a, b) {
      var ea = isEmergency(a) ? 0 : 1, eb = isEmergency(b) ? 0 : 1;
      return ea !== eb ? ea - eb : byRecent(a, b);
    });
  }

  function visible() {
    var q = state.filter.q.toLowerCase();
    return sortRows(state.complaints.filter(function (c) {
      if (state.filter.dept && deptOf(c) !== state.filter.dept) return false;
      if (state.filter.status) {
        var f = state.filter.status;
        if (f.indexOf("wf:") === 0) { if (workflowOf(c) !== f.slice(3)) return false; }
        else if (f.indexOf("as:") === 0) { if (statusOf(c) !== f.slice(3)) return false; }
        else if (f === "ho:waiting") { if (!isAwaitingHandoff(c)) return false; }
        else if (f.indexOf("ho:") === 0) { if (handoffStatusOf(c.id) !== f.slice(3)) return false; }
        else if (f.indexOf("cb:") === 0) { if (callbackStatusOf(c.id) !== f.slice(3)) return false; }
        else if (f.indexOf("ug:") === 0) {
          var u = urgencyOf(c);
          if (!u || u.level !== f.slice(3)) return false;
        }
      }
      if (!q) return true;
      return haystack(c).indexOf(q) !== -1;
    }));
  }

  function haystack(c) {
    if (c._hay) return c._hay;
    var e = effective(c);
    var parts = [c.id, c.summary, c.category, deptOf(c),
                 e.assigned && e.assigned.evidence,
                 c.caller && c.caller.name_masked];
    (c.alternatives || []).forEach(function (a) { parts.push(a.full_name, a.evidence); });
    (c.transcript || []).forEach(function (t) { parts.push(t.dialect, t.standard); });
    (c.notes || []).forEach(function (n) { parts.push(n && (n.text || n.standard)); });
    var cb = state.callback[c.id];
    if (cb && cb.briefing) parts.push(cb.briefing.standard);
    var u = urgencyOf(c);
    if (u) { parts.push(u.level, u.reason); (u.signals || []).forEach(function (x) { parts.push(x); }); }
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
    var liveCount = all.filter(function (c) { return handoffStatusOf(c.id) === "open"; }).length;
    el.statLive.textContent = liveCount;
    el.statLive.className = "stat-value " + (liveCount ? "stat-value--live" : "");
    var cbWaiting = all.filter(function (c) {
      var s = callbackStatusOf(c.id);
      return s === "pending" || s === "answered";
    }).length;
    var awaiting = awaitingList().length;
    el.statLiveSub.textContent = (awaiting ? "연결 대기 " + awaiting + "건 · " : "") +
      "처리중 " + (wfCount.progress || 0) + "건" +
      (cbWaiting ? " · 안내 " + cbWaiting + "건" : "");
    el.statUnassigned.textContent = all.filter(function (c) { return statusOf(c) === "unassigned"; }).length;

    renderUrgencyStats(all);
    renderReassignRate(all);
    renderDist(all);
  }

  /** 긴급도 분포 — 담당자에게 가장 중요한 숫자는 "오늘 응급 몇 건인가" 다. */
  function renderUrgencyStats(all) {
    var counts = { 응급: 0, 중요: 0, 보통: 0, 낮음: 0 };
    var judged = 0, overridden = 0;
    all.forEach(function (c) {
      var u = urgencyOf(c);
      if (!u) return;
      judged++;
      counts[u.level] = (counts[u.level] || 0) + 1;
      if (u.overridden) overridden++;
    });

    if (!judged) {
      el.statEmergency.textContent = "–";
      el.statEmergency.className = "stat-value";
      el.statUrgencySub.textContent = "서버 판정 대기";
      el.statUrgencyDist.innerHTML = "";
      return;
    }

    el.statEmergency.textContent = counts["응급"];
    el.statEmergency.className = "stat-value" + (counts["응급"] ? " stat-value--emergency" : "");
    el.statUrgencySub.textContent = "판정 " + judged + "건" +
      (overridden ? " · 담당자 조정 " + overridden + "건" : "");
    el.statUrgencyDist.innerHTML = URGENCY.map(function (u) {
      var n = counts[u.key] || 0;
      return '<li class="' + u.cls + '"><span class="urg-dist-k">' + esc(u.key) + "</span>" +
        '<span class="urg-dist-n">' + n + "</span></li>";
    }).join("");
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

  function renderWaitBand() {
    if (!el.waitBand) return;
    var waiting = awaitingList();
    var n = waiting.length;
    if (!n) { el.waitBand.hidden = true; el.waitBand.className = "wait-band"; return; }

    // 응급이 기다리고 있으면 더 강하게 — 사람이 위험한 건을 방치하면 안 된다.
    var emg = waiting.filter(isEmergency);
    var filtered = state.filter.status === "ho:waiting";
    el.waitBand.hidden = false;
    el.waitBand.className = "wait-band" + (emg.length ? " is-emergency" : "");

    var lead = emg.length
      ? '<span class="wait-n">❗ 응급 ' + emg.length + "건이 연결을 기다립니다</span>"
      : '<span class="wait-n">연결 대기 ' + n + "건</span>";
    var msg = emg.length
      ? "지금 위험할 수 있는 민원입니다. 먼저 통화를 이어 주세요." +
        (n > emg.length ? " (그 밖 대기 " + (n - emg.length) + "건)" : "")
      : "어르신이 화면 앞에서 담당자 연결을 기다리고 있을 수 있습니다.";

    el.waitBand.innerHTML = lead +
      '<span class="wait-msg">' + esc(msg) + "</span>" +
      '<span class="wait-act">' + (filtered ? "전체 보기" : "이 건만 보기") + "</span>";
    el.waitBand.setAttribute("aria-label",
      (emg.length ? "응급 " + emg.length + "건 포함 " : "") + "연결 대기 " + n + "건. 눌러서 " +
      (filtered ? "전체 목록으로 돌아갑니다." : "대기 건만 봅니다."));

    // 응급이 새로 대기열에 들어오면 스크린리더로도 알린다(같은 건을 반복해 읽지는 않는다).
    var key = emg.map(function (c) { return c.id; }).sort().join(",");
    if (key && key !== state.lastEmergencyAlert) {
      state.lastEmergencyAlert = key;
      announce("응급 민원 " + emg.length + "건이 담당자 연결을 기다립니다.");
    } else if (!key) {
      state.lastEmergencyAlert = null;
    }
  }

  function renderList() {
    renderWaitBand();
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
      var ho = handoffStatusOf(c.id);
      var cb = callbackStatusOf(c.id);
      var urg = urgencyOf(c);
      var dept = deptOf(c);
      var fresh = isFresh(c.id);
      // 하이라이트는 도착 직후 한 번만 재생한다. 폴링·필터로 다시 튀지 않게.
      var animate = fresh && !state.animated[c.id];
      if (animate) state.animated[c.id] = 1;
      var selected = c.id === state.selectedId;
      return '<li class="card' + (selected ? " is-selected" : "") +
          (urg ? " urg-" + URG[urg.level].cls.replace("urg--", "") : "") +
          (ho === "open" ? " is-live" : "") +
          (ho === "none" && isAwaitingHandoff(c) ? " is-waiting" : "") +
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
          (urg ? '<span class="badge urg-badge ' + URG[urg.level].cls + '" title="' +
              esc(urg.reason) + '">' + (urg.level === "응급" ? "❗" : "") + esc(urg.level) +
              (urg.overridden ? " (조정)" : "") + "</span>" : "") +
          (urg && urg.safety_referral
            ? '<span class="badge urg-safety">' + esc(urg.safety_referral.number) + " 안내함</span>" : "") +
          '<span class="badge ' + WF[wf].cls + '">' + WF[wf].label + "</span>" +
          (ho !== "none"
            ? '<span class="badge ' + HANDOFF[ho].cls + '">' +
              (ho === "open" ? "● " : "") + HANDOFF[ho].label + "</span>"
            : isAwaitingHandoff(c)
            ? '<span class="badge ho--waiting">☎ 연결 대기</span>' : "") +
          (cb === "pending" || cb === "answered"
            ? '<span class="badge ' + CALLBACK[cb].cls + '">☎ ' + CALLBACK[cb].label + "</span>" : "") +
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
    if (isNarrow() && !(opts && opts.silent)) setView("detail");
    if (el.backId) el.backId.textContent = "접수번호 " + id;
    if (!(opts && opts.silent)) {
      var node = el.list.querySelector('.card[data-id="' + cssEsc(id) + '"]');
      if (node) node.scrollIntoView({ block: "nearest" });
      el.detail.parentElement.scrollTop = 0;
    }
    refreshHandoff(id, { render: true });
    refreshCallback(id, { render: true });

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

    // 긴급도 — 무엇을 먼저 볼지. 안전 안내가 있으면 그것이 화면 최상단이다.
    html += renderUrgency(raw);

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

    // 통화 끝에 어르신이 덧붙인 말 — 슬롯에 안 담긴 정보가 여기 있다
    html += renderNotes(c);

    // 담당자 핸드오프 — AI 가 접수하고 사람이 이어받는 지점
    html += renderHandoff(raw);

    // 진행 안내 콜백 — 이번엔 시스템이 먼저 전화를 건다
    html += renderCallback(raw);

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

    // 전사 — 어르신이 실제로 한 말을 그대로 보여 준다.
    // 표준어 변환본을 나란히 놓지 않는다: 담당자는 사투리를 그냥 알아듣는다.
    // (dialect/standard 는 서버에 그대로 저장된다. 화면에서 대비로 보여주지 않을 뿐이다.)
    var turns = c.transcript || [];
    html += '<div class="section"><h3>통화 전문</h3>';
    if (turns.length) {
      html += '<div class="scroll-x"><div class="transcript">' +
        turns.map(function (t) {
          var caller = t.role === "caller";
          return '<div class="tr-row ' + (caller ? "is-caller" : "is-agent") + '">' +
            '<div class="tr-who">' + (caller ? "신고자" : "AI 상담") + "</div>" +
            '<div class="tr-cell">' + esc(t.dialect || t.standard || "") + "</div>" +
          "</div>";
        }).join("") + "</div></div>";
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
          '<div class="hist-ev">근거: ' + esc(truncate(String(ai.evidence || "근거 없음"), 90)) + "</div>" +
          (raw.urgency && raw.urgency.level
            ? '<div class="hist-ev">긴급도 판정: <b>' + esc(raw.urgency.level) + "</b> — " +
              esc(truncate(String(raw.urgency.reason || "근거 없음"), 70)) + "</div>"
            : "") +
        "</div></li>"
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
            : ev.type === "urgency"
            ? "<b>긴급도 " + esc(ev.from || "") + " → " + esc(ev.to || "") + "</b>" +
              (ev.from_reason ? '<div class="hist-ev">AI 판정 근거: ' + esc(truncate(String(ev.from_reason), 80)) + "</div>" : "") +
              (ev.to_reason ? '<div class="hist-ev">담당자 사유: ' + esc(ev.to_reason) + "</div>" : "")
            : "처리 상태 " + esc(ev.from || "") + " → <b>" + esc(ev.to || "") + "</b>") +
        "</div></li>");
    });

    var flips = events.filter(function (e) { return e.type === "assign"; }).length;
    var urgFlips = events.filter(function (e) { return e.type === "urgency"; }).length;
    return '<div class="section"><h3>처리 이력' +
      (flips ? ' <span class="hist-flag">담당자 재배정 ' + flips + "회</span>" : "") +
      (urgFlips ? ' <span class="hist-flag">긴급도 조정 ' + urgFlips + "회</span>" : "") + "</h3>" +
      '<div class="scroll-x"><ol class="hist">' + rows.reverse().join("") + "</ol></div>" +
      '<p class="note">담당자가 AI 배정을 뒤집은 기록은 라우팅 품질 측정에 쓰입니다(목표: 재배정 20% 미만).</p></div>';
  }

  /**
   * 긴급도 블록 (계약 5-A).
   *
   * 배정 근거와 같은 원칙 — **왜 이 판정인지(reason)를 반드시 보여 준다.**
   * 담당자가 납득하지 못하는 표시는 무시되고, 무시되는 순간 이 기능은 없는 것과 같다.
   * 색만으로 구분하지 않는다: 라벨 글자 + 테두리 + 목록 상단 고정을 겹쳐 쓴다.
   */
  function renderUrgency(raw) {
    var u = urgencyOf(raw);
    var html = "";

    // 안전 안내가 있으면 무엇보다 먼저 보여 준다.
    // 담당자가 "이 민원인은 이미 119 안내를 받았다" 를 모르면 중복 안내하거나, 더 나쁘게는
    // 아무도 신고하지 않았다고 착각한다.
    if (u && u.safety_referral) {
      var ref = u.safety_referral;
      html += '<div class="safety"><span class="safety-mark">안전 안내</span>' +
        '<div class="safety-body"><b>통화 중 ' + esc(ref.number) + " 안내를 이미 드렸습니다" +
          (ref.label ? " (" + esc(ref.label) + ")" : "") + ".</b>" +
          '<span>민원 접수가 신고를 대체하지 않습니다. 필요하면 담당자가 직접 확인해 주세요.</span>' +
        "</div></div>";
    }

    if (!u) return html;   // 서버가 아직 판정을 안 주는 카드 — 자리만 비워 둔다

    var meta = URG[u.level];
    var open = state.urgencyForm === raw.id;

    html += '<div class="urg ' + meta.cls + (u.level === "응급" ? " is-emergency" : "") + '">' +
      '<div class="urg-top">' +
        '<span class="urg-label">' + (u.level === "응급" ? "❗ " : "") + esc(u.level) + "</span>" +
        '<span class="urg-hint">' + esc(meta.hint) + "</span>" +
        '<span class="urg-by">' +
          (u.overridden ? "담당자 조정" : u.decided_by === "llm" ? "AI 문맥 판정" : "규칙 판정") + "</span>" +
        '<button class="btn btn-ghost urg-edit" data-act="urg-edit">긴급도 조정</button>' +
      "</div>" +
      '<div class="urg-body">' +
        '<div class="urg-why">▍이 판정의 근거</div>' +
        '<p class="urg-reason">' + esc(u.reason || "근거가 기록되지 않았습니다 — 담당자 확인이 필요합니다.") + "</p>" +
        (u.signals && u.signals.length
          ? '<ul class="urg-signals">' + u.signals.map(function (x) {
              return '<li><span class="urg-sig-label">감지 신호</span>' + esc(x) + "</li>";
            }).join("") + "</ul>"
          : "") +
        (u.overridden && u.ai
          ? '<p class="urg-orig">AI 최초 판정: <b>' + esc(u.ai.level) + "</b> — " +
            esc(truncate(String(u.ai.reason || "근거 없음"), 70)) + " (처리 이력에 남아 있습니다)</p>"
          : "") +
      "</div>";

    if (open) {
      html += '<div class="urg-form">' +
        '<span class="urg-form-label">긴급도를 다시 정합니다 — AI 판정은 제안이고 최종 판단은 담당자가 합니다.</span>' +
        '<div class="urg-choices">' + URGENCY.map(function (x) {
          return '<button type="button" class="urg-choice ' + x.cls +
            (x.key === u.level ? " is-on" : "") + '" data-act="urg-set" data-level="' +
            esc(x.key) + '">' + esc(x.key) + "</button>";
        }).join("") + "</div>" +
        '<label class="sr-only" for="urg-reason">조정 사유</label>' +
        '<input id="urg-reason" type="text" maxlength="120" placeholder="조정 사유 (선택) — 이력에 함께 남습니다">' +
        '<button class="btn btn-ghost" data-act="urg-cancel">닫기</button>' +
      "</div>";
    }

    return html + "</div>";
  }

  /**
   * 추가 말씀(notes).
   *
   * 통화 종료 직전 "더 하실 말씀 있으실까예?" 에서 나온 발화가 쌓인다.
   * 슬롯(무엇/어디/언제/연락처)에 안 맞는 정보 — "아침에만 그래예", "옆집도 같이 그래예" —
   * 가 담기는데, 현장에 나가는 담당자에게는 이게 요약보다 쓸모 있을 때가 많다.
   * 그래서 통화 전문 안에 묻어 두지 않고 배정 근거 바로 다음에 따로 세운다.
   *
   * 서버(P6)가 아직 notes 를 안 보내면 이 섹션은 나오지 않는다(빈 배열은 "없음"으로 표시).
   */
  function renderNotes(c) {
    var notes = c.notes;
    if (!Array.isArray(notes)) return "";   // 아직 필드를 안 주는 서버 — 자리만 비워 둔다

    var head = '<div class="section"><h3>어르신이 덧붙인 말 ' +
      '<span class="notes-count">' + notes.length + "건</span></h3>";

    if (!notes.length) {
      return head + '<p class="alt-empty">통화 마지막에 추가로 말씀하신 내용은 없습니다.</p></div>';
    }

    return head + '<ul class="notes">' + notes.map(function (n) {
      var text = String((n && (n.text || n.standard)) || "").trim();
      if (!text) return "";
      var src = NOTE_SOURCE[(n && n.source) || "caller"] || "신고자";
      // 서버가 본문 앞에 붙여 주는 "[안내 전화 문의] " 같은 접두어는 출처 라벨과 겹친다.
      // 라벨이 이미 같은 말을 하고 있으니 본문에서는 걷어낸다.
      var dupe = new RegExp("^\\[\\s*" + src.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*\\]\\s*");
      text = text.replace(dupe, "");
      return '<li class="note-item">' +
        '<p class="note-text">' + esc(text) + "</p>" +
        '<div class="note-meta"><span class="note-src">' + esc(src) + "</span>" +
          (n && n.at ? '<span class="note-at">' + esc(fmtDateTime(n.at)) + "</span>" : "") +
        "</div></li>";
    }).join("") + "</ul>" +
    '<p class="note">슬롯(무엇·어디·언제·연락처)에 담기지 않은 내용입니다. 현장 확인 전에 함께 보세요.</p></div>';
  }

  /**
   * 담당자 핸드오프 패널 (계약 5-B).
   *
   * 담당자가 친 말은 어르신 화면·음성에 사투리로 나간다(서버의 to_dialect).
   * 다만 **담당자 화면에서는 그 변환을 강조하지 않는다.** 한국인 담당자는 사투리를 그냥 알아듣는다.
   * 어르신 말은 실제로 한 그대로, 담당자 말은 자기가 친 그대로 보여 주고 변환은 조용히 돌아간다.
   */
  function renderHandoff(raw) {
    var h = state.handoff[raw.id];
    var status = h ? h.status : handoffStatusOf(raw.id);
    var dept = deptOf(raw) || "";

    var head = '<div class="section"><h3>담당자 통화' +
      (handoffLive() ? "" : ' <span class="tag tag--mock">목 모드</span>') + "</h3>";

    // ── 아직 연결 전
    if (status === "none") {
      var known = String(state.officer.name || "").trim();
      var knownDept = String(state.officer.department || dept || "").trim();

      // 이름을 이미 아는 경우 — **한 번 클릭으로 연결한다.** 급할 때 폼을 채우게 하면 못 쓴다.
      if (known && state.handoffForm !== raw.id) {
        return head + '<div class="ho ho--idle">' +
          '<div class="ho-idle-text"><b>어르신이 담당자 연결을 기다리고 있을 수 있습니다.</b>' +
            '<span>연결하면 AI 응대가 멈추고 담당자가 직접 대화합니다.</span>' +
          "</div>" +
          '<div class="ho-connect">' +
            '<button class="btn btn-primary btn-lg" data-act="ho-quick">☎ 통화 잇기</button>' +
            '<span class="ho-asme">' + esc(known) + " · " + esc(knownDept || "부서 미지정") +
              ' <button type="button" class="ho-change" data-act="ho-open">변경</button></span>' +
          "</div></div></div>";
      }

      // 아직 이름을 모르는데 폼도 열지 않은 상태 — 버튼만 보여 준다.
      // (카드마다 입력칸이 펼쳐져 있으면 목록이 시끄러워진다.)
      if (!known && state.handoffForm !== raw.id) {
        return head + '<div class="ho ho--idle">' +
          '<div class="ho-idle-text"><b>어르신이 담당자 연결을 기다리고 있을 수 있습니다.</b>' +
            '<span>연결하면 AI 응대가 멈추고 담당자가 직접 대화합니다.</span>' +
          "</div>" +
          '<button class="btn btn-primary btn-lg" data-act="ho-open">☎ 통화 잇기</button>' +
          "</div></div>";
      }

      // 처음 한 번만 이름을 묻는다. 다음부터는 이 브라우저가 기억해 바로 연결된다.
      if (state.handoffForm === raw.id || !known) {
        return head + '<div class="ho ho--form">' +
          '<p class="ho-lead">이 민원의 신고자와 직접 통화합니다. 연결하면 AI 응대는 멈춥니다.</p>' +
          '<div class="ho-fields">' +
            '<label class="ho-field"><span>담당자 이름</span>' +
              '<input id="ho-name" type="text" maxlength="20" placeholder="예: 홍길동" value="' +
              esc(state.officer.name) + '" autocomplete="off"></label>' +
            '<label class="ho-field"><span>부서</span>' +
              '<input id="ho-dept" type="text" maxlength="60" value="' +
              esc(knownDept) + '"></label>' +
          "</div>" +
          '<p class="ho-privacy">이름은 <b>어르신 화면에 표시하기 위한 용도</b>입니다. ' +
            '이 브라우저에만 기억해 두고(다음부터는 바로 연결됩니다), ' +
            '서버는 마스킹된 형태로만 기록합니다. 민원카드·CSV 에는 남지 않습니다.</p>' +
          '<div class="ho-actions">' +
            '<button class="btn btn-primary" data-act="ho-confirm">통화 연결</button>' +
            (known ? '<button class="btn btn-ghost" data-act="ho-cancel">취소</button>' : "") +
          "</div></div></div>";
      }
    }

    // ── 연결됨 / 종료됨
    var msgs = (h && h.messages) || [];
    var officer = (h && h.officer) || { name: "", department: "" };
    var open = status === "open";
    var name = state.officer.name || officer.name || "담당자";

    var out = head + '<div class="ho ho--live' + (open ? "" : " is-closed") + '">';

    out += '<div class="ho-head">' +
      '<span class="ho-dot' + (open ? " is-on" : "") + '"></span>' +
      '<div class="ho-who"><b>' + esc(name) + "</b>" +
        '<span>' + esc(officer.department || dept || "부서 미지정") + "</span></div>" +
      '<span class="badge ' + HANDOFF[status].cls + '">' + HANDOFF[status].label + "</span>" +
      (open ? '<button class="btn btn-ghost ho-close" data-act="ho-close">통화 종료</button>' : "") +
      "</div>";

    if (open) {
      out += '<p class="ho-notice">' + esc((h && h.notice) || "지금부터 담당자가 직접 응대합니더.") +
        ' <span>— 어르신 화면에도 같은 안내가 표시되고, AI 는 발화를 멈춥니다.</span></p>';
    }

    // ── 대화
    // P6 쪽에서 메시지가 중복 저장되는 버그를 고치는 중이다.
    // 화면에 같은 말이 두 번 뜨면 담당자가 "내가 두 번 보냈나" 를 의심하게 되므로
    // 완전히 같은 (역할·본문·시각) 메시지는 하나로 접는다. 서버가 고쳐진 뒤에도 무해하다.
    msgs = dedupeMessages(msgs);
    out += '<ol class="ho-log" id="ho-log">';
    if (!msgs.length) {
      out += '<li class="ho-empty">아직 대화가 없습니다. 아래에 첫 인사를 입력하세요.</li>';
    } else {
      // 어르신 말은 실제로 한 그대로, 담당자 말은 자기가 친 그대로 보여 준다.
      // (변환본은 서버에 남아 있고, 어르신 화면에는 사투리 음성이 그대로 나간다.)
      out += msgs.map(function (m) {
        var mine = m.role === "officer";
        var shown = mine ? (m.standard || m.text || "") : (m.dialect || m.text || m.standard || "");
        return '<li class="ho-msg ' + (mine ? "is-officer" : "is-caller") + '">' +
          '<div class="ho-msg-top"><span class="ho-role">' + (mine ? "담당자" : "신고자") + "</span>" +
            '<span class="ho-at">' + esc(fmtClock(m.at)) + "</span></div>" +
          '<p class="ho-text">' + esc(shown) + "</p>" +
        "</li>";
      }).join("");
    }
    out += "</ol>";

    // ── 입력
    if (open) {
      out += '<div class="ho-input">' +
        '<label class="sr-only" for="ho-text">담당자 메시지</label>' +
        '<textarea id="ho-text" rows="2" maxlength="500" placeholder="메시지를 입력하세요."></textarea>' +
        '<button class="btn btn-primary" data-act="ho-send"' + (state.handoffBusy ? " disabled" : "") + ">전송</button>" +
        "</div>" +
        '<p class="ho-hint">Enter 전송 · Shift+Enter 줄바꿈</p>';
    } else {
      out += '<p class="ho-closed-note">상담이 종료되었습니다' +
        (h && h.closed_at ? " (" + esc(fmtDateTime(h.closed_at)) + ")" : "") +
        '. 위 대화 기록은 이 민원에 계속 남습니다.</p>';
    }

    return out + "</div></div>";
  }

  /**
   * 진행 안내 콜백 패널 (계약 5-C).
   *
   * 어르신이 진행 상황을 알려면 다시 전화해 ARS 를 또 뚫어야 한다.
   * 방향을 뒤집어 시스템이 먼저 건다. 담당자는 진행 상황을 쓰고,
   * AI 는 **그 문장을 읽어 줄 뿐** 아무것도 지어내지 않는다.
   *
   * 그래서 이 화면이 반드시 보여 주는 것:
   *  1) 담당자가 전달한 내용 (실제로 나간 문장은 접힌 한 줄로 확인 가능 — 계약 5-C)
   *  2) 어르신이 추가로 물은 것 (AI 가 답하지 않았으니 담당자가 답해야 한다)
   */
  function renderCallback(raw) {
    var c = state.callback[raw.id];
    var status = c ? c.status : callbackStatusOf(raw.id);
    var dept = deptOf(raw) || "";
    var live = callbackLive();

    var head = '<div class="section"><h3>진행 안내 전화' +
      (live ? "" : ' <span class="tag tag--mock">목 모드</span>') +
      ' <span class="badge ' + CALLBACK[status].cls + '">' + CALLBACK[status].label + "</span></h3>";

    var pstn = '<p class="cb-pstn">실제 전화망(PSTN) 연동은 다음 단계입니다. ' +
      '지금은 어르신 화면에 수신 화면을 띄우는 <b>시뮬레이션</b>입니다.</p>';

    // ── 아직 안내 전 (또는 종료 후 새로 걸기)
    if (status === "none" || state.callbackForm === raw.id) {
      var prefill = state.callbackDraft || "";
      return head + '<div class="cb cb--form">' +
        '<p class="cb-lead"><b>진행 상황을 쓰면 어르신께 전화를 걸어 읽어 드립니다.</b>' +
          '<span>어르신은 다시 전화해서 ARS 를 뚫을 필요가 없습니다.</span></p>' +
        '<label class="sr-only" for="cb-text">진행 상황</label>' +
        '<textarea id="cb-text" rows="3" maxlength="600" placeholder="예: 현장 확인 완료했습니다. 이번 주 내로 배수관 준설 예정입니다.">' +
          esc(prefill) + "</textarea>" +
        '<p class="cb-rule">⚠ <b>AI 는 여기 쓰신 내용만 전달합니다.</b> ' +
          '처리 결과·일정·가능 여부를 AI 가 지어내지 않습니다. 여기 없는 것을 어르신이 물으면 ' +
          '<i>“담당자에게 여쭤보고 다시 연락드릴게예”</i> 로 넘기고, 그 질문을 이 화면에 가져옵니다.</p>' +
        '<div class="cb-actions">' +
          '<button class="btn btn-primary btn-lg" data-act="cb-send">☎ 안내 전화 걸기</button>' +
          (status !== "none" ? '<button class="btn btn-ghost" data-act="cb-cancel">취소</button>' : "") +
          '<span class="cb-who">' + esc(state.officer.name || "담당자") + " · " +
            esc(state.officer.department || dept || "부서 미지정") + "</span>" +
        "</div>" + pstn + "</div></div>";
    }

    var out = head + '<div class="cb cb--live' + (status === "closed" ? " is-closed" : "") + '">';

    // ── 전달한 내용.
    // 담당자가 쓴 글을 본문으로 보여 준다. 사투리 변환본을 나란히 놓아 대비시키지 않는다.
    // 다만 계약 5-C 는 "내가 쓴 대로 전달됐는가" 를 확인할 수 있어야 한다고 못박고 있으므로,
    // 실제로 나간 문장은 접힌 한 줄로 조용히 남겨 둔다.
    var b = (c && c.briefing) || { standard: "", dialect: "" };
    out += '<div class="cb-brief">' +
      '<span class="cb-brief-label">담당자가 전달한 내용</span>' +
      '<p class="cb-brief-text">' + esc(b.standard || "(내용 없음)") + "</p>" +
      (b.dialect && b.dialect !== b.standard
        ? '<details class="cb-sent"><summary>어르신께 나간 문장 확인</summary>' +
          '<p>' + esc(b.dialect) + "</p></details>"
        : "") +
      "</div>";
    out += '<p class="cb-verify">AI 는 담당자가 쓴 내용만 전달합니다. 새로 만든 내용은 없습니다.</p>';

    // ── 상태별 안내
    if (status === "pending") {
      out += '<p class="cb-state cb-state--pending">' +
        '<span class="cb-ring"></span> 어르신 화면에서 <b>수신 대기 중</b>입니다. 받으시면 브리핑이 재생됩니다.</p>';
    } else if (status === "answered") {
      out += '<p class="cb-state cb-state--answered">어르신이 전화를 받았습니다' +
        (c && c.answered_at ? " (" + esc(fmtClock(c.answered_at)) + ")" : "") + ".</p>";
    }

    // ── 어르신 추가 질문 — 담당자가 답해야 할 것
    var qs = dedupeMessages(callerQuestions(raw.id));
    if (qs.length) {
      out += '<div class="cb-questions"><div class="cb-q-head">' +
        '<b>어르신이 추가로 물으신 것</b> <span class="badge cb--pending">' + qs.length + "건</span>" +
        '<span class="cb-q-note">AI 가 답하지 않았습니다. 담당자 확인이 필요합니다.</span></div>' +
        "<ul>" + qs.map(function (m) {
          // 어르신이 실제로 물은 그대로 보여 준다(표준어 변환본을 나란히 놓지 않는다).
          return "<li><p class=\"cb-q-text\">" + esc(m.dialect || m.text || m.standard || "") + "</p>" +
            '<div class="cb-q-meta"><span>' + esc(fmtClock(m.at)) + "</span></div></li>";
        }).join("") + "</ul>" +
        (status !== "closed"
          ? '<button class="btn btn-primary" data-act="cb-reply">이 질문에 답해 다시 안내하기</button>'
          : '<button class="btn btn-primary" data-act="cb-reply">답변 담아 새 안내 전화</button>') +
        "</div>";
    }

    // ── 전체 통화 기록
    var msgs = (c && c.messages) || [];
    if (msgs.length) {
      out += '<details class="cb-log"><summary>안내 통화 기록 ' + msgs.length + "건</summary><ol>" +
        msgs.map(function (m) {
          var isCaller = m.role === "caller";
          return '<li class="cb-msg ' + (isCaller ? "is-caller" : "is-agent") + '">' +
            '<span class="cb-msg-role">' + (isCaller ? "신고자" : "AI 안내") + "</span>" +
            '<p>' + esc(m.standard || m.text || "") + "</p>" +
            (m.dialect && m.dialect !== (m.standard || m.text)
              ? '<p class="cb-msg-dia">' + esc(m.dialect) + "</p>" : "") +
          "</li>";
        }).join("") + "</ol></details>";
    }

    if (status !== "closed") {
      out += '<div class="cb-actions"><button class="btn btn-ghost" data-act="cb-close">안내 종료</button></div>';
    } else {
      out += '<p class="cb-closed-note">안내가 종료되었습니다' +
        (c && c.closed_at ? " (" + esc(fmtDateTime(c.closed_at)) + ")" : "") +
        '. 기록은 이 민원에 남습니다. ' +
        '<button class="btn btn-ghost" data-act="cb-again">새 안내 전화 걸기</button></p>';
    }

    return out + pstn + "</div></div>";
  }

  /** 완전히 동일한 메시지(역할·본문·시각)를 하나로 접는다. */
  function dedupeMessages(list) {
    var seen = {}, out = [];
    (list || []).forEach(function (m) {
      var k = [m.role, m.standard || m.text || "", m.dialect || "", m.at || ""].join("\u0000");
      if (seen[k]) return;
      seen[k] = 1;
      out.push(m);
    });
    return out;
  }

  function fmtClock(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function bindDetail(raw, alts) {
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

    bindUrgency(raw);
    bindHandoff(raw);
    bindCallback(raw);
  }

  // ---------- 핸드오프 동작 ----------
  function bindHandoff(raw) {
    var on = function (act, fn) {
      var b = el.detail.querySelector('[data-act="' + act + '"]');
      if (b) b.addEventListener("click", fn);
    };

    on("ho-quick", function () {
      // 기억한 이름·부서로 즉시 연결한다. 클릭 한 번.
      startHandoff(raw, state.officer.name, state.officer.department || deptOf(raw) || "");
    });
    on("ho-open", function () {
      state.handoffForm = raw.id;
      renderDetail();
      var f = document.getElementById("ho-name");
      if (f) { f.focus(); f.select && f.select(); }
    });
    on("ho-cancel", function () { state.handoffForm = null; renderDetail(); });

    on("ho-confirm", function () {
      var nameEl = document.getElementById("ho-name");
      var deptEl = document.getElementById("ho-dept");
      var name = (nameEl && nameEl.value || "").trim();
      var dept = (deptEl && deptEl.value || "").trim();
      if (!name) { toast("담당자 이름을 입력하세요."); if (nameEl) nameEl.focus(); return; }
      startHandoff(raw, name, dept);
    });

    on("ho-close", function () { closeHandoff(raw); });
    on("ho-send", function () { sendHandoff(raw); });

    var ta = document.getElementById("ho-text");
    if (ta) {
      ta.value = state.handoffDraft || "";
      ta.addEventListener("input", function () { state.handoffDraft = ta.value; });
      ta.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendHandoff(raw); }
      });
      if (state.handoffFocus) {
        // 연결되자마자 바로 타이핑할 수 있어야 한다. 패널을 보이는 데까지 올리고 커서를 둔다.
        var panel = ta.closest(".ho");
        if (panel && panel.scrollIntoView) panel.scrollIntoView({ block: "nearest" });
        ta.focus();
        state.handoffFocus = false;
      }
    }
    var log = document.getElementById("ho-log");
    if (log) log.scrollTop = log.scrollHeight;
  }

  function startHandoff(raw, name, dept) {
    // 이름은 어르신 화면 표시용으로 서버에 보내고(서버가 마스킹해 저장한다),
    // 이 탭의 메모리에만 남긴다. localStorage 에는 부서만 저장한다.
    state.officer = { name: name, department: dept };
    try {
      localStorage.setItem(LS_OFFICER_DEPT, dept);
      localStorage.setItem(LS_OFFICER_NAME, name);
    } catch (e) {}

    hoPost(raw.id, "start", { officer_name: name, department: dept }).then(function () {
      state.handoffForm = null;
      state.handoffFocus = true;
      state.lastChange = Date.now();
      if (workflowOf(raw) !== "progress" && workflowOf(raw) !== "done") {
        setWorkflow(raw.id, "progress", { silent: true });   // 통화를 시작하면 처리중이다
      }
      return refreshHandoff(raw.id, { render: true });
    }).then(function () {
      render();
      toast("통화를 연결했습니다. 지금부터 담당자가 직접 응대합니다.");
      announce("접수번호 " + raw.id + " 담당자 통화가 연결되었습니다.");
    }).catch(function (err) {
      toast("연결 실패: " + (err && err.message ? err.message : "잠시 후 다시 시도하세요."));
    });
  }

  function sendHandoff(raw) {
    var ta = document.getElementById("ho-text");
    var text = (ta && ta.value || "").trim();
    if (!text || state.handoffBusy) return;
    state.handoffBusy = true;
    if (ta) { ta.value = ""; }
    state.handoffDraft = "";

    hoPost(raw.id, "message", { role: "officer", text: text }).then(function (res) {
      state.handoffBusy = false;
      state.handoffFocus = true;
      state.lastChange = Date.now();
      var m = res && res.message;
      return refreshHandoff(raw.id, { render: true });
    }).catch(function (err) {
      state.handoffBusy = false;
      state.handoffDraft = text;
      if (ta) ta.value = text;
      toast("전송 실패: " + (err && err.message ? err.message : "다시 시도하세요."));
      renderDetail();
    });
  }

  function closeHandoff(raw) {
    hoPost(raw.id, "close", {}).then(function () {
      state.lastChange = Date.now();
      return refreshHandoff(raw.id, { render: true });
    }).then(function () {
      render();
      toast("통화를 종료했습니다. 대화 기록은 카드에 남습니다.");
      announce("접수번호 " + raw.id + " 통화를 종료했습니다.");
    }).catch(function (err) {
      toast("종료 실패: " + (err && err.message ? err.message : "다시 시도하세요."));
    });
  }

  // ---------- 긴급도 조정 ----------
  function bindUrgency(raw) {
    var edit = el.detail.querySelector('[data-act="urg-edit"]');
    if (edit) edit.addEventListener("click", function () {
      state.urgencyForm = state.urgencyForm === raw.id ? null : raw.id;
      renderDetail();
    });
    var cancel = el.detail.querySelector('[data-act="urg-cancel"]');
    if (cancel) cancel.addEventListener("click", function () {
      state.urgencyForm = null; renderDetail();
    });
    el.detail.querySelectorAll('[data-act="urg-set"]').forEach(function (b) {
      b.addEventListener("click", function () {
        var input = document.getElementById("urg-reason");
        setUrgency(raw.id, b.dataset.level, input ? input.value : "");
        state.urgencyForm = null;
        delete raw._hay;
        render();
      });
    });
  }

  // ---------- 진행 안내 콜백 동작 ----------
  function bindCallback(raw) {
    var on = function (act, fn) {
      var b = el.detail.querySelector('[data-act="' + act + '"]');
      if (b) b.addEventListener("click", fn);
    };

    var ta = document.getElementById("cb-text");
    if (ta) {
      ta.addEventListener("input", function () { state.callbackDraft = ta.value; });
      if (state.callbackFocus) { ta.focus(); state.callbackFocus = false; }
    }

    on("cb-send", function () { scheduleCallback(raw); });
    on("cb-close", function () { closeCallback(raw); });
    on("cb-cancel", function () {
      state.callbackForm = null; state.callbackDraft = "";
      renderDetail();
    });
    on("cb-again", function () {
      state.callbackForm = raw.id; state.callbackDraft = ""; state.callbackFocus = true;
      renderDetail();
    });
    on("cb-reply", function () {
      // 어르신 질문을 인용해 새 브리핑을 시작한다. 답은 담당자가 쓴다 — AI 가 만들지 않는다.
      var qs = callerQuestions(raw.id);
      var quoted = qs.map(function (m) {
        return "· 물으신 것: " + (m.standard || m.text || "");
      }).join("\n");
      state.callbackForm = raw.id;
      state.callbackDraft = quoted + "\n\n답변: ";
      state.callbackFocus = true;
      renderDetail();
    });
  }

  function scheduleCallback(raw) {
    var ta = document.getElementById("cb-text");
    var text = (ta && ta.value || "").trim();
    if (!text) { toast("전달할 진행 상황을 입력하세요."); if (ta) ta.focus(); return; }
    if (state.callbackBusy) return;
    state.callbackBusy = true;

    cbPost(raw.id, "schedule", {
      briefing: text,
      officer_name: state.officer.name || "",
      department: state.officer.department || deptOf(raw) || ""
    }).then(function () {
      state.callbackBusy = false;
      state.callbackForm = null;
      state.callbackDraft = "";
      state.lastChange = Date.now();
      return refreshCallback(raw.id, { render: true });
    }).then(function () {
      render();
      toast("어르신께 안내 전화를 걸었습니다. 수신 대기 중입니다.");
      announce("접수번호 " + raw.id + " 진행 안내 전화를 걸었습니다.");
    }).catch(function (err) {
      state.callbackBusy = false;
      toast("안내 전화 실패: " + (err && err.message ? err.message : "다시 시도하세요."));
    });
  }

  function closeCallback(raw) {
    cbPost(raw.id, "close", {}).then(function () {
      state.lastChange = Date.now();
      return refreshCallback(raw.id, { render: true });
    }).then(function () {
      render();
      toast("안내를 종료했습니다. 기록은 카드에 남습니다.");
    }).catch(function (err) {
      toast("종료 실패: " + (err && err.message ? err.message : "다시 시도하세요."));
    });
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
    visible: visible,
    // 핸드오프 (계약 5-B)
    hoGet: hoGet,
    hoPost: hoPost,
    handoffStatusOf: handoffStatusOf,
    isAwaitingHandoff: isAwaitingHandoff,
    isNarrow: isNarrow,
    setView: setView,
    dedupeMessages: dedupeMessages,
    awaitingList: awaitingList,
    refreshHandoff: refreshHandoff,
    renderHandoff: renderHandoff,
    renderNotes: renderNotes,
    render: render,
    urgencyOf: urgencyOf,
    setUrgency: setUrgency,
    renderUrgency: renderUrgency,
    sortRows: sortRows,
    cbGet: cbGet,
    cbPost: cbPost,
    callbackStatusOf: callbackStatusOf,
    callerQuestions: callerQuestions,
    refreshCallback: refreshCallback,
    renderCallback: renderCallback,
    callbackLive: callbackLive,
    handoffLive: handoffLive
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
