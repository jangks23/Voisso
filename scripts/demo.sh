#!/usr/bin/env bash
#
# Voisso 원터치 데모 실행기.
#
#   ./scripts/demo.sh                # 데이터 준비 -> 서버 기동 -> 브라우저 열기
#   ./scripts/demo.sh --no-browser   # 브라우저는 열지 않는다 (원격/CI)
#   ./scripts/demo.sh --voice        # 음성(TTS)을 켠다 — 발표·촬영 전용
#
# 기본은 음성 없음이다. 타입캐스트는 종량제고 크레딧은 발표·촬영용이라
# 개발 중에 소진하면 안 된다 (계약서 5-D).
#
# 발표장 네트워크가 끊겨도 data/gb_departments.json 이 이미 있으면 데모는 돈다.
# 각 단계가 무엇을 하는지 화면에 출력한다. 실패하면 다음에 뭘 해야 하는지 알려준다.

set -uo pipefail

# 저장소 루트로 이동한다. 어디서 호출하든 동작해야 하므로 절대경로를 박지 않는다.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}" || exit 1

OPEN_BROWSER=1
ALLOW_TTS=0
for arg in "$@"; do
  case "${arg}" in
    --no-browser) OPEN_BROWSER=0 ;;
    --voice)      ALLOW_TTS=1 ;;
    -h|--help)
      sed -n '3,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "알 수 없는 옵션: ${arg}" >&2
      echo "사용법: ./scripts/demo.sh [--no-browser] [--voice]" >&2
      exit 1 ;;
  esac
done

# ── 출력 헬퍼 ────────────────────────────────────────────────────────
if [ -t 1 ]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; D=""; N=""
fi

step() { echo; echo "${B}[$1/7] $2${N}"; }
ok()   { echo "      ${G}✓${N} $*"; }
warn() { echo "      ${Y}!${N} $*"; }
info() { echo "      ${D}$*${N}"; }

# 실패는 항상 "무엇을 하면 되는지"와 함께 끝난다.
die() {
  echo >&2
  echo "${R}✗ 중단: $1${N}" >&2
  shift
  if [ "$#" -gt 0 ]; then
    echo >&2
    echo "  해결 방법:" >&2
    for line in "$@"; do echo "    ${line}" >&2; done
  fi
  echo >&2
  exit 1
}

echo "${B}Voisso 데모 실행기${N}  ${D}(${ROOT_DIR})${N}"

# ── 1. 파이썬 ────────────────────────────────────────────────────────
step 1 "파이썬 확인 — 3.10 이상이 필요하다"

PY=""
for candidate in ".venv/bin/python" ".venv/Scripts/python.exe" "python3" "python"; do
  if command -v "${candidate}" >/dev/null 2>&1 || [ -x "${candidate}" ]; then
    if "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PY="${candidate}"
      break
    fi
    [ -z "${PY_TOO_OLD:-}" ] && PY_TOO_OLD="$("${candidate}" -V 2>&1)"
  fi
done

if [ -z "${PY}" ]; then
  die "파이썬 3.10 이상을 찾지 못했다${PY_TOO_OLD:+ (발견된 버전: ${PY_TOO_OLD})}" \
      "macOS : brew install python@3.12" \
      "Ubuntu: sudo apt install python3.12 python3.12-venv" \
      "또는  : https://www.python.org/downloads/ 에서 설치" \
      "설치 후 이 스크립트를 다시 실행해라."
fi
case "${PY}" in .venv/*) info "가상환경 .venv 를 사용한다" ;; esac
ok "$("${PY}" -V 2>&1)  (${PY})"

# ── 2. 데이터 ────────────────────────────────────────────────────────
step 2 "부서 데이터 확인 — 없으면 경상북도청에서 수집한다"

DATA_JSON="data/gb_departments.json"

data_summary() {
  "${PY}" - "${DATA_JSON}" <<'PYEOF' 2>/dev/null
import json, sys
meta = json.load(open(sys.argv[1], encoding="utf-8"))["meta"]
print("수집일: %s · 부서 %s개 · 직원 %s명"
      % (meta.get("fetched_at", "?"),
         meta.get("department_count", "?"),
         meta.get("staff_count", "?")))
PYEOF
}

if [ -s "${DATA_JSON}" ] && SUMMARY="$(data_summary)" && [ -n "${SUMMARY}" ]; then
  ok "데이터 준비됨 (${SUMMARY})"
  info "다시 수집하려면: ${PY} scripts/scrape_gb_departments.py --refresh"
else
  warn "${DATA_JSON} 이 없다. 크롤러를 실행한다 (약 40초, 네트워크 필요)"
  if "${PY}" scripts/scrape_gb_departments.py; then
    SUMMARY="$(data_summary)"
    ok "수집 완료 (${SUMMARY:-요약 없음})"
  else
    # 네트워크가 끊긴 발표장을 상정한 경로다. 가짜 데이터를 몰래 물리지 않는다.
    die "부서 데이터를 수집하지 못했다 (네트워크 또는 원본 사이트 문제)" \
        "1) 네트워크를 확인하고 다시 실행해라." \
        "2) 다른 PC에 data/gb_departments.json 이 있으면 복사해 와라." \
        "3) 급하면 합성 샘플로 화면만 볼 수 있다 (가상 부서라 실제 라우팅은 무의미):" \
        "     VOISSO_DATA_FILE=mcp_server/fixtures/sample_departments.json ${PY} -m server"
  fi
fi

# ── 3. .env ──────────────────────────────────────────────────────────
step 3 "환경변수 파일 확인 — 키가 없어도 텍스트 모드로 돈다"

if [ -f .env ]; then
  ok ".env 이미 있음"
elif [ -f .env.example ]; then
  cp .env.example .env && ok ".env.example 을 .env 로 복사했다"
  info "API 키가 비어 있으면 음성·LLM 없이 텍스트 모드로 동작한다"
else
  warn ".env 도 .env.example 도 없다 — 기본값으로 진행한다"
fi

# ── 4. 의존성 ────────────────────────────────────────────────────────
step 4 "의존성 확인 — fastapi / uvicorn / anthropic"

MISSING="$("${PY}" - <<'PYEOF'
import importlib.util
missing = [m for m in ("fastapi", "uvicorn", "anthropic")
           if importlib.util.find_spec(m) is None]
print(" ".join(missing))
PYEOF
)"

if [ -n "${MISSING// /}" ]; then
  # 임의로 pip install 하지 않는다. 남의 환경을 말없이 바꾸면 안 된다.
  die "필요한 패키지가 없다: ${MISSING}" \
      "아래를 그대로 실행한 뒤 이 스크립트를 다시 돌려라." \
      "" \
      "  python3 -m venv .venv" \
      "  source .venv/bin/activate        # Windows: .venv\\Scripts\\activate" \
      "  pip install -r requirements.txt"
fi
ok "설치 확인됨 (fastapi, uvicorn, anthropic)"

# ── 5. 서버 ──────────────────────────────────────────────────────────
step 5 "API 서버 기동 — 이미 떠 있으면 그걸 쓴다"

read_env() {  # .env 에서 값 하나 읽기 (없으면 기본값)
  local key="$1" default="$2" value=""
  [ -f .env ] && value="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" .env | tail -1 | tr -d '"'\''' | tr -d '\r')"
  echo "${!key:-${value:-${default}}}"
}

HOST="$(read_env VOISSO_HOST 127.0.0.1)"
PORT="$(read_env VOISSO_PORT 8000)"

# 8111 은 사용자 미리보기 전용이다. 바인딩도 종료도 하지 않는다.
if [ "${PORT}" = "8111" ]; then
  die "포트 8111 은 사용자 미리보기 전용이라 쓸 수 없다" \
      "다른 포트를 지정해라:" \
      "  VOISSO_PORT=8020 ./scripts/demo.sh"
fi
# 0.0.0.0 은 접속용 주소가 아니다. 브라우저에는 루프백을 준다.
BROWSER_HOST="${HOST}"
[ "${HOST}" = "0.0.0.0" ] && BROWSER_HOST="127.0.0.1"
BASE_URL="http://${BROWSER_HOST}:${PORT}"
LOG_FILE="${TMPDIR:-/tmp}/voisso-demo.log"

health() {  # 응답하면 0, 아니면 1
  "${PY}" - "${BASE_URL}/api/health" <<'PYEOF' 2>/dev/null
import json, sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as res:
        body = json.load(res)
except Exception:
    sys.exit(1)
if body.get("status") != "ok":
    sys.exit(1)


def label(section, *keys, depth=2):
    """상태 블록에서 사람이 읽을 한 단어를 뽑는다.

    agent 처럼 한 단계 더 중첩된 구조({"engine": {"primary": ...}})도 따라간다.
    필드 구조가 바뀌어도 데모가 깨지지 않게 실패는 "?" 로만 끝낸다.
    """
    if not isinstance(section, dict):
        return str(section or "?")
    for key in keys:
        value = section.get(key)
        if isinstance(value, str) and value:
            return value
    if depth > 0:
        for value in section.values():
            if isinstance(value, dict):
                found = label(value, *keys, depth=depth - 1)
                if found != "?":
                    return found
    return "?"


print("STT %s · TTS %s · 대화엔진 %s"
      % (label(body.get("stt"), "provider"),
         label(body.get("tts"), "provider"),
         label(body.get("agent"), "primary", "engine", "provider")))
PYEOF
}

SERVER_PID=""
STARTED_BY_US=0

# 정리 대상은 **이 스크립트가 띄운 PID 하나뿐**이다.
# 포트로 프로세스를 찾아 죽이면(lsof | xargs kill) 남이 보고 있는 서버를 끊게 된다.
cleanup() {
  if [ "${STARTED_BY_US}" = "1" ] && [ -n "${SERVER_PID}" ] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo
    echo "${D}서버를 정리한다 (PID ${SERVER_PID})…${N}"
    kill "${SERVER_PID}" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "${SERVER_PID}" 2>/dev/null || break
      sleep 0.3
    done
    kill -9 "${SERVER_PID}" 2>/dev/null
    echo "${D}종료됨.${N}"
  fi
}
trap cleanup EXIT INT TERM

if [ "${PORT}" = "8000" ]; then
  info "8000 은 데모용 공용 포트다. 개발·테스트로 띄울 때는 VOISSO_PORT 로 자기 포트를 써라."
fi

if STATUS="$(health)"; then
  ok "${BASE_URL} 에 서버가 이미 떠 있다 — 중복 기동하지 않는다"
  info "${STATUS}"
  info "이 서버는 스크립트를 종료해도 계속 돈다"
else
  # 계약서 5-D — 기본은 음성 없음. .env 의 typecast 설정을 그대로 태우면
  # 데모를 띄울 때마다 발표용 크레딧이 깎인다. --voice 로만 연다.
  if [ "${ALLOW_TTS}" = "1" ]; then
    TTS_ENV=""
    warn "음성(TTS)을 켠다 — 타입캐스트 크레딧이 소모된다 (발표·촬영용)"
  else
    TTS_ENV="VOISSO_TTS_PROVIDER=none"
    info "음성 없이 띄운다 (계약서 5-D). 발표·촬영 때는 --voice 를 붙여라."
  fi
  info "기동 명령: ${TTS_ENV} ${PY} -m server --host ${HOST} --port ${PORT}"
  info "로그 파일: ${LOG_FILE}"
  : > "${LOG_FILE}"
  if [ "${ALLOW_TTS}" = "1" ]; then
    "${PY}" -m server --host "${HOST}" --port "${PORT}" >>"${LOG_FILE}" 2>&1 &
  else
    VOISSO_TTS_PROVIDER=none \
      "${PY}" -m server --host "${HOST}" --port "${PORT}" >>"${LOG_FILE}" 2>&1 &
  fi
  SERVER_PID=$!
  STARTED_BY_US=1

  STATUS=""
  for _ in $(seq 1 60); do          # 최대 30초 대기
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
      echo >&2
      echo "${R}서버 프로세스가 죽었다. 로그 마지막 20줄:${N}" >&2
      tail -20 "${LOG_FILE}" >&2
      die "서버가 기동하지 못했다" \
          "· 포트 ${PORT} 를 이미 다른 프로그램이 쓰고 있을 수 있다:" \
          "    lsof -i :${PORT}          # 쓰는 프로세스 확인" \
          "    VOISSO_PORT=8020 ./scripts/demo.sh   # 다른 포트로 실행" \
          "· 전체 로그: ${LOG_FILE}"
    fi
    if STATUS="$(health)"; then break; fi
    STATUS=""
    sleep 0.5
  done

  if [ -z "${STATUS}" ]; then
    echo >&2
    echo "${R}헬스체크 응답이 없다. 로그 마지막 20줄:${N}" >&2
    tail -20 "${LOG_FILE}" >&2
    die "서버가 30초 안에 뜨지 않았다" \
        "· 전체 로그: ${LOG_FILE}" \
        "· 직접 띄워서 오류를 확인해라: ${PY} -m server" \
        "· 포트 충돌이면: VOISSO_PORT=8020 ./scripts/demo.sh"
  fi
  ok "기동 완료 (PID ${SERVER_PID})"
  info "${STATUS}"
fi

# ── 6. 브라우저 ──────────────────────────────────────────────────────
step 6 "데모 화면 열기 — 통화 화면과 담당자 대시보드"

CALL_URL="${BASE_URL}/call"
DASH_URL="${BASE_URL}/dashboard"

open_url() {
  case "$(uname -s)" in
    Darwin)                  open "$1" >/dev/null 2>&1 ;;
    Linux)                   xdg-open "$1" >/dev/null 2>&1 ;;
    MINGW*|MSYS*|CYGWIN*)    start "" "$1" >/dev/null 2>&1 ;;
    *)                       return 1 ;;
  esac
}

if [ "${OPEN_BROWSER}" = "1" ]; then
  if open_url "${CALL_URL}"; then
    sleep 1                     # 탭 두 개가 같은 창에 뜨도록 잠깐 둔다
    open_url "${DASH_URL}"
    ok "브라우저에서 두 화면을 열었다"
  else
    warn "브라우저를 자동으로 열지 못했다 — 아래 주소를 직접 열어라"
  fi
else
  ok "--no-browser 지정 — 자동으로 열지 않는다"
fi

# ── 7. 안내 ──────────────────────────────────────────────────────────
step 7 "준비 완료"

cat <<EOF

  ${B}통화 화면${N}     ${CALL_URL}
  ${B}담당자 대시보드${N} ${DASH_URL}
  ${D}API 문서       ${BASE_URL}/docs
  헬스체크       ${BASE_URL}/api/health${N}

EOF

if [ "${STARTED_BY_US}" = "1" ]; then
  echo "  ${B}Ctrl+C${N} 를 누르면 서버를 정리하고 종료한다."
  echo
  wait "${SERVER_PID}"
else
  echo "  ${D}기존 서버를 재사용했으므로 종료하지 않는다.${N}"
  echo
fi
