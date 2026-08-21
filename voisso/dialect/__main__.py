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
