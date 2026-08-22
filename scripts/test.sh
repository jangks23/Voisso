#!/usr/bin/env bash
#
# Voisso 통합 테스트 러너 — 흩어진 스위트를 한 명령으로 돌린다.
#
#   ./scripts/test.sh              # 외부 API 를 부르지 않는 검사 전부
#   ./scripts/test.sh --ci         # CI 모드: 네트워크·실데이터·키 의존 전부 제외
#   ./scripts/test.sh --network    # 실제 크롤링까지 포함 (네트워크 필요)
#   ./scripts/test.sh --live       # 외부 API 실호출 포함 (TTS 크레딧 소모 — 계약서 5-D)
#   ./scripts/test.sh -v           # 통과한 스위트의 출력까지 전부 보여준다
#
# 키가 없어서 못 도는 검사는 실패가 아니라 "건너뜀"이다. 하나라도 실패하면 1 로 끝난다.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}" || exit 1

CI_MODE=0
WITH_NETWORK=0
VERBOSE=0
WITH_LIVE=0
for arg in "$@"; do
  case "${arg}" in
    --ci)          CI_MODE=1 ;;
    --network)     WITH_NETWORK=1 ;;
    --live)        WITH_LIVE=1 ;;
    -v|--verbose)  VERBOSE=1 ;;
    -h|--help)
      sed -n '3,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "알 수 없는 옵션: ${arg}" >&2
      echo "사용법: ./scripts/test.sh [--ci] [--network] [--live] [-v]" >&2
      exit 1 ;;
  esac
done

if [ -t 1 ]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; D=""; N=""
fi

# ── 파이썬 고르기 (demo.sh 와 같은 규칙) ─────────────────────────────
PY=""
for candidate in ".venv/bin/python" ".venv/Scripts/python.exe" "python3" "python"; do
  if command -v "${candidate}" >/dev/null 2>&1 || [ -x "${candidate}" ]; then
    if "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PY="${candidate}"; break
    fi
  fi
done
[ -z "${PY}" ] && { echo "${R}파이썬 3.10 이상을 찾지 못했다.${N}" >&2; exit 1; }

LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/voisso-test.XXXXXX")"
trap 'rm -rf "${LOG_DIR}"' EXIT

# 한글은 1글자가 화면에서 2칸을 차지한다. %-28s 는 바이트/글자 기준이라 열이 어긋난다.
pad_to() {
  local text="$1" width="$2" ascii wide disp pad
  ascii="${text//[^ -~]/}"
  wide=$(( ${#text} - ${#ascii} ))
  disp=$(( ${#text} + wide ))
  pad=$(( width - disp ))
  printf '%s' "${text}"
  [ "${pad}" -gt 0 ] && printf '%*s' "${pad}" ''
}

PASSED=0; FAILED=0; SKIPPED=0; SUITE_NO=0
FAILED_NAMES=()

# 스위트 하나를 돌리고 한 줄로 요약한다.
#   run_suite <이름> <명령...>
run_suite() {
  local name="$1"; shift
  SUITE_NO=$((SUITE_NO + 1))
  local log="${LOG_DIR}/suite-${SUITE_NO}.log"
  local start end elapsed code

  printf "  "; pad_to "${name}" 30; printf " "
  start=$(date +%s)
  "$@" >"${log}" 2>&1
  code=$?
  end=$(date +%s)
  elapsed=$((end - start))

  # live_checks 는 "키가 없어 전부 건너뜀" 을 3 으로 알린다.
  if [ "${code}" = "3" ]; then
    local reason
    reason="$(grep -m1 '건너뛰었습니다' "${log}" || echo "실행 조건 미충족")"
    echo "${Y}SKIP${N}  ${D}${reason}${N}"
    SKIPPED=$((SKIPPED + 1))
    [ "${VERBOSE}" = "1" ] && sed 's/^/        /' "${log}"
    return 0
  fi

  if [ "${code}" = "0" ]; then
    echo "${G}PASS${N}  ${D}(${elapsed}s)${N}"
    PASSED=$((PASSED + 1))
    [ "${VERBOSE}" = "1" ] && sed 's/^/        /' "${log}"
    return 0
  fi

  echo "${R}FAIL${N}  ${D}(${elapsed}s, exit ${code})${N}"
  FAILED=$((FAILED + 1))
  FAILED_NAMES+=("${name}")
  echo "${D}        ── 출력 마지막 20줄 ──${N}"
  tail -20 "${log}" | sed 's/^/        /'
  echo
  return 0
}

# 실행 조건이 안 맞아 건너뛰는 스위트. 왜 건너뛰는지 반드시 남긴다.
skip_suite() {
  printf "  "; pad_to "$1" 30; printf " "
  echo "${Y}SKIP${N}  ${D}$2${N}"
  SKIPPED=$((SKIPPED + 1))
}

echo "${B}Voisso 통합 테스트${N}  ${D}($("${PY}" -V 2>&1), ${PY})${N}"
[ "${CI_MODE}" = "1" ] && echo "${D}CI 모드 — 네트워크·실데이터·API 키 의존 스위트는 건너뛴다${N}"
echo

# ── 키 없이 도는 스위트 ──────────────────────────────────────────────
echo "${B}키 없이 도는 검사${N}"

run_suite "크롤러 파싱 회귀" \
  "${PY}" -m unittest scripts.tests.test_scraper_parsing

if [ -d voisso/dialect/tests ]; then
  run_suite "방언 변환" \
    "${PY}" -m unittest discover -s voisso/dialect/tests -t .
else
  skip_suite "방언 변환" "voisso/dialect/tests 없음"
fi

if [ -f server/selftest.py ]; then
  run_suite "통화 전 과정 (키 0개)" "${PY}" -m server.selftest
else
  skip_suite "통화 전 과정 (키 0개)" "server/selftest.py 없음"
fi

if [ -f mcp_server/selftest.py ]; then
  run_suite "MCP 서버 (합성 샘플)" "${PY}" -m mcp_server.selftest
else
  skip_suite "MCP 서버 (합성 샘플)" "mcp_server/selftest.py 없음"
fi

# ── 수집된 실데이터가 있어야 도는 스위트 ─────────────────────────────
echo
echo "${B}수집 데이터가 필요한 검사${N}"

if [ "${CI_MODE}" = "1" ]; then
  skip_suite "MCP 라우팅 (실데이터)" "CI 모드 — 저장소에 실데이터를 커밋하지 않는다"
elif [ ! -s data/gb_departments.json ]; then
  skip_suite "MCP 라우팅 (실데이터)" "data/gb_departments.json 없음 — scripts/scrape_gb_departments.py 로 수집"
elif [ ! -f mcp_server/selftest.py ]; then
  skip_suite "MCP 라우팅 (실데이터)" "mcp_server/selftest.py 없음"
else
  run_suite "MCP 라우팅 (실데이터)" "${PY}" -m mcp_server.selftest --real-data
fi

# ── 네트워크가 필요한 스위트 ─────────────────────────────────────────
echo
echo "${B}네트워크가 필요한 검사${N}"

if [ "${CI_MODE}" = "1" ]; then
  skip_suite "크롤러 실수집 + 검증게이트" "CI 모드 — 도청 서버에 요청하지 않는다"
elif [ "${WITH_NETWORK}" != "1" ]; then
  skip_suite "크롤러 실수집 + 검증게이트" "기본 제외 — 포함하려면 --network"
else
  run_suite "크롤러 실수집 + 검증게이트" "${PY}" scripts/scrape_gb_departments.py
fi

# ── API 키가 있을 때만 도는 스위트 ───────────────────────────────────
echo
echo "${B}API 키가 필요한 검사${N}"

# 계약서 5-D — 개발 중 음성 생성 금지. 타입캐스트는 종량제고 크레딧은 발표·촬영용이다.
# 이 스위트가 기본으로 돌면 테스트를 한 번 돌릴 때마다 음성이 합성된다. 실제로 그렇게
# 크레딧이 한 번 소진됐다. 이제 --live 로 명시해야만 외부 API 를 부른다.
if [ "${CI_MODE}" = "1" ]; then
  skip_suite "라이브 API (TTS/STT/LLM)" "CI 모드 — 시크릿을 요구하지 않는다"
elif [ "${WITH_LIVE}" != "1" ]; then
  skip_suite "라이브 API (TTS/STT/LLM)" "기본 제외 (계약서 5-D 비용 규칙) — 포함하려면 --live"
else
  run_suite "라이브 API (TTS/STT/LLM)" "${PY}" -m scripts.tests.live_checks --allow-tts
fi

# ── 요약 ─────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────"
if [ "${FAILED}" -gt 0 ]; then
  echo "${R}${B}실패${N}  통과 ${PASSED} · ${R}실패 ${FAILED}${N} · 건너뜀 ${SKIPPED}"
  echo
  echo "  실패한 스위트:"
  for name in "${FAILED_NAMES[@]}"; do echo "    · ${name}"; done
  echo
  echo "  ${D}개별 실행: ${PY} -m unittest scripts.tests.test_scraper_parsing -v${N}"
  exit 1
fi
echo "${G}${B}전부 통과${N}  통과 ${PASSED} · 실패 0 · 건너뜀 ${SKIPPED}"
if [ "${SKIPPED}" -gt 0 ]; then
  echo "${D}  건너뛴 항목은 실행 조건(키·네트워크·수집 데이터)이 없어서다. 실패가 아니다.${N}"
fi
exit 0
