# **13\. Coding Standards**

## **Critical Rules**

1. **Strict Hexagonal Dependency**: Domain and application layers **must not** import from the adapters layer.  
2. **Forced TDD**: All new logic **must** be developed following a Test-Driven Development approach.  
3. **Pydantic for Data Structures**: All DTOs and domain models **must** be Pydantic models.  
4. **Immutable Domain Objects**: Core domain models should be treated as immutable.  
5. **No print()**: Use the configured JSON logger for all output.

---
