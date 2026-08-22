# -*- coding: utf-8 -*-
"""방언 레이어 CLI — 눈으로 확인하는 용도.

    python -m voisso.dialect --demo              민원 상황 변환 예시 실행
    python -m voisso.dialect --samples           samples.md 내용을 생성해 출력
    python -m voisso.dialect --roundtrip-report  왕복 보존 통과율
    python -m voisso.dialect --stats             사전 규모·도메인·출처 분포
    python -m voisso.dialect -d "접수해 드리겠습니다"   표준어 → 경북
    python -m voisso.dialect -n "어데서 물이 새노"      사투리 → 표준어
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from . import entries, explain, lexicon_size, normalize, rule_count, rules, source_counts, to_dialect

#: 민원 통화에서 실제로 오갈 만한 문장들. samples.md 는 여기서 생성된다.
#: 어르신 발화(사투리 → 표준어) 15개 + 시스템 응답(표준어 → 경북) 15개.
CALLER_SAMPLES = [
    ("배수 불량", "집 앞에 물이 안 빠지고 자꾸 고이가꼬 몬 살겠다"),
    ("하수구 막힘", "수채구영이 맥히가꼬 물이 넘칩니더"),
    ("누수", "어데서 물이 새노"),
    ("도로 파손", "마실 앞 질바닥이 다 패이가꼬 우예 댕기노"),
    ("가로등 고장", "가리등이 안죽 안 들어옵니더"),
    ("교통 문의", "차부가 어데고?"),
    ("버스 배차", "뻐스가 하매 갔능교?"),
    ("건강·의료", "할매가 마이 아파가꼬 빙원에 갈라꼬 캅니더"),
    ("농사 피해", "산돼지가 밭에 내려와가 꼬치를 마카 밟아뿟다"),
    ("농기계", "경운기가 맥히가꼬 시동이 안 걸린다"),
    ("주거 파손", "담부랑이 무너지가꼬 우짜꼬"),
    ("쓰레기·악취", "씨레기 내미가 억수로 심합니더"),
    ("소음", "새복부터 씨끄럽어가 잠을 몬 잡니더"),
    ("지원금 문의", "노인 수당을 우예 신청하노"),
    ("마무리 인사", "고맙심더. 단디 좀 봐 주이소."),
]

AGENT_SAMPLES = [
    ("첫 인사", "안녕하세요. 경상북도 민원실입니다."),
    ("용건 확인", "어떤 일로 전화 주셨어요?"),
    ("경청", "천천히 말씀해 주세요."),
    ("되묻기", "어느 마을에 사세요?"),
    ("연락처 확인", "연락처를 하나만 남겨 주시겠어요?"),
    ("대기 안내", "잠시만 기다려 주세요."),
    ("접수 확인", "접수해 드리겠습니다."),
    ("처리 안내", "담당자가 확인 후 연락드리겠습니다."),
    ("당일 처리", "오늘 중으로 처리해 드릴게요."),
    ("부서 안내", "건설도시국 도로과로 접수했습니다."),
    ("대표번호 안내", "대표번호는 1522-0120입니다."),
    ("신청 안내", "기초연금은 읍면사무소에서 신청합니다."),
    ("현장 확인", "현장에 나가서 확인하겠습니다."),
    ("공감", "많이 불편하셨겠어요."),
    ("마무리", "더 궁금한 점 있으세요?"),
]


#: 데모 1단계용 사투리 대사. 상황은 경북 실정에 맞췄다.
#:
#: ``stt`` 는 **예측이다.** 표준어 기준 Web Speech(ko-KR)가 사투리 음성을 어떻게
#: 받아쓸지 추측한 값이고, 우리가 실제로 브라우저에서 측정한 결과가 아니다.
#: 실측은 P7이 브라우저에서 하고, 그 결과로 이 값을 갈아끼워야 한다.
#: ``normalize`` 결과와 라우팅 결과는 예측이 아니라 **실제 실행 결과**다.
DEMO_LINES = [
    ("하수구 막힘", "수채구영이 맥히가꼬 물이 넘쳐 나옵니더",
     "수채구영이 맥히가꼬 물이 넘쳐 나옵니다"),
    ("상수도 누수", "수도물이 며칠째 안 나옵니더. 상수도가 우예 된 거라예",
     "수도물이 며칠째 안 나옵니다 상수도가 우예 된 거라예"),
    ("농로 유실", "비 와가 논에 물 대는 농로가 다 떠내리가뿟심더. 경지정리 좀 해 주이소",
     "비 와가 논에 물 대는 농로가 다 떠내리가뿟심더 경지정리 좀 해주이소"),
    ("버스 배차", "우리 마실에 뻐스가 하루에 두 번밖에 안 옵니더",
     "우리 마실에 뻐스가 하루에 두 번밖에 안 옵니다"),
    ("경로당 지원", "노인정 보일러가 고장나가 어르신들이 추와가 몬 모입니더",
     "노인정 보일러가 고장나가 어르신들이 추와가 몬 모입니다"),
    ("산불 예방", "산에 검불이 마이 쌓이가 산불 나믄 우짜노 예방 좀 해 주이소",
     "산에 검불이 마이 쌓이가 산불 나믄 우짜노 예방 좀 해주이소"),
    ("폐기물 무단투기", "밤중에 누가 질가에 씨레기를 마카 내삐리고 갑니더. 단속 좀 해 주이소",
     "밤중에 누가 질가에 씨레기를 마카 내삐리고 갑니다 단속 좀 해주이소"),
    ("독거노인 돌봄", "우리 마실에 혼차 사시는 노인이 마이 계신데 돌봄 서비스가 안 옵니더",
     "우리 마실에 혼차 사시는 노인이 마이 계신데 돌봄 서비스가 안 옵니다"),
    ("멧돼지 피해", "산돼지가 밭에 내려와가 꼬치를 마카 밟아뿟습니더",
     "산돼지가 밭에 내려와가 꼬치를 마카 밟아뿟습니다"),
    ("노인 일자리", "일할 데가 엄써가 그라는데 노인 일자리 좀 알아봐 주이소",
     "일할 데가 엄써가 그라는데 노인 일자리 좀 알아봐 주이소"),
]


#: STT가 방언 낱말을 **다른 표준어 낱말로 바꿔 버린** 경우. 우리도 복구하지 못한다.
#: 데모에서 숨기지 않고 한계로 함께 보여준다.
UNRECOVERABLE = [
    ("수채구영이 맥히가꼬", "수채 구멍이 매키가꼬",
     "'수채구영'(하수구)이 '수채 구멍'으로 쪼개졌다. 표제어가 사라져 사전이 걸리지 않는다"),
    ("나락이 다 씨러졌심더", "나락이 다 쓰러졌습니다",
     "'나락'(벼)은 표준어에도 있는 낱말이라 STT가 그대로 넘긴다. "
     "여기서는 우리 사전이 '벼'로 고쳐 주지만, 반대로 STT가 '나라기'처럼 쪼개면 복구 못 한다"),
]


def _route(text: str):
    """라우팅 결과를 (부서, 점수, 근거, 확신) 로. 라우팅이 없으면 None."""
    try:
        from voisso.routing import route
    except ImportError:
        return None
    try:
        result = route(text, top_k=1)
    except Exception:  # noqa: BLE001 - 부서 데이터가 없을 수 있다
        return None
    matches = result.get("matches") or []
    if not matches:
        return ("(배정 실패)", 0.0, "", False)
    top = matches[0]
    return (top["full_name"], round(top["score"], 3),
            " ".join(top["evidence"].split())[:80], result.get("confident", False))


def _demo_lines_markdown() -> str:
    out = [
        "# 데모 1단계 — 사투리 대사 세트\n\n",
        "> 이 파일은 `python -m voisso.dialect --demo-lines` 로 **생성된다.**\n",
        "> 손으로 고치지 말고 사전이나 대사를 고친 뒤 다시 생성하라.\n\n",
        "데모 1단계 시나리오는 이렇다.\n\n",
        "```\n어르신이 사투리로 말함\n  → 표준어 STT가 잘못 받아씀\n"
        "  → normalize() 가 교정\n  → 라우팅이 담당 부서를 찾음\n```\n\n",
        "## ⚠️ 어느 값이 실측이고 어느 값이 예측인가\n\n",
        "| 열 | 성격 |\n|---|---|\n",
        "| 사투리 원문 | 사람이 작성 |\n",
        "| **STT 예측** | **예측이다. 검증하지 않았다.** 표준어 Web Speech(ko-KR)가 이렇게 "
        "받아쓸 것이라는 추측일 뿐, 브라우저에서 측정한 값이 아니다 |\n",
        "| 정규화 결과 | **실행 결과** — `normalize()` 를 실제로 통과시킨 값 |\n",
        "| 라우팅 | **실행 결과** — `voisso.routing.route()` 실측. 점수·근거·확신도 그대로 |\n\n",
        "**P7에게**: 브라우저에서 실제 Web Speech 출력을 받으면 `__main__.py` 의 "
        "`DEMO_LINES` 세 번째 항목을 실측값으로 갈아끼우고 이 파일을 다시 생성하라. "
        "그러면 아래 표 전체가 실측이 된다.\n\n",
    ]

    for index, (label, dialect, stt) in enumerate(DEMO_LINES, 1):
        norm_stt = normalize(stt)
        norm_true = normalize(dialect)
        out.append(f"## {index}. {label}\n\n")
        out.append(f"- **어르신 발화(사투리)** — {dialect}\n")
        out.append(f"- **STT 예측** *(미검증)* — {stt}\n")
        out.append(f"- **정규화 결과** — {norm_stt}\n")
        if norm_true != norm_stt:
            out.append(f"- *(참고) 사투리 원문을 직접 정규화하면* — {norm_true}\n")

        routed_raw = _route(stt)
        routed_norm = _route(norm_stt)
        if routed_raw and routed_norm:
            out.append("\n| 라우팅 입력 | 배정 부서 | 점수 | 확신 |\n|---|---|---|---|\n")
            out.append(f"| STT 원문 그대로 | {routed_raw[0]} | {routed_raw[1]} | "
                       f"{'○' if routed_raw[3] else '×'} |\n")
            out.append(f"| **정규화 후** | **{routed_norm[0]}** | **{routed_norm[1]}** | "
                       f"{'○' if routed_norm[3] else '×'} |\n")
            if routed_norm[2]:
                out.append(f"\n배정 근거: `{routed_norm[2]}`\n")
            if routed_raw[0] != routed_norm[0]:
                out.append(f"\n> **정규화가 부서를 바꿨다.** "
                           f"{routed_raw[0]} → {routed_norm[0]}\n")
        else:
            out.append("\n> 라우팅 결과 없음 — `data/gb_departments.json` 이 필요하다.\n")
        out.append("\n")

    out.append("## 한계 — 우리가 복구하지 못하는 경우\n\n")
    out.append(
        "STT가 방언 낱말을 **소리 나는 대로** 받아쓰면 사전이 걸린다. 하지만 STT의 "
        "언어모델이 방언 낱말을 다른 표준어 낱말로 **바꿔 버리면** 표제어 자체가 사라져서 "
        "우리도 복구하지 못한다. 데모에서 이 점을 숨기지 않는 편이 낫다.\n\n"
    )
    out.append("| 원래 말 | STT가 이렇게 바꾸면 | 정규화 결과 | 왜 |\n|---|---|---|---|\n")
    for original, broken, why in UNRECOVERABLE:
        out.append(f"| {original} | {broken} | {normalize(broken)} | {why} |\n")
    out.append(
        "\n그래서 이 레이어의 전제는 **\"STT가 방언 음운을 그대로 받아쓴다\"** 이다. "
        "한국어 STT는 모르는 낱말을 대체로 소리 나는 대로 적으므로 이 전제는 웬만하면 "
        "성립하지만, 항상은 아니다. **P7의 브라우저 실측으로 확인해야 할 지점이 정확히 "
        "여기다.**\n\n"
    )
    out.append("## 기계 판독용\n\n")
    out.append("웹 UI에서 바로 쓸 수 있게 같은 내용을 JSON으로 붙인다.\n\n```json\n")
    payload = []
    for label, dialect, stt in DEMO_LINES:
        norm = normalize(stt)
        routed = _route(norm)
        payload.append({
            "label": label,
            "dialect": dialect,
            "stt_predicted": stt,
            "stt_is_verified": False,
            "normalized": norm,
            "department": routed[0] if routed else None,
            "score": routed[1] if routed else None,
            "evidence": routed[2] if routed else None,
            "confident": routed[3] if routed else None,
        })
    out.append(json.dumps(payload, ensure_ascii=False, indent=2))
    out.append("\n```\n")
    return "".join(out)


def _demo() -> None:
    print("\n어르신 발화 → 표준어  (normalize · STT 결과 교정)")
    print("=" * 78)
    for label, text in CALLER_SAMPLES:
        print(f"[{label}]\n  들린 말 : {text}\n  알아들음: {normalize(text)}\n")

    print("\n시스템 응답 → 경북 말투  (to_dialect · TTS 입력)")
    print("=" * 78)
    for label, text in AGENT_SAMPLES:
        print(f"[{label}]\n  표준어  : {text}\n  경북    : {to_dialect(text)}\n")


def _samples_markdown() -> str:
    out: list[str] = []
    out.append("# 변환 예시 30선\n")
    out.append(
        "> 이 파일은 `python -m voisso.dialect --samples` 로 **생성된다.** "
        "손으로 고치지 말고 사전을 고친 뒤 다시 생성하라.\n"
    )
    out.append(
        "> 아래는 손으로 지어낸 기대값이 아니라 **실제 실행 결과**다. "
        f"사전 규모: 어휘 {lexicon_size()}개 / 규칙 {rule_count()}개.\n"
    )
    out.append(
        "\n## 1. 어르신 발화 → 표준어 (`normalize`)\n\n"
        "STT가 사투리를 잘못 받아적은 결과를 교정한다. 이 출력이 라우팅·요약의 입력이 된다.\n\n"
        "| # | 상황 | 들린 말 (사투리) | 알아들은 말 (표준어) |\n|---|---|---|---|\n"
    )
    for i, (label, text) in enumerate(CALLER_SAMPLES, 1):
        out.append(f"| {i} | {label} | {text} | {normalize(text)} |\n")

    out.append(
        "\n## 2. 시스템 응답 → 경북 말투 (`to_dialect`)\n\n"
        "TTS에 넣기 전 단계다. 어미 변환이 체감 차이의 대부분이고, "
        "부서명·전화번호는 그대로 보존된다.\n\n"
        "| # | 상황 | 표준어 | 경북 말투 |\n|---|---|---|---|\n"
    )
    for i, (label, text) in enumerate(AGENT_SAMPLES, 16):
        out.append(f"| {i} | {label} | {text} | {to_dialect(text)} |\n")

    out.append("\n## 3. 왕복 보존\n\n")
    out.append(
        "`to_dialect` 로 만든 사투리를 `normalize` 로 되돌렸을 때 의미가 보존되는지 "
        "확인한 결과다. 통계는 `python -m voisso.dialect --roundtrip-report` 로 다시 낼 수 있다.\n\n"
    )
    out.append("| 표준어 | → 경북 | → 되돌림 |\n|---|---|---|\n")
    for _label, text in AGENT_SAMPLES[:8]:
        dialect = to_dialect(text)
        out.append(f"| {text} | {dialect} | {normalize(dialect)} |\n")
    return "".join(out)


def _roundtrip_report() -> int:
    try:
        from .tests.test_roundtrip import CORPUS, classify
    except ImportError:
        print("테스트 모듈을 찾을 수 없다.", file=sys.stderr)
        return 1

    counts: Counter[str] = Counter()
    failures: list[tuple[str, str, str]] = []
    for sentence in CORPUS:
        dialect = to_dialect(sentence)
        back = normalize(dialect)
        verdict = classify(sentence, back)
        counts[verdict] += 1
        if verdict == "fail":
            failures.append((sentence, dialect, back))

    total = len(CORPUS)
    print(f"왕복 보존 검사 — 표준어 문장 {total}개")
    print(f"  글자까지 동일 (exact)   : {counts['exact']:3d}  ({counts['exact'] / total:.1%})")
    print(f"  의미 보존   (semantic)  : {counts['semantic']:3d}  ({counts['semantic'] / total:.1%})")
    print(f"  실패        (fail)      : {counts['fail']:3d}")
    for original, dialect, back in failures:
        print(f"\n  ! {original}\n    → {dialect}\n    → {back}")
    return 1 if failures else 0


def _stats() -> None:
    print(f"어휘 {lexicon_size()}개 / 어미·문법 규칙 {rule_count()}개\n")

    print("도메인별 어휘")
    for domain, count in Counter(e.get("domain", "미분류") for e in entries()).most_common():
        print(f"  {domain:<12} {count:4d}")

    print("\n출처별 (어휘 + 규칙)")
    for prefix, count in source_counts().items():
        print(f"  {prefix:<12} {count:4d}")

    print("\n방향별 규칙")
    for direction, count in Counter(r.get("dir") for r in rules()).most_common():
        print(f"  {direction:<12} {count:4d}")

    print("\n재배포 금지 출처 항목: ", end="")
    from .core import restricted_entries
    offenders = restricted_entries()
    print(f"{len(offenders)}건" + (" — 저장소에서 걷어내야 한다!" if offenders else " (정상)"))


def _convert_one(text: str, direction: str, verbose: bool) -> None:
    result = to_dialect(text) if direction == "to_dialect" else normalize(text)
    print(result)
    if verbose:
        for hit in explain(text, direction):
            desc = f"  — {hit['desc']}" if hit["desc"] else ""
            print(f"  [{hit['kind']}] {hit['from']} → {hit['to']}{desc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m voisso.dialect",
        description="Voisso 경북 방언 레이어 — 사투리 ↔ 표준어 변환",
    )
    parser.add_argument("-d", "--to-dialect", metavar="TEXT", help="표준어 → 경북 사투리")
    parser.add_argument("-n", "--normalize", metavar="TEXT", help="사투리 → 표준어")
    parser.add_argument("--demo", action="store_true", help="민원 상황 변환 예시 실행")
    parser.add_argument("--samples", action="store_true", help="samples.md 내용 생성")
    parser.add_argument("--demo-lines", action="store_true", help="demo_lines.md 내용 생성")
    parser.add_argument("--roundtrip-report", action="store_true", help="왕복 보존 통과율")
    parser.add_argument("--stats", action="store_true", help="사전 규모·분포")
    parser.add_argument("-v", "--verbose", action="store_true", help="적용된 규칙을 함께 표시")
    args = parser.parse_args(argv)

    if args.to_dialect:
        _convert_one(args.to_dialect, "to_dialect", args.verbose)
    elif args.normalize:
        _convert_one(args.normalize, "to_standard", args.verbose)
    elif args.samples:
        print(_samples_markdown(), end="")
    elif args.demo_lines:
        print(_demo_lines_markdown(), end="")
    elif args.roundtrip_report:
        return _roundtrip_report()
    elif args.stats:
        _stats()
    elif args.demo:
        _demo()
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
