/* Voisso 통화 데모 UI — 앱 로직
 * 순수 JS. 빌드 스텝 없음. index.html 을 그냥 열면 동작한다. */
(function () {
  'use strict';

  const API = window.VoissoAPI;
  const CFG = window.VOISSO_CONFIG || {};
  const $ = (id) => document.getElementById(id);

  const el = {
    phone: $('phone'),
    btnTheme: $('btnTheme'), btnSize: $('btnTextSize'),
    screens: { idle: $('screenIdle'), call: $('screenCall'), result: $('screenResult') },
    btnCall: $('btnCall'), modeChip: $('modeChip'),
    callee: document.querySelector('.callee'), callStatus: $('callStatus'), callTimer: $('callTimer'),
    chkStdAll: $('chkStandardAll'), pathChip: $('pathChip'),
    transcript: $('transcript'),
    slots: $('slots'), slotsCount: $('slotsCount'),
    suggestions: $('suggestions'), textIn: $('textIn'), btnSend: $('btnSend'),
    btnMic: $('btnMic'), micLevel: document.querySelector('.mic-level'),
    hint: $('composerHint'), btnEnd: $('btnEnd'),
    delivery: $('delivery'), card: $('card'), btnAgain: $('btnAgain'),
    audio: $('replyAudio'), toast: $('toast'),
  };

  const state = {
    sessionId: null, startedAt: 0, timer: null,
    slots: {}, turns: [], busy: false, done: false, ended: false,
    showStdAll: false, recording: false, recognizing: false, inputPath: 'text',
  };

  /* ── 유틸 ──────────────────────────────────────────────── */
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // 서버가 세션을 잃었을 때(재기동·만료) 날 HTTP 문자열을 보여주지 않는다.
  function isSessionLost(e) {
    return !!e && (e.status === 404 || /세션/.test(e.detail || '') || /HTTP 404/.test(e.message || ''));
  }

  function handleSessionLost(where) {
    clearInterval(state.timer);
    state.sessionId = null;
    state.ended = true;
    el.callee.classList.remove('is-live');
    el.callStatus.textContent = '통화 끊김';
    el.hint.classList.add('alert');
    el.hint.textContent = '통화가 끊어졌습니더. 아래 버튼으로 다시 걸어 주이소.';
    el.btnEnd.textContent = '다시 전화 걸기';
    el.btnEnd.classList.remove('ready');
    el.btnEnd.onclick = () => {
      el.btnEnd.textContent = '통화 끝내고 민원 접수';
      el.btnEnd.onclick = null;
      startCall();
    };
    toast('통화가 끊어졌습니더. 다시 걸어 주이소.' + (where ? ' (' + where + ')' : ''), 5000);
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
  function bubbleLabels(role, source) {
    if (role !== 'caller') {
      return { who: 'Voisso 상담원', std: '표준어 변환', on: '표준어 보기', off: '사투리 원문만 보기' };
    }
    if (source === 'voice' || source === 'voice-server') {
      return { who: source === 'voice' ? '나 · STT 원본 (브라우저 음성인식)' : '나 · STT 원본 (서버 음성인식)',
               std: '방언 정규화 후', on: '방언 정규화 결과 보기', off: 'STT 원본만 보기' };
    }
    return { who: '나 (발신자)', std: '표준어 변환', on: '표준어 보기', off: '사투리 원문만 보기' };
  }

  function addBubble(role, dialect, standard, opts) {
    const o = opts || {};
    const L = bubbleLabels(role, o.source);
    const isVoice = o.source === 'voice' || o.source === 'voice-server';

    const b = document.createElement('div');
    b.className = 'bubble ' + (role === 'caller' ? 'caller' : 'agent');
    if (o.pending) b.classList.add('pending');
    if (o.listening) { b.classList.add('listening'); b.setAttribute('aria-hidden', 'true'); }
    if (state.showStdAll) b.classList.add('show-std');

    b.innerHTML =
      '<div class="bubble-who"><span class="who-text">' + esc(L.who) + '</span>' +
        '<span class="pick-badge" hidden>방언 사전이 고른 후보</span></div>' +
      '<div class="bubble-dialect"></div>' +
      '<div class="bubble-std">' +
        '<div class="std-row alt-row" hidden>' +
          '<span class="lbl">받아쓴 것 (STT 1순위)</span><span class="alt-body"></span>' +
        '</div>' +
        '<div class="std-row">' +
          '<span class="lbl">' + esc(L.std) + '</span><span class="std-body"></span>' +
        '</div>' +
      '</div>' +
      '<button class="bubble-toggle" type="button">' + esc(L.on) + '</button>';

    const toggle = b.querySelector('.bubble-toggle');
    const syncToggle = () => { toggle.textContent = b.classList.contains('show-std') ? L.off : L.on; };
    toggle.addEventListener('click', () => { b.classList.toggle('show-std'); syncToggle(); });
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
        scrollDown();
      },
      live(text) {                         // 인식 중간 결과
        b.classList.add('listening');
        b.querySelector('.bubble-dialect').textContent = text || '';
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
    };
    api.set(dialect, standard);
    if (o.listening) api.live(dialect);
    return api;
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
          setTimeout(() => node.classList.remove('just-filled'), 520);
        }
      } else {
        valNode.textContent = '듣는 중…';
        node.classList.remove('filled');
      }
    });
    el.slotsCount.textContent = filled + ' / 4';
    state.slots = next;
    renderSuggestions();
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
    setScreen('call');
    el.transcript.innerHTML = '';
    el.callee.classList.remove('is-live');
    el.callStatus.textContent = '연결 중…';
    el.btnEnd.classList.remove('ready');
    el.hint.classList.remove('alert');
    el.hint.textContent = '마이크를 눌러 말하거나, 글로 적어도 됩니더.';
    state.slots = {}; state.turns = []; state.done = false; state.ended = false;
    renderSlots({});
    setBusy(true);

    let startResp = null;
    try {
      const r = await API.start();
      startResp = r;
      state.sessionId = r.session_id;
      state.startedAt = Date.now();
      el.callee.classList.add('is-live');
      el.callStatus.textContent = '통화 중';
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
      el.callStatus.textContent = '연결 실패';
      toast('서버 연결 실패: ' + (e.message || e), 6000);
      el.hint.classList.add('alert');
      el.hint.textContent = '서버에 연결하지 못했습니더. 주소 뒤에 ?mock=1 을 붙이면 데모를 볼 수 있습니더.';
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
    const typing = addTyping();

    try {
      const r = await API.turn(state.sessionId, payload) || {};

      // 발신자 발화: 서버가 STT/정규화 결과를 주면 그것으로 교체한다.
      const callerRaw = r.caller_text || r.stt_text || r.user_text ||
        (typeof r.transcript === 'string' ? r.transcript : null);
      let callerStd = r.caller_standard || r.text_standard || r.normalized_text || null;
      // 계약서 5절 transcript 항목 형태로 오는 경우도 받는다: {"caller_turn": {"dialect","standard"}}
      const ct = r.caller_turn || (r.caller && (r.caller.dialect || r.caller.standard) ? r.caller : null);
      if (ct) { callerStd = ct.standard || callerStd; }
      const ctDia = ct && ct.dialect ? ct.dialect : null;
      if (callerBubble) {
        const dia = ctDia || callerRaw || payload.text || '(음성 발화)';
        callerBubble.set(dia, callerStd || dia);
        if (o.top1 && callerBubble.setTop1) callerBubble.setTop1(o.top1);
        state.turns.push({ role: 'caller', dialect: dia, standard: callerStd || dia });
      }

      // 음성 발화에서 정규화가 실제로 일어났다면, 그 결과를 잠깐 보여주고 답변을 띄운다.
      // (데모 스크립트의 핵심 컷 — STT 원문과 정규화 결과가 같이 보이는 프레임)
      if (o.source === 'voice' && callerStd && callerStd !== (ctDia || callerRaw || payload.text)) {
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
      playAudio(r.audio_b64, r.audio_mime);

      if (r.done) {
        state.done = true;
        el.btnEnd.classList.add('ready');
        el.hint.textContent = '필요한 내용은 다 들었니더. 아래 버튼을 누르면 접수됩니더.';
      }
      setBusy(false);
    } catch (e) {
      typing.remove();
      if (callerBubble) callerBubble.set(payload.text || '(전송 실패)', payload.text || '(전송 실패)');
      setBusy(false);
      if (isSessionLost(e)) { handleSessionLost('전송 중'); return; }
      toast('전송 실패: ' + (e.message || e), 5000);
    }
  }

  function sendText() {
    const t = el.textIn.value.trim();
    if (!t) { el.textIn.focus(); return; }
    el.textIn.value = '';
    sendTurn({ text: t });
  }

  async function endCall() {
    if (!state.sessionId || state.ended) return;
    if (state.recording) stopRecording(true);
    if (state.recognizing) { window.VoissoSpeech.abort(); resetMicUI(); }
    if (liveBubble) { liveBubble.remove(); liveBubble = null; }
    state.ended = true;
    clearInterval(state.timer);
    el.callStatus.textContent = '통화 종료';
    el.callee.classList.remove('is-live');
    setBusy(true);

    setScreen('result');
    el.delivery.className = 'delivery';
    el.delivery.querySelector('.delivery-text').textContent = '통화 내용을 정리해서 담당 부서를 찾는 중…';
    el.card.innerHTML = '';

    try {
      const complaint = await API.end(state.sessionId);
      renderCard(complaint);
      setTimeout(() => {
        el.delivery.classList.add('done');
        el.delivery.querySelector('.delivery-text').textContent =
          '담당자에게 전달됨 — ' + ((complaint.assigned && complaint.assigned.full_name) || '담당 부서');
      }, 1300);
    } catch (e) {
      const lost = isSessionLost(e);
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

  /* ── 민원카드 ──────────────────────────────────────────── */
  function renderCard(c) {
    c = c || {};
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
        slotSummary(c) +
      '</div>';
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
    web:    { chip: '🎙 브라우저 음성인식', cls: 'on',
              long: '브라우저 내장 음성인식 (Web Speech · 키 불필요)' },
    server: { chip: '🎙 서버 음성인식', cls: 'on',
              long: '서버 STT (녹음 → audio_b64)' },
    text:   { chip: '⌨️ 텍스트 입력', cls: 'off',
              long: '텍스트 입력 (이 브라우저는 음성 입력을 지원하지 않습니다)' },
  };

  function mediaRecorderSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function resolveInputPath() {
    const forced = String(QS.get('stt') || CFG.STT_MODE || 'auto').toLowerCase();
    const web = window.VoissoSpeech && window.VoissoSpeech.supported();
    if (forced === 'text') return 'text';
    if (forced === 'web') return web ? 'web' : 'text';
    if (forced === 'server') return mediaRecorderSupported() ? 'server' : 'text';
    if (web) return 'web';                                          // 기본 경로
    if (CFG.SERVER_STT && mediaRecorderSupported()) return 'server'; // 서버 STT 가 켜져 있을 때만
    return 'text';                                                  // 항상 가능한 최후 경로
  }

  function applyInputPath() {
    state.inputPath = resolveInputPath();
    const P = PATHS[state.inputPath];
    el.pathChip.textContent = P.chip;
    el.pathChip.className = 'path-chip ' + P.cls;
    el.pathChip.title = '음성 입력 경로: ' + P.long;
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
        sendTurn({ text: picked.text, alternatives: alts },
                 { callerBubble: b, source: 'voice', top1: picked.changed ? picked.top1 : null });
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
    el.hint.textContent = '듣고 있습니더… 다 말씀하시면 마이크를 한 번 더 누르이소.';
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
  el.btnEnd.addEventListener('click', endCall);
  el.btnAgain.addEventListener('click', () => {
    setScreen('idle');
    el.callTimer.textContent = '00:00';
    el.transcript.innerHTML = '';
    renderSlots({});
  });

  /* ── 초기화 ───────────────────────────────────────────── */
  const PATH = applyInputPath();

  (async function initModeChip() {
    const voice = ' · 음성 입력: <b>' + esc(PATH.long) + '</b>';
    if (API.isMock()) {
      el.modeChip.innerHTML = '<b>데모 모드</b> · 목 API로 동작 중 (서버 없이 전 과정 시연 가능)' + voice;
      return;
    }
    el.modeChip.textContent = '서버 확인 중…';
    const p = await API.probe();
    el.modeChip.innerHTML = (p.ok
      ? '<b>서버 연결됨</b> · ' + esc(p.base)
      : '<b>서버 응답 없음</b> · ' + esc(p.base) + ' — 주소 뒤에 <b>?mock=1</b> 을 붙이면 데모로 진행됩니더')
      + voice;
  })();
})();
