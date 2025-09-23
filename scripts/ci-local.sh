#!/usr/bin/env bash
set -euo pipefail

# Local CI helper supporting staged runs to mirror GitHub Actions
# Usage:
#   ./scripts/ci-local.sh                # default: quality stage
#   ./scripts/ci-local.sh quality        # lint + typecheck + unit tests
#   ./scripts/ci-local.sh docker-build   # build image + basic verifications
#   ./scripts/ci-local.sh integration    # start stack + run integration tests
#   ./scripts/ci-local.sh security       # start stack (auth) + security tests
#   ./scripts/ci-local.sh failover-check # run failover drill in mock mode

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

  echo "\n🩺 Running subscription health mock check..."
  uv run python scripts/operations/check_feed_health.py \
    --mode dry-run \
    --catalogue tests/fixtures/subscription_health/contracts.json \
    --active-file tests/fixtures/subscription_health/active_snapshot.json \
    --skip-metrics \
    --out-dir logs/runbooks/mock \
    --log-prefix subscription_check_ci \
    --json-indent 2 \
    --limit-list 5

  echo "\n✅ Quality stage completed"
}

run_docker_build() {
  header "🐳 Docker build & basic verifications"
  local image="market-data-service:local"

  # Forward host proxy envs as build-args if present
  local build_args=()
  if [[ -n "${HTTP_PROXY:-}" ]]; then build_args+=(--build-arg HTTP_PROXY="$HTTP_PROXY"); fi
  if [[ -n "${HTTPS_PROXY:-}" ]]; then build_args+=(--build-arg HTTPS_PROXY="$HTTPS_PROXY"); fi
  if [[ -n "${NO_PROXY:-}" ]]; then build_args+=(--build-arg NO_PROXY="$NO_PROXY"); fi

  DOCKER_BUILDKIT=1 docker build "${build_args[@]}" -t "$image" .

  echo "\n📏 Checking image size (< 200MB target)"
  local size
  size=$(docker images "$image" --format '{{.Size}}') || true
  echo "Image size: $size"

  echo "\n👤 Verifying non-root user"
  # Override ENTRYPOINT to run id inside the container
  uid=$(docker run --rm --entrypoint /usr/bin/id "$image" -u)
  if [[ "$uid" == "0" ]]; then
    echo "ERROR: Container runs as root (uid=0)" >&2
    exit 1
  fi
  echo "✓ Runs as non-root (uid=$uid)"

  # Optional: Trivy scan if available
  if command -v trivy &>/dev/null; then
    echo "\n🛡️ Trivy scan (CRITICAL,HIGH)"
    if [[ "${TRIVY_SKIP:-0}" == "1" ]]; then
      echo "⚠️ Skipping Trivy scan (TRIVY_SKIP=1)"
    elif command -v trivy &>/dev/null; then
      # If this is the first run (no local DB), avoid noisy fatal logs and skip
      if [[ -d "${HOME}/.cache/trivy/db" ]]; then
        trivy image --severity CRITICAL,HIGH --exit-code 0 --skip-db-update "$image" || true
      else
        echo "⚠️ Trivy first run detected (no local DB). Skipping scan to avoid DB download." \
             "Set TRIVY_SKIP=0 and run 'trivy image $image' once to initialize."
      fi
    else
      echo "⚠️ Trivy not installed; skipping image scan"
    fi
  else
    echo "⚠️ Trivy not installed; skipping image scan"
  fi

  echo "\n✅ Docker build stage completed"
}

run_integration() {
  header "🔗 Integration tests"
  ensure_uv
  local C; C=$(compose_cmd)
  # Use an isolated compose project name to avoid interfering with existing services
  local PROJECT=${CI_LOCAL_COMPOSE_PROJECT:-ci-local-$(date +%s)}

  export ENVIRONMENT="${ENVIRONMENT:-test}"
  export NATS_USER="${NATS_USER:-testuser}"
  export NATS_PASSWORD="${NATS_PASSWORD:-testpass}"

  # Detect conflicts with existing fixed container names from docker-compose.yml
  # Defaults mirror docker-compose.yml fallbacks
  local NATS_NAME=${NATS_CONTAINER_NAME:-nats}
  local SERVICE_NAME=${SERVICE_CONTAINER_NAME:-market-data-service}
  local EXPORTER_NAME=${EXPORTER_CONTAINER_NAME:-nats-exporter}
  local conflict=0
  if docker ps --format '{{.Names}}' | grep -Eq "^${NATS_NAME}$|^${SERVICE_NAME}$|^${EXPORTER_NAME}$"; then
    conflict=1
  fi

  if [[ "${CI_LOCAL_SKIP_STACK:-0}" != "1" && $conflict -eq 0 ]]; then
    echo "Starting stack via: $C -p $PROJECT up -d"
    $C -p "$PROJECT" up -d
    echo "Waiting for services..."; sleep 8
  else
    if [[ $conflict -eq 1 ]]; then
      echo "⚠️ Detected existing containers with names that would conflict (nats/market-data-service/nats-exporter)."
      echo "   Skipping docker compose stack startup to avoid disrupting running services."
    else
      echo "⚠️ Skipping docker compose stack startup (CI_LOCAL_SKIP_STACK=1)"
    fi
  fi

  echo "\n🧪 Running integration tests"
  uv run pytest tests/integration/ -v --tb=short --no-cov

  if [[ "${CI_LOCAL_SKIP_STACK:-0}" != "1" && $conflict -eq 0 ]]; then
    echo "\n🧹 Tearing down stack"
    if [[ "${CI_LOCAL_KEEP_STACK:-0}" != "1" ]]; then
      $C -p "$PROJECT" down -v
    else
      echo "Keeping stack running (CI_LOCAL_KEEP_STACK=1). Project: $PROJECT"
    fi
  else
    echo "\n⏭️  Stack teardown skipped (conflict or CI_LOCAL_SKIP_STACK=1)"
  fi
  echo "\n✅ Integration stage completed"
}

run_security() {
  header "🛡️ Security configuration tests"
  ensure_uv
  local C; C=$(compose_cmd)
  local PROJECT=${CI_LOCAL_COMPOSE_PROJECT:-ci-local-sec-$(date +%s)}

  export ENVIRONMENT="${ENVIRONMENT:-test}"
  export NATS_USER="${NATS_USER:-testuser}"
  export NATS_PASSWORD="${NATS_PASSWORD:-testpass}"

  local NATS_NAME=${NATS_CONTAINER_NAME:-nats}
  local SERVICE_NAME=${SERVICE_CONTAINER_NAME:-market-data-service}
  local EXPORTER_NAME=${EXPORTER_CONTAINER_NAME:-nats-exporter}
  local conflict=0
  if docker ps --format '{{.Names}}' | grep -Eq "^${NATS_NAME}$|^${SERVICE_NAME}$|^${EXPORTER_NAME}$"; then
    conflict=1
  fi
  if [[ "${CI_LOCAL_SKIP_STACK:-0}" != "1" && $conflict -eq 0 ]]; then
    echo "Starting stack with auth via: $C -p $PROJECT up -d"
    $C -p "$PROJECT" up -d
    echo "Waiting for services..."; sleep 8
  else
    echo "⚠️ Skipping stack startup for security tests (conflict or CI_LOCAL_SKIP_STACK=1)"
  fi

  echo "\n🧪 Running security auth tests"
  uv run pytest tests/integration/test_nats_auth.py -v --tb=short --no-cov

  if [[ "${CI_LOCAL_SKIP_STACK:-0}" != "1" && $conflict -eq 0 ]]; then
    echo "\n🧹 Tearing down stack"
    if [[ "${CI_LOCAL_KEEP_STACK:-0}" != "1" ]]; then
      $C -p "$PROJECT" down -v
    else
      echo "Keeping stack running (CI_LOCAL_KEEP_STACK=1). Project: $PROJECT"
    fi
  else
    echo "\n⏭️  Stack teardown skipped (conflict or CI_LOCAL_SKIP_STACK=1)"
  fi
  echo "\n✅ Security stage completed"
}

run_failover_check() {
  header "🔁 Failover drill check"
  ensure_uv

  local log_dir=${CI_LOCAL_DRILL_LOG_DIR:-"logs/runbooks/ci-drill"}
  mkdir -p "$log_dir"

  local env_file
  env_file=$(mktemp -p "${TMPDIR:-/tmp}" ci-drill-env.XXXXXX)
  cat <<'EOF' > "$env_file"
CTP_PRIMARY_BROKER_ID=ci_primary_broker
CTP_PRIMARY_USER_ID=ci_primary_user
CTP_PRIMARY_PASSWORD=primary_pass
CTP_PRIMARY_MD_ADDRESS=tcp://primary.md:10110
CTP_PRIMARY_TD_ADDRESS=tcp://primary.td:10100
CTP_PRIMARY_APP_ID=primary_app
CTP_PRIMARY_AUTH_CODE=primary_auth

CTP_BACKUP_BROKER_ID=ci_backup_broker
CTP_BACKUP_USER_ID=ci_backup_user
CTP_BACKUP_PASSWORD=backup_pass
CTP_BACKUP_MD_ADDRESS=tcp://backup.md:20110
CTP_BACKUP_TD_ADDRESS=tcp://backup.td:20100
CTP_BACKUP_APP_ID=backup_app
CTP_BACKUP_AUTH_CODE=backup_auth
EOF

  local metrics_file
  metrics_file=$(mktemp -p "${TMPDIR:-/tmp}" ci-drill-metrics.XXXXXX)
  echo "consumer_backlog_messages 5" > "$metrics_file"

  ENV_FILE="$env_file" \
  DRILL_METRICS_SOURCE="$metrics_file" \
  DRILL_CONSUMER_BACKLOG_THRESHOLD="100" \
  DRILL_HEALTH_CMD="true" \
  ./scripts/operations/start_live_env.sh --drill --mock --profile test --window day --log-dir "$log_dir"

  local rc=$?
  rm -f "$env_file" "$metrics_file"
  if [[ $rc -ne 0 ]]; then
    echo "❌ Failover drill check failed" >&2
    exit $rc
  fi

  echo "\n✅ Failover drill check completed"
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
  failover-check|failover)
    run_failover_check ;;
  *)
    echo "Usage: $0 [quality|docker-build|integration|security|failover-check]" >&2
    exit 2 ;;
esac
