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
* **Autonomous Recovery**: The ingest service includes a stall watchdog—if ticks pause beyond 60 s (configurable via `MD_FAILOVER_THRESHOLD_SECONDS`) it reconnects, flips to backup credentials when available, and replays every tracked subscription before resuming publish.

## **Deployment Strategy**

* **Strategy**: Script-based Docker Deployment.
* **CI/CD Platform**: GitHub Actions.
* **Image Registry**: **GitHub Container Registry (GHCR)**. CI will build and push images; on-prem servers will pull from GHCR.
* **Operations Console UI**:
  - Build pipeline: `cd ui/operations-console && npm ci && npm run build`（生成静态资源于 `dist/`）。
  - Artifact promotion: 将 `dist/` 打包为版本化 tarball（`ops-console-v{git_sha}.tar.gz`）并发布至 GHCR 或对象存储；生产环境通过 Nginx `root` 指向解压目录。
  - Runtime configuration: `VITE_OPS_API_BASE_URL` 与 `VITE_OPS_API_TOKEN` 在部署时以环境变量注入，默认读取 `/etc/ops-console/.env`。（前端会自动在 Base URL 末尾拼接 `/api`，因此此处配置只需提供主机地址。）
  - `OPS_API_CORS_ORIGINS` 默认取值为 `*`，实现开箱即用的局域网访问；若需收紧范围，可在 `.env` 中覆盖为逗号分隔的具体来源。 `OPS_API_CORS_METHODS` 建议设置为 `GET,POST,OPTIONS` 以满足浏览器预检请求。
  - Rollback: 保留最近三个 UI 构建包，切换 Nginx symlink 到 `releases/<previous_tag>` 并执行 `systemctl reload nginx`。
  - CI 扩展：新增 `ui-console` job 执行 `npm run test`（Vitest）、`npm run test:e2e -- --reporter=list --retries=1`（Playwright，使用 mock API），再运行 `npm run build`，将构建产物作为 workflow artifact 供后续部署作业下载。
* **Operations API Service (`ops-api`)**:
  - Containerized FastAPI runtime exposed via Docker Compose `ops-api` service (`uvicorn src.infrastructure.http.ops_api:app --host 0.0.0.0 --port 9180`)。
  - Host mapping defaults到 `http://localhost:9180`，对外服务通常由反向代理（Nginx/Traefik）转发并追加 TLS。
  - 需要挂载 `logs/runbooks`（供 runbook 日志与 `ops_console_status.json` 持久化）与 `scripts/operations/`（执行最新 runbook 脚本）；若部署在 compose 之外，确保同样的目录结构与非 root 执行权限。
  - `OPS_API_TOKENS`（逗号分隔）、`OPS_PROMETHEUS_URL`（默认 `http://prometheus:9090`）、`OPS_RUNBOOK_SCRIPT` 和相关目录环境变量在 Compose `ops-api` 服务中设置，可通过 `.env` 覆盖。

## **Environments & Promotion Flow**

* A standard Development -> Staging -> Production flow is used, with CI acting as the gatekeeper for merges into the main branch.

## **Rollback Strategy**

* **Method**: Re-deploy the previously stable Docker image tag from GHCR and reapply the last-known-good configuration profile via the automation scripts.

---
