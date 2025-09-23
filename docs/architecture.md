# **Architecture Document: Internal Market Data Service Prototype**

| Date | Version | Description | Author |
| :---- | :---- | :---- | :---- |
| 2025-09-18 | 1.1 | Production operations & multi-source expansion baseline | Architect (Winston) |
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

Epic 3 formalizes a production-operations plane around the service. Automated runbooks sequence start/restart/shutdown of NATS, the market-data-service, and subscription workers; health agents continuously reconcile live subscriptions against the required contract universe; and the observability stack exports metrics into Prometheus with Grafana-driven dashboards and alerts. Multi-account configuration and alternate feed routing now sit alongside the primary CTP gateway so failover flows can execute without disturbing downstream subscribers.

### **Architectural and Design Patterns**

* **Hexagonal Architecture (Ports and Adapters)**: This is our primary architectural pattern. The core business logic is isolated and interacts with the outside world through well-defined "ports" (interfaces). The CTP integration is an input adapter, and the NATS publication is an output adapter.
* **Domain-Driven Design (DDD)**: We will model our logic around the core "market data processing" domain, using Pydantic to define clear domain objects and a ubiquitous language.
* **Thread Supervisor Pattern**: The CTP adapter runs the vnpy gateway in a separate thread pool and acts as a supervisor, restarting the thread upon disconnection (required by CTP's reconnection mechanism).
* **Publisher-Subscriber Pattern**: This is the fundamental pattern for communication with downstream consumers via NATS, ensuring a high degree of decoupling.
* **Configurable Serialization Strategy (Strategy Pattern)**: The service will use a configurable strategy for data serialization (Pickle for flexibility, Pydantic+JSON for standardization), allowing the system to adapt to different consumer needs.
* **Runbook Automation Pattern**: Operational scripts encapsulate the startup, restart, and shutdown choreography so operators can execute repeatable playbooks with idempotent behavior.
* **Observable Control Loop Pattern**: Subscription health agents feed metrics to Prometheus and trigger Grafana alerts, creating a closed loop between detection and remediation.
* **Failover Playbook Pattern**: Primary/backup gateway wiring and configuration profiles enable rapid, low-risk failover without modifying core application code.

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
| **Monitoring** | Prometheus | 2.51.x | Metrics collection & storage | Required for production operations; integrates with health agents. |
| **Visualization & Alerting** | Grafana | 10.4.x | Dashboards and alert routing | Delivers runbook-ready insights and alerting automation. |
| **Operational Automation** | Bash / Python CLI | N/A | Runbooks (`start_live_env.sh`, `check_feed_health.py`) | Provides repeatable orchestration and health remediation flows. |
| **Secrets & Config Management** | `.env` + Vault-ready pattern | N/A | Live credential & rate-limit governance | Documents primary/backup accounts, supports secure storage upgrades. |

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
4. **Operations Orchestrator**
   * **Responsibility**: Automates lifecycle tasks through scripts such as `scripts/operations/start_live_env.sh`, sequencing NATS, the market-data-service, and subscription workers; captures command outcomes and exposes hooks for alert-driven retries.
   * **Dependencies**: Bash, uv, Docker Compose, structured logging.
5. **Subscription Health Agent**
   * **Responsibility**: Executes scheduled checks (`scripts/operations/check_feed_health.py`) comparing active subscriptions against the expected contract universe, emitting structured reports and triggering remediation paths.
   * **Dependencies**: Python CLI tooling, contract catalogue, Prometheus client.
6. **Observability Exporters**
   * **Responsibility**: Surface runtime metrics (throughput, coverage, latency, rate-limit events) to Prometheus and manage alert definitions consumed by Grafana dashboards.
   * **Dependencies**: prometheus-client, Grafana provisioning templates.
7. **Configuration Registry**
   * **Responsibility**: Documents and validates environment variables for primary/backup accounts, rate-limit tuning, and failover routing; designed to plug into Vault or encrypted stores without altering code paths.
   * **Dependencies**: `.env` files, Pydantic BaseSettings, optional secret backends.

### **Optimized Component Interaction Diagram**

Code snippet

graph TD
    subgraph "Infrastructure (External)"
        A\["Primary CTP Gateway"\]
        A2\["Backup Feed / Alternate Source"\]
        E\["NATS JetStream Cluster"\]
    end

    subgraph "Adapters & Ops Layer"
        I\["Ops Orchestrator\n(start\_live\_env.sh)"\]
        B\["CTP Gateway Adapter"\]
        H\["Subscription Health Agent"\]
        D\["NATS Publisher Adapter"\]
        X\["Observability Exporters"\]
        I \-- Bootstrap --> B
        B \-- Heartbeat --> H
        H \-- Recovery Hooks --> I
        H \-- Metrics --> X
        D \-- Publish Ack --> X
    end

    subgraph "Core App (Domain & App Layers)"
        C \--- MarketDataPort \--- B
        C \--- EventPublisherPort \--- D
        C{Core Application Service}
    end

    subgraph "Operations & Insights"
        P\["Prometheus"\]
        G\["Grafana Alerts"\]
        O\["Ops Engineer"\]
    end

    A \-- "Raw Ticks" \--\> B
    A2 \-- "Failover Route" \--\> B
    C \-- "Publish DomainTick" \--\> D
    D \-- "Publish Ticks" \--\> E
    X \-- "Metric Samples" \--\> P
    P \-- "Dashboards & Alerts" \--\> G
    G \-- "Alert Actions" \--\> O
    O \-- "Runbook Trigger" \--\> I

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

### **Workflow: Live Environment Orchestration**

Code snippet

sequenceDiagram
    participant Ops as Ops Engineer
    participant Runbook as start\_live\_env.sh
    participant Compose as Docker Compose
    participant NATS as NATS Cluster
    participant Service as Market Data Service
    participant Subs as Subscription Worker
    participant Prom as Prometheus

    Ops-\>\>+Runbook: 1\. Execute runbook (pre-market)
    Runbook-\>\>+Compose: 2\. docker compose up --profile live
    Compose-\>\>+NATS: 3\. Start NATS live profile
    Compose-\>\>+Service: 4\. Start market-data-service
    Runbook-\>\>+Subs: 5\. Launch full\_feed\_subscription.py
    Service-\>\>Runbook: 6\. Emit readiness / health log
    Runbook-\>\>Prom: 7\. Register job status metrics
    Runbook--\>\>-Ops: 8\. Summarize success / errors

### **Workflow: Subscription Health Check & Recovery**

Code snippet

sequenceDiagram
    participant Scheduler as Cron/Scheduler
    participant Health as check\_feed\_health.py
    participant Service as Market Data Service
    participant Catalogue as Contract Catalogue
    participant Prom as Prometheus
    participant Ops as Ops Engineer

    Scheduler-\>\>+Health: 1\. Invoke health script
    Health-\>\>+Service: 2\. Fetch active subscription list
    Health-\>\>Catalogue: 3\. Retrieve expected contract universe
    Health-\>\>Health: 4\. Compare + detect gaps/latency issues
    Health-\>\>Prom: 5\. Push metrics / anomalies
    Prom-\>\>Ops: 6\. Fire Grafana alert (if thresholds breached)
    Ops-\>\>Health: 7\. Trigger remediation (resubscribe / escalate)
    Health--\>\>-Scheduler: 8\. Exit code reflects status

### **Workflow: Feed Failover Drill**

Code snippet

sequenceDiagram
    participant Ops as Ops Engineer
    participant Runbook as start\_live\_env.sh (failover mode)
    participant Config as Config Registry
    participant Adapter as CTP Adapter
    participant Backup as Backup Feed
    participant Prom as Prometheus
    participant Consumers as Downstream Subscribers

    Ops-\>\>+Runbook: 1\. Invoke failover playbook
    Runbook-\>\>Config: 2\. Load backup credentials/profile
    Runbook-\>\>Adapter: 3\. Restart adapter with backup config
    Adapter-\>\>Backup: 4\. Establish new feed session
    Adapter-\>\>Consumers: 5\. Maintain outbound tick stream
    Prom-\>\>Ops: 6\. Monitor latency / drop indicators
    Ops--\>\>-Runbook: 7\. Confirm stability & log drill outcome

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
│   └── ops/
│       ├── production-runbook.md
│       ├── monitoring-dashboard.md
│       └── subscription-check.md
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
├── scripts/
│   └── operations/
│       ├── start\_live\_env.sh
│       ├── full\_feed\_subscription.py
│       └── check\_feed\_health.py
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

### **Operational Automation & Runbooks**

* **Primary Script**: `scripts/operations/start_live_env.sh` orchestrates pre-market startup, intra-day restarts, and controlled shutdown with structured logging and exit codes.
* **Subscription Worker**: `scripts/operations/full_feed_subscription.py` now exposes CLI flags for rate limiting, retries, and health probes so runbooks can operate headlessly.
* **Health Checks**: `scripts/operations/check_feed_health.py` produces machine-readable reports (JSON/exit status) for CI, cron, and manual execution.
* **Scheduling**: Cron or systemd timers execute health checks and drill playbooks; each invocation registers metrics to Prometheus via pushgateway or direct client.

### **Configuration & Secrets Governance**

* **Environment Layout**: `.env.example` documents `CTP_PRIMARY_*`, `CTP_BACKUP_*`, rate-limit knobs, and monitoring toggles; production secrets stored in Vault-compatible secure stores.
* **Validation**: Pydantic BaseSettings performs boot-time validation and surfaces misconfiguration errors to runbook logs and alerts.
* **Rotation**: Credential rotation playbooks mirror failover drills to ensure downstream consumers remain unaffected.

### **Monitoring & Alerting Integration**

* **Metrics**: Prometheus scrapes the market-data-service, subscription workers, and runbook exporters for throughput, coverage, latency, and error counts.
* **Dashboards**: Grafana dashboards bundle default panels (coverage gap heatmap, mps trend, rate-limit incidents) and ship with provisioning templates under version control.
* **Alerts**: Grafana Alertmanager routes incidents to the ops channel; alerts reference runbook steps and link to remediation scripts.

### **Failover & Recovery Strategy**

* **Playbooks**: Dedicated failover mode in `start_live_env.sh` swaps credentials/config profiles and verifies recovery via health metrics.
* **Downstream Assurance**: Alert rules watch consumer lag/backlog to confirm switchovers remain transparent to subscribers.
* **Rollback**: Previous configuration snapshots and Docker image tags are retained so rollback equals re-running the runbook with last-known-good parameters.

### **Deployment Strategy**

* **Strategy**: Script-based Docker Deployment.
* **CI/CD Platform**: GitHub Actions.
* **Image Registry**: **GitHub Container Registry (GHCR)**. CI will build and push images; on-prem servers will pull from GHCR.

### **Environments & Promotion Flow**

* A standard Development \-\> Staging \-\> Production flow will be used, with CI acting as the gatekeeper for merges into the main branch.

### **Rollback Strategy**

* **Method**: Re-deploying the previously stable Docker image tag from GHCR and reapplying the last-known-good configuration profile through the automation scripts.

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
