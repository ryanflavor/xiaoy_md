# **5\. Components**

The architecture is divided into the following components, adhering to the Ports and Adapters pattern.

## **Ports (Interface Definitions)**

* **MarketDataPort**: An input port for managing and consuming market data. It includes methods for lifecycle management (connect(), disconnect(), get_status()) and provides an asynchronous stream of DomainTick data.
* **EventPublisherPort**: An output port for publishing events. It includes a publish(tick: DomainTick) method.

## **Core Components**

1. **CTP Gateway Adapter**
   * **Responsibility**: Implements the MarketDataPort. It encapsulates the vnpy CTP gateway, running it in a supervised thread (ThreadPoolExecutor). Its core tasks are managing the gateway's lifecycle, handling thread restarts on disconnection, and **translating** the external vnpy.TickData object into our internal DomainTick object.
   * **CTP Retry Constraint**: On failure or disconnect, the adapter must start a fresh session thread for each retry (threads are not reusable for CTP sessions). The supervisor coordinates retries and backoff; the executor may be reused.
   * **Dependencies**: vnpy==4.1.0, Python concurrent.futures (ThreadPoolExecutor).
2. **Core Application Service**
   * **Responsibility**: The application's core. It orchestrates the adapters via the ports, receives the DomainTick stream, and performs core domain logic (e.g., validating the tick data against business invariants like price > 0). It has no knowledge of vnpy or NATS.
   * **Dependencies**: Pydantic.
3. **NATS Publisher Adapter**
   * **Responsibility**: Implements the EventPublisherPort. It receives DomainTick objects from the core service, serializes them using the configurable strategy, and publishes them to the NATS JetStream cluster.
   * **Dependencies**: nats.py, Pydantic.
4. **Operations Orchestrator**
   * **Responsibility**: Automates lifecycle tasks via `scripts/operations/start_live_env.sh`, orchestrating NATS, the market-data-service, and subscription workers; emits structured logs/metrics for Prometheus.
   * **Dependencies**: Bash, uv, Docker Compose, structured logging.
5. **Subscription Health Agent**
   * **Responsibility**: Schedules and executes `scripts/operations/check_feed_health.py` to compare active subscriptions against the contract catalogue, triggering resubscribe or escalation flows.
   * **Dependencies**: Python CLI tooling, contract catalogue, Prometheus client, control-plane subject `md.subscriptions.active`.
6. **Observability Exporters**
   * **Responsibility**: Publish throughput, latency, coverage, rate-limit, and runbook status metrics to Prometheus and manage Grafana dashboard/alert provisioning.
   * **Dependencies**: prometheus-client, Grafana provisioning templates.
7. **Configuration Registry**
   * **Responsibility**: Validates and documents environment variables for primary/backup accounts, rate-limit tuning, and failover routing; ready for Vault/secret-store integration.
   * **Dependencies**: `.env` files, Pydantic BaseSettings, optional secret backends.

## **Optimized Component Interaction Diagram**

Code snippet

graph TD
    subgraph "Infrastructure (External)"
        A\["Primary CTP Gateway"\]
        A2\["Backup Feed / Alternate Source"\]
        E\["NATS JetStream Cluster"\]
    end

    subgraph "Adapters & Ops Layer"
        I\["Ops Orchestrator\\n(start\_live\_env.sh)"\]
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
