"""`python3 -m server` 로 서버를 띄운다.

동등한 명령: `uvicorn server.main:app --reload`
"""

from __future__ import annotations

import argparse

from . import config


def main() -> None:
    config.load_dotenv()

    parser = argparse.ArgumentParser(prog="python3 -m server", description="Voisso API 서버")
    parser.add_argument("--host", default=config.HOST, help=f"기본 {config.HOST}")
    parser.add_argument("--port", type=int, default=config.PORT, help=f"기본 {config.PORT}")
    parser.add_argument("--reload", action="store_true", help="코드 변경 시 자동 재시작")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run("server.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
