# **3\. Tech Stack**

This table represents the definitive technology choices for the project. All development must adhere to these specifications.

## **Cloud Infrastructure**

* **Provider**: Local Area Network (LAN) / On-Premises  
* **Key Services**: Docker, NATS JetStream Cluster, GitHub Container Registry (GHCR)

## **Technology Stack Table**

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
