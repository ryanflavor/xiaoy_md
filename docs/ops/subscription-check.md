# Subscription Health Procedure — 全量订阅巡检

**版本 Version:** 1.2

本流程定义 `scripts/operations/check_feed_health.py` 的使用方式、输出解释以及补救措施，确保 Epic 3 要求的订阅覆盖率与数据质量。

---

## 1. Script Overview 脚本概览

- **路径**: `scripts/operations/check_feed_health.py`
- **功能**: 对比实时订阅列表与理论合约全集，检测漏订、停滞、速率异常，并在需要时触发补救。
- **关键参数**:
  - `--mode {dry-run,enforce,audit}`：只读、自动补救、或生成审计制品。
  - `--catalogue <file>` / `--active-file <file>`：离线运行使用本地 JSON/CSV 输入。
  - `--coverage-threshold`、`--lag-warning`、`--lag-critical`：自定义覆盖率和停滞阈值。
  - `--max-remediation-attempts`、`--escalation-marker`、`--escalation-command`：控制补救重试次数和触发 Slack/PagerDuty 等升级钩子的方式（命令支持 `{marker}`、`{exit_code}` 占位符）。
  - `--skip-metrics` / `--pushgateway-url`：控制 Prometheus Pushgateway 推送行为。
  - `--out {json,csv}`、`--out-dir`、`--log-prefix`：生成审计制品及日志的路径设置。
- **输出**: stdout 输出结构化摘要，默认生成 `logs/runbooks/<prefix>_YYYYMMDD-HHMMSS.log` JSON 日志；可选 JSON/CSV 制品用于审计。
- **指标**: 推送 `md_subscription_coverage_ratio`、`md_subscription_missing_total`、`md_subscription_stalled_total` 至 Pushgateway，标签包含 `feed`、`account`、`session_window`。
- **可视化**: Operations Console → Subscription Health 页面实时展示最近一次健康检查的覆盖率、缺失/停滞合约以及警告/错误摘要，可作为脚本输出的双语可视化入口。

---

## 2. Required Inputs 输入前置条件

| 变量/参数 | 描述 | 示例 |
| :--- | :--- | :--- |
| `NATS_URL` | 控制平面连接地址（未提供 `--catalogue`/`--active-file` 时必填） | `nats://127.0.0.1:4222` |
| `NATS_USER` / `NATS_PASSWORD` | 控制平面认证信息 | `ops_user` |
| `--catalogue` | 本地合约全集（JSON `{"symbols": []}` 或 CSV 第一列） | `config/contracts/full_catalogue.json` |
| `--active-file` | 活跃订阅快照（JSON `{"subscriptions": []}`） | `logs/runbooks/subscriptions_live.json` |
| `--coverage-threshold` | 覆盖率告警阈值（默认 `0.995`） | `0.999` |
| `--lag-warning` | 停滞警告阈值（秒，默认 `120`） | `180` |
| `--lag-critical` | 停滞错误阈值（秒，默认 `300`） | `240` |
| `--skip-metrics` | 禁止向 Pushgateway 推送样本 | `--skip-metrics` |
| `--max-remediation-attempts` | `--mode enforce` 下的最大自动重试次数（默认 3） | `2` |
| `--escalation-marker` | 升级日志标记（默认 `subscription_health_escalation`） | `md_ops_escalation` |
| `--escalation-command` | 升级时执行的 shell 命令（支持 `{marker}`、`{exit_code}` 占位符） | `./scripts/notify_slack.sh --tag {marker}` |

---

## 3. Execution 知识步骤

### 3.1 Hourly Cron 每小时巡检

```
0 * * * * cd /srv/market-data-service && \
  uv run python scripts/operations/check_feed_health.py \
    --mode enforce \
    --out-dir logs/runbooks/subscription-hourly \
    --out json --out csv
```

### 3.2 Manual Run 手工执行

```
uv run python scripts/operations/check_feed_health.py \
  --mode dry-run \
  --catalogue config/contracts/full_catalogue.json \
  --skip-metrics --json-indent 2
```

---

## 4. Output Interpretation 输出解读

| 字段 | 含义 | 处理建议 |
| :--- | :--- | :--- |
| `coverage_ratio` | 覆盖率（匹配 / 期望） | < 阈值 → 立即补救或升级 |
| `missing_contracts[]` | 漏订合约列表 | `--mode enforce` 自动补订，仍失败则人工处理 |
| `stalled_contracts[]` | 停滞合约，附带秒级滞后与严重级别 | `critical` → 触发补救，`warning` → 监控下轮复核 |
| `unexpected_contracts[]` | 非合约全集内的活跃订阅 | 审核数据源/控制平面配置 |
| `remediation.rate_limit_events` | 补救时触发限流次数 | 检查 `AppSettings` 中 rate limit 配置 |
| `exit_code` | 退出码 | 0=健康，1=警告（需要复查），≥2=错误（需补救/升级） |

---

## 5. Remediation Workflow 补救流程

1. **自动补订** (`--mode enforce`)
   - 直接发布 `md.subscribe.bulk` 请求补订缺失与严重停滞的合约。
   - 每次补救均记录 `event=remediation_attempt` / `event=remediation_result`，包含 `attempt`、`max_attempts`、限流统计等字段。
   - 若连续 `--max-remediation-attempts` 次（默认 3）仍保持退出码 ≥2，则触发升级路径。
2. **手动干预**
   - 执行 `uv run python scripts/operations/full_feed_subscription.py --contracts <file>` 或使用控制平面自助脚本。
   - 确认 Grafana 面板 `Subscription Coverage` 恢复至 ≥99.5%。
3. **升级路径**
   - 脚本输出 `event=health_check_escalation`，携带 `marker`、`attempts`、`missing`、`stalled` 字段。
   - 如定义 `--escalation-command`（例如 Slack/PagerDuty webhook 包装脚本），将以 shell 命令执行并记录 `event=escalation_command_executed` 或 `event=escalation_command_error`。
   - 若 `stalled_contracts` critical > 0 持续两个周期：通知 Tech Lead。
   - 若 `rate_limit_events` 持续 > 5，每分钟：与账户运营沟通调整限流策略。

---

## 6. Audit & Reporting 审计与报告

- `--out json` / `--out csv` 可生成制品至 `--out-dir`（默认 `logs/runbooks/`）。
- 日终将 `logs/runbooks/subscription_check_*.log` 与制品归档至集中存储（如 S3/NAS）。
- 每周生成巡检报告：统计覆盖率、异常次数、补救耗时与限流事件。

---

## 7. Checklist 巡检检查清单

- [ ] 成功运行脚本并获取退出码。
- [ ] Grafana 告警已处理或静默（如适用）。
- [ ] 缺失/停滞合约均有补救记录。
- [ ] 更新运维日志与 Jira 记录。

---

## 8. References 参考

- `docs/architecture.md` — Components §5, Workflows §7
- `docs/ops/production-runbook.md` — Section 5
- `docs/sprint-change-proposal-production-ops.md` — Story 3.4
