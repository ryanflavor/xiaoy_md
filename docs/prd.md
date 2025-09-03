# **Internal Market Data Service Prototype Product Requirements Document (PRD)**

**内部市场数据服务原型产品需求文档（PRD）**

| Date  日期 | Version  版本 | Description  描述 | Author  作者 |
| :---- | :---- | :---- | :---- |
| 2025-09-02 | 1.0 | Initial draft and finalization 初稿和定稿 | PM (John)  总理（约翰） |

## **Goals and Background Context**

**目标和背景**

### **Goals  目标**

* Provide a standardized行情 service to reduce development friction for internal projects.  
  提供标准化的行情服务，减少内部项目的开发摩擦。  
* Create a stable data foundation to enable rapid innovation for Quant and Application teams.  
  创建稳定的数据基础，以实现量化和应用团队的快速创新。  
* Validate the DDD/Hexagonal/NATS architecture pattern for future internal services.  
  验证 DDD/Hexagonal/NATS 架构模式以适应未来的内部服务。

### **Background Context  背景环境**

This project aims to solve the integration challenge between the company's synchronous vnpy-based trading infrastructure and modern asynchronous application development. By building a centralized asynchronous gateway adapter, we will provide a unified, highly available, and easy-to-access real-time market data source for all internal teams, enhancing overall R\&D efficiency and system stability.

该项目旨在解决公司基于 vnpy 的同步交易基础设施与现代异步应用程序开发之间的集成挑战。通过构建集中式异步网关适配器，我们将为所有内部团队提供统一、高可用且易于访问的实时市场数据源，从而提升整体研发效率和系统稳定性。

## **Requirements  要求**

### **Functional Requirements (FR)**

**功能需求（法语）**

* **FR1 (Revised)**: The service must be able to host **at least one** vnpy gateway instance (**starting with CTP for the MVP**) in a separate thread using ThreadPoolExecutor, and manage its lifecycle including thread restarts for reconnection.  
  **FR1（修订版）** ：该服务必须能够使用ThreadPoolExecutor在独立线程中托管**至少一个** vnpy 网关实例（ **从 MVP 的 CTP 开始** ），并管理其生命周期，包括重连所需的线程重启。  
* **FR2**: The service must implement an event bridge to safely pass market data events from the synchronous vnpy EventEngine to an asynchronous NATS publisher.  
  **FR2** ：服务必须实现事件桥，以便将市场数据事件从同步 vnpy EventEngine 安全地传递到异步 NATS 发布者。  
* **FR3**: The service must publish vnpy.trader.object.TickData formatted market data to a configurable NATS topic.  
  **FR3** ：服务必须将 vnpy.trader.object.TickData 格式的市场数据发布到可配置的 NATS 主题。  
* **FR4 (Revised)**: The service must support configuring connection parameters for **different gateway types**, with CTP's configuration being the first implementation.  
  **FR4（修订版）** ：服务必须支持配置**不同网关类型**的连接参数，其中 CTP 的配置是第一个实现。  
* **FR5**: The entire service must be packaged as a Docker image for deployment.  
  **FR5** ：必须将整个服务打包为 Docker 镜像进行部署。  
* **FR6**: The NATS topic structure for publishing market data should be simple and hierarchical.  
  **FR6** ：发布市场数据的 NATS 主题结构应该简单且有层次。

### **Non-Functional Requirements (NFR)**

**非功能性需求（NFR）**

* **NFR1**: The service's design must adhere to Domain-Driven Design (DDD) and Hexagonal Architecture (Ports and Adapters) principles.  
  **NFR1** ：服务的设计必须遵循领域驱动设计（DDD）和六边形架构（端口和适配器）原则。  
* **NFR2**: All internal data model definitions and validations within the service must use the Pydantic library.  
  **NFR2** ：服务内的所有内部数据模型定义和验证都必须使用 Pydantic 库。  
* **NFR3**: The service prototype should be designed to handle a peak message rate of at least **5,000 messages/second** (verification deferred to post-MVP testing).  
  **NFR3** ：服务原型应设计为能够处理至少**每秒 5,000 条消息**的峰值消息速率（验证推迟到MVP后测试）。  
* **NFR4**: As an internal prototype, the MVP does not require complex security mechanisms (e.g., client authentication, authorization).  
  **NFR4** ：作为内部原型，MVP 不需要复杂的安全机制（例如，客户端身份验证、授权）。  
* **NFR5**: The end-to-end latency for the service itself (from CTP data receipt to NATS publication) should be minimized.  
  **NFR5** ：应最小化服务本身的端到端延迟（从 CTP 数据接收到 NATS 发布）。  
* **NFR6**: The service must provide basic logging for connection status, errors, and critical operations.  
  **NFR6** ：服务必须提供连接状态、错误和关键操作的基本日志记录。  
* **NFR7 (Extensibility)**: The architecture must define a generic "Gateway Adapter" port (interface). The CTP gateway integration will be the first implementation of this port, ensuring that other gateways (like SOPT) can be added in the future with minimal changes to the core application logic.  
  **NFR7（可扩展性）** ：架构必须定义一个通用的“网关适配器”端口（接口）。CTP 网关集成将是该端口的首次实现，以确保将来能够在核心应用程序逻辑改动最小的情况下添加其他网关（如 SOPT）。

### **Post-MVP Reliability Requirements**

**MVP 后的可靠性要求**

*(The following requirements were identified as critical for a production-ready system but are deferred from the initial MVP to ensure rapid delivery.)*

*（以下要求对于生产就绪系统至关重要，但从初始 MVP 开始推迟以确保快速交付。）*

* **Health Checks & Auto-Recovery**: Implement a mechanism to health-check the managed vnpy gateway instance and automatically restart it if it becomes unresponsive.  
  **健康检查和自动恢复** ：实施一种机制来检查托管的 vnpy 网关实例的健康情况，并在其无响应时自动重新启动它。  
* **Backpressure Strategy**: Define and implement a strategy to handle message storms from the data source, preventing memory overload and service crashes (e.g., buffered dropping, configurable throttling).  
  **背压策略** ：定义并实施策略来处理来自数据源的消息风暴，防止内存过载和服务崩溃（例如，缓冲丢弃、可配置节流）。  
* **Market Data Snapshot**: Implement a mechanism to provide a current market state snapshot for new or reconnecting subscribers to prevent data gaps.  
  **市场数据快照** ：实施一种机制，为新用户或重新连接的用户提供当前市场状态快照，以防止数据缺口。

## **Technical Assumptions  技术假设**

### **Repository Structure  存储库结构**

* A **single, dedicated repository** (Polyrepo approach) will be used for this service.  
  此服务将使用**单一专用存储库** （Polyrepo 方法）。

### **Service Architecture  服务架构**

* The service will be designed using **Hexagonal Architecture (Ports and Adapters)** to isolate core domain logic, with CTP and NATS integrations implemented as external adapters. This aligns with the requested **Domain-Driven Design (DDD)** principles.  
  该服务将采用**六边形架构（端口和适配器）** 进行设计，以隔离核心域逻辑，并将 CTP 和 NATS 集成实现为外部适配器。这符合所要求的**领域驱动设计 (DDD)** 原则。

### **Development & Testing Process**

**开发和测试流程**

* **Test-Driven Development (TDD)**: All new feature development **must** follow the TDD methodology.  
  **测试驱动开发 (TDD)** ：所有新功能开发都**必须**遵循 TDD 方法。  
* **Dependency Management**: The project will use **uv** for all Python package and virtual environment management.  
  **依赖管理** ：该项目将使用 **uv** 进行所有 Python 包和虚拟环境管理。  
* **Code Quality**: A strict quality gate will be enforced using **Black** for formatting and **Mypy** for static type checking.  
  **代码质量** ：将使用 **Black** 进行格式化并使用 **Mypy** 进行静态类型检查来强制执行严格的质量门。  
* **Continuous Integration (CI)**: A CI pipeline using **GitHub Actions** will be established. This pipeline must automatically run linters, type checkers, and all tests on every commit/pull request, blocking merges on failure.  
  **持续集成 (CI)** ：将建立使用 **GitHub Actions 的** CI 流水线。该流水线必须在每次提交/拉取请求时自动运行 linters、类型检查器和所有测试，并在失败时阻止合并。

### **Additional Technical Assumptions**

**额外的技术假设**

* **Backend Technology**: Python with Asyncio.  
  **后端技术** ：带有 Asyncio 的 Python。  
* **Configuration Management**: Configuration will be managed via a type-safe model using Pydantic's BaseSettings.  
  **配置管理** ：配置将使用 Pydantic 的 BaseSettings 通过类型安全模型进行管理。  
* **Data Modeling**: Pydantic will be used for all internal data models.  
  **数据建模** ：Pydantic 将用于所有内部数据模型。  
* **Messaging Infrastructure**: The service will connect to and publish on an existing NATS cluster.  
  **消息传递基础设施** ：该服务将连接到现有的 NATS 集群并在其上发布。

## **Epics  史诗**

### **Epic 1: Service Foundation & DevOps (Optimized)**

**史诗 1：服务基础与 DevOps（优化）**

**Goal**: Establish a robust, automated, and deployable empty service shell. The final output will be a Docker image that can be deployed and respond to a basic health check, proving our entire development-to-deployment workflow is functional.

**目标** ：建立一个健壮、自动化且可部署的空服务外壳。最终输出将是一个可部署并响应基本健康检查的 Docker 镜像，以证明我们整个从开发到部署的工作流程正常运行。

#### **Story 1.1: Project Repository and Tooling Setup**

**故事 1.1：项目存储库和工具设置**

As a Developer, I want a standardized project repository initialized with uv, code formatters, and type checkers, so that I can have a consistent and high-quality development environment from day one.  
ACs: Git repo initialized; pyproject.toml configured for uv; Black & Mypy configured; README.md includes clear uv setup instructions.作为开发人员， 我想要一个用 uv 、代码格式化程序和类型检查器初始化的标准化项目存储库， 以便从第一天起我就能拥有一致且高质量的开发环境。  
ACs ：Git repo 已初始化； pyproject.toml 已为 uv 配置； Black 和 Mypy 已配置； README.md 包含清晰的 uv 设置说明。

#### **Story 1.2: Code Quality CI Pipeline**

**故事 1.2：代码质量 CI 管道**

As a Tech Lead, I want a code quality CI pipeline in GitHub Actions, so that every change is automatically linted and type-checked before merging.  
ACs: GitHub Actions workflow created; triggers on push/PR; runs uv install, black \--check, mypy; focuses only on code quality.作为技术主管， 我希望 GitHub Actions 中有一个代码质量 CI 管道， 以便在合并之前自动对每个更改进行 lint 和类型检查。  
ACs ：GitHub Actions 工作流程已创建；在推送/PR 时触发；运行 uv install 、 black \--check 、 mypy ；仅关注代码质量。

#### **Story 1.3: Runnable Application Shell with Local Test**

**故事 1.3：可运行应用程序 Shell 和本地测试**

As a Developer, I want a minimal, runnable application shell based on the Hexagonal architecture that can be verified with a simple local test, so that we have a concrete, testable foundation.  
ACs: src directory with Hexagonal structure created; main.py entrypoint exists; Pydantic config model used; application runs and exits cleanly; a simple pytest is added to CI to verify it runs without exceptions.作为开发人员， 我想要一个基于六边形架构的最小、可运行的应用程序外壳，可以通过简单的本地测试进行验证， 以便我们有一个具体的、可测试的基础。  
ACs ：创建了六边形结构的 src 目录；存在 main.py 入口点；使用了 Pydantic 配置模型；应用程序运行并干净退出；向 CI 添加了一个简单的 pytest 来验证它运行时没有异常。

#### **Story 1.4: Service Dockerization & Build Verification**

**故事 1.4：服务 Docker 化和构建验证**

As an SRE, I want the runnable application shell to be packaged in a Docker image and have the build process verified in CI, so that the service artifact is standardized.  
ACs: Multi-stage Dockerfile created; CI pipeline is updated to build the Docker image after quality checks pass (does not push).作为 SRE， 我希望将可运行的应用程序外壳打包在 Docker 镜像中，并在 CI 中验证构建过程， 以便服务工件标准化。  
ACs ：创建多阶段 Dockerfile ；质量检查通过后更新 CI 管道以构建 Docker 镜像（不推送）。

#### **Story 1.5: End-to-End NATS Health Check & Integration Test**

**故事 1.5：端到端 NATS 健康检查和集成测试**

As an SRE, I want the Dockerized service to connect to NATS and respond to a health check, with this entire flow tested automatically in CI, so that I can be confident our core infrastructure is working.  
ACs: App logic extended to connect to NATS; service listens and responds on a health check subject; CI pipeline is updated to run a NATS service container alongside the app container and execute an integration test to verify the health check.作为 SRE， 我希望 Dockerized 服务能够连接到 NATS 并响应健康检查，并在 CI 中自动测试整个流程， 这样我就可以确信我们的核心基础设施正在运行。  
ACs ：应用程序逻辑扩展以连接到 NATS；服务监听并响应健康检查主题；CI 管道已更新以与应用程序容器一起运行 NATS 服务容器并执行集成测试以验证健康检查。

### **Epic 2: CTP Market Data Integration & Publication**

**史诗 2：CTP 市场数据整合与发布**

**Goal**: Building upon the foundation from Epic 1, implement the end-to-end market data pipeline. This involves integrating the vnpy CTP gateway, implementing the sync-to-async event bridge, and publishing TickData onto the NATS cluster.

**目标** ：在 Epic 1 的基础上，实现端到端的市场数据管道。这包括集成 vnpy CTP 网关、实现同步到异步事件桥接，以及将 TickData 发布到 NATS 集群。

#### **Story 2.1: CTP Gateway Adapter Implementation**

**故事 2.1：CTP 网关适配器实现**

As a Developer, I want to implement the CTP Gateway Adapter based on the defined port, so that the service can connect to and manage the vnpy CTP gateway's lifecycle.  
ACs: CTPGatewayAdapter class created implementing MarketDataGatewayPort; adapter connects/logs in to CTP gateway in a separate thread (ThreadPoolExecutor); connection errors are handled with thread restart capability; unit tests verify state transitions using mocks.作为开发人员， 我想根据定义的端口实现 CTP 网关适配器， 以便服务可以连接并管理 vnpy CTP 网关的生命周期。  
ACs ：创建实现 MarketDataGatewayPort CTPGatewayAdapter 类；适配器在单独的线程（ThreadPoolExecutor）中连接/登录到 CTP 网关；处理连接错误并具备线程重启能力；单元测试使用模拟验证状态转换。

#### **Story 2.2: Sync-to-Async Event Bridge**

**故事 2.2：同步到异步事件桥**

As a Developer, I want to bridge vnpy's synchronous EventEngine events from the executor thread to the main asyncio loop, so that market data can be processed asynchronously.  
ACs: Adapter subscribes to vnpy events in executor thread; uses asyncio.run_coroutine_threadsafe() to pass TickData to main loop's asyncio.Queue; unit tests verify the bridging mechanism.作为开发人员， 我想将执行器线程中vnpy的同步 EventEngine 事件桥接到主 asyncio 循环， 以便可以异步处理市场数据。  
ACs ：适配器在执行器线程中订阅 vnpy 事件；使用 asyncio.run_coroutine_threadsafe() 将 TickData 传递给主循环的 asyncio.Queue ；单元测试验证了桥接机制。

#### **Story 2.3: NATS Publisher Adapter Implementation**

**故事 2.3：NATS 发布者适配器实现**

As a Developer, I want to implement the NATS Publisher Adapter that consumes from the internal queue, so that the service can publish the received market data onto the NATS cluster.  
ACs: NATSEventPublisher class created implementing EventPublisherPort; app service layer passes data from queue to adapter; adapter serializes and publishes TickData to NATS; unit tests verify the adapter calls the NATS client correctly.作为开发人员， 我想实现从内部队列中使用的 NATS 发布器适配器， 以便服务可以将接收到的市场数据发布到 NATS 集群上。  
ACs ：创建实现 EventPublisherPort NATSEventPublisher 类；应用服务层将数据从队列传递到适配器；适配器序列化并将 TickData 发布到 NATS；单元测试验证适配器是否正确调用 NATS 客户端。

#### **Story 2.4: End-to-End Data Flow Integration Test**

**故事 2.4：端到端数据流集成测试**

As a Tech Lead, I want a full end-to-end integration test, so that I can verify the complete data flow from a mock vnpy event to a NATS subscriber.  
ACs: Integration test starts the full application; uses a mock vnpy gateway to emit a known TickData event; includes a real NATS subscriber client; asserts the subscriber receives the exact data; CI is updated to run this test.作为技术主管， 我想要一个完整的端到端集成测试， 以便我可以验证从模拟 vnpy 事件到 NATS 订阅者的完整数据流。  
ACs ：集成测试启动完整的应用程序；使用模拟 vnpy 网关发出已知的 TickData 事件；包括真实的 NATS 订阅者客户端；断言订阅者接收到准确的数据；CI 已更新以运行此测试。

#### **Story 2.5 (Final): Live Environment Throughput and Performance Validation**

**故事 2.5（最终版）：实时环境吞吐量和性能验证**

As a Tech Lead, I want the service to be able to query all available contracts, subscribe to the entire market feed, and process the full data stream under live trading conditions, so that I can validate it meets our 5,000 messages/second performance target.  
ACs: New RPC methods added for querying all contracts and bulk subscribing; service is deployed against a live, full-feed market data account; a test client subscribes to all instruments; service remains stable under full load for 1 hour of peak trading; throughput is measured and must meet or exceed 5,000 mps.作为技术主管， 我希望该服务能够查询所有可用的合约、订阅整个市场信息并在实时交易条件下处理完整的数据流， 以便我可以验证它是否符合我们每秒 5,000 条消息的性能目标。  
ACs ：添加了用于查询所有合约和批量订阅的新 RPC 方法；服务针对实时、全程市场数据账户进行部署；测试客户端订阅所有工具；服务在高峰交易 1 小时的满负荷下保持稳定；吞吐量经过测量，必须达到或超过 5,000 mps。

## **Checklist Results Report  核对清单结果报告**

* **Overall Assessment**: The PRD is complete, logically consistent, and has a well-defined scope.  
  **总体评价** ：PRD 完整、逻辑一致、范围明确。  
* **Final Conclusion**: ✅ **READY FOR ARCHITECT**  
  **最终结论** ：✅ **为建筑师做好准备**
