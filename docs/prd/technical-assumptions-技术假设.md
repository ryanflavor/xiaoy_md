# **Technical Assumptions  技术假设**

## **Repository Structure  存储库结构**

* A **single, dedicated repository** (Polyrepo approach) will be used for this service.
  此服务将使用**单一专用存储库** （Polyrepo 方法）。

## **Service Architecture  服务架构**

* The service will be designed using **Hexagonal Architecture (Ports and Adapters)** to isolate core domain logic, with CTP and NATS integrations implemented as external adapters. This aligns with the requested **Domain-Driven Design (DDD)** principles.
  该服务将采用**六边形架构（端口和适配器）** 进行设计，以隔离核心域逻辑，并将 CTP 和 NATS 集成实现为外部适配器。这符合所要求的**领域驱动设计 (DDD)** 原则。

## **Development & Testing Process**

**开发和测试流程**

* **Test-Driven Development (TDD)**: All new feature development **must** follow the TDD methodology.
  **测试驱动开发 (TDD)** ：所有新功能开发都**必须**遵循 TDD 方法。
* **Dependency Management**: The project will use **uv** for all Python package and virtual environment management.
  **依赖管理** ：该项目将使用 **uv** 进行所有 Python 包和虚拟环境管理。
* **Code Quality**: A strict quality gate will be enforced using **Black** for formatting and **Mypy** for static type checking.
  **代码质量** ：将使用 **Black** 进行格式化并使用 **Mypy** 进行静态类型检查来强制执行严格的质量门。
* **Continuous Integration (CI)**: A CI pipeline using **GitHub Actions** will be established. This pipeline must automatically run linters, type checkers, and all tests on every commit/pull request, blocking merges on failure.
  **持续集成 (CI)** ：将建立使用 **GitHub Actions 的** CI 流水线。该流水线必须在每次提交/拉取请求时自动运行 linters、类型检查器和所有测试，并在失败时阻止合并。

## **Additional Technical Assumptions**

**额外的技术假设**

* **Backend Technology**: Python with Asyncio.
  **后端技术** ：带有 Asyncio 的 Python。
* **Configuration Management**: Configuration will be managed via a type-safe model using Pydantic's BaseSettings.
  **配置管理** ：配置将使用 Pydantic 的 BaseSettings 通过类型安全模型进行管理。
* **Data Modeling**: Pydantic will be used for all internal data models.
  **数据建模** ：Pydantic 将用于所有内部数据模型。
* **Messaging Infrastructure**: The service will connect to and publish on an existing NATS cluster.
  **消息传递基础设施** ：该服务将连接到现有的 NATS 集群并在其上发布。
