# **11\. Infrastructure and Deployment**

## **Infrastructure as Code**

* **Tool**: Docker Compose 2.24.x
* **Method**: A single docker-compose.yml file, used with environment-specific .env files, will define the application stack for all environments to prevent configuration drift.
* **Data Persistence**: Named volumes **must** be used for Prometheus and Grafana to persist monitoring data.

## **Operational Automation & Runbooks**

* **Primary Script**: `scripts/operations/start_live_env.sh` orchestrates pre-market startup, intra-day restarts, and controlled shutdown with structured logging and exit codes.
* **Subscription Worker**: `scripts/operations/full_feed_subscription.py` exposes CLI flags for rate limiting, retries, and health probes so runbooks can operate headlessly.
* **Health Checks**: `scripts/operations/check_feed_health.py` produces machine-readable reports (JSON/exit status) for CI, cron, and manual execution.
* **Scheduling**: Cron/systemd timers execute health checks and failover drills; each invocation registers metrics to Prometheus (direct scrape or pushgateway).

## **Configuration & Secrets Governance**

* **Environment Layout**: `.env.example` documents `CTP_PRIMARY_*`, `CTP_BACKUP_*`, rate-limit knobs, and monitoring toggles; production secrets stored in Vault-compatible secure stores.
* **Validation**: Pydantic BaseSettings performs boot-time validation and surfaces misconfiguration errors to runbook logs and alerts.
* **Pre-Flight Tooling**: `scripts/operations/validate_env.py` mirrors the runbook pre-market checklist and halts startup when profiles are incomplete; see Story 3.2 for traceability across docs.
* **Rotation**: Credential rotation playbooks mirror failover drills to ensure downstream consumers remain unaffected.

## **Monitoring & Alerting Integration**

* **Metrics**: Prometheus scrapes the market-data-service, subscription workers, and runbook exporters for throughput, coverage, latency, and error counts.
* **Dashboards**: Grafana dashboards bundle default panels (coverage heatmap, throughput trend, rate-limit incidents) and ship with provisioning templates under version control (`docs/ops/monitoring-dashboard.md`).
* **Alerts**: Grafana Alertmanager routes incidents to the ops channel; alerts reference runbook steps and link to remediation scripts.

## **Failover & Recovery Strategy**

* **Playbooks**: Dedicated failover mode in `start_live_env.sh` swaps credentials/config profiles and verifies recovery via health metrics.
* **Downstream Assurance**: Alert rules watch consumer lag/backlog to confirm switchovers remain transparent to subscribers.
* **Rollback**: Previous configuration snapshots and Docker image tags are retained so rollback equals re-running the runbook with last-known-good parameters.

## **Deployment Strategy**

* **Strategy**: Script-based Docker Deployment.
* **CI/CD Platform**: GitHub Actions.
* **Image Registry**: **GitHub Container Registry (GHCR)**. CI will build and push images; on-prem servers will pull from GHCR.

## **Environments & Promotion Flow**

* A standard Development -> Staging -> Production flow is used, with CI acting as the gatekeeper for merges into the main branch.

## **Rollback Strategy**

* **Method**: Re-deploy the previously stable Docker image tag from GHCR and reapply the last-known-good configuration profile via the automation scripts.

---
