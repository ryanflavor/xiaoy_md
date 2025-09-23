#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

# Disable coverage enforcement for targeted drill checks.
uv run pytest --no-cov tests/unit/operations -k drill "$@"
