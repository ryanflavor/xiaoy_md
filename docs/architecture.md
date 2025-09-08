# **Architecture Document: Internal Market Data Service Prototype**

| Date | Version | Description | Author |
| :---- | :---- | :---- | :---- |
| 2025-09-02 | 1.0 | Initial Design and Finalization | Architect (Winston) |

## **1\. Introduction**

This document outlines the overall project architecture for the “Internal Market Data Service Prototype,” including backend systems, shared services, and all non-UI related technical considerations. This document is intended to serve as the core architectural blueprint for subsequent AI-driven development, ensuring consistency and adherence to the selected patterns and technologies.

### **Starter Template or Existing Project**

This project is not based on a standard third-party starter template. However, the project's core architecture will strictly follow the reference implementations and pattern documents you provided, including the asynchronous adapter pattern defined in vnpy-integration-best-practices.md and the NATS IPC node implemented in core.py. These files will serve as the "de facto standard" and foundation for our architecture.

---

## **2\. High-Level Architecture**

### **Technical Summary**

This project's core is a Python asynchronous service built on the **Hexagonal Architecture (Ports and Adapters)** principle. A dedicated "input adapter" will manage the synchronous vnpy CTP gateway in an isolated thread using ThreadPoolExecutor, while an "output adapter" publishes the processed data to a NATS JetStream cluster. The entire design aims to create a highly decoupled, testable, and scalable middleware solution, fulfilling the PRD's objectives for a rapid yet robust prototype.

### **Architecture Overview**

We will construct a single, independent market data service that acts as a bridge between the vnpy data source and internal asynchronous applications. The primary data flow is as follows:

1. **Data Input**: The vnpy CTP gateway runs in a separate, supervised thread (using ThreadPoolExecutor), receiving raw market data and emitting synchronous events.
2. **Event Bridging**: The CTP adapter uses asyncio.run_coroutine_threadsafe() to safely transfer events from the executor thread to the main asynchronous event loop.
3. **Data Publication**: The core application logic processes these events and hands them to the NATS adapter for publication on the NATS cluster.
4. **Data Consumption**: Internal applications (strategies, dashboards, etc.) can then subscribe to this market data asynchronously from the NATS cluster.

This design fully encapsulates the complexity and synchronous nature of vnpy within the input adapter, safeguarding the stability and technological consistency of our core application.

### **High-Level Project Diagram**

Code snippet

graph TD
    subgraph "External Systems"
        A\["vnpy CTP Gateway"\]
    end

    subgraph "Market Data Service Container (Docker)"
        B\["CTP Adapter (Input Port)"\]
        C\["Core Application Logic (Domain Layer)"\]
        D\["NATS Publisher (Output Port)"\]
        B \-- TickData Event \--\> C
        C \-- Publish Command \--\> D
    end

    subgraph "Infrastructure"
        E\["NATS JetStream Cluster"\]
    end

    subgraph "Internal Consumers"
        F\["Strategy App A"\]
        G\["Monitoring Dashboard B"\]
    end

    A \-- "Real-time Ticks (TCP)" \--\> B
    D \-- "Publish Ticks (NATS Protocol)" \--\> E
    E \-- "Subscribe to Ticks (NATS Protocol)" \--\> F
    E \-- "Subscribe to Ticks (NATS Protocol)" \--\> G

### **Architectural and Design Patterns**

* **Hexagonal Architecture (Ports and Adapters)**: This is our primary architectural pattern. The core business logic is isolated and interacts with the outside world through well-defined "ports" (interfaces). The CTP integration is an input adapter, and the NATS publication is an output adapter.
* **Domain-Driven Design (DDD)**: We will model our logic around the core "market data processing" domain, using Pydantic to define clear domain objects and a ubiquitous language.
* **Thread Supervisor Pattern**: The CTP adapter runs the vnpy gateway in a separate thread pool and acts as a supervisor, restarting the thread upon disconnection (required by CTP's reconnection mechanism).
* **Publisher-Subscriber Pattern**: This is the fundamental pattern for communication with downstream consumers via NATS, ensuring a high degree of decoupling.
* **Configurable Serialization Strategy (Strategy Pattern)**: The service will use a configurable strategy for data serialization (Pickle for flexibility, Pydantic+JSON for standardization), allowing the system to adapt to different consumer needs.

---

## **3\. Tech Stack**

This table represents the definitive technology choices for the project. All development must adhere to these specifications.

### **Cloud Infrastructure**

* **Provider**: Local Area Network (LAN) / On-Premises
* **Key Services**: Docker, NATS JetStream Cluster, GitHub Container Registry (GHCR)

### **Technology Stack Table**

| Category | Technology | Version | Purpose | Rationale |
| :---- | :---- | :---- | :---- | :---- |
| **Language** | Python | **3.13** | Core development language | User-specified; modern async features. |
| **Runtime** | Python CPython | **3.13** | Python code execution | Community standard, stable performance. |
| **Framework** | Custom Asyncio App | N/A | Application core framework | Lightweight, full control of the event loop. |
| **Message Queue** | NATS / JetStream | 2.10.x | Core message bus | High performance, with persistence via JetStream. |
| **API Style** | NATS (RPC & Pub/Sub) | N/A | Service communication | High-performance internal communication. |
| **Testing** | Pytest | 8.x | Automated testing | Powerful, extensible, community standard. |
| **Package Management** | uv | 0.1.x | Dependency management | User-specified; modern and fast. |
| **IaC Tool** | **Docker Compose** | 2.24.x | **Standardized app stack deployment** | Provides service discovery and simplified management. |
| **Logging** | Logging (Python Module) | 3.13 | Application logging | Python's built-in standard library. |
| **Serialization** | Pickle / Pydantic+JSON | Configurable | Data transfer format | User-specified; balances flexibility and standards. |
| **\*\*Monitoring\*\*** | **Prometheus** | 2.51.x | **Metrics collection & storage (Post-MVP)** | Industry-standard open-source monitoring. |
| **\*\*Visualization\*\*** | **Grafana** | 10.4.x | **Monitoring dashboards (Post-MVP)** | Powerful visualization for Prometheus data. |

---

## **4\. Data Models**

The core data model for the MVP will be based on vnpy.trader.object.TickData and defined using Pydantic to ensure type safety.

### **TickDataModel (Pydantic)**

**Purpose**: Defines the standard market data structure for all inter-service communication (DTO).

Python

\# file: src/domain/models/tick.py
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

class Exchange(str, Enum):
    CFFEX \= "CFFEX"
    SHFE \= "SHFE"
    CZCE \= "CZCE"
    DCE \= "DCE"
    INE \= "INE"
    GFEX \= "GFEX"
    SSE \= "SSE"
    SZSE \= "SZSE"

class DomainTick(BaseModel):
    """
    Internal domain model for a tick, decoupled from vnpy's structure.
    """
    symbol: str \= Field(..., description="Contract symbol")
    exchange: Exchange \= Field(..., description="Exchange")
    datetime: datetime \= Field(..., description="Timestamp (UTC)")
    last\_price: float \= Field(..., description="Last price")
    volume: float \= Field(..., description="Volume")
    \# ... other essential fields

    class Config:
        use\_enum\_values \= True

*Note: We will maintain a clear maintenance process to keep this model in sync with any future changes to vnpy's TickData object and will standardize all timestamps to UTC during translation.*

---

## **5\. Components**

The architecture is divided into the following components, adhering to the Ports and Adapters pattern.

### **Ports (Interface Definitions)**

* **MarketDataPort**: An input port for managing and consuming market data. It includes methods for lifecycle management (connect(), disconnect(), get\_status()) and provides an asynchronous stream of DomainTick data.
* **EventPublisherPort**: An output port for publishing events. It includes a publish(tick: DomainTick) method.

### **Core Components**

1. **CTP Gateway Adapter**
   * **Responsibility**: Implements the MarketDataPort. It encapsulates the vnpy CTP gateway, running it in a supervised thread (ThreadPoolExecutor). Its core tasks are managing the gateway's lifecycle, handling thread restarts on disconnection, and **translating** the external vnpy.TickData object into our internal DomainTick object.
   * **Dependencies**: vnpy==4.1.0, Python concurrent.futures (ThreadPoolExecutor).
2. **Core Application Service**
   * **Responsibility**: The application's core. It orchestrates the adapters via the ports, receives the DomainTick stream, and performs core domain logic (e.g., validating the tick data against business invariants like price \> 0). It has no knowledge of vnpy or NATS.
   * **Dependencies**: Pydantic.
3. **NATS Publisher Adapter**
   * **Responsibility**: Implements the EventPublisherPort. It receives DomainTick objects from the core service, serializes them using the configurable strategy, and publishes them to the NATS JetStream cluster.
   * **Dependencies**: nats.py, Pydantic.

### **Optimized Component Interaction Diagram**

Code snippet

graph TD
    subgraph "Infrastructure (External)"
        A\["vnpy CTP Gateway"\]
        E\["NATS JetStream Cluster"\]
    end

    subgraph "Adapters (Infrastructure Layer)"
        B\[CTP Gateway Adapter\]
        D\[NATS Publisher Adapter\]
    end

    subgraph "Core App (Domain & App Layers)"
        C \--- MarketDataPort \--- B
        C \--- EventPublisherPort \--- D
        C{Core Application Service}
    end

    A \-- "Raw Ticks" \--\> B
    B \-- "Translate to DomainTick" \--\> C
    C \-- "Execute Domain Logic (Validate)" \--\> C
    C \-- "Publish DomainTick" \--\> D
    D \-- "Serialize & Publish" \--\> E

    style C fill:\#FFE4B5

---

## **6\. External APIs**

*(Not applicable, as the service does not consume any third-party REST/GraphQL APIs.)*

---

## **7\. Core Workflows**

The primary workflow involves processing a market tick. The system is designed to be robust against backpressure (via bounded queues with a drop-and-log policy), serialization errors (via try/except blocks to prevent poison pills), and NATS publish failures (via an exponential backoff retry policy).

### **Workflow: Processing a Market Tick**

Code snippet

sequenceDiagram
    participant CTP\_Gateway as vnpy CTP Gateway\<br\>(Child Process)
    participant CTP\_Adapter as CTP Adapter\<br\>(Supervisor)
    participant Core\_Service as Core App Service\<br\>(Async Loop)
    participant NATS\_Adapter as NATS Publisher
    participant NATS\_Cluster as NATS JetStream

    CTP\_Gateway-\>\>+CTP\_Adapter: 1\. on\_tick(vnpy\_tick)
    CTP\_Adapter-\>\>CTP\_Adapter: 2\. Translate to DomainTick
    CTP\_Adapter--\>\>-Core\_Service: 3\. tick\_queue.put(domain\_tick)
    Core\_Service-\>\>+Core\_Service: 4\. Validate DomainTick
    Core\_Service--\>\>-Core\_Service: Validation OK
    Core\_Service-\>\>+NATS\_Adapter: 5\. publisher.publish(domain\_tick)
    NATS\_Adapter-\>\>NATS\_Adapter: 6\. Serialize (JSON/Pickle)
    NATS\_Adapter-\>\>+NATS\_Cluster: 7\. js.publish(subject, data)
    NATS\_Cluster--\>\>-NATS\_Adapter: 8\. Ack
    NATS\_Adapter--\>\>-Core\_Service: 9\. Return Success

---

## **8\. REST API Spec**

*(Not applicable.)*

---

## **9\. Database Schema**

*(Not applicable, as the MVP is a stateless service.)*

---

## **10\. Source Tree**

The project directory will be structured to clearly reflect the Hexagonal Architecture.

Plaintext

market-data-service/
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
├── src/
│   ├── adapters/
│   │   ├── ctp\_adapter.py
│   │   ├── nats\_publisher.py
│   │   └── serializers.py
│   ├── domain/
│   │   ├── models.py
│   │   └── ports.py
│   ├── application/
│   │   └── services.py
│   ├── config.py
│   └── \_\_main\_\_.py
├── tests/
│   ├── integration/
│   └── unit/
├── .dockerignore
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md

---

## **11\. Infrastructure and Deployment**

### **Infrastructure as Code**

* **Tool**: Docker Compose 2.24.x
* **Method**: A single docker-compose.yml file, used with environment-specific .env files, will define the application stack for all environments to prevent configuration drift.
* **Data Persistence**: Named volumes **must** be used for Prometheus and Grafana to persist monitoring data.

### **Deployment Strategy**

* **Strategy**: Script-based Docker Deployment.
* **CI/CD Platform**: GitHub Actions.
* **Image Registry**: **GitHub Container Registry (GHCR)**. CI will build and push images; on-prem servers will pull from GHCR.

### **Environments & Promotion Flow**

* A standard Development \-\> Staging \-\> Production flow will be used, with CI acting as the gatekeeper for merges into the main branch.

### **Rollback Strategy**

* **Method**: Re-deploying the previously stable Docker image tag from GHCR.

---

## **12\. Error Handling Strategy**

### **CTP Gateway Connection Errors**

* **Strategy**: **Thread Supervisor & Restart**. The CTP adapter runs the vnpy gateway in an isolated thread. Upon detecting a disconnection or failure, the adapter will shutdown the executor and create a new ThreadPoolExecutor with fresh threads (required for CTP reconnection).

### **NATS Publish Failures**

* **Strategy**: The NATS adapter will use an **exponential backoff** retry strategy.

### **"Poison Pill" Messages**

* **Strategy**: All processing steps, especially serialization, will be wrapped in try...except blocks to isolate failing messages, log them, and continue processing the queue, ensuring the service does not crash.

---

## **13\. Coding Standards**

### **Critical Rules**

1. **Strict Hexagonal Dependency**: Domain and application layers **must not** import from the adapters layer.
2. **Forced TDD**: All new logic **must** be developed following a Test-Driven Development approach.
3. **Pydantic for Data Structures**: All DTOs and domain models **must** be Pydantic models.
4. **Immutable Domain Objects**: Core domain models should be treated as immutable.
5. **No print()**: Use the configured JSON logger for all output.

---

## **14\. Test Strategy and Standards**

### **Testing Philosophy**

* **Approach**: Test-Driven Development (TDD).
* **Core Principle**: **Test Behavior, Not Implementation**. All tests must be valuable and avoid "vanity" checks.

### **Good vs. Bad Tests: A Specification for AI Agents**

* **Bad Tests (Avoid)**: Trivial assertions (assert True), testing constants, testing implementation details.
* **Good Tests (Enforce)**: Follow AAA pattern; verify a specific business rule or AC (with a comment linking to it); assert a meaningful outcome (return value or state change); verify interactions with mocks.

---

## **15\. Security**

A minimal set of security best practices will be enforced for this internal prototype.

* **Input Validation**: Handled by Pydantic models.
  **输入验证** ：由 Pydantic 模型处理。
* **Secrets Management**: CTP credentials **must** be loaded from environment variables via Pydantic BaseSettings.
  **机密管理** ： **必须**通过 Pydantic BaseSettings 从环境变量加载 CTP 凭证。
* **Dependency Security**: CI pipeline will include a job to scan for known vulnerabilities.
  **依赖安全** ：CI 管道将包括扫描已知漏洞的作业。
* **Authentication/Authorization**: Not in scope for the MVP.
  **身份验证/授权** ：不在 MVP 范围内。

---
