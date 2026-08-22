/* Voisso 통화 데모 UI — 브라우저 내장 음성인식 (Web Speech API)
 * ---------------------------------------------------------------------------
 * API 키가 필요 없고, 노트북에 모델을 내려받지 않으며, 말하는 중에 중간 결과가 나온다.
 * 지원: Chrome / Edge (webkitSpeechRecognition). Safari·Firefox 는 미지원 → 상위에서 폴백.
 *
 * 어르신 통화에 맞춘 두 가지 조정:
 *   1) continuous = true — 천천히 말하다 잠깐 쉬어도 인식이 끊기지 않는다.
 *      대신 "무음 N초"를 한 턴의 끝으로 본다(silenceMs).
 *   2) 엔진이 스스로 끝내 버리면(no-speech 등) 통화 중인 동안 자동으로 다시 켠다.
 *
 * maxAlternatives 로 후보를 여러 개 받아 그대로 넘긴다. 어느 후보를 쓸지는
 * 상위(app.js + VoissoHints)가 방언 사전으로 재점수화해서 정한다.
 *
 * 주의: start() 는 반드시 사용자 조작(마이크 버튼) 뒤에 호출한다.
 *       페이지 로드 시점에 부르면 마이크 권한을 먼저 묻게 된다.
 * --------------------------------------------------------------------------- */
window.VoissoSpeech = (function () {
  'use strict';

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  // 실패 원인별로 다른 안내를 한다. 특히 권한 문제는 푸는 방법까지 알려준다.
  const ERRORS = {
    'no-speech': {
      msg: '말씀이 들리지 않았니더. 마이크를 한 번 더 누르고 말씀해 주이소.',
      hard: false,
    },
    'audio-capture': {
      msg: '마이크를 찾지 못했니더. 컴퓨터에 마이크가 연결돼 있는지 확인해 주이소. 글로 적어도 됩니더.',
      hard: true,
    },
    'not-allowed': {
      msg: '마이크 권한이 막혀 있니더. 주소창 왼쪽 자물쇠 → 마이크 → "허용" 으로 바꾸고 새로고침해 주이소. 그동안은 아래 칸에 적어 주시면 됩니더.',
      hard: true,
    },
    'service-not-allowed': {
      msg: '이 브라우저에서 음성인식이 막혀 있니더. Chrome 으로 열거나, 아래 칸에 적어 주이소.',
      hard: true,
    },
    'network': {
      msg: '음성인식 서버에 연결하지 못했니더. 인터넷을 확인하시고, 급하면 아래 칸에 적어 주이소.',
      hard: true,
    },
    'aborted': { msg: '', hard: true },
  };

  let rec = null;
  let active = false;
  let session = null;      // 현재 인식 세션 상태

  function supported() { return !!SR; }

  /* 여러 조각으로 끊긴 최종 결과를 하나의 발화로 합친다.
     후보(alternatives)도 같은 순위끼리 이어 붙여 조합 후보를 만든다. */
  function mergeChunks(chunks, maxAlts) {
    if (!chunks.length) return { text: '', alternatives: [] };
    const depth = Math.min(maxAlts || 1, Math.max.apply(null, chunks.map((c) => c.alts.length)));
    const alternatives = [];
    for (let k = 0; k < depth; k++) {
      const parts = [];
      let conf = 0;
      for (const c of chunks) {
        const a = c.alts[k] || c.alts[0];
        parts.push(a.transcript);
        conf += (typeof a.confidence === 'number' ? a.confidence : 0);
      }
      const transcript = parts.join(' ').replace(/\s+/g, ' ').trim();
      if (transcript && !alternatives.some((x) => x.transcript === transcript)) {
        alternatives.push({ transcript: transcript, confidence: conf / chunks.length });
      }
    }
    return { text: alternatives.length ? alternatives[0].transcript : '', alternatives: alternatives };
  }

  /* handlers:
       onStart()                      인식 시작
       onInterim(text)                말하는 중 (중간 결과)
       onFinal(text, alternatives)    한 턴 확정 — alternatives = [{transcript, confidence}, ...]
       onError(msg, code)             안내 문구와 원인 코드
       onEnd(delivered)               인식 종료
       shouldContinue()               true 면 엔진이 혼자 끝나도 다시 켠다 (통화 중일 때만) */
  function start(opts) {
    const o = opts || {};
    if (!SR) { o.onError && o.onError('이 브라우저는 음성 입력을 지원하지 않습니다.', 'unsupported'); return false; }
    if (active) return false;

    const maxAlts = Math.max(1, o.maxAlternatives || 4);
    const silenceMs = o.silenceMs == null ? 1800 : o.silenceMs;
    const continuous = o.continuous !== false;

    session = {
      chunks: [],          // 확정된 조각들
      interim: '',
      delivered: false,
      restarts: 0,
      maxRestarts: 5,
      timer: 0,
      stopping: false,
    };

    const clearTimer = () => { if (session.timer) { clearTimeout(session.timer); session.timer = 0; } };

    const deliver = () => {
      if (!session || session.delivered) return;
      clearTimer();
      const merged = mergeChunks(session.chunks, maxAlts);
      const text = (merged.text || session.interim || '').trim();
      if (!text) return;
      session.delivered = true;
      session.stopping = true;
      try { rec && rec.stop(); } catch (e) {}
      o.onFinal && o.onFinal(text, merged.alternatives.length
        ? merged.alternatives
        : [{ transcript: text, confidence: 0 }]);
    };

    session.deliver = deliver;      // stop() 에서 재사용한다

    const armSilence = () => {
      clearTimer();
      if (!continuous || silenceMs <= 0) return;
      session.timer = setTimeout(deliver, silenceMs);   // 말이 멈추면 한 턴으로 본다
    };

    function build() {
      const r = new SR();
      r.lang = o.lang || 'ko-KR';
      r.interimResults = true;        // 말하는 중에 텍스트가 뜬다 (데모의 핵심)
      r.continuous = continuous;      // 중간에 잠깐 쉬어도 끊기지 않는다
      r.maxAlternatives = maxAlts;    // 후보를 여러 개 받아 방언 사전으로 다시 고른다

      r.onstart = () => { active = true; if (session.restarts === 0) o.onStart && o.onStart(); };

      r.onresult = (e) => {
        session.interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i];
          if (res.isFinal) {
            const alts = [];
            for (let j = 0; j < res.length; j++) {
              const t = (res[j].transcript || '').trim();
              if (t) alts.push({ transcript: t, confidence: res[j].confidence });
            }
            if (alts.length) session.chunks.push({ alts: alts });
          } else {
            session.interim += res[0] ? res[0].transcript : '';
          }
        }
        const shown = (mergeChunks(session.chunks, 1).text + ' ' + session.interim).trim();
        if (shown) o.onInterim && o.onInterim(shown);

        if (session.chunks.length) {
          if (!continuous) deliver();     // 한 발화 = 한 턴
          else armSilence();              // 무음이 이어지면 그때 확정
        }
      };

      r.onerror = (e) => {
        const code = (e && e.error) || 'unknown';
        const info = ERRORS[code] || { msg: '음성인식에 문제가 생겼니더. 아래 칸에 적어 주이소.', hard: true };
        session.lastError = code;
        if (info.hard && info.msg) o.onError && o.onError(info.msg, code);
        if (info.hard) session.stopping = true;          // 자동 재시작하지 않는다
      };

      r.onend = () => {
        active = false;
        // 엔진이 혼자 끝났는데 아직 통화 중이면 다시 켠다(어르신이 천천히 말할 때 자주 일어난다).
        const canRestart = !session.delivered && !session.stopping &&
          session.restarts < session.maxRestarts &&
          (!o.shouldContinue || o.shouldContinue());
        if (canRestart) {
          session.restarts++;
          try { rec = build(); rec.start(); return; } catch (err) { /* 아래로 흘러 종료 처리 */ }
        }
        clearTimer();
        if (!session.delivered) {
          // 확정 전에 끝났으면 지금까지 들은 것이라도 살린다(발화를 통째로 잃는 것보다 낫다).
          const merged = mergeChunks(session.chunks, maxAlts);
          const text = (merged.text || session.interim || '').trim();
          if (text) {
            session.delivered = true;
            o.onFinal && o.onFinal(text, merged.alternatives.length
              ? merged.alternatives
              : [{ transcript: text, confidence: 0 }]);
          } else if (session.lastError === 'no-speech') {
            o.onError && o.onError(ERRORS['no-speech'].msg, 'no-speech');
          }
        }
        const delivered = session.delivered;
        rec = null;
        o.onEnd && o.onEnd(delivered);
      };

      return r;
    }

    try {
      rec = build();
      rec.start();
    } catch (err) {
      active = false; rec = null;
      o.onError && o.onError('음성인식을 시작하지 못했니더. 아래 칸에 적어 주이소.', 'start-failed');
      return false;
    }
    return true;
  }

  function stop() {                       // 지금까지 들은 것을 확정하고 끝낸다
    if (!session) { if (rec) { try { rec.stop(); } catch (e) {} } return; }
    session.stopping = true;              // 자동 재시작하지 않는다
    if (session.deliver) session.deliver();
    else if (rec) { try { rec.stop(); } catch (e) {} }
  }

  function abort() {                      // 버린다
    if (session) { session.stopping = true; session.delivered = true; }
    if (rec) { try { rec.abort(); } catch (e) {} }
  }

  function isActive() { return active; }

  return { supported, start, stop, abort, isActive };
})();
