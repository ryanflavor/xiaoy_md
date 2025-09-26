# Operations Console Specification — Market Data Ops

**版本 Version:** 0.1 (Story 3.6 implementation)

> Drives Story 3.6 acceptance criteria for the operations monitoring console. Anchored to PRD v4, Architecture v4, and Ops Runbook v1.1.

---

## 1. Personas & Outcomes 角色与目标

| Persona | Primary Goals | Pain Points Addressed |
| :--- | :--- | :--- |
| **Ops Engineer (当班运维)** | Monitor live coverage/throughput, trigger scripted remediation, capture evidence. | Fragmented tooling, inconsistent drill execution, manual log scraping. |
| **Shift Lead (班长)** | Coordinate failover/failback, approve high-risk actions, maintain audit trail. | No single view of drill history and operator actions. |
| **SRE / Automation Owner** | Validate automation health, observe metric gaps, tune thresholds. | Hard to correlate metrics, runbook outputs, and annotation timelines. |

Success metrics:
- < 90s to evaluate health and launch remediation from Overview.
- Drill completion tracked with annotated metrics and audit entries in < 2 clicks.
- Runbook-triggered actions automatically produce bilingual confirmations and JSON log references.

---

## 2. Information Architecture 信息架构

Global layout: dark technology aesthetic, desktop-first (1440×900 reference), responsive down to 1280px.

Navigation (left rail):
1. **Overview 总览** — KPI tiles, status badges, active profile banner.
2. **Drill Control 演练控制** — Start/monitor drills, failover/failback controls, dry-run previews.
3. **Subscription Health 订阅健康** — Coverage trends, missing contracts table, remediation shortcuts.
4. **Audit Timeline 审计时间线** — Chronological ledger of actions, metrics annotations, exports.

Top-right cluster: Session selector (Day/Night/Mock), profile indicator (Primary/Backup), user menu with auth context.

Breadcrumbs show page context plus latest drill status capsule (Idle, Running, Failed).

---

## 3. State Models 状态模型

### 3.1 Normal State 正常态
```
[Idle Monitoring]
   │ (Prometheus metrics healthy)
   ▼
[Overview KPIs Green] --(Alert fired)--> [Incident Detected]
```
- KPIs (coverage, throughput, failover latency) above thresholds.
- Action buttons disabled for destructive flows until confirmation dialog is acknowledged.
- Audit Timeline streams compressed entries (collapsed by default) with filters by action type.

### 3.2 Incident State 故障态
```
[Incident Detected]
   │ (Operator opens Drill Control)
   ▼
[Action Selected]
   │ (Double confirmation + token check)
   ▼
[Runbook Execution]
   │ (Success)─────────┐
   │ (Failure)         │
   ▼                   ▼
[Status Banner: Resolved]   [Status Banner: Failed]
```
- Overview displays red banner with failed KPI, affected feed/account chips.
- Drill Control surfaces remediation cards (Failover, Restart, Health Check) with live log tail (last 20 lines) and JSON output download.
- Audit Timeline pins incident start/end, linking to log bundle.

### 3.3 Drill State 演练态
```
[Drill Idle]
   │ (Schedule or Manual Start)
   ▼
[Drill Running]
   │ (Stage complete)
   ├──> [Stage: Switch to Backup]
   │ (Stage complete)
   └──> [Stage: Switch to Primary]
   │
   ▼
[Drill Completed]
```
- Timeline tags drill stages with `success`, `warning`, `error` statuses.
- Mock mode optionally redirects metrics to fixtures; UI labels show `模拟演练` ribbon.
- Completion triggers summary modal with coverage delta, latency figures, exit codes.

---

## 4. Visual Language 视觉规范

Design tokens defined in `ui/operations-console/src/styles/tokens.ts` (see Story 3.6 UI tasks):

| Token | Value | Usage |
| :--- | :--- | :--- |
| `color.background` | `#0F172A` | App shell background. |
| `color.surface` | `#1E293B` | Card/panel surfaces. |
| `color.primary` | `#38BDF8` | Primary actions, active nav, charts. |
| `color.success` | `#22C55E` | Healthy status, positive metrics. |
| `color.warning` | `#F97316` | Degradation warnings. |
| `color.danger` | `#F43F5E` | Critical failures, destructive actions. |
| `color.neutralHigh` | `#E2E8F0` | Primary text on dark surfaces. |
| `color.neutralMid` | `#94A3B8` | Secondary text, helper labels. |
| `typography.primary` | Inter, 14–20px, 1.5 line height | Latin text. |
| `typography.secondary` | 思源黑体, 14–20px | Chinese copy. |
| `shadow.card` | `0 16px 40px rgba(15, 23, 42, 0.48)` | Elevation for main panels. |

Accessibility:
- WCAG AA contrast compliance for primary text on dark surfaces (>4.5:1).
- Focus outlines use `color.primary` at 2px offset; keyboard navigation order matches visual layout.
- High-density data tables offer density toggle and column pinning.

Micro-interactions:
- Action buttons animate with 120ms scale/opacity transition.
- Status banners use subtle gradient overlays (primary/danger) with iconography from Phosphor Icons.
- Confirmation dialogs slide up from bottom center (320px max width) with bilingual copy.

---

## 5. Component System 组件体系

### Core Components
- `HealthStatCard` — Title, value, trend sparkline, bilingual tooltip.
- `StatusBadge` — Tokenized severity color, optional countdown for SLA.
- `MetricChart` — Prometheus-backed line/area chart with live polling.
- `ActionPanel` — Contains action summary, pre-flight checklist, confirmation CTA.
- `DrillTimeline` — Stage progression with latency chips and runbook links.
- `AuditTable` — Virtualized table listing timestamp, operator, action, exit code, download link.

### Interaction Patterns
- Actions require two-step confirmation (`Confirm`, then `Execute`), plus optional dry-run preview where available.
- Bulk actions (e.g., `Restart All`) require Shift Lead approval; UI prompts for privileged token.
- Notification system surfaces success/failure toasts with JSON log anchors (`logs/runbooks/...`).
- Localization strings managed via `i18n/en.json` and `i18n/zh.json`, keys `opsConsole.*`.

---

## 6. Data Integration 数据集成

### Prometheus Metrics
- `GET /api/ops/metrics/summary` aggregates `md_subscription_coverage_ratio`, `md_throughput_mps`, `md_failover_latency_ms`, and `consumer_backlog_messages`，并附带上下文字段：覆盖率返回 `expected/covered/ignored` 统计，吞吐率使用 `max_over_time(...[1m])`，缺少 backlog 样本时返回 `null` 以驱动 “Awaiting exporter data” 提示。
- `GET /api/ops/metrics/timeseries` proxies Prometheus range queries with backend-side guardrails on lookback windows and step size；UI 默认拉取 120 分钟/60 秒采样。

### Runbook Automation APIs
- `POST /api/ops/runbooks/execute` 接收 `{command, mode, window, profile, config?, reason?, enforce?, dry_run?, confirmation_token?}`，返回 `ExecutionEnvelope`（Runbook 记录 + 可选健康快照）。
- `GET /api/ops/status` 返回持久化的 `OperationsStatusState`：最后一次 Runbook、活跃账户、健康历史、Asia/Shanghai 时间戳。
- 所有响应均以 JSON 返回；结构化日志（`logs[]`）内嵌在执行结果中，供 UI 渲染或下载。

Authentication & Authorization:
- API 采用静态 Bearer Token（`OPS_API_TOKENS`）校验；支持逗号分隔多令牌，便于轮换。
- 允许访问的控制台来源通过 `OPS_API_CORS_ORIGINS` 配置，默认取值 `*` 以支持任意局域网来源；如需锁定范围，可在 `.env` 中改写为逗号分隔的具体来源，并确保 `OPS_API_CORS_METHODS` 包含 `OPTIONS`。
- 前端通过 `.env` 注入 `VITE_OPS_API_TOKEN`，在请求头添加 `Authorization: Bearer <token>`。
- 权限粒度后续可扩展为双 Token（读/写）；当前环境默认单 Token 具备读写能力，仍由 Runbook 确认弹窗提供防护。

---

## 7. Error Handling 失败与降级

| Scenario | UI Response | Operator Guidance |
| :--- | :--- | :--- |
| Operations API unreachable / 5xx | 顶部出现 Danger 级别双语告警横幅，展示排查建议（校验 ops-api 服务、网络代理） | 登录主机检查 `docker compose ps ops-api`、`logs/runbooks/ops_console_status.json`，必要时回退脚本执行。 |
| Metrics query failure | KPI 卡片显示 `--` 与黄色状态，Error Banner 提示检查 Prometheus；图表区域提示无法加载数据 | 验证 `prometheus:9090` 可用性，必要时重启监控栈或切换至 Runbook 指标核对。 |
| Runbook执行 4xx/失败 | ActionPanel 内联展示双语错误说明，Audit Timeline 仍记录执行尝试 | 复核令牌权限或命令参数；连续失败 3 次改用 CLI Runbook 并在日志中标记。 |
| Token 无效/过期 | Error Banner 显示 “请求未授权”，ActionPanel 禁止继续执行 | 重新申请/轮换 `OPS_API_TOKENS` 并更新 `.env`，同步记录审计。 |

---

## 8. Audit & Compliance 审计与合规

- Every action posts to `/api/ops/audit` with payload `{action, operator_id, scope, exit_code, started_at, finished_at, metadata}`.
- Audit Timeline page exposes export to CSV (Asia/Shanghai timestamps) and log bundle download.
- UI enforces masking of sensitive account IDs, displaying masked values (`***789`) consistent with security guidelines.
- All timestamps rendered via shared helper `formatDateShanghai` ensuring `UTC+08:00` suffix (`YYYY-MM-DD HH:mm:ss +08:00`).

---

## 9. Non-Functional Requirements 非功能要求

- Initial load (cold cache) < 3.5s on LAN assuming Prometheus/API available.
- Polling interval defaults: Overview metrics 60s（匹配 1 分钟吞吐峰值窗）、图表 30s、Status 5s（带去抖）。
- UI tests validate accessibility (axe-core), i18n completeness, and Prometheus query guardrails.
- Must run fully offline against mock APIs for drills; fixture data lives in `ui/operations-console/tests/__fixtures__`.

---

## 10. Open Questions & Future Enhancements

1. Evaluate WebSocket vs SSE for runbook logs once backend throughput validated.
2. Consider session-based risk scoring to prioritize alerts during high-volume windows.
3. Assess integration with Ops paging system for in-app acknowledgements.

---

**Related References:**
- `docs/ops/monitoring-dashboard.md`
- `docs/ops/production-runbook.md`
- `docs/architecture/observability-and-ops.md`
- `docs/architecture/security.md`
