# **2\. High-Level Architecture**

## **Technical Summary**

This project's core is a Python asynchronous service built on the **Hexagonal Architecture (Ports and Adapters)** principle. A dedicated "input adapter" will manage the synchronous vnpy CTP gateway in an isolated thread using ThreadPoolExecutor, while an "output adapter" publishes the processed data to a NATS JetStream cluster. The entire design aims to create a highly decoupled, testable, and scalable middleware solution, fulfilling the PRD's objectives for a rapid yet robust prototype.

## **Architecture Overview**

We will construct a single, independent market data service that acts as a bridge between the vnpy data source and internal asynchronous applications. The primary data flow is as follows:

1. **Data Input**: The vnpy CTP gateway runs in a separate, supervised thread (using ThreadPoolExecutor), receiving raw market data and emitting synchronous events.
2. **Event Bridging**: The CTP adapter uses asyncio.run_coroutine_threadsafe() to safely transfer events from the executor thread to the main asynchronous event loop.
3. **Data Publication**: The core application logic processes these events and hands them to the NATS adapter for publication on the NATS cluster.
4. **Data Consumption**: Internal applications (strategies, dashboards, etc.) can then subscribe to this market data asynchronously from the NATS cluster.

This design fully encapsulates the complexity and synchronous nature of vnpy within the input adapter, safeguarding the stability and technological consistency of our core application.

## **High-Level Project Diagram**

Code snippet

graph TD
    subgraph "External Systems"
        A\["Primary CTP Gateway"\]
        A2\["Backup Feed / Alternate Source"\]
    end

    subgraph "Market Data Service Container (Docker)"
        I\["Ops Orchestrator\\n(start\_live\_env.sh)"\]
        B\["CTP Adapter (Input Port)"\]
        C\["Core Application Logic (Domain Layer)"\]
        H\["Subscription Health Agent"\]
        D\["NATS Publisher (Output Port)"\]
        I \-- Bootstrap --> B
        B \-- TickData Event \--\> C
        C \-- Publish Command \--\> D
        C \-- Health Snapshot \--\> H
        H \-- Recovery Hooks \--\> I
    end

    subgraph "Infrastructure"
        E\["NATS JetStream Cluster"\]
        M\["Prometheus Metrics Store"\]
    end

    subgraph "Operations & Insights"
        F\["Ops Engineer / Runbook"\]
        G\["Grafana Dashboards & Alerts"\]
    end

    A \-- "Real-time Ticks" \--\> B
    A2 \-- "Failover Route" \--\> B
    D \-- "Publish Ticks" \--\> E
    E \-- "Subscribe to Ticks" \--\> F
    H \-- "Metrics & Events" \--\> M
    M \-- "Dashboards & Alerts" \--\> G
    G \-- "Alert Actions" \--\> F
    F \-- "Automation Trigger" \--\> I

### **Production Operations Layer (Epic 3 Scope)**

Epic 3 正式引入生产运维平面：自动化 Runbook 负责顺序启动/重启/关闭 NATS、market-data-service 与订阅脚本；订阅健康代理持续对比实时订阅与理论合约全集，并与 Prometheus/Grafana 闭环；主备账户与备用行情源与主链路并列建模，实现平滑故障切换。

## **Architectural and Design Patterns**

* **Hexagonal Architecture (Ports and Adapters)**: This is our primary architectural pattern. The core business logic is isolated and interacts with the outside world through well-defined "ports" (interfaces). The CTP integration is an input adapter, and the NATS publication is an output adapter.
* **Domain-Driven Design (DDD)**: We will model our logic around the core "market data processing" domain, using Pydantic to define clear domain objects and a ubiquitous language.
* **Thread Supervisor Pattern**: The CTP adapter runs the vnpy gateway in a separate thread pool and acts as a supervisor. On disconnection/failure it spawns a fresh session thread for each retry (CTP requires a new thread per session), using exponential backoff and capped retries.
* **Publisher-Subscriber Pattern**: This is the fundamental pattern for communication with downstream consumers via NATS, ensuring a high degree of decoupling.
* **Configurable Serialization Strategy (Strategy Pattern)**: The service will use a configurable strategy for data serialization (Pickle for flexibility, Pydantic+JSON for standardization), allowing the system to adapt to different consumer needs.
* **Runbook Automation Pattern**: 运维脚本封装启动/重启/停机编排，保证重复执行的幂等性与可审计性。
* **Observable Control Loop Pattern**: 监控指标驱动告警，告警又反向触发恢复操作，形成自愈闭环。
* **Failover Playbook Pattern**: 预置主备账号配置与切换流程，确保故障时快速切换且不影响下游消费者。

---
