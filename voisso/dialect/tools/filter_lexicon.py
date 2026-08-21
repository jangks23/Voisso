# -*- coding: utf-8 -*-
"""출처 접두사로 사전 항목을 분리한다.

라이선스 결론이 바뀌어도 명령 한 줄로 대응하기 위한 도구다.

    # 재배포 가능한 항목만 뽑아 새 파일로 (aihub: 제외)
    python -m voisso.dialect.tools.filter_lexicon --exclude-source-prefix aihub: -o lexicon.public.json

    # 출처별 항목 수 집계 (문서·보고용)
    python -m voisso.dialect.tools.filter_lexicon --stats

현재 배포본에는 ``aihub:`` 항목이 **0개**라 이 명령은 아무것도 걷어내지 않는다.
나중에 급하게 손대지 않으려고 미리 넣어 둔 것이다. 배경은 ``../SOURCES.md`` 참조.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

LEXICON_PATH = Path(__file__).resolve().parent.parent / "lexicon.json"


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fp:
        return json.load(fp)


def split_by_prefix(data: dict, prefixes: tuple[str, ...]) -> tuple[dict, int]:
    """접두사에 걸리는 항목을 걷어낸 사전과, 걷어낸 개수를 돌려준다."""
    removed = 0
    result = dict(data)
    for key in ("entries", "rules"):
        kept = []
        for item in data.get(key, []):
            if str(item.get("source", "")).startswith(prefixes):
                removed += 1
            else:
                kept.append(item)
        result[key] = kept
    meta = dict(result.get("meta", {}))
    meta["entry_count"] = len(result.get("entries", []))
    meta["rule_count"] = len(result.get("rules", []))
    result["meta"] = meta
    return result, removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사전 항목을 출처 접두사로 분리")
    parser.add_argument("-i", "--input", type=Path, default=LEXICON_PATH)
    parser.add_argument("-o", "--output", type=Path,
                        help="결과를 쓸 경로. 생략하면 표준출력")
    parser.add_argument("--exclude-source-prefix", action="append", default=[],
                        metavar="PREFIX", help="걷어낼 출처 접두사 (예: aihub:)")
    parser.add_argument("--stats", action="store_true", help="출처별 항목 수만 출력")
    args = parser.parse_args(argv)

    try:
        data = load(args.input)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"사전을 읽지 못했다: {exc}", file=sys.stderr)
        return 1

    if args.stats:
        counts: Counter[str] = Counter()
        for key in ("entries", "rules"):
            for item in data.get(key, []):
                counts[str(item.get("source", "?")).split(":", 1)[0] + ":"] += 1
        width = max((len(k) for k in counts), default=1)
        for prefix, count in sorted(counts.items()):
            print(f"{prefix:<{width}}  {count:4d}")
        print(f"{'합계':<{width}}  {sum(counts.values()):4d}")
        return 0

    if not args.exclude_source_prefix:
        print("--exclude-source-prefix 또는 --stats 중 하나가 필요하다.", file=sys.stderr)
        return 2

    result, removed = split_by_prefix(data, tuple(args.exclude_source_prefix))
    text = json.dumps(result, ensure_ascii=False, indent=1) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"{args.output} 생성 — {removed}건 제외, "
              f"어휘 {result['meta']['entry_count']}개 / 규칙 {result['meta']['rule_count']}개",
              file=sys.stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
