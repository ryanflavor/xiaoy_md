#!/usr/bin/env bash
set -euo pipefail

# Live Environment Orchestration Script
# Manages startup, restart, stop, and failover for production trading environment
#
# Usage:
#   ./scripts/operations/start_live_env.sh --window day --profile live
#   ./scripts/operations/start_live_env.sh --restart --window night --profile live
#   ./scripts/operations/start_live_env.sh --stop --profile live
#   ./scripts/operations/start_live_env.sh --failover --window day --config backup

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs/runbooks"
PROFILE="${PROFILE:-live}"
WINDOW="${WINDOW:-day}"
CONFIG="${CONFIG:-primary}"
ACTION="start"
DEBUG="${DEBUG:-0}"
MANAGE_LIVE="${MANAGE_LIVE:-1}"
MANAGE_NATS="${MANAGE_NATS:-1}"
MOCK_MODE="${MOCK_MODE:-${ORCH_TEST_MODE:-0}}"
ENV_FILE_OVERRIDE="${ENV_FILE:-}"
ENV_FILE=""
ACTIVE_FEED="${ACTIVE_FEED:-primary}"
ACTIVE_ACCOUNT_MASK="${ACTIVE_ACCOUNT_MASK:-}"

REQUIRED_BACKUP_VARS=(
  CTP_BACKUP_BROKER_ID
  CTP_BACKUP_USER_ID
  CTP_BACKUP_PASSWORD
  CTP_BACKUP_MD_ADDRESS
  CTP_BACKUP_TD_ADDRESS
  CTP_BACKUP_APP_ID
  CTP_BACKUP_AUTH_CODE
)

# Ensure default log directory exists early (may be overridden later)
mkdir -p "${LOG_DIR}"

mask_secret() {
  local value="$1"
  if [[ -z "$value" ]]; then
    echo ""
    return 0
  fi

  local length=${#value}
  if (( length <= 4 )); then
    echo "***"
    return 0
  fi

  local prefix=4
  if (( length <= 8 )); then
    prefix=$(( length / 2 ))
    if (( prefix < 2 )); then
      prefix=2
    fi
  fi
  local suffix=2
  local start_suffix=$(( length - suffix ))
  echo "${value:0:$prefix}...${value:$start_suffix}"
}

# JSON logging function for structured output
log_json() {
  local level="$1"
  local message="$2"
  local timestamp=$(TZ='Asia/Shanghai' date -Iseconds)
  local exit_code="${3:-0}"
  local session="${WINDOW}"
  local feed="${ACTIVE_FEED:-${CONFIG}}"
  local mock_flag="$([[ "${MOCK_MODE}" == "1" ]] && echo true || echo false)"
  local account="${ACTIVE_ACCOUNT_MASK:-unknown}"

  cat <<EOF
{"timestamp":"${timestamp}","level":"${level}","message":"${message}","session":"${session}","exit_code":${exit_code},"profile":"${PROFILE}","config":"${CONFIG}","active_feed":"${feed}","mock":${mock_flag},"account":"${account}"}
EOF
}

# Status output function
status_output() {
  local component="$1"
  local status="$2"
  local details="${3:-}"

  log_json "INFO" "Component: ${component}, Status: ${status}, Details: ${details}" 0
}

# Check readiness with timeout
check_readiness() {
  local component="$1"
  local check_cmd="$2"
  local timeout="${3:-30}"
  local elapsed=0

  while [ $elapsed -lt $timeout ]; do
    if eval "$check_cmd" > /dev/null 2>&1; then
      status_output "$component" "READY" "Health check passed"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  status_output "$component" "TIMEOUT" "Health check failed after ${timeout}s"
  return 1
}

# Push metrics to Prometheus Pushgateway
push_metric() {
  local metric_name="$1"
  local value="$2"
  local pushgateway_url="${PUSHGATEWAY_URL:-http://localhost:9091}"

  if command -v curl > /dev/null 2>&1; then
    echo "${metric_name} ${value}" | curl -s --data-binary @- "${pushgateway_url}/metrics/job/runbook/instance/${HOSTNAME:-localhost}" > /dev/null 2>&1 || true
  fi
}

start_components() {
  if [[ "${MANAGE_NATS}" == "1" ]]; then
    if ! start_nats; then
      return 1
    fi
  else
    log_json "INFO" "Skipping NATS management (MANAGE_NATS=${MANAGE_NATS})" 0
  fi

  start_monitoring_stack

  if ! start_market_data_service; then
    return 2
  fi

  if ! start_market_data_live; then
    return 21
  fi

  if ! start_subscription_worker; then
    return 3
  fi

  return 0
}

rollback_to_config() {
  local target_config="$1"
  local context="$2"

  if [[ -z "${target_config}" ]]; then
    return
  fi

  log_json "WARN" "Attempting rollback to ${target_config} (${context})" 0
  CONFIG="${target_config}"
  load_env "$ENV_FILE"

  if start_components; then
    log_json "INFO" "Rollback to ${target_config} succeeded (${context})" 0
  else
    log_json "ERROR" "Rollback to ${target_config} failed (${context}); manual intervention required" 1
  fi
}

run_health_check() {
  local phase="$1"

  if [[ -n "${DRILL_HEALTH_CMD:-}" ]]; then
    if eval "${DRILL_HEALTH_CMD}"; then
      log_json "INFO" "Health check passed (${phase})" 0
      return 0
    else
      log_json "ERROR" "Health check failed (${phase})" 1
      return 1
    fi
  fi

  local script_path="${ROOT_DIR}/scripts/operations/check_feed_health.py"
  if [[ ! -f "${script_path}" ]]; then
    log_json "WARN" "Health check script missing; skipping (${phase})" 0
    return 0
  fi

  local -a cmd
  if command -v uv >/dev/null 2>&1; then
    cmd=(uv run python "${script_path}" --mode enforce)
  else
    cmd=(python "${script_path}" --mode enforce)
  fi

  if [[ -n "${DRILL_HEALTH_EXTRA_ARGS:-}" ]]; then
    # shellcheck disable=SC2206
    local extra_args=(${DRILL_HEALTH_EXTRA_ARGS})
    cmd+=("${extra_args[@]}")
  fi

  if "${cmd[@]}"; then
    log_json "INFO" "Health check passed (${phase})" 0
    return 0
  fi

  log_json "ERROR" "Health check failed (${phase})" 1
  return 1
}

verify_consumer_metrics() {
  local phase="$1"
  local source="${DRILL_METRICS_SOURCE:-}"

  if [[ -z "${source}" ]]; then
    log_json "INFO" "Skipping metrics verification (${phase})" 0
    return 0
  fi

  local content=""
  if [[ -f "${source}" ]]; then
    content="$(cat "${source}")"
  else
    if ! command -v curl >/dev/null 2>&1; then
      log_json "WARN" "curl not available for metrics verification (${phase})" 0
      return 0
    fi
    content="$(curl -sf "${source}" 2>/dev/null || true)"
  fi

  if [[ -z "${content}" ]]; then
    log_json "ERROR" "Metrics verification failed (${phase}): no data" 1
    return 1
  fi

  local feed_filter="${DRILL_EXPECT_FEED:-${ACTIVE_FEED:-}}"
  local account_filter="${DRILL_EXPECT_ACCOUNT:-}"  # optional explicit account selector

  local backlog_line=""
  backlog_line=$(printf '%s\n' "${content}" | awk -v feed="${feed_filter}" -v account="${account_filter}" '
    /^consumer_backlog_messages/ {
      if ((feed == "" || index($0, "feed=\"" feed "\"") > 0) &&
          (account == "" || index($0, "account=\"" account "\"") > 0)) {
        print
        exit
      }
    }
  ')

  if [[ -z "${backlog_line}" ]]; then
    backlog_line=$(printf '%s\n' "${content}" | awk '/^consumer_backlog_messages/ {print; exit}')
  fi

  if [[ -z "${backlog_line}" ]]; then
    log_json "WARN" "Metrics verification missing consumer backlog (${phase})" 0
    return 0
  fi

  local backlog
  backlog=$(printf '%s\n' "${backlog_line}" | awk '{print $NF}')
  local threshold=${DRILL_CONSUMER_BACKLOG_THRESHOLD:-2000}

  if [[ -z "${backlog}" ]]; then
    log_json "WARN" "Metrics verification missing consumer backlog value (${phase})" 0
    return 0
  fi

  if awk -v backlog="${backlog}" -v threshold="${threshold}" 'BEGIN {exit !(backlog <= threshold)}'; then
    log_json "INFO" "Metrics verification passed (${phase})" 0
    return 0
  fi

  log_json "ERROR" "consumer_backlog_messages=${backlog} exceeds threshold ${threshold} (${phase})" 1
  return 1
}

ensure_backup_profile_complete() {
  local missing=()
  for var in "${REQUIRED_BACKUP_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
      missing+=("$var")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    log_json "ERROR" "Backup credential profile incomplete" 1
    log_json "ERROR" "Missing backup variables: ${missing[*]}" 1
    exit 1
  fi
}

# Load environment configuration
load_env() {
  local env_file="$1"

  if [[ ! -f "$env_file" ]]; then
    log_json "ERROR" "Environment file not found: ${env_file}" 1
    exit 1
  fi

  log_json "INFO" "Loading environment from: ${env_file}" 0

  # Source environment file
  set -a
  source "$env_file"
  set +a

  # Apply window-specific overrides
  if [[ "$WINDOW" == "night" ]]; then
    export SESSION_START="21:00"
    export SESSION_END="02:30"
    export T5_CHECKPOINT="20:55"
  else
    export SESSION_START="09:00"
    export SESSION_END="15:00"
    export T5_CHECKPOINT="08:55"
  fi

  local route_selector="${CTP_ROUTE_SELECTOR:-primary}"

  # Map primary profile into canonical variables when not explicitly provided
  if [[ -z "${CTP_USER_ID:-}" && -n "${CTP_PRIMARY_USER_ID:-}" ]]; then
    export CTP_BROKER_ID="${CTP_PRIMARY_BROKER_ID:-${CTP_BROKER_ID:-}}"
    export CTP_USER_ID="${CTP_PRIMARY_USER_ID}"
    export CTP_PASSWORD="${CTP_PRIMARY_PASSWORD:-${CTP_PASSWORD:-}}"
    export CTP_MD_ADDRESS="${CTP_PRIMARY_MD_ADDRESS:-${CTP_MD_ADDRESS:-}}"
    export CTP_TD_ADDRESS="${CTP_PRIMARY_TD_ADDRESS:-${CTP_TD_ADDRESS:-}}"
    export CTP_APP_ID="${CTP_PRIMARY_APP_ID:-${CTP_APP_ID:-}}"
    export CTP_AUTH_CODE="${CTP_PRIMARY_AUTH_CODE:-${CTP_AUTH_CODE:-}}"
  fi

  if [[ "${route_selector}" == "backup" && "${CONFIG}" == "primary" ]]; then
    CONFIG="backup"
  fi

  # Apply config-specific overrides (primary/backup)
  if [[ "$CONFIG" == "backup" ]]; then
    ensure_backup_profile_complete
    export CTP_BROKER_ID="${CTP_BACKUP_BROKER_ID:-$CTP_BROKER_ID}"
    export CTP_USER_ID="${CTP_BACKUP_USER_ID:-$CTP_USER_ID}"
    export CTP_PASSWORD="${CTP_BACKUP_PASSWORD:-$CTP_PASSWORD}"
    export CTP_MD_ADDRESS="${CTP_BACKUP_MD_ADDRESS:-$CTP_MD_ADDRESS}"
    export CTP_TD_ADDRESS="${CTP_BACKUP_TD_ADDRESS:-$CTP_TD_ADDRESS}"
    export CTP_APP_ID="${CTP_BACKUP_APP_ID:-$CTP_APP_ID}"
    export CTP_AUTH_CODE="${CTP_BACKUP_AUTH_CODE:-$CTP_AUTH_CODE}"
  fi

  export SESSION_WINDOW="${WINDOW}"
  export SESSION_CONFIG="${CONFIG}"
  export SUBSCRIPTION_ENV_FILE="${env_file}"

  ACTIVE_FEED="${CONFIG}"
  if [[ -n "${METRICS_FEED_LABEL:-}" ]]; then
    ACTIVE_FEED="${METRICS_FEED_LABEL}"
  fi

  local account_for_mask="${CTP_USER_ID:-}"
  if [[ -z "${account_for_mask}" ]]; then
    account_for_mask="${CTP_BACKUP_USER_ID:-}"
  fi

  ACTIVE_ACCOUNT_MASK="$(mask_secret "${account_for_mask}")"
  export ACTIVE_FEED
  export ACTIVE_ACCOUNT_MASK
}

# Start NATS
start_nats() {
  if [[ "${MANAGE_NATS}" != "1" ]]; then
    log_json "INFO" "MANAGE_NATS=0, not managing NATS" 0
    return 0
  fi

  log_json "INFO" "Starting NATS JetStream cluster" 0

  if [[ "${MOCK_MODE}" == "1" ]]; then
    status_output "NATS" "READY" "Mock mode"
    return 0
  fi

  cd "${ROOT_DIR}"
  docker compose --profile "${PROFILE}" up -d nats > /dev/null 2>&1

  local nats_ready_cmd="docker compose --profile ${PROFILE} ps --status running --services | grep -qx nats"

  if check_readiness "NATS" "${nats_ready_cmd}" 20; then
    return 0
  else
    log_json "ERROR" "NATS failed to start" 1
    return 1
  fi
}

start_monitoring_stack() {
  log_json "INFO" "Ensuring monitoring stack is running" 0

  if [[ "${MOCK_MODE}" == "1" ]]; then
    status_output "monitoring" "SKIPPED" "Mock mode"
    return 0
  fi

  cd "${ROOT_DIR}"
  docker compose --profile "${PROFILE}" up -d pushgateway > /dev/null 2>&1 || true
  docker compose --profile "${PROFILE}" up -d prometheus > /dev/null 2>&1 || true

  local push_ready_cmd="docker compose --profile ${PROFILE} ps --status running --services | grep -qx pushgateway"
  check_readiness "pushgateway" "${push_ready_cmd}" 20 || true

  local prom_ready_cmd="docker compose --profile ${PROFILE} ps --status running --services | grep -qx prometheus"
  check_readiness "prometheus" "${prom_ready_cmd}" 30 || true
}

# Start Market Data Service
start_market_data_service() {
  log_json "INFO" "Starting market-data-service" 0

  if [[ "${MOCK_MODE}" == "1" ]]; then
    status_output "market-data-service" "HEALTHY" "Mock mode"
    return 0
  fi

  cd "${ROOT_DIR}"

  # Build if needed
  if [[ ! -f "${ROOT_DIR}/.dockerignore" ]]; then
    docker compose --profile "${PROFILE}" build market-data-service > /dev/null 2>&1
  fi

  docker compose --profile "${PROFILE}" up -d market-data-service > /dev/null 2>&1

  local mds_container="${SERVICE_CONTAINER_NAME:-market-data-service}"
  local mds_ready_cmd="docker inspect --format '{{.State.Health.Status}}' ${mds_container} 2>/dev/null | grep -qx healthy"

  if check_readiness "market-data-service" "${mds_ready_cmd}" 45; then
    status_output "market-data-service" "HEALTHY" "Container ${mds_container} reports healthy"
    return 0
  else
    log_json "ERROR" "market-data-service health check failed" 1
    return 1
  fi
}

# Start market-data-live ingest container when enabled
start_market_data_live() {
  if [[ "${MANAGE_LIVE}" != "1" ]]; then
    log_json "INFO" "Skipping market-data-live startup (disabled)" 0
    return 0
  fi

  log_json "INFO" "Starting market-data-live ingest" 0

  if [[ "${MOCK_MODE}" == "1" ]]; then
    status_output "market-data-live" "HEALTHY" "Mock mode"
    return 0
  fi

  cd "${ROOT_DIR}"
  docker compose --profile "${PROFILE}" up -d market-data-live > /dev/null 2>&1

  local live_container="${SERVICE_LIVE_CONTAINER_NAME:-market-data-live}"
  local live_ready_cmd="docker inspect --format '{{.State.Health.Status}}' ${live_container} 2>/dev/null | grep -qx healthy"

  if check_readiness "market-data-live" "${live_ready_cmd}" 60; then
    status_output "market-data-live" "HEALTHY" "Container ${live_container} reports healthy"
    return 0
  else
    log_json "ERROR" "market-data-live health check failed" 1
    return 1
  fi
}

# Start Subscription Worker
start_subscription_worker() {
  log_json "INFO" "Starting subscription worker" 0

  if [[ "${MOCK_MODE}" == "1" ]]; then
    status_output "subscription-worker" "RUNNING" "Mock mode"
    return 0
  fi

  cd "${ROOT_DIR}"
  local log_path="${LOG_DIR}/subscription_worker.log"
  if docker compose --profile "${PROFILE}" run --rm subscription-worker \
    >> "${log_path}" 2>&1; then
    status_output "subscription-worker" "COMPLETED" "See ${log_path}"
    return 0
  fi

  log_json "ERROR" "Subscription worker execution failed" 1
  return 1
}

# Stop all components
stop_all() {
  log_json "INFO" "Stopping all components" 0

  if [[ "${MOCK_MODE}" == "1" ]]; then
    status_output "subscription-worker" "STOPPED" "Mock mode"
  fi

  # Stop Docker services
  if [[ "${MOCK_MODE}" != "1" ]]; then
    cd "${ROOT_DIR}"
    if [[ "${MANAGE_NATS}" == "1" ]]; then
      docker compose --profile "${PROFILE}" down > /dev/null 2>&1 || true
    else
      local services=(market-data-service subscription-worker pushgateway prometheus)
      if [[ "${MANAGE_LIVE}" == "1" ]]; then
        services+=(market-data-live)
      fi
      docker compose --profile "${PROFILE}" stop "${services[@]}" > /dev/null 2>&1 || true
    fi
  fi

  status_output "environment" "STOPPED" "All components shut down"
}

# Main orchestration
orchestrate() {
  local start_time=$(date +%s)
  local exit_code=0

  case "$ACTION" in
    start)
      log_json "INFO" "Starting live environment orchestration" 0
      load_env "$ENV_FILE"

      if ! start_components; then
        exit_code=$?
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      sleep 5
      status_output "environment" "READY" "All components operational"
      log_json "INFO" "HEALTH=READY" 0
      ;;

    restart)
      log_json "INFO" "Restarting live environment" 0
      stop_all
      log_json "INFO" "GRACEFUL_SHUTDOWN=OK" 0
      sleep 3

      load_env "$ENV_FILE"

      if ! start_components; then
        exit_code=$?
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      sleep 5
      status_output "environment" "READY" "Restart complete"
      log_json "INFO" "RESTART=OK" 0
      ;;

    stop)
      log_json "INFO" "Stopping live environment" 0
      stop_all
      ;;

    failover)
      log_json "INFO" "Initiating failover to backup configuration" 0
      local failover_start=$(date +%s%3N)
      local previous_config="${CONFIG:-primary}"

      CONFIG="backup"
      load_env "$ENV_FILE"

      stop_all

      if ! start_components; then
        exit_code=$?
        push_metric "md_runbook_exit_code" $exit_code
        rollback_to_config "$previous_config" "failover"
        exit $exit_code
      fi

      local failover_end=$(date +%s%3N)
      local failover_latency=$((failover_end - failover_start))

      push_metric "md_failover_latency_ms" $failover_latency
      log_json "INFO" "Failover completed in ${failover_latency}ms" 0
      status_output "environment" "READY" "Failover to backup complete"
      ;;

    failback)
      log_json "INFO" "Initiating failback to primary configuration" 0
      local failback_start=$(date +%s%3N)
      local previous_config="${CONFIG:-backup}"

      CONFIG="primary"
      load_env "$ENV_FILE"

      stop_all

      if ! start_components; then
        exit_code=$?
        push_metric "md_runbook_exit_code" $exit_code
        rollback_to_config "$previous_config" "failback"
        exit $exit_code
      fi

      local failback_end=$(date +%s%3N)
      local failback_latency=$((failback_end - failback_start))

      push_metric "md_failback_latency_ms" $failback_latency
      log_json "INFO" "Failback completed in ${failback_latency}ms" 0
      status_output "environment" "READY" "Failback to primary complete"
      ;;

    drill)
      log_json "INFO" "Executing failover drill workflow" 0
      load_env "$ENV_FILE"

      if ! start_components; then
        exit_code=$?
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      sleep 2
      status_output "environment" "READY" "Primary profile ready for drill"
      log_json "INFO" "Drill primary startup complete" 0

      if ! run_health_check "primary"; then
        exit_code=41
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      if ! verify_consumer_metrics "primary"; then
        exit_code=42
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      local drill_failover_start=$(date +%s%3N)

      CONFIG="backup"
      load_env "$ENV_FILE"

      stop_all

      if ! start_components; then
        exit_code=$?
        push_metric "md_runbook_exit_code" $exit_code
        rollback_to_config "primary" "drill failover"
        exit $exit_code
      fi

      local drill_failover_end=$(date +%s%3N)
      local drill_failover_latency=$((drill_failover_end - drill_failover_start))
      push_metric "md_failover_latency_ms" $drill_failover_latency
      status_output "environment" "READY" "Backup profile active during drill"
      log_json "INFO" "Drill failover completed in ${drill_failover_latency}ms" 0

      if ! verify_consumer_metrics "failover"; then
        exit_code=43
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      if ! run_health_check "post-failover"; then
        exit_code=44
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      local drill_failback_start=$(date +%s%3N)

      CONFIG="primary"
      load_env "$ENV_FILE"

      stop_all

      if ! start_components; then
        exit_code=$?
        push_metric "md_runbook_exit_code" $exit_code
        rollback_to_config "backup" "drill failback"
        exit $exit_code
      fi

      local drill_failback_end=$(date +%s%3N)
      local drill_failback_latency=$((drill_failback_end - drill_failback_start))
      push_metric "md_failback_latency_ms" $drill_failback_latency
      status_output "environment" "READY" "Primary profile restored after drill"
      log_json "INFO" "Drill failback completed in ${drill_failback_latency}ms" 0

      if ! verify_consumer_metrics "failback"; then
        exit_code=45
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      if ! run_health_check "post-failback"; then
        exit_code=46
        push_metric "md_runbook_exit_code" $exit_code
        exit $exit_code
      fi

      log_json "INFO" "Failover drill completed successfully" 0
      ;;

    *)
      log_json "ERROR" "Unknown action: ${ACTION}" 1
      exit 1
      ;;
  esac

  # Calculate and report execution time
  local end_time=$(date +%s)
  local duration=$((end_time - start_time))

  push_metric "md_runbook_exit_code" $exit_code
  push_metric "md_session_startup_duration_s" $duration

  log_json "INFO" "Orchestration completed in ${duration}s" $exit_code

  # Write to audit log
  echo "$(TZ='Asia/Shanghai' date -Iseconds),${ACTION},${WINDOW},${PROFILE},${exit_code}" >> "${LOG_DIR}/startup_audit.log"

  exit $exit_code
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --window)
      WINDOW="$2"
      shift 2
      ;;
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    --config)
      CONFIG="$2"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE_OVERRIDE="$2"
      shift 2
      ;;
    --restart)
      ACTION="restart"
      shift
      ;;
    --stop)
      ACTION="stop"
      shift
      ;;
    --failover)
      ACTION="failover"
      shift
      ;;
    --failback)
      ACTION="failback"
      shift
      ;;
    --drill)
      ACTION="drill"
      shift
      ;;
    --skip-live)
      MANAGE_LIVE=0
      shift
      ;;
    --mock)
      MOCK_MODE=1
      shift
      ;;
    --debug)
      DEBUG=1
      shift
      ;;
    --help|-h)
      cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --window day|night     Trading window (default: day)
  --profile PROFILE      Environment profile (default: live)
  --config CONFIG        Configuration (primary|backup, default: primary)
  --log-dir DIR          Log directory (default: logs/runbooks)
  --env-file FILE        Explicit environment file to load
  --restart              Restart all components
  --stop                 Stop all components
  --failover             Switch to backup configuration
  --failback             Switch back to primary configuration
  --drill                Execute failover drill (start -> failover -> failback)
  --skip-live            Skip starting/stopping market-data-live ingest container
  --mock                 Enable mock mode (no Docker calls, used for tests)
  --debug                Enable debug output
  -h, --help             Show this help message

Examples:
  # Start day session
  ./scripts/operations/start_live_env.sh --window day --profile live

  # Restart night session
  ./scripts/operations/start_live_env.sh --restart --window night --profile live

  # Failover to backup
  ./scripts/operations/start_live_env.sh --failover --window day --config backup
EOF
      exit 0
      ;;
    *)
      log_json "ERROR" "Unknown option: $1" 1
      exit 1
      ;;
  esac
done

# Determine environment file after argument parsing
if [[ -n "${ENV_FILE_OVERRIDE}" ]]; then
  ENV_FILE="${ENV_FILE_OVERRIDE}"
else
  ENV_FILE="${ROOT_DIR}/.env.${PROFILE}"
fi

# Allow MOCK_MODE via environment variable ORCH_TEST_MODE
if [[ "${ORCH_TEST_MODE:-}" == "mock" ]]; then
  MOCK_MODE=1
fi

# Ensure (possibly overridden) log directory exists
mkdir -p "${LOG_DIR}"

# Enable debug if requested
if [[ "$DEBUG" == "1" ]]; then
  set -x
fi

# Main execution with output to both console and log file
orchestrate 2>&1 | tee -a "${LOG_DIR}/start_live_env.log"
