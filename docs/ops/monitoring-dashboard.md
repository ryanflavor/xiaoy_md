# Monitoring Dashboard Specification — Market Data Service

**版本 Version:** 1.1

> 对应 PRD v1.1 与 Architecture v1.1 中的监控与告警要求，本文档定义 Prometheus 指标、Grafana 仪表盘布局以及告警阈值。

---

## 1. Metrics Inventory 指标清单

| 指标 ID | 来源 | 描述 | 标签 | 采样频率 |
| :--- | :--- | :--- | :--- | :--- |
| `md_throughput_mps` | market-data-service | 每秒消息数 | `feed`, `account` | 5s |
| `md_subscription_coverage_ratio` | check_feed_health.py | 实际订阅 / 理论合约数 | `feed`, `account` | 1m |
| `md_latency_ms_p99` | market-data-service | 99 分位延迟 | `feed` | 5s |
| `md_rate_limit_hits` | subscription worker | 触发速率限制次数 | `feed` | 1m |
| `md_error_count` | market-data-service | 严重错误计数 | `component`, `severity` | 30s |
| `md_failover_latency_ms` | start_live_env.sh | 主备切换耗时 | `mode` | 事件驱动 |
| `md_runbook_exit_code` | start_live_env.sh | Runbook 返回码 | `command` | 事件驱动 |
| `consumer_backlog_messages` | downstream exporters | 下游堆积 | `consumer` | 15s |

---

## 2. Grafana Dashboard Layout 仪表盘布局

### Row 1 — Executive Overview 总览
- **Panel:** `Throughput mps (feed/account)` → 度量 `md_throughput_mps`
- **Panel:** `Subscription Coverage (%)` → 度量 `md_subscription_coverage_ratio`
- **Panel:** `Active Feed Source` → 显示当前 `feed` 标签 (primary/backup)

### Row 2 — Latency & Errors 延迟与错误
- Heatmap: `Tick Latency P99` → `md_latency_ms_p99`
- Bar chart: `Rate Limit Hits` → `md_rate_limit_hits`
- Table: `Error Events (last 1h)` → `md_error_count`

### Row 3 — Operations Ops
- Stat: `Latest Runbook Exit` → `md_runbook_exit_code` (0=green, 非 0 = red)，同时在 Grafana 注释中标记 `command`
- Timeline: `Failover Latency` → `md_failover_latency_ms`，Runbook 触发后自动标注
- Gauge: `Consumer Backlog` → `consumer_backlog_messages`
- Table: `Failover Stability` → 结合 `active_feed`、`consumer_backlog_messages` 与演练日志，为每次切换/回切生成一行包含 `md_failover_latency_ms`、`md_failback_latency_ms`、`account` 掩码，快速识别下游是否受到影响。

### Row 4 — Drilldown 深入分析
- Repeating panel by `account` 展示覆盖率与限流对比。
- Logs panel (Loki/ELK) 连接 `logs/runbooks/*.log`。

---

## 3. Alert Rules 告警规则

| 名称 | 条件 | 持续时间 | 严重级别 | 动作 |
| :--- | :--- | :--- | :--- | :--- |
| `MD_Throughput_Below_Target` | `md_throughput_mps < 5000` | 5 分钟 | Critical | 通知 #market-data-ops，触发 runbook 重启 |
| `MD_Subscription_Coverage_Drop` | `md_subscription_coverage_ratio < 0.995` | 2 分钟 | Critical | 自动运行 `check_feed_health.py --mode enforce`，若失败升级 |
| `MD_Rate_Limit_Spike` | `md_rate_limit_hits > 5` | 10 分钟 | Warning | 进入节流模式，通知 Ops 调整参数 |
| `MD_Runbook_Failure` | `md_runbook_exit_code != 0` | 即时 | Critical | PagerDuty/Ops 立即处理 |
| `MD_Failover_Latency_High` | `md_failover_latency_ms > 5000` | 1 分钟 | Critical | Ops 检查备用账户与网络 |
| `Consumer_Backlog_Growth` | `increase(consumer_backlog_messages[5m]) > 2000` | 5 分钟 | Warning | 通知下游团队，验证消费能力 |

---

## 4. Dashboard Provisioning 配置

- Grafana JSON 模板固定发布在 `docs/ops/templates/grafana/md_ops_dashboard.json`，版本号随文档更新。导入流程：
  1. 登陆运维 Grafana 实例 → Dashboards → Import。
  2. 选择 `Upload JSON file` 并指向仓库中的模板。
  3. 将数据源映射为 Prometheus（UID: `prometheus`）。
  4. 验证模版变量 `feed`、`account`、`session` 均能列出标签。
- Prometheus 抓取配置维护在 `config/prometheus/prometheus.yml`：
  - `market-data-service` job → `scrape_interval: 5s` → target `market-data-service:9100`
  - `subscription-workers` job → `scrape_interval: 60s` → target `subscription-worker:9101`
  - Pushgateway job → 监测 `pushgateway:9091` 并保留标签
- Runbook 启动时由 `subscription-worker` 容器执行 `scripts/operations/full_feed_subscription.py`，自动暴露 `md_subscription_coverage_ratio` / `md_rate_limit_hits` 指标。
- Pushgateway 服务通过 `docker compose` (`pushgateway` 服务) 暴露，`start_live_env.sh` 启动序列会自动确保 Prometheus/Pushgateway 上线。

---

## 5. Validation Checklist 验证清单

- [ ] 所有指标在预发布环境可见。
- [ ] Dashboard 导航中 `Market Data Ops` 面板上线。
- [ ] 告警通知连接 Slack/PagerDuty 并通过测试事件验证。
- [ ] 记录仪表盘 URL 与版本号。
- [ ] CI 校验通过：`tests/test_documentation.py::TestMonitoringArtifacts` 解析模板成功。

---

## 6. References 参考

- `docs/architecture.md` §2, §5, §7, §11
- `docs/sprint-change-proposal-production-ops.md` §6.2, §6.3
