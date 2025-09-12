#!/usr/bin/env bash
set -euo pipefail

# Start LIVE ingest (CTP → Adapter → NATS) for a bounded duration.
#
# Usage:
#   ./scripts/start_live_ingest.sh -d 30 -n nats://localhost:4222
#   SYMBOL=rb2510.SHFE ./scripts/start_live_ingest.sh -d 60
#
# Reads CTP_* and NATS_* from .env by default (repo root), unless already set.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
DURATION="${DURATION:-30}"
NATS_URL_ARG="${NATS_URL:-nats://localhost:4222}"
SYMBOL="${SYMBOL:-}"
CONNECTOR="${CTP_GATEWAY_CONNECT:-src.infrastructure.ctp_live_connector:live_gateway_connect}"
START_NATS="${START_NATS:-1}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  -e, --env-file <path>     Path to .env (default: ${ENV_FILE})
  -d, --duration <seconds>  Run duration (default: ${DURATION})
  -s, --symbol <vt_symbol>  Override CTP_SYMBOL (e.g., rb2510.SHFE)
  -n, --nats-url <url>      NATS URL (default: ${NATS_URL_ARG})
  --no-nats                 Do not start NATS container automatically
  -h, --help                Show this help
USAGE
}

load_env_keys() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# || "$line" != *=* ]] && continue
    local key="${line%%=*}"; key="${key## }"; key="${key%% }"
    local val="${line#*=}"; val="${val## }"; val="${val%% }"
    # strip quotes
    if [[ ( "$val" == \"*\" && "$val" == *\" ) || ( "$val" == '"'*'"' && "$val" == *'"' ) ]]; then
      val="${val:1:-1}"
    fi
    case "$key" in
      CTP_*|NATS_USER|NATS_PASSWORD|NATS_URL)
        if [[ -z "${!key-}" ]]; then
          export "$key=$val"
        fi
        ;;
    esac
  done < "$file"
}

# Parse args
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--env-file) ENV_FILE="$2"; shift 2;;
    -d|--duration) DURATION="$2"; shift 2;;
    -s|--symbol) SYMBOL="$2"; shift 2;;
    -n|--nats-url) NATS_URL_ARG="$2"; shift 2;;
    --no-nats) START_NATS=0; shift;;
    -h|--help) usage; exit 0;;
    *) ARGS+=("$1"); shift;;
  esac
done
set -- "${ARGS[@]:-}"

echo "[start_live_ingest] Loading env from: ${ENV_FILE}"
load_env_keys "${ENV_FILE}"

if [[ -n "${SYMBOL}" ]]; then
  export CTP_SYMBOL="${SYMBOL}"
fi
if [[ -z "${CTP_SYMBOL-}" ]]; then
  echo "[start_live_ingest] ERROR: CTP_SYMBOL not set (vt_symbol required)" >&2
  exit 2
fi
export CTP_GATEWAY_CONNECT="${CONNECTOR}"

export NATS_URL="${NATS_URL_ARG}"

if [[ "${START_NATS}" == "1" ]]; then
  echo "[start_live_ingest] Ensuring NATS is running..."
  (cd "${ROOT_DIR}" && docker compose up -d nats > /dev/null)
  sleep 2
fi

echo "[start_live_ingest] Running ingest for ${DURATION}s with CTP_SYMBOL=${CTP_SYMBOL}"
MD_RUN_INGEST=1 MD_DURATION_SECONDS="${DURATION}" \
  uv run python -m src.main

echo "[start_live_ingest] Done."
