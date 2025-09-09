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

## **Architectural and Design Patterns**

* **Hexagonal Architecture (Ports and Adapters)**: This is our primary architectural pattern. The core business logic is isolated and interacts with the outside world through well-defined "ports" (interfaces). The CTP integration is an input adapter, and the NATS publication is an output adapter.
* **Domain-Driven Design (DDD)**: We will model our logic around the core "market data processing" domain, using Pydantic to define clear domain objects and a ubiquitous language.
* **Thread Supervisor Pattern**: The CTP adapter runs the vnpy gateway in a separate thread pool and acts as a supervisor. On disconnection/failure it spawns a fresh session thread for each retry (CTP requires a new thread per session), using exponential backoff and capped retries.
* **Publisher-Subscriber Pattern**: This is the fundamental pattern for communication with downstream consumers via NATS, ensuring a high degree of decoupling.
* **Configurable Serialization Strategy (Strategy Pattern)**: The service will use a configurable strategy for data serialization (Pickle for flexibility, Pydantic+JSON for standardization), allowing the system to adapt to different consumer needs.

---
