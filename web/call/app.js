/* Voisso 통화 데모 UI — 앱 로직
 * 순수 JS. 빌드 스텝 없음. index.html 을 그냥 열면 동작한다. */
(function () {
  'use strict';

  const API = window.VoissoAPI;
  const CFG = window.VOISSO_CONFIG || {};
  const $ = (id) => document.getElementById(id);

  const el = {
    phone: $('phone'),
    btnTheme: $('btnTheme'), btnSize: $('btnTextSize'), btnMode: $('btnMode'),
    demoBar: $('demoBar'), elderStatus: $('elderStatus'), micLabel: $('micLabel'),
    safetyBar: $('safetyBar'), safetyHead: $('safetyHead'), safetyCalls: $('safetyCalls'),
    screens: { idle: $('screenIdle'), call: $('screenCall'), result: $('screenResult'),
               incoming: $('screenIncoming') },
    btnCall: $('btnCall'), modeChip: $('modeChip'),
    callee: document.querySelector('.callee'), callStatus: $('callStatus'), callTimer: $('callTimer'),
    chkStdAll: $('chkStandardAll'), pathChip: $('pathChip'),
    transcript: $('transcript'),
    slots: $('slots'), slotsCount: $('slotsCount'),
    capAgent: $('capAgent'), capCaller: $('capCaller'),
    capAgentText: $('capAgentText'), capCallerText: $('capCallerText'),
    suggestions: $('suggestions'), textIn: $('textIn'), btnSend: $('btnSend'),
    btnMic: $('btnMic'), micLevel: document.querySelector('.mic-level'),
    hint: $('composerHint'), btnEnd: $('btnEnd'),
    delivery: $('delivery'), card: $('card'), btnAgain: $('btnAgain'),
    handoffWait: $('handoffWait'), btnAnswer: $('btnAnswer'),
    hwElapsed: $('hwElapsed'), hwNo: $('hwNo'),
    hwIn: $('hwIn'), btnHwSend: $('btnHwSend'), hwQueue: $('hwQueue'),
    btnSimOfficer: $('btnSimOfficer'), btnSimOfficerMsg: $('btnSimOfficerMsg'),
    demoBarText: $('demoBarText'), btnSimMsg2: $('btnSimMsg2'),
    incomingTitle: $('incomingTitle'), incomingSub: $('incomingSub'), incomingNote: $('incomingNote'),
    audio: $('replyAudio'), toast: $('toast'),
  };

  const state = {
    sessionId: null, startedAt: 0, timer: null,
    slots: {}, turns: [], busy: false, done: false, ended: false,
    showStdAll: false, recording: false, recognizing: false, inputPath: 'text', lastMs: 0,
    serverStt: null,          // /api/health 가 알려주는 서버 STT 가용 여부 (null = 아직 모름)
    handoff: { id: null, status: 'none', open: false, rendered: 0, timer: 0, officer: null },
    callback: { status: 'none', open: false, rendered: 0, officer: null },
    callerBubbles: [],        // 통화 중 만든 내 말풍선들 (종료 후 서버 전사로 채운다)
    sttForced: null,          // 사용자가 화면에서 직접 고른 경로
  };

  /* ── 유틸 ──────────────────────────────────────────────── */
  // 경북도청 원문에는 한글 폰트에 글리프가 없는 사용자 정의 영역(PUA) 문자가 섞여 있다
  // (예: 맑은물정책과 사무분장의 U+F09E — 한컴/워드 기호 폰트에서 넘어온 글머리표).
  // 그대로 두면 담당자 화면에 네모가 뜬다. 근본 수정은 데이터 쪽이고, 여기서는 방어만 한다.
  const PUA = /[\uE000-\uF8FF\uFFFD]/g;
  const esc = (s) => String(s == null ? '' : s)
    .replace(PUA, '').replace(/[ \t]{2,}/g, ' ')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // 서버가 세션을 잃었을 때(재기동·만료) 날 HTTP 문자열을 보여주지 않는다.
  function isSessionLost(e) {
    return !!e && (e.status === 404 || /세션/.test(e.detail || '') || /HTTP 404/.test(e.message || ''));
  }

  /* 연결 실패 안내 — 진단 정보를 숨기지 않는다.
     어르신에게 보여줄 화면과 시연자가 볼 화면은 다르다. 오류 상황에서는 주소를 그대로 보여준다.
     (옛 config.js 가 캐시돼 API 주소가 페이지 주소와 어긋나는 사고가 실제로 있었다) */
  function connectionHelpHTML() {
    const api = API.baseLabel();
    const page = location.origin || '(파일에서 직접 열림)';
    let html = '<b>' + esc(api) + '</b> 에 연결하지 못했습니더.<br>' +
               '지금 페이지는 <b>' + esc(page) + '</b> 에서 열렸습니더.';
    if (api !== page) {
      html += '<br>주소가 다르면 브라우저 캐시를 비워 보이소 (⌘⇧R / Ctrl+Shift+R).';
    }
    return html;
  }

  // fetch 자체가 실패한 경우(서버 다운·네트워크 끊김). HTTP 상태가 아예 없다.
  function isNetworkDown(e) {
    return !!e && e.status === undefined &&
      /Failed to fetch|NetworkError|Load failed|network|ERR_/i.test(String(e.message || e));
  }

  // 큰 버튼의 동작은 이 변수 하나로 갈아끼운다(리스너를 겹쳐 달면 두 개가 같이 돈다).
  let btnEndAction = null;

  function resetEndButton() {
    btnEndAction = null;
    el.btnEnd.textContent = isDemo() ? '통화 끝내고 민원 접수' : '통화 끝내기';
    el.btnEnd.classList.remove('ready');
  }

  // 막다른 화면을 만들지 않는다.
  function offerRestart(label) {
    el.btnEnd.textContent = label || '다시 전화 걸기';
    el.btnEnd.classList.remove('ready');
    btnEndAction = () => { resetEndButton(); startCall(); };
  }

  function handleSessionLost(where) {
    stopReconnect();
    clearInterval(state.timer);
    state.sessionId = null;
    state.ended = true;
    el.callee.classList.remove('is-live');
    setPhase('통화 끊김');
    say('통화가 끊어졌습니더');
    el.hint.classList.add('alert');
    el.hint.textContent = '통화가 끊어졌습니더. 아래 버튼으로 다시 걸어 주이소.';
    offerRestart('다시 전화 걸기');
    toast('통화가 끊어졌습니더. 다시 걸어 주이소.' + (where ? ' (' + where + ')' : ''), 5000);
  }

  /* ── 통화 중 서버가 죽었을 때 ─────────────────────────────
     조용히 멈추면 시연자가 당황한다. 상태를 말해 주고, 스스로 다시 붙어 본다. */
  let reconnectTimer = 0, reconnecting = false;

  function stopReconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = 0; }
    reconnecting = false;
  }

  function handleNetworkDown() {
    if (reconnecting) return;
    el.callee.classList.remove('is-live');
    setPhase('연결 끊김');
    say('연결이 끊어졌습니더');
    el.hint.classList.add('alert');
    el.hint.textContent = API.baseLabel() + ' 에 연결하지 못했니더. 다시 연결해 보는 중입니더…';
    toast('서버와 연결이 끊어졌습니더. 다시 연결해 보는 중입니더.', 4000);
    startReconnect();
  }

  function startReconnect() {
    if (reconnecting) return;
    reconnecting = true;
    let tries = 0;
    const MAX = 10;                      // 3초 간격 · 약 30초 동안 붙어 본다
    const tick = async () => {
      if (!reconnecting) return;
      tries++;
      let ok = false;
      try { ok = (await API.probe()).ok; } catch (e) { ok = false; }
      if (!reconnecting) return;
      if (ok) {
        stopReconnect();
        el.callee.classList.add('is-live');
        el.callStatus.textContent = '통화 중';
        el.hint.classList.remove('alert');
        el.hint.textContent = '연결이 돌아왔니더. 이어서 말씀해 주이소.';
        toast('연결이 돌아왔습니더.', 3000);
        return;
      }
      if (tries >= MAX) {
        stopReconnect();
        say('연결이 안 됩니더');
        el.hint.textContent = API.baseLabel() + ' 이 응답하지 않습니더. 아래 버튼으로 다시 걸어 주이소.';
        offerRestart('다시 전화 걸기');
        return;
      }
      el.hint.textContent = API.baseLabel() + ' 에 다시 연결해 보는 중입니더… (' + tries + '/' + MAX + ')';
      reconnectTimer = setTimeout(tick, 3000);
    };
    reconnectTimer = setTimeout(tick, 1200);
  }

  function toast(msg, ms) {
    el.toast.textContent = msg;
    el.toast.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.toast.classList.remove('show'), ms || 3600);
  }

  function mmss(sec) {
    const m = Math.floor(sec / 60), s = sec % 60;
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  }

  /* ── 테마 / 글자 크기 ──────────────────────────────────── */
  const THEMES = ['auto', 'light', 'dark'];
  function applyTheme(pref) {
    const dark = pref === 'dark' || (pref === 'auto' &&
      window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    try { localStorage.setItem('voisso.theme', pref); } catch (e) {}
    el.btnTheme.title = { auto: '화면: 시스템 설정', light: '화면: 밝게', dark: '화면: 어둡게' }[pref];
  }
  let themePref = 'auto';
  try { themePref = localStorage.getItem('voisso.theme') || 'auto'; } catch (e) {}
  applyTheme(themePref);
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => { if (themePref === 'auto') applyTheme('auto'); };
    mq.addEventListener ? mq.addEventListener('change', onChange) : mq.addListener(onChange);
  }
  el.btnTheme.addEventListener('click', () => {
    themePref = THEMES[(THEMES.indexOf(themePref) + 1) % THEMES.length];
    applyTheme(themePref);
    toast({ auto: '화면 밝기: 시스템 설정', light: '화면 밝기: 밝게', dark: '화면 밝기: 어둡게' }[themePref], 1600);
  });

  const SIZES = ['m', 'l', 'xl'];
  el.btnSize.addEventListener('click', () => {
    const cur = document.documentElement.dataset.size || 'm';
    const next = SIZES[(SIZES.indexOf(cur) + 1) % SIZES.length];
    document.documentElement.dataset.size = next;
    try { localStorage.setItem('voisso.size', next); } catch (e) {}
    toast({ m: '글자 크기: 보통', l: '글자 크기: 크게', xl: '글자 크기: 아주 크게' }[next], 1600);
  });

  /* ── 어르신 모드 / 시연 모드 ─────────────────────────────
     기본은 어르신 모드다. 화면에는 지금 할 일 하나만 남긴다.
     진단 정보는 시연 모드에서 전부 보인다(기능을 지우지 않는다). */
  const isDemo = () => document.documentElement.dataset.mode === 'demo';

  function setMode(mode) {
    document.documentElement.dataset.mode = mode;
    try { localStorage.setItem('voisso.mode', mode); } catch (e) {}
    el.btnMode.textContent = mode === 'demo' ? '어르신' : '시연';
    el.btnMode.title = mode === 'demo' ? '어르신 화면으로 돌아가기' : '시연 모드 — 내부 동작 보기';
    el.demoBar.hidden = mode !== 'demo';
    if (!btnEndAction) el.btnEnd.textContent = mode === 'demo' ? '통화 끝내고 민원 접수' : '통화 끝내기';
    renderDemoBar();
  }

  // 상태는 색이나 아이콘이 아니라 '글자'로 알린다.
  // 큰 글자는 '지금 무엇을 하면 되는지'(행동), 헤더는 '지금 어떤 상태인지'(단계).
  function say(text, kind) {
    el.elderStatus.textContent = text;
    el.elderStatus.classList.toggle('listening', kind === 'listening');
  }

  function setPhase(text) { el.callStatus.textContent = text; }

  function renderDemoBar() {
    if (!isDemo()) return;
    const filled = ['what', 'where', 'when', 'contact'].filter((k) => state.slots[k]).length;
    const bits = [
      (API.isMock() ? '목 API' : '서버') + ' <b>' + esc(API.baseLabel()) + '</b>',
      '입력 <b>' + esc((PATHS[state.inputPath] || {}).chip || state.inputPath) + '</b>',
      '슬롯 <b>' + filled + '/4</b>',
      state.lastMs ? '응답 <b>' + (state.lastMs / 1000).toFixed(1) + '초</b>' : '',
      state.handoff.open ? '<b>담당자 연결됨</b>' : '',
    ].filter(Boolean);
    el.demoBarText.innerHTML = bits.join(' · ');
  }

  /* ── 화면 전환 ─────────────────────────────────────────── */
  function setScreen(name) {
    Object.keys(el.screens).forEach((k) => el.screens[k].classList.toggle('is-active', k === name));
  }

  /* ── 사투리 / 표준어 말풍선 ────────────────────────────── */
  // 표준어 문장에서 사투리 원문에 없던 단어를 표시한다(LCS 기반 단어 정렬).
  function markChanged(dialect, standard) {
    const a = String(dialect || '').split(/\s+/).filter(Boolean);
    const b = String(standard || '').split(/\s+/).filter(Boolean);
    if (!b.length) return '';
    if (!a.length) return esc(standard);
    const n = a.length, m = b.length;
    const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    const keep = new Array(m).fill(false);
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { keep[j] = true; i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
      else j++;
    }
    return b.map((w, k) => (keep[k] ? esc(w) : '<mark>' + esc(w) + '</mark>')).join(' ');
  }

  // 발화 출처에 따라 위/아래 라벨이 달라진다.
  //  - 타이핑한 말   : [사투리 원문] / [표준어 변환]
  //  - 음성으로 한 말 : [STT 원본]   / [방언 정규화 후]  ← 방언 레이어가 왜 필요한지 보여주는 자리
  function bubbleLabels(role, source, opts) {
    if (!isDemo()) {
      // 어르신 모드: 누가 말하는지만. 진단용 라벨은 시연 모드에서 보인다.
      if (role === 'officer') {
        const o = (opts && opts.officer) || {};
        return { who: '담당자' + (o.department ? ' · ' + o.department : ''),
                 std: '표준어 원문', on: '표준어 원문 보기', off: '접기' };
      }
      return role === 'caller'
        ? { who: '나', std: '표준어 변환', on: '표준어 보기', off: '접기' }
        : { who: '민원실', std: '표준어 변환', on: '표준어 보기', off: '접기' };
    }
    if (role === 'officer') {
      // 사람 담당자. AI 와 헷갈리면 안 되므로 이름표를 분명히 단다.
      const o = (opts && opts.officer) || {};
      const who = '담당자' + (o.name ? ' ' + o.name : '') + (o.department ? ' · ' + o.department : '');
      return { who: who, std: '담당자가 쓴 표준어 원문',
               on: '표준어 원문 보기', off: '사투리로만 보기' };
    }
    if (role !== 'caller') {
      return { who: 'Voisso 상담원 (AI)', std: '표준어 변환', on: '표준어 보기', off: '사투리 원문만 보기' };
    }
    if (source === 'voice' || source === 'voice-server') {
      return { who: source === 'voice' ? '나 · 받아쓴 것 (브라우저 음성인식)' : '나 · 받아쓴 것 (Whisper 음성인식)',
               std: '방언 정규화 후', on: '전사 결과 보기', off: '접기' };
    }
    return { who: '나 (발신자)', std: '표준어 변환', on: '표준어 보기', off: '사투리 원문만 보기' };
  }

  function addBubble(role, dialect, standard, opts) {
    const o = opts || {};
    const L = bubbleLabels(role, o.source, o);
    const isVoice = o.source === 'voice' || o.source === 'voice-server';

    const b = document.createElement('div');
    b.className = 'bubble ' + (role === 'caller' ? 'caller' : role === 'officer' ? 'officer' : 'agent');
    if (o.pending) b.classList.add('pending');
    if (o.listening) { b.classList.add('listening'); b.setAttribute('aria-hidden', 'true'); }
    if (state.showStdAll) b.classList.add('show-std');

    b.innerHTML =
      '<div class="bubble-who"><span class="who-text">' + esc(L.who) + '</span>' +
        '<span class="pick-badge" hidden>방언 사전이 고른 후보</span></div>' +
      '<div class="bubble-dialect"></div>' +
      '<div class="bubble-std">' +
        '<div class="std-row alt-row" hidden>' +
          '<span class="lbl">받아쓴 것 (STT 원본)</span><span class="alt-body"></span>' +
        '</div>' +
        '<div class="std-row sent-row" hidden>' +
          '<span class="lbl">보낸 것</span><span class="sent-body"></span>' +
        '</div>' +
        '<div class="std-row">' +
          '<span class="lbl">' + esc(L.std) + '</span><span class="std-body"></span>' +
        '</div>' +
      '</div>' +
      '<button class="bubble-toggle" type="button">' + esc(L.on) + '</button>';

    const toggle = b.querySelector('.bubble-toggle');
    const syncToggle = () => { toggle.textContent = b.classList.contains('show-std') ? L.off : L.on; };
    const flip = () => { b.classList.toggle('show-std'); syncToggle(); };
    toggle.addEventListener('click', (e) => { e.stopPropagation(); flip(); });
    b.addEventListener('click', (e) => {          // 말풍선 어디를 눌러도 펼쳐진다
      if (e.target.closest('button') || window.getSelection().toString()) return;
      flip();
    });
    syncToggle();

    el.transcript.appendChild(b);
    scrollDown();

    const api = {
      node: b,
      labels: L,
      set(dia, std) {
        b.classList.remove('pending', 'listening');
        b.removeAttribute('aria-hidden');       // 확정된 뒤에 한 번만 읽어준다
        const d = dia || std || '';
        const t = std || dia || '';
        const same = d.trim() === t.trim();
        b.querySelector('.bubble-dialect').textContent = d;
        b.querySelector('.std-body').innerHTML = markChanged(d, t);
        b.querySelector('.bubble-std .lbl').textContent = same ? L.std + ' (원문과 동일)' : L.std;
        // 음성 발화이고 실제로 교정이 일어났으면 접지 않고 바로 펼친다.
        // (데모 스크립트의 핵심 컷: STT 원문과 정규화 결과가 동시에 보이는 순간)
        if (isVoice && !same) b.classList.add('show-std');
        syncToggle();
        showCaption(role, d);            // 어르신 모드 자막
        scrollDown();
      },
      live(text) {                         // 인식 중간 결과
        b.classList.add('listening');
        b.querySelector('.bubble-dialect').textContent = text || '';
        if (text) showCaption(role, text, { live: true });
        scrollDown();
      },
      // 방언 사전이 1순위가 아닌 후보를 골랐을 때만 '받아쓴 것' 줄을 띄운다.
      setTop1(top1) {
        const row = b.querySelector('.alt-row');
        const badge = b.querySelector('.pick-badge');
        const chosen = (b.querySelector('.bubble-dialect').textContent || '').trim();
        const t = (top1 || '').trim();
        const show = !!t && t !== chosen;
        row.hidden = !show;
        badge.hidden = !show;
        if (show) {
          b.querySelector('.alt-body').textContent = t;
          // 본문이 더 이상 'STT 원본'이 아니므로 머리말도 정확하게 바꾼다.
          b.querySelector('.who-text').textContent = '나 · 음성 입력';
          b.classList.add('show-std');
          syncToggle();
        }
        scrollDown();
      },
      remove() { b.remove(); },
      // 서버가 알려준 STT 출처를 머리말에 반영한다 (Whisper / 브라우저 음성인식)
      setSource(provider) {
        if (!provider) return;
        const name = provider === 'web' ? '브라우저 음성인식'
                   : /openai|whisper/i.test(provider) ? 'Whisper 음성인식'
                   : provider === 'text' ? '직접 입력' : provider;
        const w = b.querySelector('.who-text');
        if (w && role === 'caller') w.textContent = '나 · 받아쓴 것 (' + name + ')';
      },
      // 실제로 서버에 보낸 텍스트가 표시된 것과 다르면 그대로 드러낸다
      setSent(text) {
        const row = b.querySelector('.sent-row');
        const chosen = (b.querySelector('.bubble-dialect').textContent || '').trim();
        const t = (text || '').trim();
        row.hidden = !(t && t !== chosen);
        if (!row.hidden) b.querySelector('.sent-body').textContent = t;
      },
    };
    api.set(dialect, standard);
    if (o.listening) api.live(dialect);
    return api;
  }

  /* 화자가 아닌 시스템 알림. 어르신에게는 이 한 줄이 '반영됐다'는 신호가 된다. */
  function addNotice(text) {
    const n = document.createElement('div');
    n.className = 'notice-line';
    n.setAttribute('role', 'status');
    n.textContent = text;
    el.transcript.appendChild(n);
    scrollDown();
    return n;
  }

  /* ── 자막 ────────────────────────────────────────────────
     어르신 모드에서는 말풍선 목록 대신 이것만 보인다.
     지금 오간 말 두 개(위=민원실, 아래=나)만 남기고 이전 것은 흐려진다. */
  const CAP_WHO = { agent: '민원실', officer: '담당자', caller: '나' };

  function showCaption(role, text, opts) {
    const t = String(text || '').trim();
    if (!t) return;
    const mine = role === 'caller';
    const box = mine ? el.capCaller : el.capAgent;
    const body = mine ? el.capCallerText : el.capAgentText;
    const other = mine ? el.capAgent : el.capCaller;
    body.textContent = t;
    box.querySelector('.cap-who').textContent =
      CAP_WHO[role] || (mine ? '나' : '민원실');
    box.classList.remove('blank', 'stale');
    other.classList.add('stale');          // 방금 온 말이 아니면 흐려진다
    // 인식 중간 결과는 계속 바뀌므로 스크린리더가 읽지 않게 둔다
    box.setAttribute('aria-live', (opts && opts.live) ? 'off' : (mine ? 'off' : 'polite'));
  }

  function clearCaptions() {
    [el.capAgent, el.capCaller].forEach((b) => { b.classList.add('blank'); b.classList.remove('stale'); });
    el.capAgentText.textContent = '';
    el.capCallerText.textContent = '';
  }

  function addTyping() {
    const b = document.createElement('div');
    b.className = 'bubble agent';
    b.setAttribute('aria-hidden', 'true');        // 점 세 개를 읽어줄 필요는 없다
    b.innerHTML = '<div class="bubble-who">Voisso 상담원</div><div class="typing"><i></i><i></i><i></i></div>';
    el.transcript.appendChild(b);
    scrollDown();
    return b;
  }

  function scrollDown() {
    requestAnimationFrame(() => {
      const t = el.transcript;
      const last = t.lastElementChild;
      // 말풍선이 화면보다 크면(음성 3단 표시 등) 맨 아래가 아니라 그 말풍선의 처음을 보여준다.
      if (last && last.offsetHeight > t.clientHeight - 12) {
        t.scrollTop += last.getBoundingClientRect().top - t.getBoundingClientRect().top - 8;
      } else {
        t.scrollTop = t.scrollHeight;
      }
    });
  }

  el.chkStdAll.addEventListener('change', () => {
    state.showStdAll = el.chkStdAll.checked;
    el.transcript.querySelectorAll('.bubble').forEach((b) => {
      b.classList.toggle('show-std', state.showStdAll);
      const t = b.querySelector('.bubble-toggle');
      if (t) t.textContent = state.showStdAll ? '사투리 원문만 보기' : '표준어 보기';
    });
  });

  /* ── 슬롯 ─────────────────────────────────────────────── */
  // 서버가 어떤 키로 보내든 4칸에 매핑되도록 관대하게 읽는다.
  const SLOT_ALIASES = {
    what:    ['what', 'issue', 'problem', 'subject', 'topic', 'complaint', 'content', '무슨일', '내용', '민원내용'],
    where:   ['where', 'location', 'place', 'address', 'region', 'area', '어디', '위치', '장소', '지역'],
    when:    ['when', 'since', 'start', 'started', 'started_at', 'period', 'time', '언제', '언제부터', '기간'],
    contact: ['contact', 'phone', 'tel', 'phone_number', 'caller_phone', '연락처', '전화', '전화번호'],
  };
  const SLOT_LABEL = { what: '무슨 일', where: '어디서', when: '언제부터', contact: '연락처' };

  function slotValue(v) {
    if (v == null) return null;
    if (typeof v === 'string') return v.trim() || null;
    if (typeof v === 'number' || typeof v === 'boolean') return String(v);
    if (Array.isArray(v)) return v.filter(Boolean).join(', ') || null;
    if (typeof v === 'object') return slotValue(v.value != null ? v.value : v.text);
    return null;
  }

  function normalizeSlots(raw) {
    const out = {};
    if (!raw || typeof raw !== 'object') return out;
    const lower = {};
    Object.keys(raw).forEach((k) => { lower[String(k).toLowerCase()] = raw[k]; });
    Object.keys(SLOT_ALIASES).forEach((key) => {
      for (const a of SLOT_ALIASES[key]) {
        const v = slotValue(lower[a.toLowerCase()]);
        if (v) { out[key] = v; return; }
      }
    });
    return out;
  }

  function renderSlots(next) {
    let filled = 0;
    // 어르신이 정정했는데 반영됐는지 모르면 불안하다. 값이 '바뀐' 경우를 잡아낸다.
    const revised = [];
    Object.keys(SLOT_LABEL).forEach((key) => {
      const before = state.slots[key];
      const after = next[key];
      if (before && after && before !== after) revised.push({ key: key, from: before, to: after });
    });

    Object.keys(SLOT_LABEL).forEach((key) => {
      const node = el.slots.querySelector('.slot[data-slot="' + key + '"]');
      const val = next[key];
      const valNode = node.querySelector('.slot-val');
      if (val) {
        filled++;
        if (valNode.textContent !== val) {
          valNode.textContent = val;
          node.title = val;
          node.classList.add('filled', 'just-filled');
          // 칸보다 긴 값이면 '눌러서 전문 보기'를 띄운다(고령자 대상이라 hover 로만 열지 않는다)
          node.classList.toggle('is-long', String(val).length > 12);
          setTimeout(() => node.classList.remove('just-filled'), 520);
        }
      } else {
        valNode.textContent = '듣는 중…';
        node.classList.remove('filled', 'is-long');
        node.setAttribute('aria-expanded', 'false');
      }
    });
    el.slotsCount.textContent = filled + ' / 4';

    revised.forEach((r) => {
      const node = el.slots.querySelector('.slot[data-slot="' + r.key + '"]');
      if (node) {
        node.classList.add('revised');
        node.dataset.prev = r.from;                  // 시연 모드에서 이전 값을 보여준다
        setTimeout(() => node.classList.remove('just-revised'), 900);
        node.classList.add('just-revised');
      }
      // 어르신 모드: 이력 대신 말로 알린다. 시연 모드: 슬롯에 이전 값이 취소선으로 남는다.
      if (!isDemo()) addNotice(SLOT_LABEL[r.key] + '을(를) "' + r.to + '"(으)로 고쳤습니더.');
    });
    if (revised.length) state.slotRevisions = (state.slotRevisions || []).concat(revised);

    state.slots = next;
    renderSuggestions();
    renderDemoBar();
  }

  /* ── 예시 답변(데모 속도용) ────────────────────────────── */
  const SUGGEST = {
    what: ['비만 오면 집 앞에 물이 안 빠지니더', '가로등이 안 켜져가 밤에 캄캄합니더', '버스가 하루 두 번뿐이라예'],
    where: ['안동시 옥동, 마을회관 앞이라예', '구미시 선산읍입니더', '우리 동네 경로당 앞이시더'],
    when: ['지난주 비 온 뒤부터라예', '한 달쯤 됐니더', '작년 장마 때부터 계속 그캅니더'],
    contact: ['010-0000-0000 입니더', '집 전화 054-000-0000 이라예'],
  };
  function renderSuggestions() {
    el.suggestions.innerHTML = '';
    if (state.busy || state.ended) return;
    const missing = ['what', 'where', 'when', 'contact'].find((k) => !state.slots[k]);
    if (!missing) return;
    SUGGEST[missing].forEach((s) => {
      const c = document.createElement('button');
      c.type = 'button'; c.className = 'chip'; c.textContent = s;
      c.addEventListener('click', () => { el.textIn.value = ''; sendTurn({ text: s }); });
      el.suggestions.appendChild(c);
    });
  }

  /* ── 통화 흐름 ─────────────────────────────────────────── */
  function setBusy(on) {
    state.busy = on;
    el.btnSend.disabled = on;
    el.textIn.disabled = on;
    el.btnMic.disabled = on;
    if (on) el.suggestions.innerHTML = '';
    else renderSuggestions();
  }

  async function startCall() {
    unlockAudio();                      // 반드시 사용자 클릭 핸들러 안에서 호출해야 한다
    stopReconnect();
    resetHandoff();
    resetEndButton();
    el.callee.classList.remove('is-handoff');
    el.callee.querySelector('.callee-meta strong').textContent = '경상북도 민원실';
    setScreen('call');
    el.transcript.innerHTML = '';
    clearCaptions();
    el.callee.classList.remove('is-live');
    setPhase('연결 중');
    say('연결하고 있습니더');
    el.btnEnd.classList.remove('ready');
    el.hint.classList.remove('alert');
    el.hint.textContent = '마이크를 눌러 말하거나, 글로 적어도 됩니더.';
    state.slots = {}; state.turns = []; state.done = false; state.ended = false;
    state.callerBubbles = []; state.slotRevisions = []; state.pending = [];
    if (el.hwQueue) el.hwQueue.innerHTML = '';
    state.safety = []; state.hurry = 0; state.safetyConfirmed = false;
    el.safetyBar.hidden = true;
    el.safetyBar.classList.remove('again', 'confirmed');
    document.documentElement.dataset.sos = '';
    el.safetyCalls.innerHTML = '';
    renderSlots({});
    setBusy(true);

    let startResp = null;
    try {
      const r = await API.start();
      startResp = r;
      state.sessionId = r.session_id;
      state.startedAt = Date.now();
      el.callee.classList.add('is-live');
      setPhase('통화 중');
      say('말씀해 주이소');
      clearInterval(state.timer);
      const paintTimer = (v) => {
        el.callTimer.innerHTML = '<span class="sr-only">통화 시간 </span>' + esc(v);
      };
      state.timer = setInterval(() => {
        paintTimer(mmss(Math.floor((Date.now() - state.startedAt) / 1000)));
      }, 500);
      paintTimer('00:00');
    } catch (e) {
      setBusy(false);
      const addr = API.baseLabel();
      setPhase('연결 실패');
      say('연결이 안 됩니더');
      toast(addr + ' 에 연결하지 못했습니더.', 6000);
      el.hint.classList.add('alert');
      el.hint.innerHTML = connectionHelpHTML() +
        '<br>아래 버튼을 누르면 서버 없이 데모로 볼 수 있습니더.';
      // 막다른 화면을 만들지 않는다 — 한 번 눌러 목 모드로 넘어간다.
      el.btnEnd.textContent = '데모 모드로 보기';
      el.btnEnd.classList.remove('ready');
      btnEndAction = () => {
        const u = new URL(location.href);
        u.searchParams.set('mock', '1');
        location.href = u.toString();
      };
      return;
    }

    setBusy(false);                       // sendTurn 이 다시 busy 를 건다

    // 서버가 start 응답에 첫 인사를 얹어 주면 왕복을 한 번 아낀다(계약 외 추가 필드).
    if (startResp && (startResp.reply_dialect || startResp.reply_text)) {
      const dia = startResp.reply_dialect || startResp.reply_text;
      const std = startResp.reply_text || startResp.reply_dialect;
      addBubble('agent', dia, std);
      state.turns.push({ role: 'agent', dialect: dia, standard: std });
      renderSlots(normalizeSlots(startResp.slots));
      playAudio(startResp.audio_b64, startResp.audio_mime);
    } else if (CFG.GREETING_ON_START !== false) {
      await sendTurn({ text: '' }, { silentCaller: true });
    }
  }

  // payload: {text} 또는 {audio_b64}
  async function sendTurn(payload, opts) {
    if (!state.sessionId || state.busy) return;
    const o = opts || {};
    setBusy(true);

    // 음성인식 중에 이미 만들어 둔 말풍선이 있으면 그걸 이어서 쓴다(중복 생성 방지).
    let callerBubble = o.callerBubble || null;
    if (!callerBubble && !o.silentCaller) {
      callerBubble = payload.audio_b64
        ? addBubble('caller', '(음성 전송 중…)', '(음성 전송 중…)', { pending: true, source: 'voice-server' })
        : addBubble('caller', payload.text, payload.text, { source: o.source });
    }
    if (callerBubble) state.callerBubbles.push(callerBubble);   // 종료 후 서버 전사로 채운다
    const typing = addTyping();

    const t0 = Date.now();
    say('잠시만예');
    try {
      const r = await API.turn(state.sessionId, payload) || {};
      state.lastMs = Date.now() - t0;

      // ── 발신자 발화 (계약 5절) ──────────────────────────────
      // caller_turn 이 정본이다. 나머지 필드는 구버전 서버용 하위호환일 뿐이다.
      const ct = readCallerTurn(r);
      const sent = payload.text || '';                 // 우리가 실제로 서버에 보낸 텍스트
      const dia = ct.dialect || sent || '';
      const callerStd = ct.standard || null;

      if (callerBubble) {
        if (dia) {
          callerBubble.set(dia, callerStd || dia);
          // 시연 모드 3단 표시: [받아쓴 것] stt_raw → [정규화 후] standard → [보낸 것] sent
          const rawTop = ct.stt_raw && ct.stt_raw !== dia ? ct.stt_raw : (o.top1 || null);
          if (rawTop && callerBubble.setTop1) callerBubble.setTop1(rawTop);
          if (callerBubble.setSource) callerBubble.setSource(ct.stt_provider || o.sttProvider || null);
          if (callerBubble.setSent) callerBubble.setSent(sent);
          state.turns.push({ role: 'caller', dialect: dia, standard: callerStd || dia });
        } else {
          // 서버가 caller_turn 을 주지 않았다. 조용히 감추지 않는다 — 그건 버그다.
          console.warn('[Voisso] 서버가 caller_turn 을 주지 않았습니다. 발화 텍스트를 표시할 수 없습니다. ' +
                       '응답 필드: ' + Object.keys(r).join(', '));
          state.callerTurnMissing = true;
          if (isDemo()) {
            callerBubble.set('⚠ 서버가 caller_turn 을 주지 않음 (전사 텍스트 없음)', '');
            callerBubble.node.classList.add('missing');
          } else {
            callerBubble.set('잘 못 알아들었습니더. 다시 말씀해 주이소.', '');
          }
        }
      }

      // 음성 발화에서 정규화가 실제로 일어났다면, 그 결과를 잠깐 보여주고 답변을 띄운다.
      // (데모 스크립트의 핵심 컷 — STT 원문과 정규화 결과가 같이 보이는 프레임)
      if (o.source === 'voice' && callerStd && callerStd !== dia) {
        await new Promise((res) => setTimeout(res, CFG.VOICE_REVEAL_MS == null ? 700 : CFG.VOICE_REVEAL_MS));
      }

      typing.remove();

      const dialect = r.reply_dialect || r.reply_text || '';
      const standard = r.reply_text || r.reply_dialect || '';
      if (dialect || standard) {
        addBubble('agent', dialect, standard);
        state.turns.push({ role: 'agent', dialect, standard });
      }

      renderSlots(normalizeSlots(r.slots));

      // ── 안전 안내 (계약 5-A) ───────────────────────────────
      // 1순위: 서버의 구조화 판정. 없으면 답변·발화에서 직접 잡는다(안전 쪽으로 치우친다).
      const u = r.urgency || null;
      let shown = false;
      if (u && u.safety_referral) shown = applySafety(u.safety_referral);
      if (!shown) {
        const guess = detectSafetyFallback(r.reply_text || r.reply_dialect, sent || dia);
        if (guess.length) {
          shown = applySafety(guess);
          if (shown && !u) console.warn('[Voisso] 서버가 urgency 를 주지 않아 답변·발화에서 ' +
            '안전 안내를 추론했습니다: ' + guess.join(', '));
        }
      }
      // 다급함이 반복되면 이미 떠 있는 버튼을 다시 강조한다.
      state.hurry = (state.hurry || 0) + countHurry(sent || dia);
      if (state.hurry >= 2) { pulseSafety(); state.hurry = 0; }

      renderDemoBar();
      playAudio(r.audio_b64, r.audio_mime);
      if (!state.handoff.open) say('말씀해 주이소');

      if (r.done) {
        state.done = true;
        el.btnEnd.classList.add('ready');
        el.hint.textContent = '필요한 내용은 다 들었니더. 아래 버튼을 누르면 접수됩니더.';
        // 응급이면 같은 안내를 반복하며 붙잡아 두지 않는다. 바로 접수하고 담당자에게 넘긴다.
        // (119 버튼은 화면에 고정돼 있고, 상태는 글자로 계속 보인다)
        if ((state.safety || []).length && !state.ended) {
          say('접수하고 있습니더');
          el.hint.textContent = '접수하고 담당자한테 바로 넘길게예.';
          setTimeout(() => { if (!state.ended) endCall(); },
                     CFG.EMERGENCY_AUTO_END_MS == null ? 2000 : CFG.EMERGENCY_AUTO_END_MS);
        }
      }
      setBusy(false);
    } catch (e) {
      typing.remove();
      if (callerBubble) callerBubble.set(payload.text || '(전송 실패)', payload.text || '(전송 실패)');
      setBusy(false);
      if (isSessionLost(e)) { handleSessionLost('전송 중'); return; }
      if (isNetworkDown(e)) { handleNetworkDown(); return; }
      toast('전송 실패: ' + (e.message || e), 5000);
    }
  }

  function sendText() {
    const t = el.textIn.value.trim();
    if (!t) { el.textIn.focus(); return; }
    el.textIn.value = '';
    // 핸드오프가 열리면 AI 를 부르지 않는다. 담당자에게 바로 간다.
    if (state.callback.open) { sendCallback(t); return; }
    if (state.handoff.open) { sendHandoff(t); return; }
    sendTurn({ text: t });
  }

  async function endCall() {
    if (!state.sessionId || state.ended) return;
    stopReconnect();
    if (state.recording) stopRecording(true);
    if (state.recognizing) { window.VoissoSpeech.abort(); resetMicUI(); }
    if (liveBubble) { liveBubble.remove(); liveBubble = null; }
    state.ended = true;
    clearInterval(state.timer);
    setPhase('접수 중');
    say('접수하고 있습니더');
    el.callee.classList.remove('is-live');
    setBusy(true);

    setScreen('result');
    el.delivery.className = 'delivery';
    el.delivery.querySelector('.delivery-text').textContent = '통화 내용을 정리해서 담당 부서를 찾는 중…';
    el.card.innerHTML = '';

    try {
      const complaint = await API.end(state.sessionId);
      backfillTranscript(complaint);
      renderCard(complaint);
      setTimeout(() => {
        el.delivery.classList.add('done');
        el.delivery.querySelector('.delivery-text').textContent =
          '담당자에게 전달됨 — ' + ((complaint.assigned && complaint.assigned.full_name) || '담당 부서');
      }, 1300);
      // 화면을 닫지 않는다. 담당자가 이어받을 때까지 기다린다(계약 5-B).
      watchHandoff(complaint.id);
    } catch (e) {
      const lost = isSessionLost(e) || isNetworkDown(e);
      el.delivery.querySelector('.delivery-text').textContent = lost
        ? '통화가 중간에 끊어져 접수하지 못했습니더. 다시 걸어 주이소.'
        : '접수 실패: ' + (e.message || e);
      el.card.innerHTML = '<div class="card-body"><div class="field-key">어떻게 하면 되는교</div>' +
        '<div class="field-val">아래 "처음으로" 를 누르고 다시 전화를 걸어 주이소. ' +
        '급하시면 경상북도청 대표번호 1522-0120 으로 전화하시면 됩니더.</div></div>';
      toast(lost ? '통화가 끊어져 접수하지 못했습니더.' : '민원 접수 실패: ' + (e.message || e), 6000);
    } finally {
      state.sessionId = null;
      setBusy(false);
    }
  }

  /* 발신자 발화 읽기 — 계약 5절 caller_turn 이 1순위다.
       {"dialect","standard","source":"stt"|"text","stt_raw","stt_provider"}
     아래 나머지는 caller_turn 이전 서버를 위한 하위호환이며, 새 코드에서는 쓰지 마라. */
  function readCallerTurn(r) {
    const ct = r && r.caller_turn;
    if (ct && (ct.dialect || ct.standard)) {
      return {
        dialect: ct.dialect || ct.standard || '',
        standard: ct.standard || null,
        stt_raw: ct.stt_raw || null,
        stt_provider: ct.stt_provider || null,
        source: ct.source || null,
      };
    }
    // ── 하위호환 (구버전 서버) ──
    const legacyDia = (r && (r.caller_text || r.stt_text || r.user_text)) ||
      (r && typeof r.transcript === 'string' ? r.transcript : null) ||
      (r && r.caller && r.caller.dialect) || null;
    const legacyStd = (r && (r.caller_standard || r.text_standard || r.normalized_text)) ||
      (r && r.caller && r.caller.standard) || null;
    return { dialect: legacyDia || '', standard: legacyStd, stt_raw: null,
             stt_provider: null, source: null, legacy: !!(legacyDia || legacyStd) };
  }

  /* ── 계약 5-A. 안전 안내 ───────────────────────────────────
     긴급도 자체는 담당자용이라 어르신에게 보여주지 않는다("응급입니다"는 불안만 준다).
     단 하나의 예외가 이것 — 응급 판정 시 서버가 safety_referral 을 내려보내면
     크고 명확하게, 그리고 **접수가 신고를 대체하지 않는다**는 것을 함께 알린다. */
  const KNOWN_NUMBERS = { '119': '소방·구조', '112': '경찰', '110': '민원상담', '1522-0120': '경상북도청' };

  /* 화면에 119·112 버튼을 띄운다.
     말로만 안내하면 어르신이 번호를 외워 다시 걸어야 한다 — 그건 실패다.
     한 번 뜨면 통화가 끝날 때까지 내리지 않는다. */
  function applySafety(list) {
    const refs = normalizeReferrals(list);
    if (!refs.length) return false;

    // 이미 떠 있는 번호는 유지하고, 새 번호만 더한다(내리지 않는다).
    const merged = (state.safety || []).slice();
    let added = false;
    refs.forEach((r) => {
      const i = merged.findIndex((y) => y.number === r.number);
      if (i === -1) { merged.push(r); added = true; }
      else { merged[i] = Object.assign({}, merged[i], r); }   // 확인 표시 갱신
    });
    state.safety = merged;

    // 어르신이 말로 동의했는가. 브라우저는 tel: 을 자동 실행하지 못하므로
    // 마지막 한 번의 누름은 필요하다 — 그 누름을 최대한 쉽게 만든다.
    const confirmed = merged.filter((r) => r.confirmed);
    const declined = refs.some((r) => r.declined);
    const show = confirmed.length ? confirmed.slice(0, 1) : merged;   // 확인되면 화면에 하나만

    el.safetyHead.textContent = confirmed.length
      ? '여기 한 번만 눌러 주이소'
      : (show.length > 1 ? '지금 위험하시믄 눌러 주이소'
                         : '지금 위험하시믄 ' + show[0].number + ' 눌러 주이소');

    el.safetyCalls.innerHTML = show.map((r, i) =>
      '<a class="sb-call' + (i > 0 ? ' secondary' : '') + '" href="tel:' + esc(r.number) + '"' +
      ' aria-label="' + esc(r.number) + '번으로 전화 걸기' + (r.label ? ', ' + esc(r.label) : '') + '">' +
      '<span class="sb-num">' + esc(r.number) + '</span>' +
      '<span>' + (r.label ? '(' + esc(r.label) + ') ' : '') + '전화 걸기</span></a>').join('');

    el.safetyBar.hidden = false;
    el.safetyBar.classList.toggle('confirmed', confirmed.length > 0);
    // 화면에 큰 단추가 하나만 보이게 한다(AI 안내와 일치시킨다).
    document.documentElement.dataset.sos = confirmed.length ? '1' : '';

    if (confirmed.length && !state.safetyConfirmed) {
      state.safetyConfirmed = true;
      const a = el.safetyCalls.querySelector('.sb-call');
      if (a) { try { a.focus({ preventScroll: true }); } catch (e) { a.focus(); } }
      say('여기 한 번만 눌러 주이소');
    }
    // 거절하면 크기만 되돌린다. 버튼 자체는 화면에서 없애지 않는다.
    if (declined && !confirmed.length) {
      state.safetyConfirmed = false;
      el.safetyBar.classList.remove('confirmed');
      document.documentElement.dataset.sos = '';
    }

    if (added) pulseSafety();
    return true;
  }

  // {number,label} / [{...}] / "119" 무엇으로 오든 받는다.
  function normalizeReferrals(v) {
    if (!v) return [];
    const arr = Array.isArray(v) ? v : [v];
    const out = [];
    arr.forEach((x) => {
      if (!x) return;
      const raw = typeof x === 'string' ? x : (x.number || x.tel || '');
      const num = String(raw).replace(/[^0-9*#+-]/g, '');
      if (!num) return;
      if (out.some((y) => y.number === num)) return;
      out.push({
        number: num,
        label: (typeof x === 'object' && x.label) || KNOWN_NUMBERS[num] || '',
        confirmed: isConfirmed(x),
        declined: isDeclined(x),
      });
    });
    return out;
  }

  /* 어르신이 "예" 라고 말하면 서버가 확인 표시를 실어 보낸다.
     P6 과 필드명이 확정되기 전까지 흔한 형태를 모두 받는다.
     확정되면 이 목록을 줄이면 된다. */
  function isConfirmed(x) {
    if (!x || typeof x !== 'object') return false;
    if (x.confirmed === true || x.accepted === true || x.agreed === true) return true;
    if (x.confirmed_at) return true;
    return /^(confirmed|accepted|agreed|yes)$/i.test(String(x.status || x.state || ''));
  }

  function isDeclined(x) {
    if (!x || typeof x !== 'object') return false;
    if (x.confirmed === false && (x.asked || x.declined || x.status)) return !!(x.declined || /declin|refus|no/i.test(String(x.status || '')));
    if (x.declined === true || x.refused === true) return true;
    return /^(declined|refused|no)$/i.test(String(x.status || x.state || ''));
  }

  // 다급함이 반복되면 다시 눈에 들어오게. 깜빡임 같은 과한 효과는 쓰지 않는다.
  function pulseSafety() {
    if (el.safetyBar.hidden) return;
    el.safetyBar.classList.add('again');
    clearTimeout(pulseSafety._t);
    pulseSafety._t = setTimeout(() => el.safetyBar.classList.remove('again'), 2500);
  }

  /* 안전망 — 서버가 urgency 를 안 줘도 위험 신호는 놓치지 않는다.
     실사용에서 서버가 답변으로는 "119에 전화해 주이소" 라고 하면서
     urgency 는 null 로 보내 버튼이 뜨지 않은 사고가 있었다. */
  const DANGER_WORDS = ['가스', '불이 나', '불났', '화재', '무너지', '붕괴', '함몰', '갇혔', '고립',
    '감전', '떠내려', '차올', '물이 차', '잠기고 있', '쓰러지', '다쳤', '피가', '숨이',
    '연기가', '폭발', '누전'];
  const HURRY_WORDS = ['빨리', '빨랑', '지금 당장', '당장', '급해', '급합', '야단났', '큰일났', '우짜노'];

  function detectSafetyFallback(replyText, callerText) {
    const found = [];
    const reply = String(replyText || '');
    // 1) 상담원이 이미 번호를 말했다면 그 번호를 버튼으로 만든다.
    (reply.match(/\b(119|112|110)\b/g) || []).forEach((n) => found.push(n));
    // 2) 발화 자체에 명백한 위험 신호가 있으면 119 를 띄운다(안전 쪽으로 치우친다).
    const said = String(callerText || '');
    if (!found.length && DANGER_WORDS.some((w) => said.includes(w))) found.push('119');
    return found;
  }

  function countHurry(text) {
    const t = String(text || '');
    let n = HURRY_WORDS.filter((w) => t.includes(w)).length;
    if (/!{2,}/.test(t)) n++;
    return n;
  }

  function safetyHTML() {
    const refs = state.safety || [];
    if (!refs.length) return '';
    return '<div class="safety-bar" role="alert">' +
      '<p class="sb-head">지금 위험하시믄 눌러 주이소</p><div class="sb-calls">' +
      refs.map((r, i) => '<a class="sb-call' + (i > 0 ? ' secondary' : '') + '" href="tel:' + esc(r.number) +
        '" aria-label="' + esc(r.number) + '번으로 전화 걸기"><span class="sb-num">' + esc(r.number) +
        '</span><span>' + (r.label ? '(' + esc(r.label) + ') ' : '') + '전화 걸기</span></a>').join('') +
      '</div><p class="sb-sub">민원은 접수해 뒀습니더. 신고는 따로 해 주셔야 합니더.</p></div>';
  }

  // 긴급도 상세는 시연 모드에서만 (CSS 로 숨긴다. 데이터는 항상 들어 있다)
  function urgencyHTML(u) {
    if (!u || !u.level) return '';
    const sig = (u.signals || []).map((x) => '<span class="tag">' + esc(x) + '</span>').join('');
    return '<div class="urgency-box"><div class="field-key">AI 긴급도 판정</div>' +
      '<span class="urgency-badge" data-level="' + esc(u.level) + '">' + esc(u.level) + '</span>' +
      (u.decided_by ? ' <span class="tag">' + esc(u.decided_by) + '</span>' : '') +
      (u.reason ? '<div class="evidence" style="margin-top:8px"><b>판정 근거</b>' + esc(u.reason) + '</div>' : '') +
      (sig ? '<div class="urgency-signals">' + sig + '</div>' : '') +
      // 담당자가 AI 판정을 고치면 이력이 남는다. "AI 판정은 제안, 최종 판단은 사람"을 보여주는 자리다.
      ((u.history && u.history.length)
        ? '<div class="alts" style="margin-top:8px">' + u.history.map((h) =>
            '<div class="alt"><span>이전 판정 <b>' + esc(h.level || '') + '</b>' +
            (h.decided_by ? ' (' + esc(h.decided_by) + ')' : '') +
            (h.reason ? ' · ' + esc(h.reason) : '') + '</span></div>').join('') + '</div>'
        : '') + '</div>';
  }

  /* ── 계약 5-B. 담당자 핸드오프 ─────────────────────────────
     AI 가 접수하고 사람이 이어받는다. 핸드오프가 열리면 AI 는 발화를 멈추고,
     어르신 입력은 /api/handoff/{id}/message 로 간다.
     담당자는 표준어로 쓰고 어르신은 사투리로 듣는다 — 방언 레이어가 통역기로 쓰인다. */

  function stopHandoffPoll() {
    if (state.handoff.timer) { clearTimeout(state.handoff.timer); state.handoff.timer = 0; }
  }

  function resetHandoff() {
    stopHandoffPoll();
    stopWaitClock();
    state.handoff = { id: null, status: 'none', open: false, rendered: 0, timer: 0, officer: null };
    state.callback = { status: 'none', open: false, rendered: 0, officer: null };
    el.handoffWait.hidden = true;
    el.handoffWait.classList.remove('done');
  }

  // 민원카드를 보여준 뒤에도 화면을 닫지 않고 담당자 연결을 기다린다.
  /* 담당자가 붙기 전에 한 말은 큐에 쌓았다가, 연결되는 순간 그대로 전달한다. */
  function queueForOfficer(text) {
    const t = String(text || '').trim();
    if (!t) return;
    state.pending = (state.pending || []).concat([t]);
    renderQueue();
    toast('적어 뒀습니더. 담당자가 연결되면 바로 전해 드릴게예.', 3200);
  }

  function renderQueue() {
    const q = state.pending || [];
    el.hwQueue.innerHTML = q.map((t) => '<li>' + esc(t) + '</li>').join('');
  }

  async function flushQueue() {
    const q = (state.pending || []).slice();
    state.pending = [];
    renderQueue();
    for (const t of q) {
      try { await API.handoffSay(state.handoff.id, t); } catch (e) { /* 다음 것 계속 */ }
    }
    return q.length;
  }

  function stopWaitClock() {
    if (state.waitTimer) { clearInterval(state.waitTimer); state.waitTimer = 0; }
  }

  // "멈춘 것처럼" 보이지 않게 경과 시간을 센다. 어르신 모드에서도 과하지 않은 한 줄이다.
  function startWaitClock() {
    stopWaitClock();
    const t0 = Date.now();
    const paint = () => {
      const sec = Math.floor((Date.now() - t0) / 1000);
      el.hwElapsed.textContent = sec < 60 ? sec + '초'
        : Math.floor(sec / 60) + '분 ' + (sec % 60) + '초';
    };
    paint();
    state.waitTimer = setInterval(paint, 1000);
  }

  function watchHandoff(complaintId, silent) {
    if (!complaintId) return;
    state.handoff.id = complaintId;
    if (!silent) {
      el.handoffWait.hidden = false;
      el.handoffWait.classList.remove('done');
      el.hwNo.textContent = complaintId;
      el.btnSimOfficer.hidden = false;
      el.btnSimOfficer.disabled = false;
      el.btnSimOfficer.textContent = '담당자 연결 시뮬레이션';
      el.btnSimOfficerMsg.hidden = true;
      startWaitClock();
    }

    const tick = async () => {
      if (!state.handoff.id) return;
      let h = null;
      try { h = await API.handoffGet(state.handoff.id); } catch (e) { /* 서버가 잠깐 죽어도 계속 기다린다 */ }
      if (!state.handoff.id) return;
      if (h && h.status === 'open' && !state.handoff.open) {
        enterHandoff(h);
      } else if (h && state.handoff.open) {
        renderHandoff(h);
        if (h.status === 'closed') exitHandoff(h);
      }
      // 담당자 통화가 끝난 뒤에도 계속 기다린다 — 시스템이 먼저 전화를 걸 수 있다(5-C).
      if (!state.handoff.open) {
        let c = null;
        try { c = await API.callbackGet(state.handoff.id); } catch (e) {}
        if (c && c.status === 'pending' && !state.callback.open) showIncoming(c);
        else if (c && state.callback.open) {
          renderCallback(c);
          if (c.status === 'closed') { exitCallback(); return; }
        }
      }
      state.handoff.timer = setTimeout(tick, CFG.HANDOFF_POLL_MS || 3000);
    };
    stopHandoffPoll();
    state.handoff.timer = setTimeout(tick, 1200);
  }

  function enterHandoff(h) {
    stopWaitClock();
    state.handoff.open = true;
    state.handoff.status = 'open';
    state.handoff.officer = h.officer || null;
    state.handoff.rendered = 0;

    const o = h.officer || {};
    const title = (o.department || '담당 부서') + ' · 담당자' + (o.name ? ' ' + o.name : '');

    setScreen('call');
    el.callee.classList.add('is-handoff');
    el.callee.classList.remove('is-live');
    el.callee.querySelector('.callee-meta strong').textContent = title;
    setPhase('담당자와 통화 중');
    say('담당자와 통화 중입니더');
    el.handoffWait.hidden = true;
    el.btnSimMsg2.hidden = !isDemo();       // 통화 화면에서 담당자 역할을 이어갈 수 있게

    // 대화 흐름이 바뀌는 지점을 화면에 남긴다.
    const div = document.createElement('div');
    div.className = 'thread-divider';
    div.innerHTML = '<span>' + esc(h.notice || '지금부터 담당자가 직접 응대합니더') + '</span>';
    el.transcript.appendChild(div);

    // 핸드오프 메시지 API 는 text 만 받는다. 서버 STT(오디오) 경로는 여기서 쓸 수 없다.
    if (state.inputPath === 'server') {
      state.sttForced = (window.VoissoSpeech && window.VoissoSpeech.supported()) ? 'web' : 'text';
      applyInputPath();
    }

    resetEndButton();
    el.btnEnd.textContent = '통화 끝내기';
    btnEndAction = () => closeHandoff();

    el.hint.classList.remove('alert');
    el.hint.textContent = '담당자에게 바로 말씀하시면 됩니더.';
    setBusy(false);
    toast('담당자가 연결됐습니더.', 4000);
    renderHandoff(h);
    // 기다리는 동안 적어 둔 말씀을 그대로 전달한다.
    if ((state.pending || []).length) {
      flushQueue().then((n) => {
        if (!n) return;
        addNotice('기다리시는 동안 적어 두신 말씀 ' + n + '건을 담당자한테 전했습니더.');
        API.handoffGet(state.handoff.id).then(renderHandoff).catch(() => {});
      });
    }
  }

  function renderHandoff(h) {
    const msgs = Array.isArray(h.messages) ? h.messages : [];
    for (let i = state.handoff.rendered; i < msgs.length; i++) {
      const m = msgs[i] || {};
      if (m.role === 'officer') {
        // 담당자는 표준어로 썼고, 어르신에게는 사투리로 들려준다.
        addBubble('officer', m.dialect || m.text || '', m.standard || m.text || '',
                  { officer: state.handoff.officer || h.officer || {} });
      } else {
        addBubble('caller', m.dialect || m.text || '', m.standard || m.text || '',
                  { source: 'handoff' });
      }
    }
    state.handoff.rendered = msgs.length;
    if (h.officer && h.officer.department) state.handoff.officer = h.officer;
  }

  async function sendHandoff(text) {
    if (!state.handoff.open || !text) return;
    setBusy(true);
    try {
      await API.handoffSay(state.handoff.id, text);
      const h = await API.handoffGet(state.handoff.id);   // 내 말이 포함된 최신 목록으로 갱신
      renderHandoff(h);
      if (h.status === 'closed') { exitHandoff(h); return; }
    } catch (e) {
      toast('담당자에게 전하지 못했습니더. 다시 해 보이소.', 4500);
    }
    setBusy(false);
  }

  async function closeHandoff() {
    stopHandoffPoll();
    try { await API.handoffClose(state.handoff.id); } catch (e) { /* 실패해도 화면은 정리한다 */ }
    exitHandoff({ status: 'closed' });
  }

  function exitHandoff(h) {
    stopHandoffPoll();
    el.btnSimMsg2.hidden = true;
    state.handoff.open = false;
    state.handoff.status = 'closed';
    state.handoff.rendered = 0;
    setPhase('통화 종료');
    say('통화가 끝났습니더');
    el.callee.classList.remove('is-handoff');
    const div = document.createElement('div');
    div.className = 'thread-divider';
    div.innerHTML = '<span>담당자와의 통화가 끝났습니더. 고생하셨습니더.</span>';
    el.transcript.appendChild(div);
    scrollDown();
    el.hint.textContent = '아래 버튼을 누르면 처음으로 돌아갑니더.';
    resetEndButton();
    el.btnEnd.textContent = '처음으로';
    btnEndAction = () => { resetHandoff(); goIdle(); };
    setBusy(true);
    el.textIn.disabled = true;
    el.btnSend.disabled = true;
    el.btnMic.disabled = true;
    // 담당자 통화가 끝난 뒤에도 계속 기다린다. 처리가 끝나면 시스템이 먼저 전화를 건다(5-C).
    if (state.handoff.id) watchHandoff(state.handoff.id, true);
  }

  function goIdle() {
    stopReconnect();
    resetHandoff();
    resetEndButton();
    el.callee.classList.remove('is-handoff');
    el.callee.querySelector('.callee-meta strong').textContent = '경상북도 민원실';
    setScreen('idle');
    el.callTimer.innerHTML = '<span class="sr-only">통화 시간 </span>00:00';
    el.transcript.innerHTML = '';
    clearCaptions();
    renderSlots({});
  }

  /* 통화 중에는 서버가 발신자 발화를 응답에 실어 주지 않는다(계약 5절에 그 필드가 없다).
     대신 민원카드의 transcript 에는 dialect/standard 가 둘 다 들어온다.
     통화가 끝나면 그 값으로 말풍선을 채워, **서버가 실제로 쓴 정규화 결과**를 보여준다. */
  function backfillTranscript(complaint) {
    const tr = (complaint && Array.isArray(complaint.transcript)) ? complaint.transcript : [];
    const callerTurns = tr.filter((t) => t && t.role === 'caller');
    state.callerBubbles.forEach((b, i) => {
      const t = callerTurns[i];
      if (!t || !b || !b.set) return;
      const dia = t.dialect || t.standard || '';
      const std = t.standard || t.dialect || '';
      if (dia || std) b.set(dia, std);
    });
  }

  /* ── 계약 5-C. 진행 안내 콜백 ──────────────────────────────
     시스템이 먼저 전화를 건다. 어르신 화면은 '벨 + 받기 버튼 하나'다.
     AI 는 담당자가 쓴 브리핑만 사투리로 전한다 — 없는 답을 지어내지 않는다. */
  function showIncoming(c) {
    state.callback.status = 'pending';
    state.callback.officer = c.officer || null;
    el.incomingTitle.textContent = c.incoming_title || '경상북도청에서 전화가 왔습니더';
    const dept = (c.officer && c.officer.department) || '';
    el.incomingSub.textContent = dept ? dept + '에서 진행 상황을 알려드릴게예.'
                                      : '민원 진행 상황을 알려드릴게예.';
    // 실제 전화망 연동이 아니라는 사실은 숨기지 않는다(시연 모드에만 표시).
    el.incomingNote.textContent = c.transport || '';
    setScreen('incoming');
    toast('경상북도청에서 전화가 왔습니더.', 5000);
  }

  async function answerCallback() {
    el.btnAnswer.disabled = true;
    let c = null;
    try { c = await API.callbackAnswer(state.handoff.id); } catch (e) {}
    el.btnAnswer.disabled = false;
    if (!c) { toast('전화를 받지 못했습니더. 다시 눌러 주이소.', 4000); return; }

    state.callback.open = true;
    state.callback.status = 'answered';
    state.callback.rendered = 0;
    const dept = (c.officer && c.officer.department) || '경상북도청';

    setScreen('call');
    el.callee.classList.add('is-handoff');
    el.callee.querySelector('.callee-meta strong').textContent = dept + ' · 진행 안내';
    setPhase('진행 안내 통화');
    say('안내를 들어 보이소');
    el.transcript.innerHTML = '';
    const div = document.createElement('div');
    div.className = 'thread-divider';
    div.innerHTML = '<span>담당자가 남긴 진행 상황을 전해 드릴게예</span>';
    el.transcript.appendChild(div);

    if (state.inputPath === 'server') {           // 콜백 메시지도 text 만 받는다
      state.sttForced = (window.VoissoSpeech && window.VoissoSpeech.supported()) ? 'web' : 'text';
      applyInputPath();
    }
    resetEndButton();
    el.btnEnd.textContent = '통화 끝내기';
    btnEndAction = () => closeCallback();
    el.hint.classList.remove('alert');
    el.hint.textContent = '더 궁금한 것이 있으시믄 말씀해 주이소.';
    setBusy(false);
    renderCallback(c);
  }

  function renderCallback(c) {
    const msgs = Array.isArray(c.messages) ? c.messages : [];
    for (let i = state.callback.rendered; i < msgs.length; i++) {
      const m = msgs[i] || {};
      if (m.role === 'caller') {
        addBubble('caller', m.dialect || m.text || '', m.standard || m.text || '', { source: 'handoff' });
      } else {
        // 담당자가 쓴 글을 AI 가 사투리로 읽어 준다. 표준어 원문은 토글로 확인한다.
        addBubble('agent', m.dialect || m.text || '', m.standard || m.text || '');
      }
    }
    state.callback.rendered = msgs.length;
  }

  async function sendCallback(text) {
    if (!state.callback.open || !text) return;
    setBusy(true);
    say('잠시만예');
    try {
      await API.callbackSay(state.handoff.id, text);
      const c = await API.callbackGet(state.handoff.id);
      renderCallback(c);
      if (c.status === 'closed') { exitCallback(); return; }
    } catch (e) {
      toast('전하지 못했습니더. 다시 해 보이소.', 4000);
    }
    say('말씀해 주이소');
    setBusy(false);
  }

  async function closeCallback() {
    stopHandoffPoll();
    try { await API.callbackClose(state.handoff.id); } catch (e) {}
    exitCallback();
  }

  function exitCallback() {
    stopHandoffPoll();
    state.callback.open = false;
    state.callback.status = 'closed';
    say('통화가 끝났습니더');
    const div = document.createElement('div');
    div.className = 'thread-divider';
    div.innerHTML = '<span>안내 전화가 끝났습니더. 고생하셨습니더.</span>';
    el.transcript.appendChild(div);
    scrollDown();
    el.hint.textContent = '아래 버튼을 누르면 처음으로 돌아갑니더.';
    resetEndButton();
    el.btnEnd.textContent = '처음으로';
    btnEndAction = () => { resetHandoff(); goIdle(); };
    setBusy(true);
    el.textIn.disabled = true; el.btnSend.disabled = true; el.btnMic.disabled = true;
  }

  /* ── 민원카드 ──────────────────────────────────────────── */
  function renderCard(c) {
    c = c || {};
    if (c.urgency && c.urgency.safety_referral) applySafety(c.urgency.safety_referral);
    const a = c.assigned || {};
    const caller = c.caller || {};
    const alts = Array.isArray(c.alternatives) ? c.alternatives : [];
    const created = c.created_at ? new Date(c.created_at) : new Date();
    const when = isNaN(created) ? '' :
      created.toLocaleString('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });

    el.card.innerHTML =
      '<div class="card-top">' +
        '<div class="card-no">민원 접수번호 ' + esc(c.id || '----') + '</div>' +
        '<h2 class="card-summary">' + esc(c.summary || '민원 요약 없음') + '</h2>' +
        '<div class="card-tags">' +
          (c.category ? '<span class="tag">' + esc(c.category) + '</span>' : '') +
          '<span class="tag">' + esc(when) + '</span>' +
          '<span class="tag">통화 ' + mmss(Number(c.duration_sec) || 0) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="card-body">' +
        safetyHTML() +
        urgencyHTML(c.urgency) +
        '<div class="assigned">' +
          '<div class="field-key">담당 부서</div>' +
          '<div class="field-val">' + esc(a.full_name || '배정 대기') + '</div>' +
          '<div class="evidence"><b>이 부서로 보낸 근거 (사무분장 원문)</b>' +
            esc(a.evidence || '근거 없음 — 담당자 확인 필요') + '</div>' +
          (a.phone_token ? '<div class="alt" style="margin-top:9px">연락처 토큰 <span class="score">' +
            esc(a.phone_token) + '</span></div>' : '') +
        '</div>' +
        (alts.length ? '<div><div class="field-key">다음 후보</div><div class="alts">' +
          alts.map((x) => '<div class="alt"><span>' + esc(x.full_name || '') + '</span>' +
            (x.score != null ? '<span class="score">' + Math.round(Number(x.score) * 100) + '%</span>' : '') +
            '</div>').join('') + '</div></div>' : '') +
        '<div class="kv-grid">' +
          '<div><div class="field-key">발신자</div><div class="field-val">' + esc(caller.name_masked || '익명') + '</div></div>' +
          '<div><div class="field-key">연락처</div><div class="field-val">' + esc(caller.phone_masked || '미확인') + '</div></div>' +
        '</div>' +
        notesBlock(c) +
        slotSummary(c) +
        transcriptLog(c) +
      '</div>';
  }

  /* 통화 전사 결과 — 어르신에게는 방해되지만 시연자·담당자에게는 필수다.
     기본은 접어두고 누르면 펼친다. 사투리 원문과 표준어를 나란히 보여준다. */
  function transcriptLog(c) {
    const tr = (c && Array.isArray(c.transcript)) ? c.transcript : [];
    if (!tr.length) return '';
    const rows = tr.map((t) => {
      const who = t.role === 'caller' ? '어르신' : 'Voisso (AI)';
      const dia = t.dialect || t.standard || '';
      const std = t.standard || '';
      const same = dia.trim() === std.trim();
      return '<div class="tl-row ' + (t.role === 'caller' ? 'caller' : 'agent') + '">' +
        '<div class="tl-who">' + esc(who) + '</div>' +
        '<div class="tl-dialect">' + esc(dia) + '</div>' +
        (same || !std ? '' :
          '<div class="tl-standard"><b>표준어</b> ' + markChanged(dia, std) + '</div>') +
        '</div>';
    }).join('');
    return '<details class="tl-wrap"><summary class="field-key" style="cursor:pointer">' +
           '통화 전사 결과 ' + tr.length + '줄 — 눌러서 보기</summary>' +
           '<div class="transcript-log" style="margin-top:8px">' + rows + '</div></details>';
  }

  /* 슬롯에 안 들어가는 추가 발화. 서버가 민원카드 notes 로 준다. */
  function notesBlock(c) {
    const notes = (c && Array.isArray(c.notes)) ? c.notes.filter((n) => n && n.text) : [];
    if (!notes.length) return '';
    return '<div class="notes-block"><div class="field-key">추가로 말씀하신 내용</div>' +
      '<div class="alts">' +
      notes.map((n) => '<div class="alt"><span>' + esc(n.text) + '</span></div>').join('') +
      '</div></div>';
  }

  function slotSummary(c) {
    const fromCard = c && c.slots ? normalizeSlots(c.slots) : null;
    const src = (fromCard && Object.keys(fromCard).length) ? fromCard : state.slots;
    const keys = Object.keys(SLOT_LABEL).filter((k) => src[k]);
    if (!keys.length) return '';
    return '<div><div class="field-key">통화에서 확인한 내용</div><div class="alts">' +
      keys.map((k) => '<div class="alt"><span><b>' + esc(SLOT_LABEL[k]) + '</b> · ' +
        esc(src[k]) + '</span></div>').join('') + '</div></div>';
  }

  /* ── 음성 재생 ─────────────────────────────────────────── */
  // 브라우저 자동재생 정책: 사용자가 페이지를 건드리기 전에는 소리를 낼 수 없다.
  // 통화 버튼 클릭(진짜 제스처) 시점에 무음을 한 번 재생해 오디오 엘리먼트를 열어둔다.
  const SILENT_WAV = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAAAAA==';
  let audioUnlocked = false;
  function unlockAudio() {
    if (audioUnlocked) return;
    try {
      el.audio.src = SILENT_WAV;
      const p = el.audio.play();
      if (p && p.then) {
        p.then(() => { audioUnlocked = true; el.audio.pause(); el.audio.currentTime = 0; })
         .catch(() => { /* 그래도 텍스트로는 다 보인다 */ });
      } else { audioUnlocked = true; }
    } catch (e) { /* 무시 */ }
  }

  function guessMime(b64) {
    if (!b64) return 'audio/mpeg';
    if (b64.startsWith('SUQz') || b64.startsWith('//')) return 'audio/mpeg';
    if (b64.startsWith('T2dn')) return 'audio/ogg';
    if (b64.startsWith('UklG')) return 'audio/wav';
    if (b64.startsWith('GkXf')) return 'audio/webm';
    return 'audio/mpeg';
  }
  function playAudio(b64, mime) {
    if (!b64 || CFG.AUTO_PLAY_AUDIO === false) return;      // 텍스트 모드면 조용히 넘어간다
    try {
      el.audio.src = 'data:' + (mime || guessMime(b64)) + ';base64,' + b64;
      const p = el.audio.play();
      if (p && p.catch) p.catch((e) => {
        // 텍스트는 이미 화면에 있으므로 통화는 계속된다. 원인만 남긴다.
        console.warn('[Voisso] 음성 재생 차단됨:', e && e.name, e && e.message);
        if (e && e.name === 'NotAllowedError') {
          el.hint.classList.add('alert');
          el.hint.textContent = '소리가 막혀 있니더. 화면을 한 번 누르시면 목소리가 나옵니더.';
        }
      });
    } catch (e) { /* 재생 실패해도 통화는 계속된다 */ }
  }

  /* ── 입력 경로: 1) 브라우저 음성인식 → 2) 서버 STT → 3) 텍스트 ── */
  const QS = new URLSearchParams(location.search);

  const PATHS = {
    server: { chip: '🎙 Whisper 음성인식', cls: 'on',
              long: '서버 음성인식 (Whisper 계열 · 사투리 원문을 그대로 받아쓴다)' },
    web:    { chip: '🎙 브라우저 음성인식', cls: 'on',
              long: '브라우저 내장 음성인식 (Web Speech · 실시간 중간결과, 표준어 기준)' },
    text:   { chip: '⌨️ 텍스트 입력', cls: 'off',
              long: '텍스트 입력 (음성 입력을 쓸 수 없는 환경)' },
  };

  function mediaRecorderSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  // 서버가 STT 를 켰는지 — 하드코딩하지 않고 /api/health 응답을 본다.
  function serverSttAvailable() {
    if (CFG.SERVER_STT === true) return true;
    if (CFG.SERVER_STT === false) return false;
    return state.serverStt === true;              // 'auto'
  }

  // 지금 고를 수 있는 경로들 (칩을 눌러 순환한다)
  function availablePaths() {
    const out = [];
    if (serverSttAvailable() && mediaRecorderSupported()) out.push('server');
    if (window.VoissoSpeech && window.VoissoSpeech.supported()) out.push('web');
    out.push('text');
    return out;
  }

  function resolveInputPath() {
    if (state.sttForced) return state.sttForced;          // 화면에서 직접 고른 값이 최우선
    const forced = String(QS.get('stt') || CFG.STT_MODE || 'auto').toLowerCase();
    const web = window.VoissoSpeech && window.VoissoSpeech.supported();
    if (forced === 'text') return 'text';
    if (forced === 'web') return web ? 'web' : 'text';
    if (forced === 'server') return mediaRecorderSupported() ? 'server' : 'text';
    // auto — 서버 STT 가 살아 있으면 그것이 기본이다.
    // 근거: 서버 STT 는 사투리 어미를 그대로 받아쓴다(실측). 브라우저 음성인식은 표준어로
    // 바꿔 적는 경향이 있어, 입력 단계에서 사투리가 지워지면 방언 레이어가 할 일이 없어진다.
    if (serverSttAvailable() && mediaRecorderSupported()) return 'server';
    if (web) return 'web';
    return 'text';
  }

  function applyInputPath() {
    state.inputPath = resolveInputPath();
    const P = PATHS[state.inputPath];
    const others = availablePaths().filter((k) => k !== state.inputPath);
    el.pathChip.textContent = P.chip;
    el.pathChip.className = 'path-chip ' + P.cls;
    el.pathChip.title = '음성 입력 경로: ' + P.long +
      (others.length ? '\n눌러서 바꾸기 → ' + others.map((k) => PATHS[k].chip).join(' / ') : '');
    el.pathChip.setAttribute('aria-label', '음성 입력 경로: ' + P.long + '. 눌러서 바꿉니다.');
    renderDemoBar();
    el.btnMic.title = state.inputPath === 'text'
      ? '이 브라우저는 음성 입력을 지원하지 않습니다. 아래 칸에 입력해 주세요.'
      : '눌러서 말하기';
    return P;
  }

  /* ── 1) 브라우저 내장 음성인식 (Web Speech) ─────────────── */
  let liveBubble = null;

  function resetMicUI() {
    state.recognizing = false;
    state.recording = false;
    el.btnMic.classList.remove('recording', 'speech');
    el.btnMic.setAttribute('aria-label', '음성으로 말하기');
    if (el.micLabel) el.micLabel.textContent = '말하기';
  }

  /* 후보 재점수화 — 표준어 기준 1순위 대신, 방언 사전에 가장 잘 맞는 후보를 고른다.
     사전 신호가 없으면 1순위를 그대로 쓴다(억지로 바꾸지 않는다). */
  function rescore(alts, fallback) {
    const top1 = (alts && alts[0] && String(alts[0].transcript || '').trim()) || (fallback || '');
    const off = CFG.RESCORE_WITH_DIALECT === false || !window.VoissoHints;
    if (off || !alts || alts.length < 2) return { text: fallback || top1, top1: top1, changed: false };

    const r = window.VoissoHints.pick(alts);
    if (!r) return { text: fallback || top1, top1: top1, changed: false };

    // 데모 중에도 근거를 확인할 수 있게 콘솔에 남긴다.
    try {
      console.log('[Voisso] STT 후보 재점수화 — 선택 #' + (r.index + 1) +
        (r.changed ? ' (1순위 아님)' : ' (1순위 유지)'));
      console.table(r.scores.map((x, i) => ({
        '순위': i + 1, '후보': x.text, '점수': Number(x.total.toFixed(2)),
        '사투리어휘': x.detail.dialect, '어미': x.detail.ending,
        '민원어휘': x.detail.domain, '지명': x.detail.sigun,
        'STT신뢰도': x.confidence ? Number(x.confidence.toFixed(2)) : null,
      })));
    } catch (e) {}

    return { text: r.text, top1: top1, changed: r.changed, scores: r.scores };
  }

  function startSpeech() {
    liveBubble = null;
    window.VoissoSpeech.start({
      lang: CFG.SPEECH_LANG || 'ko-KR',
      continuous: CFG.SPEECH_CONTINUOUS !== false,
      silenceMs: CFG.SPEECH_SILENCE_MS,
      maxAlternatives: CFG.SPEECH_ALTERNATIVES || 4,
      // 통화 중이고 아직 보내는 중이 아니면, 엔진이 혼자 끝나도 다시 켠다.
      shouldContinue: () => !!state.sessionId && !state.ended && !state.busy,
      onStart: () => {
        state.recognizing = true;
        el.btnMic.classList.add('recording', 'speech');
        el.btnMic.setAttribute('aria-label', '말 끝내고 보내기');
        if (el.micLabel) el.micLabel.textContent = '다 말했어예';
        say('듣고 있습니더', 'listening');
        el.hint.classList.remove('alert');
        el.hint.textContent = '듣고 있습니더… 다 말씀하시면 마이크를 한 번 더 누르이소.';
        // 말하는 중에 실시간으로 채워지는 말풍선
        liveBubble = addBubble('caller', '', '', { source: 'voice', listening: true, pending: true });
      },
      onInterim: (t) => { if (liveBubble) liveBubble.live(t); },
      onFinal: (t, alts) => {
        const b = liveBubble; liveBubble = null;
        resetMicUI();
        el.hint.textContent = '마이크를 눌러 말하거나, 글로 적어도 됩니더.';
        const picked = rescore(alts, t);
        if (b) {
          b.set(picked.text, picked.text);        // 우선 고른 후보 그대로 고정
          if (picked.changed) b.setTop1(picked.top1);
        }
        if (state.callback.open || state.handoff.open) {
          if (b) b.remove();                      // 서버 목록으로 다시 그린다
          (state.callback.open ? sendCallback : sendHandoff)(picked.text);
          return;
        }
        sendTurn({ text: picked.text, alternatives: alts, stt_provider: 'web' },
                 { callerBubble: b, source: 'voice', sttProvider: 'web',
                   top1: picked.changed ? picked.top1 : null });
      },
      onError: (msg, code) => {
        resetMicUI();
        if (liveBubble) { liveBubble.remove(); liveBubble = null; }
        if (!msg) return;
        el.hint.classList.add('alert');
        el.hint.textContent = msg;
        if (code === 'not-allowed' || code === 'service-not-allowed' || code === 'network') toast(msg, 5000);
      },
      onEnd: (delivered) => {
        resetMicUI();
        if (!delivered && liveBubble) { liveBubble.remove(); liveBubble = null; }
      },
    });
  }

  function stopSpeech() { window.VoissoSpeech.stop(); }

  /* ── 2) 서버 STT (MediaRecorder → audio_b64) ────────────── */
  let rec = null, chunks = [], audioCtx = null, analyser = null, rafId = 0, micStream = null;

  function pickMime() {
    const cands = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
    for (const m of cands) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) return m;
    }
    return '';
  }

  async function startRecording() {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      el.hint.classList.add('alert');
      el.hint.textContent = '마이크를 쓸 수 없니더. 아래 칸에 글로 적어도 됩니더.';
      toast('마이크 권한이 없습니다. 텍스트로 진행하세요.', 4500);
      return;
    }
    const mime = pickMime();
    chunks = [];
    rec = new MediaRecorder(micStream, mime ? { mimeType: mime } : undefined);
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = onRecStop;
    rec.start();
    state.recording = true;
    el.btnMic.classList.add('recording');
    el.btnMic.setAttribute('aria-label', '녹음 멈추고 보내기');
    el.hint.classList.remove('alert');
    el.hint.textContent = '듣고 있습니더… 다 말씀하시면 한 번 더 누르이소.';
    if (el.micLabel) el.micLabel.textContent = '다 말했어예';
    say('듣고 있습니더', 'listening');
    meter(micStream);
  }

  function stopRecording(discard) {
    if (!rec) return;
    rec._discard = !!discard;
    try { rec.stop(); } catch (e) {}
    state.recording = false;
    el.btnMic.classList.remove('recording');
    el.btnMic.setAttribute('aria-label', '음성으로 말하기');
    stopMeter();
  }

  function onRecStop() {
    const discard = rec && rec._discard;
    if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
    const blob = new Blob(chunks, { type: (rec && rec.mimeType) || 'audio/webm' });
    rec = null; chunks = [];
    el.hint.textContent = '마이크를 눌러 말하거나, 글로 적어도 됩니더.';
    if (discard || !blob.size) return;
    const fr = new FileReader();
    fr.onload = () => {
      const b64 = String(fr.result).split(',')[1] || '';
      sendTurn({ audio_b64: b64 });
    };
    fr.readAsDataURL(blob);
  }

  function meter(stream) {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      audioCtx = new AC();
      const src = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const loop = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
        const rms = Math.sqrt(sum / buf.length);
        el.micLevel.style.transform = 'scale(' + (1 + Math.min(rms * 3.2, .55)).toFixed(3) + ')';
        rafId = requestAnimationFrame(loop);
      };
      loop();
    } catch (e) { /* 레벨 미터는 없어도 그만 */ }
  }

  function stopMeter() {
    cancelAnimationFrame(rafId);
    el.micLevel.style.transform = 'scale(1)';
    if (audioCtx) { try { audioCtx.close(); } catch (e) {} audioCtx = null; }
    analyser = null;
  }

  function onMicClick() {
    if (state.busy) return;
    if (state.inputPath === 'web')    return state.recognizing ? stopSpeech() : startSpeech();
    if (state.inputPath === 'server') return state.recording ? stopRecording(false) : startRecording();
    // 미지원 브라우저(Safari 등): 버튼을 숨기지 않고 안내한다
    const msg = '이 브라우저는 음성 입력을 지원하지 않습니다. 아래에 입력해 주세요.';
    el.hint.classList.add('alert');
    el.hint.textContent = msg;
    toast(msg, 4500);
    el.textIn.focus();
  }

  /* ── 이벤트 ───────────────────────────────────────────── */
  el.btnCall.addEventListener('click', startCall);
  el.btnSend.addEventListener('click', sendText);
  el.textIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); sendText(); } });
  el.btnMic.addEventListener('click', onMicClick);

  // 칩을 눌러 음성 입력 경로를 즉석에서 바꾼다.
  // 데모에서 "브라우저 인식 vs 우리 서버 인식" 차이를 그 자리에서 보여줄 수 있다.
  el.slots.addEventListener('click', (e) => {
    const slot = e.target.closest('.slot');
    if (!slot) return;
    slot.setAttribute('aria-expanded', slot.getAttribute('aria-expanded') === 'true' ? 'false' : 'true');
  });

  el.pathChip.addEventListener('click', () => {
    if (state.recognizing) stopSpeech();
    if (state.recording) stopRecording(true);
    const opts = availablePaths();
    const i = opts.indexOf(state.inputPath);
    state.sttForced = opts[(i + 1) % opts.length];
    const P = applyInputPath();
    el.hint.classList.remove('alert');
    el.hint.textContent = P.long;
    toast('음성 입력: ' + P.chip.replace(/^\S+\s/, ''), 2600);
  });
  el.btnEnd.addEventListener('click', () => (btnEndAction ? btnEndAction() : endCall()));
  el.btnAnswer.addEventListener('click', answerCallback);

  function hwSubmit() {
    const t = el.hwIn.value.trim();
    if (!t) { el.hwIn.focus(); return; }
    el.hwIn.value = '';
    if (state.handoff.open) { sendHandoff(t); return; }   // 이미 연결됐으면 바로 보낸다
    queueForOfficer(t);
  }
  el.btnHwSend.addEventListener('click', hwSubmit);
  el.hwIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); hwSubmit(); } });

  /* 시연 트리거 — 대시보드를 따로 열지 않고 한 화면에서 6단계를 흐르게 한다.
     어르신 모드에서는 CSS 로 숨겨져 있고, 시연 모드에서만 보인다. */
  el.btnSimOfficer.addEventListener('click', async () => {
    if (!state.handoff.id) return;
    el.btnSimOfficer.disabled = true;
    el.btnSimOfficer.textContent = '연결하는 중…';
    try {
      await API.handoffStartAsOfficer(state.handoff.id);
      el.btnSimOfficer.textContent = '담당자 연결됨';
      el.btnSimOfficerMsg.hidden = false;
      toast('담당자를 연결했습니더. (시연 트리거)', 3000);
    } catch (e) {
      el.btnSimOfficer.disabled = false;
      el.btnSimOfficer.textContent = '담당자 연결 시뮬레이션';
      toast('연결 실패: ' + (e.message || e), 4000);
    }
  });

  const OFFICER_LINES = [
    '안녕하세요. 담당자입니다. 접수 내용 확인했습니다. 오늘 오후에 현장 확인 나가겠습니다.',
    '현장을 보니 배수로가 막혀 있습니다. 이번 주 안에 준설하겠습니다.',
    '다른 불편한 점은 없으신가요?',
  ];
  let officerLineIdx = 0;

  async function simOfficerMessage(btn) {
    if (!state.handoff.id) return;
    btn.disabled = true;
    try {
      await API.handoffSayAsOfficer(state.handoff.id, OFFICER_LINES[officerLineIdx % OFFICER_LINES.length]);
      officerLineIdx++;
      toast('담당자 메시지를 보냈습니더. (시연 트리거)', 2600);
    } catch (e) {
      toast('전송 실패: ' + (e.message || e), 4000);
    }
    btn.disabled = false;
  }

  el.btnSimOfficerMsg.addEventListener('click', () => simOfficerMessage(el.btnSimOfficerMsg));
  el.btnSimMsg2.addEventListener('click', () => simOfficerMessage(el.btnSimMsg2));

  /* 발표용 분할 화면(web/demo)이 담당자 역할을 대신 눌러 줄 수 있게 노출한다.
     어르신 모드에서는 화면의 버튼이 숨겨져 있으므로, 상단 바가 이 함수를 쓴다. */
  window.VoissoSimOfficer = {
    canConnect: () => !!state.handoff.id && !state.handoff.open,
    isOpen: () => !!state.handoff.open,
    connect: async () => {
      if (!state.handoff.id) return { ok: false, why: '아직 접수 전입니더' };
      try { await API.handoffStartAsOfficer(state.handoff.id); return { ok: true }; }
      catch (e) { return { ok: false, why: String(e.message || e) }; }
    },
    message: async (text) => {
      if (!state.handoff.id) return { ok: false, why: '아직 접수 전입니더' };
      try {
        await API.handoffSayAsOfficer(state.handoff.id,
          text || OFFICER_LINES[officerLineIdx++ % OFFICER_LINES.length]);
        return { ok: true };
      } catch (e) { return { ok: false, why: String(e.message || e) }; }
    },
  };
  el.btnAgain.addEventListener('click', goIdle);

  /* ── 초기화 ───────────────────────────────────────────── */
  // 발표용 분할 화면(web/demo)이 리로드 없이 모드를 바꿀 수 있도록 노출한다.
  window.VoissoSetMode = setMode;
  setMode(document.documentElement.dataset.mode || 'elder');
  el.btnMode.addEventListener('click', () => setMode(isDemo() ? 'elder' : 'demo'));

  const PATH = applyInputPath();

  // 개발자도구만 열면 즉시 상태를 알 수 있어야 한다.
  console.log('[Voisso] API base = ' + API.baseLabel() +
              ' · mode = ' + (API.isMock() ? 'mock' : 'server') +
              ' · STT = ' + state.inputPath +
              ' · assets v' + (window.VOISSO_ASSET_VERSION || '?') +
              ' · page = ' + (location.origin || location.href));

  (async function initModeChip() {
    const voice = ' · 음성 입력: <b>' + esc(PATH.long) + '</b>';
    if (API.isMock()) {
      el.modeChip.innerHTML = '<b>데모 모드</b> · 목 API로 동작 중 (서버 없이 전 과정 시연 가능)' + voice;
      return;
    }
    el.modeChip.textContent = '서버 확인 중…';
    const p = await API.probe();
    // 서버가 STT 를 켰는지 확인하고 경로를 다시 고른다(하드코딩 금지).
    state.serverStt = !!(p.stt && p.stt !== 'none');
    const after = applyInputPath();
    if (p.ok) {
      console.log('[Voisso] 서버 능력 — STT=' + (p.stt || 'none') +
                  ' · TTS=' + (p.tts || 'none') + ' · engine=' + (p.engine || '?') +
                  ' → 입력 경로 ' + state.inputPath);
    }
    const voice2 = ' · 음성 입력: <b>' + esc(after.long) + '</b>';
    el.modeChip.innerHTML = (p.ok
      ? '<b>서버 연결됨</b> · ' + esc(p.base) + voice2
      : connectionHelpHTML() + '<br>주소 뒤에 <b>?mock=1</b> 을 붙이면 서버 없이 데모로 진행됩니더.' + voice);
  })();
})();
