#!/usr/bin/env bash
set -euo pipefail

# Live ingest verification against local NATS and LIVE CTP
# - Starts/ensures NATS container is up
# - Subscribes to market.tick.> and prints a few samples
# - Runs ingest for a bounded duration using vt_symbol (CTP_SYMBOL)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
DURATION="${DURATION:-20}"
NATS_URL_ARG="${NATS_URL:-nats://localhost:4222}"
SYMBOL="${SYMBOL:-}"
CONNECTOR="${CTP_GATEWAY_CONNECT:-}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  -e, --env-file <path>     Path to .env (default: ${ENV_FILE})
  -d, --duration <seconds>  Ingest run duration (default: ${DURATION})
  -s, --symbol <vt_symbol>  Override CTP_SYMBOL (e.g., rb2510.SHFE)
  -n, --nats-url <url>      NATS URL for both subscriber and ingest (default: ${NATS_URL_ARG})
  -h, --help                Show this help

This will:
  1) docker compose up -d nats
  2) launch a Python subscriber for market.tick.>
  3) run live ingest for <duration> seconds
  4) print a short sample output from both
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

# Parse CLI
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--env-file) ENV_FILE="$2"; shift 2;;
    -d|--duration) DURATION="$2"; shift 2;;
    -s|--symbol) SYMBOL="$2"; shift 2;;
    -n|--nats-url) NATS_URL_ARG="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) ARGS+=("$1"); shift;;
  esac
done
set -- "${ARGS[@]:-}"

echo "[live_ingest_verify] Loading env from: ${ENV_FILE}"
load_env_keys "${ENV_FILE}"

# Resolve symbol and connector
if [[ -n "${SYMBOL}" ]]; then
  export CTP_SYMBOL="${SYMBOL}"
fi
if [[ -z "${CTP_SYMBOL-}" ]]; then
  echo "[live_ingest_verify] ERROR: CTP_SYMBOL not set (vt_symbol required)" >&2
  exit 2
fi
if [[ -n "${CONNECTOR}" ]]; then
  export CTP_GATEWAY_CONNECT="${CONNECTOR}"
fi
if [[ -z "${CTP_GATEWAY_CONNECT-}" ]]; then
  export CTP_GATEWAY_CONNECT="src.infrastructure.ctp_live_connector:live_gateway_connect"
fi

# Start NATS (local)
echo "[live_ingest_verify] Ensuring NATS is running..."
(cd "${ROOT_DIR}" && docker compose up -d nats > /dev/null)
sleep 2

# Prepare tmp files
SUB_OUT="$(mktemp -t nats_sub.XXXX)"
ING_OUT="$(mktemp -t ingest.XXXX)"
cleanup() { rm -f "$SUB_OUT" "$ING_OUT" 2>/dev/null || true; }
trap cleanup EXIT

# Launch subscriber (prints and exits after a few messages or timeout)
echo "[live_ingest_verify] Starting NATS subscriber on ${NATS_URL_ARG} ..."
uv run python - <<'PY' > "$SUB_OUT" 2>&1 &
import asyncio, json, os
import nats

async def main():
    url = os.environ.get('NATS_URL_ARG', 'nats://localhost:4222')
    user = os.environ.get('NATS_USER')
    pwd = os.environ.get('NATS_PASSWORD')
    nc = await nats.connect(url, user=user, password=pwd) if user and pwd else await nats.connect(url)
    got = 0
    async def cb(msg):
        nonlocal got
        try:
            data = json.loads(msg.data.decode())
        except Exception:
            data = {}
        print(f"SUB {msg.subject} {data.get('symbol')}", flush=True)
        got += 1
        if got >= 5:
            await nc.close()
    await nc.subscribe('market.tick.>', cb=cb)
    try:
        for _ in range(30):
            await asyncio.sleep(1)
            if nc.is_closed:
                break
    finally:
        if not nc.is_closed:
            await nc.close()

asyncio.run(main())
PY

# Run ingest for DURATION seconds
echo "[live_ingest_verify] Running ingest for ${DURATION}s with CTP_SYMBOL=${CTP_SYMBOL} ..."
MD_RUN_INGEST=1 MD_DURATION_SECONDS="${DURATION}" NATS_URL="${NATS_URL_ARG}" \
  uv run python -m src.main > "$ING_OUT" 2>&1 || true

sleep 1

echo "[live_ingest_verify] Subscriber sample:"
if [[ -s "$SUB_OUT" ]]; then
  tail -n 5 "$SUB_OUT"
else
  echo "(no subscriber output)"
fi

echo "[live_ingest_verify] Ingest logs sample:"
if [[ -s "$ING_OUT" ]]; then
  tail -n 20 "$ING_OUT"
else
  echo "(no ingest output)"
fi

echo "[live_ingest_verify] Done."
