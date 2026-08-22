#!/usr/bin/env python3
"""voisso/dialect/lexicon.json → web/call/dialect-hints.js 를 다시 만든다.

통화 UI는 빌드 스텝이 없고 file:// 로도 열려야 해서 사전을 fetch 할 수 없다.
그래서 P5 사전에서 '표면형'만 뽑아 JS 파일로 굽는다. 사전이 갱신되면 다시 돌려라.

    python3 web/call/tools/regen_dialect_hints.py

이 파일이 하는 일은 재점수화(rescoring)용 힌트 제공뿐이다.
실제 방언 정규화는 언제나 서버의 voisso.dialect 가 한다.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "voisso" / "dialect" / "lexicon.json"
OUT = ROOT / "web" / "call" / "dialect-hints.js"
OUT_LINES = ROOT / "web" / "call" / "stt-lines.js"
DEMO_SRC = ROOT / "voisso" / "dialect" / "__main__.py"

# 민원 도메인 어휘 — 후보 중 '민원처럼 들리는 것'에 가산점을 준다.
DOMAIN = [
    "하수구", "하수도", "배수", "우수", "상수도", "수도", "누수", "단수", "침수", "역류",
    "도랑", "농로", "경지정리", "농기계", "비료", "농약", "과수", "축사",
    "도로", "포장", "포트홀", "가드레일", "가로등", "보안등", "신호등", "횡단보도",
    "버스", "노선", "배차", "정류장", "택시",
    "쓰레기", "폐기물", "무단투기", "악취", "소각", "분리수거",
    "경로당", "노인정", "돌봄", "요양", "복지", "일자리", "독거",
    "산불", "멧돼지", "고라니", "유해조수", "산사태", "제방", "축대",
    "보일러", "지붕", "담장", "공사", "소음", "민원", "신고", "접수",
]

# 경상북도 시·군 — 지명이 들어간 후보에 가산점.
SIGUN = [
    "포항", "경주", "김천", "안동", "구미", "영주", "영천", "상주", "문경", "경산",
    "의성", "청송", "영양", "영덕", "청도", "고령", "성주", "칠곡", "예천", "봉화",
    "울진", "울릉", "군위",
]


def main() -> None:
    lex = json.loads(SRC.read_text(encoding="utf-8"))
    entries = lex["entries"]
    meta = lex.get("meta", {})

    dialect_forms = sorted({e["dialect"] for e in entries if len(e.get("dialect", "")) >= 2})
    # 사투리→표준어 대응쌍. 긴 표제어부터 적용해야 부분 겹침으로 깨지지 않는다.
    pairs = sorted(
        {(e["dialect"], e["standard"]) for e in entries
         if len(e.get("dialect", "")) >= 2 and e.get("standard")},
        key=lambda kv: (-len(kv[0]), kv[0]),
    )
    standard_forms = sorted({e["standard"] for e in entries if len(e.get("standard", "")) >= 2})

    # to_standard 규칙의 좌변에서 '사투리 어미 표면형'만 뽑는다(정규식 메타문자 제외).
    import re as _re
    endings = set()
    for r in lex.get("rules", []):
        if r.get("dir") != "to_standard":
            continue
        head = r.get("pattern", "").split("(?=")[0].split("(?<")[0]
        if _re.fullmatch(r"[가-힣]{1,6}", head):
            endings.add(head)
    # '습니더'만 넣으면 '나옵니더/갑니더'에 안 걸린다. 꼬리 2글자로 일반화한다.
    endings |= {e[-2:] for e in list(endings) if len(e) >= 2}
    endings = sorted(endings)

    js = f"""/* Voisso 통화 UI — 방언 재점수화 힌트 (자동 생성 파일, 직접 고치지 마라)
 * ---------------------------------------------------------------------------
 * 생성: python3 web/call/tools/regen_dialect_hints.py
 * 출처: voisso/dialect/lexicon.json  (v{meta.get('version', '?')}, 표제어 {meta.get('entry_count', len(entries))}개)
 * 라이선스: {meta.get('license', 'voisso/dialect/SOURCES.md 참조')}
 *
 * 쓰임: Web Speech 가 돌려주는 후보(maxAlternatives) 중에서 '경북 사투리 민원처럼
 *       들리는' 후보를 고르는 데만 쓴다. 실제 방언 정규화는 서버(voisso.dialect)가 한다.
 *       브라우저는 빌드 스텝 없이 file:// 로도 열려야 해서 fetch 대신 구워 넣는다.
 * --------------------------------------------------------------------------- */
window.VoissoHints = (function () {{
  'use strict';

  const DIALECT = {json.dumps(dialect_forms, ensure_ascii=False)};
  // 사투리 → 표준어 대응쌍 (긴 것부터). 서버가 없을 때 목(mock)이 쓰는 폴백 사전이다.
  const PAIRS = {json.dumps([list(p) for p in pairs], ensure_ascii=False)};
  const STANDARD = {json.dumps(standard_forms, ensure_ascii=False)};
  const ENDINGS = {json.dumps(endings, ensure_ascii=False)};
  const DOMAIN = {json.dumps(DOMAIN, ensure_ascii=False)};
  const SIGUN = {json.dumps(SIGUN, ensure_ascii=False)};

  const W = {{ dialect: 2.0, ending: 1.0, domain: 1.5, sigun: 1.5, confidence: 1.0, order: 0.35 }};

  function hits(text, list) {{
    let n = 0;
    for (const w of list) if (w && text.indexOf(w) !== -1) n++;
    return n;
  }}

  /* 후보 한 개의 점수. 반환값은 진단용 세부 내역을 포함한다. */
  function score(text, opts) {{
    const o = opts || {{}};
    const t = String(text || '');
    const d = {{
      dialect: hits(t, DIALECT),
      ending: hits(t, ENDINGS),
      domain: hits(t, DOMAIN),
      sigun: hits(t, SIGUN),
    }};
    const conf = typeof o.confidence === 'number' && isFinite(o.confidence) ? o.confidence : 0;
    const idx = o.index || 0;
    const total =
      d.dialect * W.dialect + d.ending * W.ending + d.domain * W.domain +
      d.sigun * W.sigun + conf * W.confidence - idx * W.order;   // 1순위 편향은 남겨 둔다
    return {{ total, detail: d, confidence: conf, index: idx }};
  }}

  /* alts: [{{transcript, confidence}}, ...] (엔진이 준 순서 그대로)
     반환: {{ text, index, changed, scores }} — changed=true 면 1순위가 아닌 후보를 골랐다는 뜻 */
  function pick(alts) {{
    const list = (alts || []).filter((a) => a && String(a.transcript || '').trim());
    if (!list.length) return null;
    const scores = list.map((a, i) =>
      Object.assign({{ text: String(a.transcript).trim() }},
                    score(a.transcript, {{ confidence: a.confidence, index: i }})));
    let best = 0;
    for (let i = 1; i < scores.length; i++) if (scores[i].total > scores[best].total) best = i;
    return {{
      text: scores[best].text,
      index: best,
      changed: best !== 0 && scores[best].text !== scores[0].text,
      scores: scores,
    }};
  }}

  return {{
    score, pick, pairs: PAIRS,
    info: {{ entries: DIALECT.length, endings: ENDINGS.length, domain: DOMAIN.length,
             pairs: PAIRS.length,
             source: 'voisso/dialect/lexicon.json v{meta.get('version', '?')}' }},
  }};
}})();
"""
    OUT.write_text(js, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} 생성 — 사투리 표제어 {len(dialect_forms)}개, "
          f"표준어 {len(standard_forms)}개, 어미 규칙 {len(endings)}개")
    write_demo_lines()


def write_demo_lines() -> None:
    """P5 의 DEMO_LINES(사투리 대사 + STT 예측)를 STT 실측 페이지용으로 굽는다."""
    import ast

    tree = ast.parse(DEMO_SRC.read_text(encoding="utf-8"))
    lines = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "DEMO_LINES" for t in node.targets
        ):
            for el in node.value.elts:
                label, dialect, stt = [x.value for x in el.elts]
                lines.append({"label": label, "dialect": dialect, "stt_predicted": stt})
    js = (
        "/* Voisso — STT 실측용 대사 (자동 생성 파일, 직접 고치지 마라)\n"
        " * 생성: python3 web/call/tools/regen_dialect_hints.py\n"
        " * 출처: voisso/dialect/__main__.py DEMO_LINES\n"
        " *   dialect       = 어르신이 말할 사투리 문장\n"
        " *   stt_predicted = P5 가 '표준어 STT 가 이렇게 받아쓸 것'이라 예측한 값 (미검증)\n"
        " * stt-check.html 에서 실제 브라우저 음성인식 결과와 나란히 비교한다.\n"
        " */\n"
        "window.VoissoSttLines = " + json.dumps(lines, ensure_ascii=False, indent=2) + ";\n"
    )
    OUT_LINES.write_text(js, encoding="utf-8")
    print(f"{OUT_LINES.relative_to(ROOT)} 생성 — 대사 {len(lines)}줄")


if __name__ == "__main__":
    main()
