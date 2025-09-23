# **Epics  史诗**

## **Epic 1: Service Foundation & DevOps (Optimized)**

**史诗 1：服务基础与 DevOps（优化）**

**Goal**: Establish a robust, automated, and deployable empty service shell. The final output will be a Docker image that can be deployed and respond to a basic health check, proving our entire development-to-deployment workflow is functional.

**目标** ：建立一个健壮、自动化且可部署的空服务外壳。最终输出将是一个可部署并响应基本健康检查的 Docker 镜像，以证明我们整个从开发到部署的工作流程正常运行。

### **Story 1.1: Project Repository and Tooling Setup**

**故事 1.1：项目存储库和工具设置**

As a Developer, I want a standardized project repository initialized with uv, code formatters, and type checkers, so that I can have a consistent and high-quality development environment from day one.
ACs: Git repo initialized; pyproject.toml configured for uv; Black & Mypy configured; README.md includes clear uv setup instructions.作为开发人员， 我想要一个用 uv 、代码格式化程序和类型检查器初始化的标准化项目存储库， 以便从第一天起我就能拥有一致且高质量的开发环境。
ACs ：Git repo 已初始化； pyproject.toml 已为 uv 配置； Black 和 Mypy 已配置； README.md 包含清晰的 uv 设置说明。

### **Story 1.2: Code Quality CI Pipeline**

**故事 1.2：代码质量 CI 管道**

As a Tech Lead, I want a code quality CI pipeline in GitHub Actions, so that every change is automatically linted and type-checked before merging.
ACs: GitHub Actions workflow created; triggers on push/PR; runs uv install, black --check, mypy; focuses only on code quality.作为技术主管， 我希望 GitHub Actions 中有一个代码质量 CI 管道， 以便在合并之前自动对每个更改进行 lint 和类型检查。
ACs ：GitHub Actions 工作流程已创建；在推送/PR 时触发；运行 uv install 、 black --check 、 mypy ；仅关注代码质量。

### **Story 1.3: Runnable Application Shell with Local Test**

**故事 1.3：可运行应用程序 Shell 和本地测试**

As a Developer, I want a minimal, runnable application shell based on the Hexagonal architecture that can be verified with a simple local test, so that we have a concrete, testable foundation.
ACs: src directory with Hexagonal structure created; main.py entrypoint exists; Pydantic config model used; application runs and exits cleanly; a simple pytest is added to CI to verify it runs without exceptions.作为开发人员， 我想要一个基于六边形架构的最小、可运行的应用程序外壳，可以通过简单的本地测试进行验证， 以便我们有一个具体的、可测试的基础。
ACs ：创建了六边形结构的 src 目录；存在 main.py 入口点；使用了 Pydantic 配置模型；应用程序运行并干净退出；向 CI 添加了一个简单的 pytest 来验证它运行时没有异常。

### **Story 1.4: Service Dockerization & Build Verification**

**故事 1.4：服务 Docker 化和构建验证**

As an SRE, I want the runnable application shell to be packaged in a Docker image and have the build process verified in CI, so that the service artifact is standardized.
ACs: Multi-stage Dockerfile created; CI pipeline is updated to build the Docker image after quality checks pass (does not push).作为 SRE， 我希望将可运行的应用程序外壳打包在 Docker 镜像中，并在 CI 中验证构建过程， 以便服务工件标准化。
ACs ：创建多阶段 Dockerfile ；质量检查通过后更新 CI 管道以构建 Docker 镜像（不推送）。

### **Story 1.5: End-to-End NATS Health Check & Integration Test**

**故事 1.5：端到端 NATS 健康检查和集成测试**

As an SRE, I want the Dockerized service to connect to NATS and respond to a health check, with this entire flow tested automatically in CI, so that I can be confident our core infrastructure is working.
ACs: App logic extended to connect to NATS; service listens and responds on a health check subject; CI pipeline is updated to run a NATS service container alongside the app container and execute an integration test to verify the health check.作为 SRE， 我希望 Dockerized 服务能够连接到 NATS 并响应健康检查，并在 CI 中自动测试整个流程， 这样我就可以确信我们的核心基础设施正在运行。
ACs ：应用程序逻辑扩展以连接到 NATS；服务监听并响应健康检查主题；CI 管道已更新以与应用程序容器一起运行 NATS 服务容器并执行集成测试以验证健康检查。

## **Epic 2: CTP Market Data Integration & Publication**

**史诗 2：CTP 市场数据整合与发布**

**Goal**: Building upon the foundation from Epic 1, implement the end-to-end market data pipeline. This involves integrating the vnpy CTP gateway, implementing the sync-to-async event bridge, and publishing TickData onto the NATS cluster.

**目标** ：在 Epic 1 的基础上，实现端到端的市场数据管道。这包括集成 vnpy CTP 网关、实现同步到异步事件桥接，以及将 TickData 发布到 NATS 集群。

### **Story 2.1: CTP Gateway Adapter Implementation**

**故事 2.1：CTP 网关适配器实现**

As a Developer, I want to implement the CTP Gateway Adapter based on the defined port, so that the service can connect to and manage the vnpy CTP gateway's lifecycle.
ACs: CTPGatewayAdapter class created implementing MarketDataGatewayPort; adapter connects/logs in to CTP gateway in a separate thread (ThreadPoolExecutor); connection errors are handled with thread restart capability; unit tests verify state transitions using mocks.作为开发人员， 我想根据定义的端口实现 CTP 网关适配器， 以便服务可以连接并管理 vnpy CTP 网关的生命周期。
ACs ：创建实现 MarketDataGatewayPort CTPGatewayAdapter 类；适配器在单独的线程（ThreadPoolExecutor）中连接/登录到 CTP 网关；处理连接错误并具备线程重启能力；单元测试使用模拟验证状态转换。

### **Story 2.2: Sync-to-Async Event Bridge**

**故事 2.2：同步到异步事件桥**

As a Developer, I want to bridge vnpy's synchronous EventEngine events from the executor thread to the main asyncio loop, so that market data can be processed asynchronously.
ACs: Adapter subscribes to vnpy events in executor thread; uses asyncio.run_coroutine_threadsafe() to pass TickData to main loop's asyncio.Queue; unit tests verify the bridging mechanism.作为开发人员， 我想将执行器线程中vnpy的同步 EventEngine 事件桥接到主 asyncio 循环， 以便可以异步处理市场数据。
ACs ：适配器在执行器线程中订阅 vnpy 事件；使用 asyncio.run_coroutine_threadsafe() 将 TickData 传递给主循环的 asyncio.Queue ；单元测试验证了桥接机制。

### **Story 2.3: NATS Publisher Adapter Implementation**

**故事 2.3：NATS 发布者适配器实现**

As a Developer, I want to implement the NATS Publisher Adapter that consumes from the internal queue, so that the service can publish the received market data onto the NATS cluster.
ACs: NATSEventPublisher class created implementing EventPublisherPort; app service layer passes data from queue to adapter; adapter serializes and publishes TickData to NATS; unit tests verify the adapter calls the NATS client correctly.作为开发人员， 我想实现从内部队列中使用的 NATS 发布器适配器， 以便服务可以将接收到的市场数据发布到 NATS 集群上。
ACs ：创建实现 EventPublisherPort NATSEventPublisher 类；应用服务层将数据从队列传递到适配器；适配器序列化并将 TickData 发布到 NATS；单元测试验证适配器是否正确调用 NATS 客户端。

### **Story 2.4: End-to-End Data Flow Integration Test**

**故事 2.4：端到端数据流集成测试**

As a Tech Lead, I want a full end-to-end integration test, so that I can verify the complete data flow from a mock vnpy event to a NATS subscriber.
ACs: Integration test starts the full application; uses a mock vnpy gateway to emit a known TickData event; includes a real NATS subscriber client; asserts the subscriber receives the exact data; CI is updated to run this test.作为技术主管， 我想要一个完整的端到端集成测试， 以便我可以验证从模拟 vnpy 事件到 NATS 订阅者的完整数据流。
ACs ：集成测试启动完整的应用程序；使用模拟 vnpy 网关发出已知的 TickData 事件；包括真实的 NATS 订阅者客户端；断言订阅者接收到准确的数据；CI 已更新以运行此测试。

### **Story 2.5 (Final): Live Environment Throughput and Performance Validation**

**故事 2.5（最终版）：实时环境吞吐量和性能验证**

As a Tech Lead, I want the service to be able to query all available contracts, subscribe to the entire market feed, and process the full data stream under live trading conditions, so that I can validate it meets our 5,000 messages/second performance target.
ACs: New RPC methods added for querying all contracts and bulk subscribing; service is deployed against a live, full-feed market data account; a test client subscribes to all instruments; service remains stable under full load for 1 hour of peak trading; throughput is measured and must meet or exceed 5,000 mps.作为技术主管， 我希望该服务能够查询所有可用的合约、订阅整个市场信息并在实时交易条件下处理完整的数据流， 以便我可以验证它是否符合我们每秒 5,000 条消息的性能目标。
ACs ：添加了用于查询所有合约和批量订阅的新 RPC 方法；服务针对实时、全程市场数据账户进行部署；测试客户端订阅所有工具；服务在高峰交易 1 小时的满负荷下保持稳定；吞吐量经过测量，必须达到或超过 5,000 mps。

## **Epic 3: Production Operations & Multi-Source Expansion**

**史诗 3：生产运维与多源扩展**

**Goal**: Deliver a production-ready operational layer—covering automation, observability, and resilience—that keeps the CTP market data feed reliable while preparing the stack for additional accounts and sources such as SOPT.

**目标** ：交付生产就绪的运维层，覆盖自动化、可观测性与弹性，确保 CTP 行情流稳定，同时为包括 SOPT 在内的额外账户与数据源做好技术准备。

### **Story 3.1: Production Environment Orchestration**

**故事 3.1：生产环境编排**

As an Operations Engineer, I want automated scripts and documented runbooks that sequence the live environment startup and shutdown, so that pre-market preparations and emergency recoveries are repeatable and auditable.
ACs: Runbook outlines daily pre-market startup, intra-day restart, and end-of-day shutdown; `scripts/operations/start_live_env.sh` sequences NATS, market-data-service, and subscription workers with status output; failure handling paths are documented for each step.作为运维工程师， 我需要自动化脚本和文档化的运行手册来串联实时环境的启动与停机， 以便盘前准备和应急恢复可重复且可审计。验收标准：运行手册涵盖盘前启动、盘中重启、日终关停；`scripts/operations/start_live_env.sh` 按顺序启动 NATS、market-data-service、订阅工作器并输出状态；每个步骤都文档化失败处理路径。

### **Story 3.2: Environment Variables & Secrets Governance**

**故事 3.2：环境变量与秘密管理治理**

As a Platform Engineer, I want a governed configuration scheme for live credentials, rate limits, and routing parameters, so that multiple accounts can be managed safely across environments.
ACs: `.env.example` documents primary/backup account variables and rate-limit tuning knobs; guidance for secure secret storage (e.g., Vault, encrypted files) is added to the PRD/architecture; validation steps ensure misconfigured credentials are detected before startup.作为平台工程师， 我需要一套受控的线上凭证、速率限制和路由参数配置方案， 以便在多个环境中安全管理多账户。验收标准：`.env.example` 文档化主备账户变量与限流调节项；PRD/架构补充安全存储建议（如 Vault、加密文件）；提供验证步骤以在启动前检测错误配置。

### **Story 3.3: Market Data Monitoring Dashboards**

**故事 3.3：行情监控与告警仪表盘**

As a DevOps Engineer, I want dashboards and alerts for core feed metrics, so that we can detect coverage gaps, latency spikes, or rate-limit incidents in real time.
ACs: Prometheus scrape targets or exporters defined for the market-data-service and subscription scripts; Grafana dashboard template captures subscription coverage, messages-per-second, latency percentiles, error counts, and rate-limit triggers; alert thresholds and notification channels documented for sustained anomalies.作为 DevOps 工程师， 我需要针对核心行情指标的仪表盘与告警， 以便实时发现覆盖缺口、延迟波动或限流事件。验收标准：为 market-data-service 与订阅脚本定义 Prometheus 采集目标或 exporter；Grafana 仪表盘模板展示订阅覆盖率、每秒消息数、延迟分位数、错误计数和限流触发；文档化持续异常的告警阈值和通知渠道。

### **Story 3.4: Subscription Health Checks & Recovery**

**故事 3.4：订阅健康检查与恢复机制**

As a Market Data SRE, I want automated checks that compare actual subscriptions against the expected contract universe, so that missing instruments or stalled feeds are remediated quickly.
ACs: `scripts/operations/check_feed_health.py` lists missing or stalled contracts with exit codes for CI/automation; health reports can run in read-only mode without disrupting live traffic; runbook or automation triggers resubscription or operator escalation when anomalies persist.作为行情 SRE， 我需要自动校验实际订阅与期望合约全集的机制， 以便快速修复缺失合约或停滞的数据流。验收标准：`scripts/operations/check_feed_health.py` 列出缺失或停滞合约并通过退出码供 CI/自动化使用；健康检查可在只读模式下运行且不影响实时流量；运行手册或自动化在异常持续时触发重新订阅或人工升级。

### **Story 3.5: Multi-Account & Feed Failover Readiness**

**故事 3.5：多账户与行情源故障切换准备**

As a Tech Lead, I want documented and tested procedures for swapping to backup CTP accounts or alternate feeds, so that downtime and downstream disruptions are minimized during incidents.
ACs: Configuration supports primary/backup credentials with clear routing precedence; failover drill documented with expected operator actions and rollback steps; monitoring hooks confirm downstream consumers remain stable during switchovers.作为技术主管， 我需要文档化且经过演练的主备账户或备用数据源切换流程， 以便事故期间最小化停机和对下游的影响。验收标准：配置支持主备凭证并具有明确的路由优先级；故障切换演练文档化预期操作步骤与回滚方案；监控钩子验证切换期间下游消费者保持稳定。

### **Future Story Seeds**

**后续故事种子**

- Story 3.6: Monitoring UI for dashboards if a dedicated front-end is required.
  故事 3.6：如需独立前端，则实现仪表盘可视化界面。
- Story 3.7: SOPT or additional market source integration once production operations are stable.
  故事 3.7：生产运维稳定后接入 SOPT 或其他行情源。
