#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run the E2E NATS tick demo with uv
# Usage: ./scripts/run_e2e_tick_demo.sh [--base-symbol IF2312] [--exchange CFFEX] [--ts <iso>] [--keep-container]

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install via: pip install uv or see project docs." >&2
  exit 2
fi

uv run python scripts/demo_e2e_tick_to_nats.py "$@"
