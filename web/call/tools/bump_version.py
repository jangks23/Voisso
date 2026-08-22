#!/usr/bin/env python3
"""정적 자산 버전을 한 번에 올린다 (브라우저 캐시 무효화).

    python3 web/call/tools/bump_version.py          # 자동으로 +1
    python3 web/call/tools/bump_version.py 12       # 특정 값으로

왜 필요한가:
  통화 UI 는 빌드 스텝이 없어 파일명이 항상 같다(config.js, app.js …).
  브라우저가 옛 파일을 캐시하고 있으면 서버 코드를 아무리 고쳐도 화면이 그대로다.
  실제로 발표 준비 중에 옛 config.js 때문에 API 주소가 반영되지 않는 사고가 있었다.
  태그에 ?v=N 을 붙이고 이 스크립트로 N 을 올리면 브라우저가 반드시 새로 받는다.

배포/발표 전에 자산을 고쳤다면 이걸 한 번 돌려라. HTML 자체의 캐시는 서버가
no-store 로 막는다(server/ 담당).
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CALL = HERE.parent
TARGETS = ["index.html", "stt-check.html"]
ASSET = re.compile(r'(?P<attr>(?:src|href)=")(?P<file>[\w.\-/]+\.(?:js|css))(?:\?v=\d+)?(?P<end>")')
MARK = re.compile(r"(<!-- ASSET_VERSION = )(\d+)( -->)")


def current_version() -> int:
    m = MARK.search((CALL / "index.html").read_text(encoding="utf-8"))
    return int(m.group(2)) if m else 0


def main() -> int:
    new = int(sys.argv[1]) if len(sys.argv) > 1 else current_version() + 1
    for name in TARGETS:
        p = CALL / name
        if not p.exists():
            continue
        s = p.read_text(encoding="utf-8")
        s, n = ASSET.subn(lambda m: f'{m.group("attr")}{m.group("file")}?v={new}{m.group("end")}', s)
        if MARK.search(s):
            s = MARK.sub(rf"\g<1>{new}\g<3>", s)
        else:
            s = s.replace("<head>", f"<head>\n<!-- ASSET_VERSION = {new} -->", 1)
        s = re.sub(r"(VOISSO_ASSET_VERSION\s*=\s*')(\d+)(')", rf"\g<1>{new}\g<3>", s)
        p.write_text(s, encoding="utf-8")
        print(f"  {name}: 자산 {n}개 → ?v={new}")
    print(f"자산 버전 {new} 로 갱신했다. 브라우저는 캐시를 비우지 않아도 새로 받는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
