# **5\. Components**

The architecture is divided into the following components, adhering to the Ports and Adapters pattern.

## **Ports (Interface Definitions)**

* **MarketDataPort**: An input port for managing and consuming market data. It includes methods for lifecycle management (connect(), disconnect(), get\_status()) and provides an asynchronous stream of DomainTick data.  
* **EventPublisherPort**: An output port for publishing events. It includes a publish(tick: DomainTick) method.

## **Core Components**

1. **CTP Gateway Adapter**  
   * **Responsibility**: Implements the MarketDataPort. It encapsulates the vnpy CTP gateway, running it in a supervised thread (ThreadPoolExecutor). Its core tasks are managing the gateway's lifecycle, handling thread restarts on disconnection, and **translating** the external vnpy.TickData object into our internal DomainTick object.  
   * **Dependencies**: vnpy==4.1.0, Python concurrent.futures (ThreadPoolExecutor).  
2. **Core Application Service**  
   * **Responsibility**: The application's core. It orchestrates the adapters via the ports, receives the DomainTick stream, and performs core domain logic (e.g., validating the tick data against business invariants like price \> 0). It has no knowledge of vnpy or NATS.  
   * **Dependencies**: Pydantic.  
3. **NATS Publisher Adapter**  
   * **Responsibility**: Implements the EventPublisherPort. It receives DomainTick objects from the core service, serializes them using the configurable strategy, and publishes them to the NATS JetStream cluster.  
   * **Dependencies**: nats.py, Pydantic.

## **Optimized Component Interaction Diagram**

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
