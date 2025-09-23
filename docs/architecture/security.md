# **15\. Security**

We enforce pragmatic security controls suitable for an internal production feed while aligning with Epic 3's multi-account governance needs.

* **Input Validation**: Handled by Pydantic models.
  **输入验证**：由 Pydantic 模型负责。
* **Secrets Management**: All CTP credentials (primary/backup), NATS users, and rate-limit tokens **must** load via Pydantic BaseSettings from environment variables or Vault-backed secret files. `.env.example` documents required keys; production secrets reside in Vault/secret manager with short-lived leases.
  **机密管理**：主/备账户、NATS 用户、速率限制密钥必须通过环境变量或 Vault 支持的安全文件注入，并由 Pydantic BaseSettings 管理。
* **Secrets Distribution Workflow**: Operators extract the `CTP_PRIMARY_*` / `CTP_BACKUP_*` blocks from Vault into a transient `.env.runtime`, execute `uv run python scripts/operations/validate_env.py --profile live --source .env.runtime` to fail fast on misconfiguration, and then launch `start_live_env.sh`. The runtime file is shredded after startup to maintain least exposure.（运维人员先将 `CTP_PRIMARY_*`、`CTP_BACKUP_*` 从 Vault 写入临时 `.env.runtime`，运行 `uv run python scripts/operations/validate_env.py --profile live --source .env.runtime` 以提前发现配置错误，再执行 `start_live_env.sh`；启动完成后立即销毁临时文件，以降低泄露风险。）
* **Traceability**: Each secrets update references Story 3.2 《环境变量与秘密管理治理》，保证运营人员能追溯凭证治理来源，并与 `docs/ops/production-runbook.md` 的盘前步骤保持一致。
  **可追溯性**：所有密钥更新需标注 Story 3.2 《环境变量与秘密管理治理》，并与 `docs/ops/production-runbook.md` 中的盘前步骤映射，确保跨文档一致。
* **Credential Rotation**: Runbook `start_live_env.sh --failover/--failback` doubles as the rotation procedure; rotation events log to Ops journal and trigger health verification.
  **凭证轮换**：利用 `start_live_env.sh` 的 failover/failback 流程执行轮换，并记录日志。
* **Dependency Security**: CI includes `uv pip audit` / `pip-audit` to detect known vulnerabilities; runbook artifacts capture the audit version.
  **依赖安全**：CI 管道执行依赖漏洞扫描。
* **Transport Security**: NATS connections use credential-authenticated TCP; when promoted beyond LAN, enable TLS certificates managed by Ops.
  **传输安全**：NATS 连接需启用凭证认证，并可按需开启 TLS。
* **Authentication/Authorization**: Not in scope for consuming clients within MVP, but runbooks require PAM/SSH access control.
  **认证/授权**：MVP 阶段未对下游开放复杂鉴权，但运维脚本需通过受控 SSH/PAM。
* **Audit Logging**: Runbook executions and subscription health checks append structured entries to `logs/runbooks/` with timestamp, operator, exit code, and actions; Prometheus retains status metrics for 30 days.
  **审计日志**：Runbook 与巡检脚本必须写入结构化日志，Prometheus 保留指标 30 天。

---
