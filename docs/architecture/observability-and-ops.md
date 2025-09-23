# **12\. Observability and Operations Plane**

## **Purpose**

This section codifies the production observability and operations blueprint introduced in Sprint Change Proposal — Production Ops. It ensures runbooks, dashboards, and automation expose the live health of the CTP feed, surface actionable alerts, and enable low-risk failover for primary/backup routes.

## **Objectives**

* Deliver real-time visibility into throughput, subscription coverage, latency, and error paths.
* Capture runbook execution outcomes so operators can audit startup, restart, and failover actions.
* Provide alerting hooks that map directly to remediation steps documented in `docs/ops/production-runbook.md`.
* Maintain traceability between primary and backup feeds, ensuring observability data proves failovers are transparent to downstream subscribers.

## **Telemetry Architecture**

| Layer | Signals | Tooling | Notes |
| :---- | :---- | :---- | :---- |
| Market Data Service | Throughput, latency buckets, serialization errors | `prometheus-client`, in-process exporter | Exposes `md_throughput_mps`, `md_latency_ms_p99`, `md_error_count`. |
| Subscription Workers | Rate-limit trips, retry counters, heartbeat | CLI flag `--metrics-port` publishing to Prometheus | Integrates with bulk subscribe flow. |
| Health Agent | Coverage ratio, missing/stalled instruments | JSON + Pushgateway | `check_feed_health.py` pushes `md_subscription_coverage_ratio`, `md_subscription_missing_total`, `md_subscription_stalled_total`. |
| Runbook Automation | Start/restart status, failover latency | Pushgateway payloads | `start_live_env.sh` emits `md_runbook_exit_code`, `md_failover_latency_ms`. |
| Downstream Consumers | Backlog depth, delivery lag | Prometheus exporters maintained by consumer teams | `consumer_backlog_messages` validates downstream stability. |

Telemetry flow: exporters expose `/metrics` endpoints scraped every 5s–60s; runbook scripts push ephemeral metrics to Pushgateway before exit. Prometheus stores time series and forwards alert evaluations to Grafana Alerting.

## **Metric Catalog**

| Metric | Type | Source | Description | Alert Tie-in |
| :---- | :---- | :---- | :---- | :---- |
| `md_throughput_mps` | Gauge | market-data-service | Per-second tick volume labelled by `feed`/`account`. | `MD_Throughput_Below_Target`. |
| `md_subscription_coverage_ratio` | Gauge | check_feed_health.py | Actual vs expected contract coverage ratio. | `MD_Subscription_Coverage_Drop`. |
| `md_subscription_missing_total` | Gauge | check_feed_health.py | Count of missing subscriptions detected during health check. | feeds remediation dashboard + alert context. |
| `md_subscription_stalled_total` | Gauge | check_feed_health.py | Count of stalled streams at warning/critical severity. | correlated with stalled contract alerts. |
| `md_latency_ms_p99` | Gauge | market-data-service | P99 processing latency in milliseconds. | Latency playbooks in runbook §5. |
| `md_rate_limit_hits` | Counter | full_feed_subscription.py | Count of throttling events per interval. | `MD_Rate_Limit_Spike`. |
| `md_error_count` | Counter | market-data-service | Categorized fatal/critical errors. | Ops log triage. |
| `md_failover_latency_ms` | Gauge | start_live_env.sh | Time from failover start to feed parity. | `MD_Failover_Latency_High`. |
| `md_runbook_exit_code` | Gauge | start_live_env.sh | Exit status of latest automation step. | `MD_Runbook_Failure`. |
| `consumer_backlog_messages` | Gauge | downstream exporters | Pending tick backlog per consumer. | `Consumer_Backlog_Growth`. |

## **Dashboards**

Grafana dashboard `Market Data Ops` aggregates the catalog above. Layout mirrors `docs/ops/monitoring-dashboard.md` with four rows: executive overview, latency/errors, operations, and drilldown. Provisioning templates live under `docs/ops/templates/grafana/` (future export). Dashboard annotations capture runbook events (restart, failover) for forensic review.

### **Provisioning Workflow**

1. Export dashboard JSON and commit to repository under `docs/ops/templates/grafana/` when versions change.
2. Grafana provisioning references the JSON template and tags the dashboard with `ops`, `market-data`.
3. Alert rules are defined via Grafana Alerting and stored alongside dashboard provisioning files for drift detection.

## **Alerting Model**

Alerts route to the `#market-data-ops` channel (primary) and PagerDuty for critical incidents. Each alert description links to corrective actions in `docs/ops/production-runbook.md` or automation commands.

| Alert | Condition | Duration | Target Runbook Step |
| :---- | :---- | :---- | :---- |
| `MD_Throughput_Below_Target` | Throughput < 5,000 mps | 5 min | Runbook §2 (restart) |
| `MD_Subscription_Coverage_Drop` | Coverage < 99.5% | 2 min | Runbook §5 + health script enforce mode |
| `MD_Rate_Limit_Spike` | Rate limit hits > 5 | 10 min | Adjust rate knobs per Runbook §5 |
| `MD_Runbook_Failure` | Exit code != 0 | Immediate | Runbook incident template |
| `MD_Failover_Latency_High` | Failover latency > 5,000 ms | 1 min | Runbook §4 |
| `Consumer_Backlog_Growth` | Backlog growth > 2,000 msgs/5m | 5 min | Coordinate with consumer owners |

## **Operations Telemetry Loop**

1. **Detect**: Prometheus evaluates rules and Grafana triggers alerts.
2. **Diagnose**: Operators review dashboard panels and runbook logs (`logs/runbooks/`).
3. **Remediate**: Execute `start_live_env.sh` actions or `check_feed_health.py` as prescribed.
4. **Verify**: Metrics confirm recovery; alerts auto-resolve once thresholds normalize.
5. **Document**: Incident template (Runbook §6) captures context for retrospectives.

## **Integration with Runbooks**

* Startup scripts mark success/failure using Pushgateway metrics and structured log entries.
* Health checks run hourly (cron/systemd timer) and produce both machine-readable JSON and Prometheus samples.
* Failover playbooks annotate dashboards via Grafana annotation API with operator, timestamp, and exit code.
* Subscription health escalations emit `event=health_check_escalation` logs and optionally execute the configured escalation command for Slack/PagerDuty handoff.

## **Dependencies & Configuration**

* Prometheus scrape job added under `config/prometheus/prometheus.yml` with 5s interval for live services and 60s for health checks.
* Pushgateway endpoint maintained within the live environment VPC; runbooks require `PUSHGATEWAY_URL` in environment configuration.
* Secrets management ensures metrics endpoints remain internal; optional basic auth recommended for remote Grafana.
* Synthetic validation: `scripts/operations/alert_smoke.py` pushes `md_runbook_exit_code` through Pushgateway and queries Prometheus to confirm alert wiring.
* Escalation hooks: set `--max-remediation-attempts`, `--escalation-marker`, and `--escalation-command` in health-check automation to surface persistent gaps via Slack/PagerDuty integrations.

## **Traceability Matrix**

| Requirement | Artifact |
| :---- | :---- |
| PRD NFR8 (Operational Readiness) | Runbook telemetry + automation metrics |
| PRD NFR9 (Observability & Alerting) | Dashboard + alert catalog |
| PRD NFR10 (Multi-Account Resilience) | Failover metrics, annotations |
| Sprint Proposal §6.2 | Observability architecture documented here |
| Sprint Proposal §6.3 | Script metrics and CLI enhancements referenced |

---

**Related Documents**: `docs/ops/production-runbook.md`, `docs/ops/monitoring-dashboard.md`, `docs/architecture/infrastructure-and-deployment.md`.
