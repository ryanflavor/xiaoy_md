# Production Runbook — Market Data Service

**版本 Version:** 1.1 (Aligned with PRD v1.1 / Architecture v1.1)

> 本 Runbook 旨在指导运维人员以一致、可审计的方式启动、监控、重启和关闭 CTP 行情生产环境。

---

## Session Timelines 交易时段时间线

### Day Session 日盘时段
- **Session Hours:** 09:00 - 15:00 (CST)
- **T-5 Target:** Complete all checks by 08:55
- **Buffer Time:** 08:55 - 09:00 for remediation

### Night Session 夜盘时段
- **Session Hours:** 21:00 - 02:30 (CST)
- **T-5 Target:** Complete all checks by 20:55
- **Buffer Time:** 20:55 - 21:00 for remediation

---

## 1. Pre-Market Startup 盘前启动

### Day Session Startup (Execute by 08:45)

1. **Validate Environment Variables 环境验证**
   - `uv run python scripts/operations/validate_env.py --profile live --source .env.live`，对 `CTP_PRIMARY_*` / `CTP_BACKUP_*`、`RATE_LIMIT_*`、监控开关执行严格校验，并输出建议修复步骤。
   - 如 `.env.live` 由 Vault 生成，先运行 `vault read ... > .env.runtime` 再执行 `validate_env.py --source .env.runtime`，确认通过后再加载到 shell 会话。
   - 检查 `.env.live` 中的速率限制及订阅批量配置是否与当日计划一致；参考 `.env.example` 注释保持变量映射清晰。
   - 切换备账户前先确认 `.env.live` 中 `CTP_BACKUP_*` 全部就绪，并将 `ACTIVE_FEED=backup` 或在运行脚本时传入 `--config backup`，确保 runbook 与监控仪表盘都指向正确的账户。
   - **Failure Handling:** If validation fails → 修复 `.env.live` / `.env.runtime`，重新运行脚本直至返回 `EXIT 0`。
   - **Audit:** Log validation timestamp to `logs/runbooks/startup_audit.log`
2. **Warm Up Secrets 预热密钥**
   - 如果使用 Vault/密钥管理服务：执行 `vault read secret/ctp/live` 并写入 `.env.runtime`。
3. **Execute Runbook Script 执行启动脚本**
   - Day Session: `./scripts/operations/start_live_env.sh --window day --profile live --log-dir logs/runbooks`
   - Night Session: `./scripts/operations/start_live_env.sh --window night --profile live --log-dir logs/runbooks`
   - 该脚本顺序启动：NATS → market-data-service → full_feed_subscription.py。
   - **Failure Handling:** Non-zero exit code → check logs, retry with `--debug`, escalate if 3 failures
   - **Audit:** Record exit code as metric `md_runbook_exit_code`
4. **Verify Health 校验健康状态**
 - 观察脚本输出，确认 `HEALTH=READY` 标记出现。
  - `uv run python scripts/operations/check_feed_health.py --mode dry-run --skip-metrics --json-indent 2`，确认覆盖率≥99.5%，`missing_contracts[]` 为空。
  - 核对最新日志 `logs/runbooks/subscription_check_*.log`，确保无 `exit_code>=2` 或 `event=health_check_escalation` 记录。
  - 打开 Operations Console → Overview 页面，确认 Coverage Ratio、Throughput、Failover Latency 卡片均处于绿色或蓝色状态；如显示告警颜色，进入 Subscription Health 页面排查缺失/停滞合约。
  - 通过 Console → Drill Control 页面执行一次 `Run Health Check`（mock 模式）以验证控制台认证与 API 返回是否正常。
5. **Register Metrics 注册监控指标**
   - 检查 Prometheus Target `market-data-service-live` 状态为 `UP`。
   - `curl -sf http://localhost:9100/metrics | grep md_throughput_mps` => 返回最近样本。
   - `curl -sf http://localhost:9101/metrics | grep md_subscription_coverage_ratio` => 订阅工作流指标就绪。
   - `curl -sf http://localhost:9091/metrics | egrep 'md_subscription_(coverage_ratio|missing_total|stalled_total)'` => Pushgateway 缓存最新健康样本。
   - `curl -sf http://localhost:9091/metrics | grep md_runbook_exit_code` => Pushgateway 缓存可读。
   - `uv run python scripts/operations/alert_smoke.py --wait-seconds 3` → 验证 Prometheus API 能读取推送的 `md_runbook_exit_code`（完成后自动复位）。
   - 在 Grafana Dashboard *MD Ops* 中确认以下面板：
     - Throughput mps ≥ 5,000
     - Subscription Coverage = 100%
     - Rate Limit Incidents = 0
   - **T-5 Checkpoint:** All metrics green by 08:55 (day) or 20:55 (night)
   - **Failure Handling:** Metrics unavailable → `docker compose --profile live up -d pushgateway prometheus` 并重新 `start_monitoring_stack`
   - **Audit:** Screenshot dashboard, save to `logs/runbooks/$(date +%Y%m%d)_startup.png`

### Night Session Startup (Execute by 20:45)

Follow same steps as Day Session with adjusted timeline:
- Start environment validation at 20:45
- Complete health checks by 20:50
- T-5 checkpoint must pass by 20:55
- Use `--window night` flag for session-specific configuration

---

## 2. Intra-Day Restart 盘中重启流程

> 仅当监控报警或手动确认需要重启时执行。

1. 通知下游消费者 (Slack/钉钉频道 #market-data-ops)。
2. 执行 `./scripts/operations/start_live_env.sh --restart --window <day|night> --profile live`。
3. 确认脚本输出中 `GRACEFUL_SHUTDOWN=OK` 与 `RESTART=OK`。
4. 运行 `check_feed_health.py --mode enforce`；若检测到缺失自动触发重订阅。
5. 在 Grafana 中确认 `Consumer Lag` 没有异常峰值；若存在，需要进一步调查。
6. 记录 Jira/运维日志：时间、原因、执行人、运行结果。

---

## 3. Planned Shutdown 收盘/计划停机

1. `./scripts/operations/start_live_env.sh --stop --window <day|night> --profile live`。
2. 确认以下组件状态：
   - NATS live profile 关闭 (`docker compose ps` 无 `market-data-live` 服务)。
   - 订阅脚本停止，日志包含 `UNSUBSCRIBED`。
3. 归档日志：`tar -czf logs/archive/$(date +%Y%m%d)_runbook.tar.gz logs/runbooks logs/soak`。
4. 清理敏感 `.env.runtime` 文件。

---

## 4. Emergency Failover 紧急故障切换

1. **触发条件**：
   - 主账户连接失败 > 3 次。
   - Prometheus 指标 `feed_failover_required` > 0。
2. **执行步骤**：
   - 优先使用 Operations Console → Overview 页面中的 “Trigger Failover / 触发故障切换” 卡片，控制台会在执行前弹出双语确认框，并在完成后显示 JSON 结果与延迟指标。如控制台不可用，再回退到以下 CLI 流程。
   1. `./scripts/operations/start_live_env.sh --failover --window <day|night> --profile live --config backup`。
   2. 脚本会导出 `ACTIVE_FEED=backup` 并加载 `CTP_BACKUP_*` 环境变量；所有 JSON 日志都带有 `"config":"backup"` 和屏蔽后的 `"account"` 字段便于审计。
   3. 监控 `md_failover_latency_ms` 指标必须 < 5,000ms。
3. **验证**：
   - Grafana 面板 `Feed Source` 显示 `backup`。
   - `check_feed_health.py --mode enforce` 返回 `EXIT 0`。
   - 下游消费无新增错误：检查 `Consumer Error Rate` 面板。
4. **复盘**：
   - 在运维日志记录触发原因、开始/结束时间、指标表现。
   - 评估是否需要回切主账户 (`--failback`).

## 4.1 Failover Drill Workflow 故障演练流程

> 每周例行执行一次演练以验证 runbook、监控与备份账户的可靠性。

1. **启动演练**
  - `./scripts/operations/start_live_env.sh --drill --profile live --log-dir logs/runbooks`
  - 可选：`./scripts/operations/run_drill_tests.sh` 触发演练相关的 pytest 套件（自动附加 `--no-cov`，避免覆盖率门槛影响冒烟结果）。
  - 如需指定校验指标的标签，可设置 `DRILL_EXPECT_FEED`（默认采用当前 `SESSION_CONFIG`）与 `DRILL_EXPECT_ACCOUNT` 环境变量，确保 `verify_consumer_metrics` 只检查目标 feed/account。
   - 参数可与实际窗口匹配：`--window day|night`。
2. **脚本流程**
   - 自动启动主账户 → 切换至备账户 → 回切主账户，期间每个阶段都会调用 `check_feed_health.py --mode enforce`（可通过 `DRILL_HEALTH_CMD` 覆盖）。
   - 若需要离线校验监控，可在执行前导出 `DRILL_METRICS_SOURCE=/path/to/metrics.prom` 或 Prometheus URL，脚本会读取 `consumer_backlog_messages` 并与 `DRILL_CONSUMER_BACKLOG_THRESHOLD`（默认 2000）对比。
3. **验收标准**
   - `md_failover_latency_ms` / `md_failback_latency_ms` < 5,000ms。
   - 演练输出中 `"account"` 字段保持屏蔽显示，`"active_feed"` 在备份阶段变为 `backup`。
   - 监控验证通过（`verify_consumer_metrics` 日志为 INFO）；如超过阈值脚本会以退出码 43/45 终止。
4. **审计**
   - `logs/runbooks/start_live_env.log` 中会有 `Failover drill completed successfully` 记录。
   - `logs/runbooks/startup_audit.log` 追加 `drill` 条目，方便对演练频率进行取证。

---

## 5. Routine Health Checks 日常健康巡检

| 任务 | 命令 | 频率 |
| :--- | :--- | :--- |
| 订阅覆盖率复核 | `uv run python scripts/operations/check_feed_health.py --mode enforce --out json --max-remediation-attempts 3 --escalation-command './scripts/notify_slack.sh --tag {marker} --code {exit_code}'` | 每小时 (cron) |
| 吞吐速率趋势 | Grafana 面板 `Throughput mps` | 持续监控 |
| 限流/错误日志 | `tail -n 200 logs/runbooks/start_live_env.log` | 每 4 小时 |
| 合约列表更新 | `uv run python scripts/tools/refresh_contracts.py` | 每日盘前 |

---

## 6. Failure Handling Matrix 故障处理矩阵

| Stage | Failure Indicator | Immediate Action | Escalation (if 3 attempts fail) | Audit Record |
|-------|------------------|------------------|----------------------------------|---------------|
| Environment Validation | Missing env vars | Reload `.env.live`, verify | Contact DevOps for secrets refresh | `startup_audit.log` |
| NATS Startup | Connection refused | Check Docker, restart service | Switch to backup NATS cluster | `md_runbook_exit_code` |
| Market Data Service | Health check timeout | Restart with `--debug` | Check CTP connectivity | `health_check.log` |
| Subscription Worker | Coverage < 100% | Run `check_feed_health.py --enforce` | Manual subscription via script | `subscription_audit.log` |
| Metrics Registration | Prometheus DOWN | Restart exporters | Check network/firewall | Dashboard screenshot |
| T-5 Checkpoint | Not ready by deadline | Execute remediation steps | Notify trading desk of delay | `t5_checkpoint.log` |

## 7. Incident Logging 事件记录模板

```yaml
incident:
  date_time: # Asia/Shanghai timestamp
  session: # day|night
  operator: # Name/ID
  trigger: # What initiated the incident
  actions: # Steps taken
  metrics:
    - md_runbook_exit_code: # Exit code value
    - md_failover_latency_ms: # If failover occurred
  outcome: # Resolution status
  follow_ups: # Required actions
  audit_files:
    - # List of relevant log files
```

## 8. Operations Console Usage 控制台操作指南

> Story 3.6 引入的前端控制台可在不直接 SSH 登录的情况下执行运维 Runbook 操作，并实时展示 Prometheus 指标。

- **入口**：`ui/operations-console` 构建的 Web 前端，通过 Nginx 或 Vite Preview 暴露于 `https://ops-console.local/`。首次访问需提供 `OPS_API_TOKEN`（Bearer 头）。
- **Overview 总览**：
  - Coverage / Throughput / Failover Latency / Backlog 等核心指标与色彩状态同步 Prometheus。
  - 右侧 Runbook 状态展示最近一次操作与健康检查结果，支持一键触发 `failover`、`failback`，执行前有双语确认弹窗，执行后展示 JSON 响应与 Asia/Shanghai 时间戳。
- 详细角色、导航与状态图请参阅 `docs/ops/operations-console-spec.md`。
- **Drill Control 演练控制**：
  - `Start Drill`：mock 模式调用 `start_live_env.sh --drill` 包装 API，日志在面板内可预览，完成后自动刷新 Audit Timeline。
  - `Run Health Check`：调用 `check_feed_health.py --mode enforce`（mock/live），用于演练前预检。
- **Subscription Health 订阅健康**：
  - 显示最后一次健康检查的缺失/停滞合约、警告/错误摘要。
  - 操作员可在 CLI 审计之前先从页面获取关键异常详情。
- **Audit Timeline 审计时间线**：
  - 按时间倒序列出所有控制台执行的 Runbook 操作，含 `command`、`window`、`profile`、`exit_code`、`finished_at` 与 `reason` 字段。
  - 使用 `Export CSV`（后续 roadmap）可导出同一数据集，当前可通过 API 响应中的 raw_output 下载。
- **降级策略**：若控制台无法访问， fall back 到脚本流程；所有 console 操作仍写入 `logs/runbooks/start_live_env.log` 与 Pushgateway 指标，确保审计一致性。

---

## 8. Audit Trail Requirements 审计追踪要求

### Required Logging
- All orchestration commands must emit structured JSON logs
- Timestamps must use Asia/Shanghai timezone (UTC+08:00)
- Exit codes must be pushed to Prometheus via Pushgateway
- Session type (day/night) must be included in all log entries

### Metrics Collection
- `md_runbook_exit_code`: Capture for every script execution
- `md_failover_latency_ms`: Measure when failover occurs
- `md_t5_checkpoint_status`: Binary (0=failed, 1=passed)
- `md_session_startup_duration_s`: Time from start to ready

### Log Retention
- Runbook logs: 30 days minimum
- Audit screenshots: 7 days
- Incident reports: 90 days
- Metrics: Per Prometheus retention policy

## 9. References 参考资料

- `docs/prd.md` — MVP Operational Scope Update
- `docs/architecture.md` — Sections 2, 5, 7, 11
- `docs/sprint-change-proposal-production-ops.md` — Epic 3 Actions
