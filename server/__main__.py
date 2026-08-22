"""`python3 -m server` 로 서버를 띄운다.

동등한 명령: `uvicorn server.main:app --reload`

## 개발용으로 띄울 때 (계약서 5-D)

에이전트·개발자가 자기 테스트 서버를 띄울 때는 **사용자 데모와 분리**해야 한다.

    python3 -m server --port 8023 --sandbox

`--sandbox` 는 두 가지를 한 번에 한다.

- `VOISSO_TTS_PROVIDER=none` — 타입캐스트 음성을 만들지 않는다.
  크레딧은 발표·촬영용이고, 개발 중 테스트로 소진하면 정작 시연 때 음성이 안 나온다.
- `VOISSO_DATA_DIR=/tmp/voisso-<포트>` — 민원카드·핸드오프·콜백을 임시 디렉터리에
  쓴다. 부서 데이터(gb_departments.json)는 저장소 것을 링크해 그대로 읽는다.

이걸 안 쓰면 `data/complaints/` 에 테스트 민원이 쌓여 발표 화면에 섞인다.
실제로 그렇게 됐다.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import config

# 사용자 미리보기 전용 포트. 여기는 실데이터·실음성으로 떠야 한다.
PREVIEW_PORT = 8111


def _prepare_sandbox(port: int) -> Path:
    """포트별 임시 데이터 디렉터리를 만들고 부서 데이터를 링크한다."""
    sandbox = Path(f"/tmp/voisso-{port}")
    sandbox.mkdir(parents=True, exist_ok=True)

    # 부서 데이터는 읽기 전용이라 링크로 충분하다. 복사하면 갱신을 놓친다.
    for name in ("gb_departments.json", "gb_departments.csv"):
        source = config.ROOT_DIR / "data" / name
        if not source.is_file():
            continue
        link = sandbox / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(source)

    # private/phone_map.json 이 있으면 그것도 링크한다.
    private = config.ROOT_DIR / "data" / "private"
    if private.is_dir():
        link = sandbox / "private"
        if link.is_symlink() or link.exists():
            if link.is_symlink():
                link.unlink()
        if not link.exists():
            link.symlink_to(private, target_is_directory=True)

    os.environ["VOISSO_DATA_DIR"] = str(sandbox)
    os.environ["VOISSO_TTS_PROVIDER"] = "none"

    # config 는 import 시점에 경로를 확정한다. 이미 불러온 뒤라 환경변수만
    # 바꿔서는 늦다 — 파생 경로를 직접 갱신한다.
    # (uvicorn 이 server.main 을 나중에 import 하므로 이 값이 그대로 쓰인다)
    config.DATA_DIR = sandbox
    config.COMPLAINTS_DIR = sandbox / "complaints"
    config.HANDOFFS_DIR = sandbox / "handoffs"
    config.CALLBACKS_DIR = sandbox / "callbacks"
    return sandbox


def main() -> None:
    config.load_dotenv()

    parser = argparse.ArgumentParser(prog="python3 -m server", description="Voisso API 서버")
    parser.add_argument("--host", default=config.HOST, help=f"기본 {config.HOST}")
    parser.add_argument("--port", type=int, default=config.PORT, help=f"기본 {config.PORT}")
    parser.add_argument("--reload", action="store_true", help="코드 변경 시 자동 재시작")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="개발용: 음성 끄고 데이터를 /tmp/voisso-<포트> 로 분리한다",
    )
    args = parser.parse_args()

    if args.sandbox:
        sandbox = _prepare_sandbox(args.port)
        print(f"[sandbox] 데이터 {sandbox} · 음성 생성 없음")
    elif args.port != PREVIEW_PORT:
        # 데모 데이터를 오염시키기 직전이다. 조용히 넘어가면 안 된다.
        print(
            f"[경고] --sandbox 없이 포트 {args.port} 로 뜹니다. "
            f"민원카드가 {config.DATA_DIR} 에 쌓여 발표 화면에 섞입니다.\n"
            f"        개발용이면 --sandbox 를 붙이세요."
        )

    import uvicorn

    uvicorn.run("server.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
