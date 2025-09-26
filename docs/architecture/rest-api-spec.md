# **8\. REST API Spec**

## Operations Console API

> All endpoints require `Authorization: Bearer <OPS_API_TOKEN>` header. Responses are JSON encoded in UTF-8.

### `GET /api/ops/status`
- **Description**: Returns current runbook status, last health report, and recent audit entries.
- **Query Parameters**: _None_
- **Response** (`200 OK`):
  ```json
  {
    "environment_mode": "live",
    "active_profile": "primary",
    "active_window": "day",
    "last_runbook": { "command": "start", "exit_code": 0, ... },
    "runbook_history": [],
    "health_by_request": { "req-123": { "coverage_ratio": 0.999, ... } },
    "last_health": { "coverage_ratio": 0.999, "generated_at": "2025-09-22T08:00:00+08:00", ... },
    "last_exit_codes": { "start": 0, "health_check": 0 },
    "last_updated_at": "2025-09-22T08:05:10+08:00"
  }
  ```

### `GET /api/ops/metrics/summary`
- **Description**: Aggregated Prometheus metrics required by the console overview.
- **Response** (`200 OK`):
  ```json
  {
    "coverage_ratio": {
      "metric": "md_subscription_coverage_ratio",
      "value": 0.999,
      "unit": null,
      "stale": false,
      "context": {
        "expected_total": 1280,
        "active_total": 1278,
        "matched_total": 1276,
        "ignored_total": 2
      }
    },
    "throughput_mps": {
      "metric": "md_throughput_mps",
      "value": 5400,
      "unit": "msg/s",
      "stale": false,
      "context": { "window": "max_over_time[1m]" }
    },
    "failover_latency_ms": { "metric": "md_failover_latency_ms", "value": 1800, "unit": "ms", "stale": false },
    "runbook_exit_code": { "metric": "md_runbook_exit_code", "value": 0, "stale": false },
    "consumer_backlog_messages": {
      "metric": "consumer_backlog_messages",
      "value": null,
      "unit": "messages",
      "stale": true,
      "context": { "note": "no exporter sample" }
    }
  }
  ```

### `GET /api/ops/metrics/timeseries`
- **Description**: Returns time series samples for a Prometheus metric. Used by overview charts.
- **Query Parameters**:
  - `metric` (required) — Prometheus metric name
  - `minutes` (optional, default 60) — lookback window
  - `step_seconds` (optional, default 60) — sampling step
- **Response** (`200 OK`):
  ```json
  {
    "metric": "md_throughput_mps",
    "unit": "msg/s",
    "points": [
      { "timestamp": "2025-09-22T07:55:00+08:00", "value": 4800 },
      { "timestamp": "2025-09-22T07:56:00+08:00", "value": 5100 }
    ]
  }
  ```

### `POST /api/ops/runbooks/execute`
- **Description**: Executes an orchestration command (`start`, `stop`, `restart`, `failover`, `failback`, `drill`, `health_check`).
- **Request Body**:
  ```json
  {
    "command": "failover",
    "mode": "live",
    "window": "day",
    "profile": "live",
    "config": "backup",
    "request_id": "uuid",
    "enforce": false,
    "dry_run": false,
    "reason": "manual failover"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "runbook": {
      "request_id": "uuid",
      "command": "failover",
      "exit_code": 0,
      "status": "success",
      "finished_at": "2025-09-22T08:02:00+08:00",
      "logs": [{ "level": "INFO", "message": "Failover completed" }]
    },
    "health": null
  }
  ```
- **Error Responses**:
  - `401 Unauthorized` — missing or invalid token
  - `403 Forbidden` — token lacks permission
  - `422 Unprocessable Entity` — validation failed (e.g., unknown command)
  - `500 Internal Server Error` — script execution error (response contains `detail` message)

---
