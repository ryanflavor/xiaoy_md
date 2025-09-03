# **Requirements  要求**

## **Functional Requirements (FR)**

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

## **Non-Functional Requirements (NFR)**

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

## **Post-MVP Reliability Requirements**

**MVP 后的可靠性要求**

*(The following requirements were identified as critical for a production-ready system but are deferred from the initial MVP to ensure rapid delivery.)*

*（以下要求对于生产就绪系统至关重要，但从初始 MVP 开始推迟以确保快速交付。）*

* **Health Checks & Auto-Recovery**: Implement a mechanism to health-check the managed vnpy gateway instance and automatically restart it if it becomes unresponsive.  
  **健康检查和自动恢复** ：实施一种机制来检查托管的 vnpy 网关实例的健康情况，并在其无响应时自动重新启动它。  
* **Backpressure Strategy**: Define and implement a strategy to handle message storms from the data source, preventing memory overload and service crashes (e.g., buffered dropping, configurable throttling).  
  **背压策略** ：定义并实施策略来处理来自数据源的消息风暴，防止内存过载和服务崩溃（例如，缓冲丢弃、可配置节流）。  
* **Market Data Snapshot**: Implement a mechanism to provide a current market state snapshot for new or reconnecting subscribers to prevent data gaps.  
  **市场数据快照** ：实施一种机制，为新用户或重新连接的用户提供当前市场状态快照，以防止数据缺口。
