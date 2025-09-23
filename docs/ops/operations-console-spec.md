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
- `/api/ops/metrics/summary` aggregates `md_subscription_coverage_ratio`, `md_throughput_mps`, `md_failover_latency_ms`, `consumer_backlog_messages`, returning computed thresholds and trend data (see backend contract in Story 3.6).
- `/api/ops/metrics/timeseries` proxied queries for chart components with server-side validation of query ranges.

### Runbook Automation APIs
- `POST /api/ops/runbooks/execute` accepts `{command: "failover" | "failback" | "restart" | "start" | "stop" | "health_check", mode: "live" | "mock", window: "day" | "night", confirmation_token}`.
- `GET /api/ops/runbooks/status` returns structured JSON: environment mode, active profile, last exit codes, pending actions, Asia/Shanghai timestamps.
- Streams runbook logs via Server-Sent Events (`/api/ops/runbooks/log-stream?command=...`) for Drill Control live tail.

Authentication & Authorization:
- Operators authenticate with SSO-backed JWT; API enforces audience `ops-console` and scopes `ops.runbook.execute` / `ops.metrics.read`.
- Per-action guard checks ensure destructive commands require `ops.runbook.admin` scope.
- Console spec documents least privilege role mapping (Ops Engineer vs Shift Lead).

---

## 7. Error Handling 失败与降级

| Scenario | UI Response | Operator Guidance |
| :--- | :--- | :--- |
| Metrics endpoint unreachable | Overview displays warning banner `无法获取指标 (Metrics Unavailable)` with retry control | Prompt to check Prometheus status; link to Runbook §5 health verification. |
| Runbook execution fails | Drill Control banner in danger color, exit code + translated message; auto-scroll to Audit Timeline entry. | Provide retry CTA, open logs modal, suggest fallback runbook command. |
| Authorization failure | Modal `权限不足 / Insufficient Privileges` with contact instructions. | Encourage Shift Lead to grant temporary token or escalate. |
| SSE stream timeout | Toast `日志流已断开` with `Reconnect` button. | On reconnect, fetch last 50 log lines for context. |

---

## 8. Audit & Compliance 审计与合规

- Every action posts to `/api/ops/audit` with payload `{action, operator_id, scope, exit_code, started_at, finished_at, metadata}`.
- Audit Timeline page exposes export to CSV (Asia/Shanghai timestamps) and log bundle download.
- UI enforces masking of sensitive account IDs, displaying masked values (`***789`) consistent with security guidelines.
- All timestamps rendered via shared helper `formatDateShanghai` ensuring `UTC+08:00` suffix (`YYYY-MM-DD HH:mm:ss +08:00`).

---

## 9. Non-Functional Requirements 非功能要求

- Initial load (cold cache) < 3.5s on LAN assuming Prometheus/API available.
- Polling interval defaults: Overview metrics 10s, charts 30s, status 5s (debounced).
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
