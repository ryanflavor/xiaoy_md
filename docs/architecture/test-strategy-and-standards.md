# **14\. Test Strategy and Standards**

## **Testing Philosophy**

* **Approach**: Test-Driven Development (TDD).
* **Core Principle**: **Test Behavior, Not Implementation**. All tests must be valuable and avoid "vanity" checks.

## **Good vs. Bad Tests: A Specification for AI Agents**

* **Bad Tests (Avoid)**: Trivial assertions (assert True), testing constants, testing implementation details.
* **Good Tests (Enforce)**: Follow AAA pattern; verify a specific business rule or AC (with a comment linking to it); assert a meaningful outcome (return value or state change); verify interactions with mocks.

---
