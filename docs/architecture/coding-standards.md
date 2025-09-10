# **13\. Coding Standards**

## **Critical Rules**

1. **Strict Hexagonal Dependency**: Domain and application layers **must not** import from the infrastructure layer.
2. **Forced TDD**: All new logic **must** be developed following a Test-Driven Development approach.
3. **Pydantic for Data Structures**: All DTOs and domain models **must** be Pydantic models.
4. **Immutable Domain Objects**: Core domain models should be treated as immutable.
5. **No print()**: Use the configured JSON logger for all output.
6. **Timezone Policy (China TZ)**: All timestamps produced and stored by the system MUST be timezone‑aware and use Asia/Shanghai (UTC+08:00). Incoming timestamps MUST be normalized to Asia/Shanghai before further processing.

### Timezone Guidance

- Domain models (e.g., MarketTick.timestamp) carry tz‑aware datetimes in Asia/Shanghai.
- Infrastructure responses (e.g., health checks) serialize timestamps with `+08:00` offset.
- Scripts and operational logs should print timestamps in Asia/Shanghai for operator clarity.
- When integrating with external systems that require UTC, perform conversion at the boundary and document it in the adapter; do not change the internal timezone policy.

---
