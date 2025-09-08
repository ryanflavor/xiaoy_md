#!/usr/bin/env bash
set -euo pipefail

# Local CI helper supporting staged runs to mirror GitHub Actions
# Usage:
#   ./scripts/ci-local.sh                # default: quality stage
#   ./scripts/ci-local.sh quality        # lint + typecheck + unit tests
#   ./scripts/ci-local.sh docker-build   # build image + basic verifications
#   ./scripts/ci-local.sh integration    # start stack + run integration tests
#   ./scripts/ci-local.sh security       # start stack (auth) + security tests

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

compose_cmd() {
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    echo "docker compose"
  elif command -v docker-compose &>/dev/null; then
    echo "docker-compose"
  else
    echo "ERROR: docker compose not found" >&2
    return 1
  fi
}

header() { echo -e "\n$1\n================================"; }

ensure_uv() {
  if [[ "${CI_LOCAL_SKIP_SYNC:-}" == "1" ]]; then
    echo "⚠️ Skipping uv sync due to CI_LOCAL_SKIP_SYNC=1"
    return 0
  fi
  header "📦 Installing dependencies..."
  uv sync --frozen
}

run_quality() {
  header "🔍 Running local CI (quality)"
  ensure_uv

  echo "\n🎨 Checking code format..."
  if [[ "${CI_LOCAL_USE_VENV:-}" == "1" && -x .venv/bin/black ]]; then
    .venv/bin/black --check src/ tests/ scripts/
  else
    uv run black --check src/ tests/ scripts/
  fi

  echo "\n🔎 Linting with Ruff..."
  if [[ "${CI_LOCAL_USE_VENV:-}" == "1" && -x .venv/bin/ruff ]]; then
    .venv/bin/ruff check src/ tests/ scripts/
  else
    uv run ruff check src/ tests/ scripts/
  fi

  echo "\n🔤 Running type checks..."
  if [[ "${CI_LOCAL_USE_VENV:-}" == "1" && -x .venv/bin/mypy ]]; then
    .venv/bin/mypy src scripts tests
  else
    uv run mypy src scripts tests
  fi

  echo "\n🏗️ Validating architecture..."
  if [ -f scripts/check_architecture.py ]; then
    uv run python scripts/check_architecture.py
  else
    echo "⚠️ Architecture validation script not found, skipping..."
  fi

  echo "\n🧪 Running unit tests (no integration/e2e) + coverage..."
  if [[ "${CI_LOCAL_USE_VENV:-}" == "1" && -x .venv/bin/pytest ]]; then
    .venv/bin/pytest tests/ -v -m "not integration and not e2e" --tb=short \
      --cov=src --cov-report=term-missing --cov-report=xml
  else
    uv run pytest tests/ -v -m "not integration and not e2e" --tb=short \
      --cov=src --cov-report=term-missing --cov-report=xml
  fi

  echo "\n✅ Quality stage completed"
}

run_docker_build() {
  header "🐳 Docker build & basic verifications"
  local image="market-data-service:local"

  docker build -t "$image" .

  echo "\n📏 Checking image size (< 200MB target)"
  local size
  size=$(docker images "$image" --format '{{.Size}}') || true
  echo "Image size: $size"

  echo "\n👤 Verifying non-root user"
  uid=$(docker run --rm "$image" id -u)
  if [[ "$uid" == "0" ]]; then
    echo "ERROR: Container runs as root (uid=0)" >&2
    exit 1
  fi
  echo "✓ Runs as non-root (uid=$uid)"

  # Optional: Trivy scan if available
  if command -v trivy &>/dev/null; then
    echo "\n🛡️ Trivy scan (CRITICAL,HIGH)"
    trivy image --severity CRITICAL,HIGH --exit-code 0 "$image" || true
  else
    echo "⚠️ Trivy not installed; skipping image scan"
  fi

  echo "\n✅ Docker build stage completed"
}

run_integration() {
  header "🔗 Integration tests"
  ensure_uv
  local C; C=$(compose_cmd)

  export ENVIRONMENT="${ENVIRONMENT:-test}"
  export NATS_USER="${NATS_USER:-testuser}"
  export NATS_PASSWORD="${NATS_PASSWORD:-testpass}"

  echo "Starting stack via: $C up -d"
  $C up -d
  echo "Waiting for services..."; sleep 8

  echo "\n🧪 Running integration tests"
  uv run pytest tests/integration/ -v --tb=short --cov-append

  echo "\n🧹 Tearing down stack"
  $C down -v
  echo "\n✅ Integration stage completed"
}

run_security() {
  header "🛡️ Security configuration tests"
  ensure_uv
  local C; C=$(compose_cmd)

  export ENVIRONMENT="${ENVIRONMENT:-test}"
  export NATS_USER="${NATS_USER:-testuser}"
  export NATS_PASSWORD="${NATS_PASSWORD:-testpass}"

  echo "Starting stack with auth via: $C up -d"
  $C up -d
  echo "Waiting for services..."; sleep 8

  echo "\n🧪 Running security auth tests"
  uv run pytest tests/integration/test_nats_auth.py -v --tb=short --cov-append

  echo "\n🧹 Tearing down stack"
  $C down -v
  echo "\n✅ Security stage completed"
}

case "${1:-quality}" in
  quality)
    run_quality ;;
  docker-build|docker|build)
    run_docker_build ;;
  integration|it)
    run_integration ;;
  security)
    run_security ;;
  *)
    echo "Usage: $0 [quality|docker-build|integration|security]" >&2
    exit 2 ;;
esac
