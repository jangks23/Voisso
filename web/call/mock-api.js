/* Voisso 통화 데모 UI — 목(mock) API
 * ---------------------------------------------------------------------------
 * 계약서 5절의 HTTP 스키마를 "그대로" 흉내 낸다. 서버(server/, P6)가 뜨면
 * config.js 의 USE_MOCK 을 false 로 바꾸는 것만으로 이 파일은 쓰이지 않는다.
 *
 *   start() -> {session_id}
 *   turn()  -> {reply_text, reply_dialect, audio_b64, done, slots}
 *   end()   -> {complaint}
 *
 * 목이지만 "스크립트 재생"이 아니라, 사용자가 실제로 말한 내용에서 슬롯을
 * 뽑아 다음 질문을 고른다. 데모 중 아무 말이나 해도 대화가 성립한다.
 * 부서/근거 데이터는 데모용 픽스처다. 실제 라우팅은 P4(voisso/routing)와
 * data/gb_departments.json 이 담당한다.
 * --------------------------------------------------------------------------- */
window.VoissoMockAPI = (function () {
  'use strict';

  const LATENCY = [420, 900];   // 사람이 응답을 기다리는 느낌
  const sessions = new Map();
  let seq = 416;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const wait = () => sleep(LATENCY[0] + Math.random() * (LATENCY[1] - LATENCY[0]));

  /* ── 경북 사투리 → 표준어 (데모용 미니 사전. 실제는 P5 voisso/dialect) ── */
  const LEXICON = [
    ['그카이까네', '그러니까'], ['그카이', '그러니까'], ['그캤는데', '그랬는데'], ['그캤니더', '그랬습니다'],
    ['됐니껴', '되었습니까'], ['하이소', '하세요'], ['주이소', '주세요'], ['보이소', '보세요'],
    ['카데예', '하더라고요'], ['카더라', '하더라'], ['맞심더', '맞습니다'], ['맞니더', '맞습니다'],
    ['이시더', '입니다'], ['이라예', '이에요'], ['이라요', '이에요'],
    ['그캅니더', '그럽니다'], ['그캅니꺼', '그럽니까'], ['카능교', '합니까'], ['카셨지예', '하셨지요'],
    ['잠기뿌니더', '잠겨버렸습니다'], ['뿌니더', '버렸습니다'], ['뿟니더', '버렸습니다'], ['뿌예', '버려요'], ['뿟다', '버렸다'],
    ['빠지가', '빠져서'], ['오모', '오면'], ['오믄', '오면'], ['하모', '하면'],
    ['니더', '습니다'],
    ['능교', '습니까'], ['니껴', '습니까'], ['십니꺼', '십니까'], ['임더', '입니다'],
    ['어데예', '어디요'], ['어데', '어디'], ['우예', '어떻게'], ['와이래', '왜 이렇게'],
    ['억수로', '매우'], ['천지삐까리', '아주 많이'], ['마카', '모두'], ['다부', '다시'],
    ['수부룩이', '수북이'], ['진주바리', '온통'], ['쪼매', '조금'], ['쫌', '좀'],
    ['안캤나', '안 그랬니'], ['그래가', '그래서'], ['이래가', '이래서'], ['해가꼬', '해서'],
    ['비가 마이', '비가 많이'], ['마이', '많이'], ['디게', '되게'], ['만다꼬', '뭐 하려고'],
    ['머하노', '뭐 하니'], ['아이고야', '아이고'], ['영판', '아주'], ['깨댕이', '개울'],
    ['도랑', '도랑'], ['하매', '벌써'], ['퍼뜩', '빨리'], ['안 빠지가', '안 빠져서'],
    ['잠기뿌고', '잠겨버리고'], ['해뿌고', '해버리고'], ['뿌고', '버리고'],
  ];

  function normalize(text) {
    let out = ' ' + (text || '') + ' ';
    for (const pair of LEXICON) {
      if (pair.length < 2) continue;
      out = out.split(pair[0]).join(pair[1]);
    }
    return out.replace(/\s+/g, ' ').trim();
  }

  /* ── 슬롯 추출 ─────────────────────────────────────────── */
  const SIGUN = ['포항', '경주', '김천', '안동', '구미', '영주', '영천', '상주', '문경', '경산',
                 '의성', '청송', '영양', '영덕', '청도', '고령', '성주', '칠곡', '예천', '봉화',
                 '울진', '울릉', '군위'];

  // 반환: {value, rank}. rank 3=시군(+동) 2=행정동 1=막연한 표현. 등급이 높을 때만 갱신한다.
  function pickWhere(text) {
    const t = text.replace(/\s+/g, ' ');
    for (const g of SIGUN) {
      if (t.includes(g)) {
        const m = t.match(new RegExp(g + '[시군]?\\s*([가-힣]{1,6}(?:동|읍|면|리))?'));
        const tail = m && m[1] ? ' ' + m[1] : '';
        return { value: g + (t.includes(g + '군') ? '군' : '시') + tail, rank: 3 };
      }
    }
    const m = t.match(/([가-힣]{2,6}(?:동|읍|면|리))/);
    if (m) return { value: m[1], rank: 2 };
    const v = t.match(/(우리\s*동네|마을회관\s*앞|경로당\s*앞|집\s*앞|마을\s*입구)/);
    if (v) return { value: v[1], rank: 1 };
    return null;
  }

  function pickWhen(text) {
    const pats = [
      /((?:지난\s*주|이번\s*주|저번\s*주|작년|올해)?\s*(?:비|태풍|장마)\s*(?:온\s*)?(?:뒤|후|때|철)(?:부터)?)/,
      /(그저께|그제|어제|오늘|아침부터|엊그제)/,
      /(지난\s*주|이번\s*주|저번\s*주|지난\s*달|저번\s*달|올해|작년|재작년)/,
      /(\d+\s*(?:일|주일|주|달|개월|년)\s*(?:전|째|쯤|정도)?)/,
      /(장마\s*(?:때|철|지나고)?|비\s*온\s*뒤|태풍\s*(?:때|지나고)?|추석\s*(?:전|후|지나고)?|봄부터|여름부터|겨울부터)/,
      /(한참|오래|한\s*달\s*쯤|계속)/,
    ];
    for (const p of pats) { const m = text.match(p); if (m) return m[1].replace(/\s+/g, ' ').trim(); }
    return null;
  }

  function pickContact(text) {
    const m = text.replace(/\s/g, '').match(/(0\d{1,2})[-.]?(\d{3,4})[-.]?(\d{4})/);
    return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
  }

  const WHAT_TEMPLATES = [
    [['잠기', '침수', '물이 안', '안 빠', '역류', '넘치'], '비 올 때 물이 안 빠져 침수'],
    [['하수', '배수', '도랑', '하수구', '우수'], '배수로 막힘'],
    [['포트홀', '패인', '갈라', '노면', '도로'], '도로 파손'],
    [['가로등', '보안등', '전등', '어두'], '가로등 점등 불량'],
    [['버스', '노선', '정류장', '차편'], '버스 노선·배차 불편'],
    [['쓰레기', '폐기물', '분리수거'], '생활폐기물 처리'],
    [['악취', '냄새', '소각'], '악취 발생'],
    [['멧돼지', '고라니', '유해'], '유해야생동물 농작물 피해'],
    [['농기계', '비료', '농약', '농사'], '영농 지원 요청'],
    [['경로당', '노인', '어르신', '돌봄', '요양'], '어르신 복지 지원 요청'],
    [['누수', '수도', '단수'], '상수도 이상'],
  ];

  function summarizeWhat(std) {
    for (const [kws, label] of WHAT_TEMPLATES) {
      if (kws.some((k) => std.includes(k))) return label;
    }
    const clean = std.replace(/[.!?]+$/, '');
    return clean.length > 22 ? clean.slice(0, 22) + '…' : clean;
  }

  /* ── 데모용 부서 픽스처 (실제 라우팅: P4 + data/gb_departments.json) ── */
  const ROUTES = [
    { kw: ['배수', '하수', '물이', '침수', '잠기', '도랑', '우수', '빗물', '역류', '하수구'],
      category: '도로·하수 유지관리', department_id: 'gb-demo-doro',
      full_name: '건설도시국 도로과', phone_token: 'PHONE_0421',
      evidence: '우수관로 정비 및 배수시설 유지관리',
      alts: [['안전행정실 재난안전과', 0.68, '풍수해 대비 및 침수 취약지 관리'],
             ['환경산림자원국 물환경과', 0.54, '하수도 시설 설치 및 운영 지원']] },
    { kw: ['도로', '포트홀', '아스팔트', '갈라', '패인', '노면', '가드레일'],
      category: '도로 유지보수', department_id: 'gb-demo-doro2',
      full_name: '건설도시국 도로과', phone_token: 'PHONE_0418',
      evidence: '도로 포장 유지보수 및 도로 안전시설 관리',
      alts: [['건설도시국 건설정책과', 0.61, '지방도 건설공사 관리']] },
    { kw: ['가로등', '전등', '불이', '어두', '조명', '보안등'],
      category: '생활 안전시설', department_id: 'gb-demo-safe',
      full_name: '안전행정실 안전정책과', phone_token: 'PHONE_0233',
      evidence: '보안등·가로등 등 생활안전시설 설치 및 정비 지원',
      alts: [['건설도시국 도시계획과', 0.49, '도시 기반시설 정비 계획']] },
    { kw: ['버스', '차편', '교통', '노선', '택시', '정류장'],
      category: '농어촌 교통', department_id: 'gb-demo-traffic',
      full_name: '건설도시국 교통정책과', phone_token: 'PHONE_0512',
      evidence: '농어촌버스 노선 조정 및 벽지노선 운행 지원',
      alts: [['복지건강국 노인복지과', 0.52, '어르신 이동 편의 지원 사업']] },
    { kw: ['쓰레기', '악취', '폐기물', '냄새', '소각', '분리수거'],
      category: '생활 환경', department_id: 'gb-demo-env',
      full_name: '환경산림자원국 환경정책과', phone_token: 'PHONE_0347',
      evidence: '생활폐기물 처리 및 악취 관리 업무',
      alts: [['환경산림자원국 자원순환과', 0.63, '폐기물 처리시설 운영 관리']] },
    { kw: ['농사', '농기계', '비료', '농약', '멧돼지', '고라니', '과수', '논', '밭'],
      category: '영농 지원', department_id: 'gb-demo-agri',
      full_name: '농축산유통국 농업정책과', phone_token: 'PHONE_0688',
      evidence: '영농 지원 및 농기계 임대사업 운영',
      alts: [['환경산림자원국 산림자원과', 0.57, '유해야생동물 피해 예방 및 포획 지원']] },
    { kw: ['경로당', '노인', '어르신', '요양', '돌봄', '복지'],
      category: '어르신 복지', department_id: 'gb-demo-welfare',
      full_name: '복지건강국 노인복지과', phone_token: 'PHONE_0195',
      evidence: '경로당 운영 지원 및 어르신 돌봄 서비스',
      alts: [['복지건강국 복지정책과', 0.55, '취약계층 생활 지원 사업']] },
  ];

  const FALLBACK_ROUTE = {
    category: '일반 민원', department_id: 'gb-demo-civil',
    full_name: '자치행정국 민원봉사과', phone_token: 'PHONE_0001',
    evidence: '도민 제안 및 일반 민원 접수·이송 업무',
    alts: [['기획조정실 정책기획관', 0.42, '도정 주요업무 계획 수립 및 조정']],
  };

  function route(text) {
    let best = null, bestHit = 0;
    for (const r of ROUTES) {
      const hit = r.kw.filter((k) => text.includes(k)).length;
      if (hit > bestHit) { best = r; bestHit = hit; }
    }
    return best || FALLBACK_ROUTE;
  }

  /* ── 에이전트 대사 ─────────────────────────────────────── */
  const GREETING = {
    dialect:  '여보세요, 경상북도 민원실이시더. 무신 일로 전화 주셨능교? 사투리로 편하게 말씀하이소.',
    standard: '여보세요, 경상북도 민원실입니다. 무슨 일로 전화 주셨습니까? 사투리로 편하게 말씀하세요.',
  };

  function ask(slot, s) {
    switch (slot) {
      case 'what':
        return { dialect: '예, 말씀하이소. 어떤 일이 있었는교?',
                 standard: '예, 말씀하세요. 어떤 일이 있었습니까?' };
      case 'where':
        return { dialect: '아이고, 마이 불편하셨겠니더. 그기 어데쯤인교? 시군캉 동네까지 말씀해 주이소.',
                 standard: '아이고, 많이 불편하셨겠습니다. 그곳이 어디쯤인가요? 시·군과 동네까지 말씀해 주세요.' };
      case 'when':
        return { dialect: `${s.where}요, 적어놨니더. 언제부터 그캤능교?`,
                 standard: `${s.where}요, 적어두었습니다. 언제부터 그랬습니까?` };
      case 'contact':
        return { dialect: '알겠니더. 담당자가 확인하고 연락드릴 낀데, 연락처 좀 불러 주이소.',
                 standard: '알겠습니다. 담당자가 확인하고 연락드릴 텐데, 연락처 좀 불러 주세요.' };
      default:
        return GREETING;
    }
  }

  const since = (v) => String(v || '').replace(/(부터|서부터)$/, '');

  function confirm(s, r) {
    return {
      dialect: `정리하면 ${s.where} ${s.what} 건이고, ${since(s.when)}부터라 카셨지예. ` +
               `${r.full_name}로 넘길 낍니더. 접수되면 문자로 알려드리겠니더. 전화 주셔서 고맙심더.`,
      standard: `정리하면 ${s.where} ${s.what} 건이고, ${since(s.when)}부터라고 하셨지요. ` +
                `${r.full_name}으로 넘기겠습니다. 접수되면 문자로 알려드리겠습니다. 전화 주셔서 고맙습니다.`,
    };
  }

  const ORDER = ['what', 'where', 'when', 'contact'];

  function maskPhone(p) {
    if (!p) return null;
    const parts = p.split('-');
    if (parts.length === 3) return `${parts[0]}-****-${parts[2]}`;
    return p.slice(0, 3) + '-****-' + p.slice(-4);
  }

  /* ── 계약 API ──────────────────────────────────────────── */
  async function start() {
    await sleep(260);
    const id = 'mock-' + Math.random().toString(36).slice(2, 9);
    sessions.set(id, { slots: {}, turns: [], started: Date.now(), done: false });
    return { session_id: id };
  }

  async function turn(body) {
    await wait();
    const s = sessions.get(body.session_id);
    if (!s) throw new Error('세션을 찾을 수 없습니다.');

    // 음성 입력은 목에서 STT 를 흉내 낼 수 없으므로, 데모용 문장으로 대체한다.
    const VOICE_FALLBACK = [
      '비만 오면 집 앞에 물이 안 빠지가 마당이 잠기뿌니더',
      '안동시 옥동, 마을회관 앞이라예',
      '지난주 비 온 뒤부터 계속 그캅니더',
      '연락처는 010-0000-0000 임더',
    ];
    let raw = (body.text || '').trim();
    if (!raw && body.audio_b64) raw = VOICE_FALLBACK[Math.min(s.turns.length, VOICE_FALLBACK.length - 1)];

    if (!raw) {                                   // 통화 시작 직후 첫 인사
      s.asked = 'what';
      s.turns.push({ role: 'agent', dialect: GREETING.dialect, standard: GREETING.standard });
      return {
        reply_text: GREETING.standard, reply_dialect: GREETING.dialect,
        audio_b64: null, done: false, slots: { ...s.slots },
      };
    }

    const std = normalize(raw);
    s.turns.push({ role: 'caller', dialect: raw, standard: std });

    // 슬롯 갱신 — (1) 문장에서 직접 추출
    const w = pickWhere(std);
    if (w && w.rank >= 2 && w.rank > (s.whereRank || 0)) { s.slots.where = w.value; s.whereRank = w.rank; }
    if (!s.slots.when)    { const v = pickWhen(std);    if (v) s.slots.when = v; }
    if (!s.slots.contact) { const v = pickContact(std); if (v) s.slots.contact = v; }
    if (!s.slots.what && !/^[\s\d\-]*$/.test(std) && std.length >= 4) s.slots.what = summarizeWhat(std);

    // (2) 방금 물어본 항목이 아직 비었으면, 이번 발화를 그 항목의 답으로 받는다.
    //     (데모 중 무슨 말을 하든 대화가 앞으로 나아가게 한다)
    const asked = s.asked;
    if (asked && !s.slots[asked]) {
      const short = std.replace(/[.!?]+$/, '');
      s.slots[asked] = asked === 'what' ? summarizeWhat(std)
                     : (short.length > 24 ? short.slice(0, 24) + '…' : short);
      if (asked === 'where') s.whereRank = w ? w.rank : 1;
    }

    const missing = ORDER.find((k) => !s.slots[k]);
    const r = route(s.turns.filter((t) => t.role === 'caller').map((t) => t.standard).join(' '));
    s.route = r;

    let line, done = false;
    s.asked = missing || null;
    if (missing) {
      line = ask(missing, s.slots);
    } else {
      line = confirm(s.slots, r);
      done = true;
      s.done = true;
    }
    s.turns.push({ role: 'agent', dialect: line.dialect, standard: line.standard });

    return {
      reply_text: line.standard,
      reply_dialect: line.dialect,
      audio_b64: null,                 // 목은 TTS 없음 → UI 는 텍스트만 표시해야 한다
      done,
      slots: { ...s.slots },
      // 아래 두 필드는 목의 편의 필드다. UI 는 없으면 없는 대로 동작한다.
      caller_text: raw,
      caller_standard: std,
    };
  }

  async function end(body) {
    await sleep(700);
    const s = sessions.get(body.session_id) || { slots: {}, turns: [], started: Date.now() };
    const r = s.route || route(s.turns.map((t) => t.standard || '').join(' '));
    const slots = s.slots;
    const where = slots.where || '경상북도';
    const what = slots.what || '민원 내용 확인 필요';
    const id = String(++seq).padStart(4, '0');

    const complaint = {
      id,
      created_at: new Date().toISOString(),
      duration_sec: Math.max(12, Math.round((Date.now() - s.started) / 1000)),
      summary: (what.includes(where) ? what : `${where} ${what}`).trim(),
      category: r.category,
      assigned: {
        department_id: r.department_id,
        full_name: r.full_name,
        phone_token: r.phone_token,
        evidence: r.evidence,
      },
      alternatives: (r.alts || []).map((a) => ({ full_name: a[0], score: a[1], evidence: a[2] })),
      caller: {
        name_masked: '김○○',
        phone_masked: maskPhone(slots.contact) || '미확인',
      },
      transcript: s.turns.map((t) => ({
        role: t.role,
        dialect: t.dialect || '',
        standard: t.standard || '',
      })),
      slots: { ...slots },
    };
    sessions.delete(body.session_id);
    return { complaint };
  }

  return { start, turn, end, normalize };
})();
