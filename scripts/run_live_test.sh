#!/usr/bin/env bash
set -euo pipefail

# Live CTP quick runner: loads only CTP_* from .env, then runs
# 1) connection smoke, 2) bridge smoke, 3) live integration test.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
DURATION="${DURATION:-30}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
SMOKE_ONLY="${SMOKE_ONLY:-0}"
TEST_ONLY="${TEST_ONLY:-0}"
WITH_COV="${WITH_COV:-0}"
SYMBOL="${SYMBOL:-}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  -e, --env-file <path>     Path to .env (default: ${ENV_FILE})
  -d, --duration <seconds>  Bridge smoke duration (default: ${DURATION})
  -l, --log-level <level>   Connect smoke log level (default: ${LOG_LEVEL})
  -s, --symbol <vt_symbol>  Override CTP_SYMBOL (e.g., rb2510.SHFE)
      --smoke-only          Run smokes only (skip pytest)
      --test-only           Run pytest only (skip smokes)
      --with-cov            Keep coverage gate for pytest (default: off)
  -h, --help                Show this help

Examples:
  ${0} --duration 45 --symbol rb2510.SHFE
  ${0} --test-only
USAGE
}

load_ctp_env() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "[run_live_test] env file not found: $file" >&2
    exit 1
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ ! "$line" =~ ^CTP_ ]] && continue
    local key="${line%%=*}"
    local val="${line#*=}"
    key="$(echo -n "$key" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    val="$(echo -n "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    # strip surrounding single/double quotes if present
    if [[ ( "$val" == \"*\" && "$val" == *\" ) || ( "$val" == '"'*'"' && "$val" == *'"' ) ]]; then
      val="${val:1:-1}"
    fi
    # Do not override if already set in environment
    if [[ -z "${!key-}" ]]; then
      export "$key=$val"
    fi
  done < "$file"
}

# Parse args
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--env-file) ENV_FILE="$2"; shift 2;;
    -d|--duration) DURATION="$2"; shift 2;;
    -l|--log-level) LOG_LEVEL="$2"; shift 2;;
    -s|--symbol) SYMBOL="$2"; shift 2;;
    --smoke-only) SMOKE_ONLY=1; shift;;
    --test-only) TEST_ONLY=1; shift;;
    --with-cov) WITH_COV=1; shift;;
    -h|--help) usage; exit 0;;
    *) ARGS+=("$1"); shift;;
  esac
done
set -- "${ARGS[@]:-}"

echo "[run_live_test] Loading CTP_* from: ${ENV_FILE}"
load_ctp_env "${ENV_FILE}"

if [[ -n "${SYMBOL}" ]]; then
  export CTP_SYMBOL="${SYMBOL}"
fi

if [[ "${TEST_ONLY}" != "1" ]]; then
  echo "== Connect smoke (20s) =="
  uv run python "${ROOT_DIR}/scripts/ctp_connect_smoke.py" --duration 20 --log-level "${LOG_LEVEL}"

  echo "== Bridge smoke (${DURATION}s) =="
  DURATION_SECONDS="${DURATION}" uv run python "${ROOT_DIR}/scripts/ctp_bridge_smoke.py"
fi

if [[ "${SMOKE_ONLY}" != "1" ]]; then
  echo "== Live integration test =="
  if [[ "${WITH_COV}" == "1" ]]; then
    CTP_LIVE=1 uv run pytest -q "${ROOT_DIR}/tests/integration/test_ctp_live_adapter.py::test_ctp_live_tick_flow"
  else
    CTP_LIVE=1 uv run pytest -q --no-cov "${ROOT_DIR}/tests/integration/test_ctp_live_adapter.py::test_ctp_live_tick_flow"
  fi
fi

echo "[run_live_test] Done."
