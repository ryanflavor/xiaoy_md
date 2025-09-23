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
| **Monitoring** | Prometheus | 2.51.x | Metrics collection & storage | Required for production ops; integrates with subscription health agents. |
| **Visualization & Alerting** | Grafana | 10.4.x | Dashboards & alert routing | Enables runbook-ready dashboards and alerting automation. |
| **Front-End Framework** | React | 18.3.x | Operations console UI | Mature ecosystem, strong telemetry integration, supports bilingual UX. |
| **Front-End Bundler** | Vite | 5.3.x | Fast dev server & build tooling | Instant feedback for ops workflows, supports module federation for future consoles. |
| **Styling System** | Tailwind CSS + CSS Variables | 3.4.x | Tokenized dark theme implementation | Enforces high-contrast Grafana-inspired aesthetic, accelerates component theming. |
| **Client Data Layer** | TanStack Query | 5.51.x | Prometheus/API polling, cache orchestration | Handles high-frequency polling with stale-while-revalidate semantics, minimizes redundant fetches. |
| **UI State Store** | Zustand | 5.0.x | Session/profile state, modal orchestration | Lightweight store with predictable updates, no Redux boilerplate. |
| **UI Testing** | Vitest + React Testing Library + Playwright | Vitest 1.6.x / Playwright 1.45.x | Component/unit, accessibility, and drill flow automation | Covers mock-mode drills, ensures regression-proof runbook interactions. |
| **Operational Automation** | Bash / Python CLI | N/A | Runbooks (`start_live_env.sh`, `check_feed_health.py`) | Implements repeatable start/stop/health workflows. |
| **Secrets & Config Management** | `.env` + Vault-ready pattern | N/A | Credential governance & rate-limit tuning | Documents primary/backup accounts, supports secure storage upgrades. |

---
