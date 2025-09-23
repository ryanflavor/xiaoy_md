# Sprint Change Proposal — 生产运维与多源扩展
Date: 2025-09-18
Triggering Story: docs/stories/2.5.story.md
Requested by: 压力测试执行后（Tech Lead）

---

## 1) Identified Issue Summary
- **触发背景**：Story 2.5 完成 1 小时 soak，达到 ≥5,000 mps 性能目标，证明链路可行。
- **核心问题**：进入生产环境需要一套可持续运营的架构与流程，目前缺失：
  - NATS、`market-data-service` 等服务的长期托管方式；必须提前在交易前启动、每天盘前重启。
  - 环境变量/秘密管理：真实账户、速率限制、订阅策略均需规范配置。
  - `scripts/operations/full_feed_subscription.py` 必须成为标准化订阅 runbook；加载失败、速率异常需有提示。
  - 对下游影响最小化，需要实时监控订阅覆盖率、漏 tick、延迟、错误率。
  - 多账户、行情源故障切换（例如主 CTP 异常时切换备用）尚无方案。
  - 后续 Post-MVP 功能（如 SOPT）在架构上需要预留。

---

## 2) Context & Evidence (Checklist §1)
- **Story 确认**：2.5 完成 soak；2.1~2.4 完成底层接入。
- **问题类型**：新识别的生产级非功能需求（Ops、监控、稳定性）。
- **影响评估**：
  - 上线时若缺乏启动/监控/切换机制，将导致服务不稳定或下游数据缺失。
  - 多账户/多源未规划会限制扩展性。
- **证据**：
  - Soak 日志显示性能达标；
  - 当前 `docker compose --profile live up -d market-data-live`、`uv run ... full_feed_subscription.py` 需手工执行；
  - 无运维文档或监控面板草稿。

Checklist §1 状态：
- [x] Identify Triggering Story
- [x] Define the Issue
- [x] Assess Initial Impact
- [x] Gather Evidence

---

## 3) Epic Impact Assessment (Checklist §2)
- **当前 Epic 2**：定位于“CTP 行情接入与发布”。保持成果，不再追加运维类故事。
- **未来 Epic**：新增 `Epic 3：生产运维与多源扩展`，涵盖上线所需能力与多源扩展。
- **Epic 顺序**：Epic 3 紧接 Epic 2；多源/SOPT 属 Epic 3 后期或后续 Epic。
- **依赖关系**：无须回退现有成果；Epic 3 依赖 Epic 2 基础设施。

Checklist §2 状态：
- [x] Current Epic 可继续；范围保持
- [x] Future Epics 需新增并调整顺序
- [x] Epic Impact 总结：新增 Epic 3，聚焦运维与扩展

---

## 4) Artifact Conflict & Impact Analysis (Checklist §3)
- **PRD (`docs/prd/epics-史诗.md`, `docs/prd.md`)**
  - 新增 Epic 3 描述，明确运维与扩展目标。
  - 补充 Story 列表（详见 §6 提议故事）。
  - 更新 MVP 说明：上线需具备运维/监控能力。
- **Architecture**
  - `infrastructure-and-deployment.md`：补充常驻服务管理、盘前 runbook、docker-compose live 操作规范、故障切换策略。
  - 新增/扩展运维文档，例如 `observability-and-ops.md`，定义监控指标、告警策略、Prometheus/Grafana 集成。
- **Ops Runbook**
  - 创建 `docs/ops/`，至少包含：
    - `production-runbook.md`：启动顺序、每日例行、重启流程。
    - `subscription-check.md`：`full_feed_subscription` 脚本使用说明、参数、错误处理。
    - `monitoring-dashboard.md`：关键指标与仪表盘布局。
- **脚本/配置说明**
  - `.env.example`、`README.md` live 环境段落补充真实配置范例。
  - 订阅脚本/启动脚本加上操作提示。
- **测试/QA 文档**
  - QA 需要新增“生产监控验证”流程：订阅覆盖率、漏 tick 检测、速率偏差、故障切换演练。

Checklist §3 状态：
- [x] PRD 更新需求确认
- [x] 架构文档需扩充
- [x] Frontend/监控界面需新增规划
- [x] 其他工件（runbook、脚本说明、QA 文档）需创建/更新
- [x] Artifact Impact 总结记录

---

## 5) Path Forward Evaluation (Checklist §4)
- **Option 1: Direct Adjustment**（在 Epic 2 内继续追加）→ 不推荐，范围失焦。
- **Option 2: Rollback** → 无意义。
- **Option 3: Re-scope 新 Epic** → 推荐方案，新增 Epic 3 负责生产运维与多源扩展。

Checklist §4 状态：
- [x] Option 1 评估（否）
- [x] Option 2 评估（否）
- [x] Option 3 评估（是）
- [x] Recommended Path：Option 3（新增 Epic 3）

---

## 6) Specific Proposed Edits & Story Seeds

### 6.1 PRD & Backlog
1. **新增 Epic 3 概述**
   Goal：交付可持续运营的行情服务，支持多账户、多行情源与未来接口扩展。
   核心需求：自动/手动启动控制、环境配置、监控与告警、故障切换、多账户路由、扩展接口（如 SOPT）。

2. **首批 Story 建议**
   - Story 3.1：生产环境启动/停机编排
     - AC：文档化每日 runbook；脚本支持 NATS、market-data-service、订阅脚本的顺序执行；记录状态与失败处理。
   - Story 3.2：环境变量与秘密管理治理
     - AC：多账户配置、速率限制参数化、敏感信息加密或集中管理策略。
   - Story 3.3：行情监控与告警仪表盘
     - AC：定义关键指标（订阅覆盖率、tick 每秒、延迟、掉线次数、速率限流、错误率）；Prometheus/Grafana 配置模板。
   - Story 3.4：订阅巡检与恢复机制
     - AC：常态检测脚本/服务（订阅列表 vs. should-list；漏 tick 检测），自动或半自动恢复。
   - Story 3.5：多账户与行情源故障切换
     - AC：支持多个 CTP 账户并行配置；主/备切换流程；告警通知；为 SOPT 打开接口。

3. **后续故事（可选）**
   - Story 3.6：监控前端 UI（若需要可视化界面）。
   - Story 3.7：SOPT 行情接入扩展（待后期）。

### 6.2 架构 & 运维文档具体编辑提案
- `docs/architecture/infrastructure-and-deployment.md`
  - 增加“生产运维”章节：
    1. **启动拓扑**：NATS（可集群）→ market-data-service live profile → 订阅脚本。
    2. **每日 runbook**：盘前重启、环境检测、日志检查。
    3. **故障切换策略**：NATS 节点、行情源、账户层面。
    4. **多账户配置**：如何在 docker-compose/环境变量中配置多份凭证，控制路由。
- 新建 `docs/architecture/observability-and-ops.md`（或在现有文档中增加模块）
  - 指标：订阅数量 vs. 全量合约、tick TPS、tick 延迟、掉线次数、队列积压、API 错误、速率限流触发等。
  - 日志策略：`mps_report`、订阅脚本输出、NATS 监控。
  - 告警策略：阈值与通知方式。
  - 与 Prometheus/Grafana 集成示意，提供配置样例或 exporter 要求。
- 新建 `docs/ops/production-runbook.md`
  - 步骤化指引：
    1. 环境变量设置（包括 NATS、CTP 账户、速率参数）；
    2. 启动顺序与检查清单；
    3. `full_feed_subscription.py` 调用范式（命令、参数含义、速率限制、重试策略）；
    4. 监控仪表盘检视列表；
    5. 故障处理：订阅失败、速率超限、NATS 宕机、行情源不可用。
- 新建 `docs/ops/monitoring-dashboard.md`
  - 定义仪表盘布局：核心 KPI、图表、告警。
  - 数值标准：≥5,000 mps、漏 tick 率、延迟阈值。
  - 对下游影响监控（下游消费错误率、消息堆积）。

### 6.3 脚本与配置增强建议
- `scripts/operations/full_feed_subscription.py`
  - 增加 CLI 帮助、错误码输出、成功/失败审计日志（CSV/JSON）。
  - 增加健康检查模式：列出未订阅的合约、超出速率限制的批次。
- 新增运维脚本（建议）：
  - `scripts/operations/start_live_env.sh`：顺序运行 NATS、market-data-service、订阅脚本，并记录日志。
  - `scripts/operations/check_feed_health.py`：比对实际订阅与合约列表，检测缺漏。
- `.env.example` & README
  - 增加多账户示例变量（`CTP_PRIMARY_*`, `CTP_BACKUP_*`），速率限制参数说明。
- docker-compose 文档
  - 描述 `--profile live` 使用方式，启动/停止命令，volume 管理。

---

## 7) Recommended Path Forward (Checklist §4 outcome)
- **选择**：Option 3（新增 Epic 3，扩展 MVP 以覆盖运维/多源能力）。
- **理由**：保持 Epic 2 聚焦；系统化补齐生产上线与运维生态；为扩展接口铺路。

---

## 8) MVP Scope & Success Criteria Update
- **MVP 范围**：不仅要实现行情接入，还需要可运维、可监控、可扩展的生产架构。
- **成功标准**：
  - 生产环境具备自动/手动可控的启动/停机流程与文档。
  - 日常 runbook 和监控仪表盘上线，关键指标可视化并有告警。
  - 订阅脚本支持批量、速率控制，并有健康检查能力。
  - 多账户/故障切换流程经过演练；对下游有最小扰动。
  - 新 Epic 3 Stories 完成后可进入 SOPT 等扩展。

---

## 9) High-Level Action Plan
1. **Product Owner**
   - 更新 PRD：添加 Epic 3 描述、初版故事。
   - 调整 backlog 顺序：Epic 3 优先于其他扩展。
2. **Architect**
   - 更新部署与运维架构文档。
   - 设计监控与故障切换方案（含多账户路由图示）。
3. **Dev / DevOps**
   - 实现启动/巡检脚本、完善订阅脚本。
   - 配置监控采集及仪表盘模板。
4. **QA**
   - 制定运维校验清单、监控回归（订阅覆盖率、漏 tick、速率）。
   - 规划故障切换演练与 Gate。
5. **未来扩展**
   - 在 Epic 3 后续 Story 中评估 SOPT 与其他接口接入。

---

## 10) Agent Handoff Plan
- **PO**：负责 PRD 更新与 backlog 排期。
- **SM**：跟进 Epic 3 Story 编排与执行顺序。
- **Architect**：输出运维/监控设计文件。
- **Dev/DevOps**：实现脚本与监控配置。
- **QA**：设定质量 Gate、监控验证。
- **UX（如需）**：设计监控前端界面。

---

## 11) Checklist Completion Summary (Checklist §6)
- [x] Checklist reviewed
- [x] Proposal内容准确反映讨论与决议
- [x] 获得用户对于推荐路径与行动计划的确认
- [x] 后续步骤与交接清晰明确

**Approval Needed**：请确认此变更提案，以便 PO、Architect 等角色开始实施相关更新。
