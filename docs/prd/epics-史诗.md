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
ACs: GitHub Actions workflow created; triggers on push/PR; runs uv install, black \--check, mypy; focuses only on code quality.作为技术主管， 我希望 GitHub Actions 中有一个代码质量 CI 管道， 以便在合并之前自动对每个更改进行 lint 和类型检查。  
ACs ：GitHub Actions 工作流程已创建；在推送/PR 时触发；运行 uv install 、 black \--check 、 mypy ；仅关注代码质量。

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
ACs: CTPGatewayAdapter class created implementing MarketDataGatewayPort; adapter connects/logs in to CTP gateway in a separate thread; connection errors are handled; unit tests verify state transitions using mocks.作为开发人员， 我想根据定义的端口实现 CTP 网关适配器， 以便服务可以连接并管理 vnpy CTP 网关的生命周期。  
ACs ：创建实现 MarketDataGatewayPort CTPGatewayAdapter 类；适配器在单独的线程中连接/登录到 CTP 网关；处理连接错误；单元测试使用模拟验证状态转换。

### **Story 2.2: Sync-to-Async Event Bridge**

**故事 2.2：同步到异步事件桥**

As a Developer, I want to bridge vnpy's synchronous EventEngine events to the main asyncio loop, so that market data can be processed asynchronously.  
ACs: Adapter subscribes to vnpy events; a thread-safe mechanism (asyncio.run\_coroutine\_threadsafe) passes TickData to an internal asyncio.Queue; unit tests verify the bridging mechanism.作为开发人员， 我想将 vnpy 的同步 EventEngine 事件桥接到主 asyncio 循环， 以便可以异步处理市场数据。  
ACs ：适配器订阅 vnpy 事件；线程安全机制 ( asyncio.run\_coroutine\_threadsafe ) 将 TickData 传递给内部 asyncio.Queue ；单元测试验证了桥接机制。

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
