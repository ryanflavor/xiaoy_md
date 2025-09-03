# 50 Key Terms for Domain-Driven Design (DDD)

A curated list of 50 essential concepts in DDD, categorized for a structured learning path from core philosophy to implementation patterns.

---

### Part 1: Core Philosophy & Principles

1.  **Domain**: The business problem space that the software is intended to solve (e.g., "e-commerce shipping," "online banking transactions").
2.  **Domain-Driven Design (DDD)**: A software development methodology that focuses on modeling the software to match the business domain, managing its complexity.
3.  **Model-Driven Design**: The principle that the domain model is the core of the design, and the code implementation should be a direct reflection of that model.
4.  **Ubiquitous Language**: A shared, unambiguous language developed by the team (developers, domain experts, stakeholders) to describe the domain. It should be used in all conversations, documentation, and code.
5.  **Domain Expert**: A person with deep knowledge of the business domain, who provides the necessary insights for building the domain model.
6.  **Domain Logic**: Also known as Business Logic. These are the rules, constraints, and processes that are fundamental to the business domain.
7.  **Rich Domain Model**: A style of domain model where objects contain not only data (attributes) but also the business logic (methods) that operates on that data. This is the ideal pursued by DDD.
8.  **Anemic Domain Model**: An anti-pattern where domain objects are merely data containers with getters and setters, and all business logic is located in external service classes.
9.  **Core Domain**: The most complex and valuable part of the business domain that provides a competitive advantage. This is where DDD efforts should be focused.
10. **Problem Space**: The space concerning "what" the business does—its needs, processes, and rules.
11. **Solution Space**: The space concerning "how" to implement a solution with technology—the system design and code. DDD aims to align the solution space with the problem space.

---

### Part 2: Strategic Design

Strategic Design deals with managing large, complex systems by defining clear boundaries and relationships between different parts of the domain.

12. **Bounded Context**: A central pattern in DDD. It is an explicit boundary (e.g., a microservice, a module) within which a specific domain model is well-defined and consistent. The Ubiquitous Language has a precise meaning inside this boundary.
13. **Context Map**: A diagram illustrating the relationships and integrations between different Bounded Contexts, providing a high-level architectural view.
14. **Shared Kernel**: A part of the domain model (code, data schema) that is shared by two or more Bounded Contexts. Requires strong team coordination.
15. **Customer-Supplier**: A relationship where one Bounded Context (the downstream "Customer") depends on another (the upstream "Supplier"). The Customer's needs influence the Supplier's priorities.
16. **Conformist**: A relationship where the downstream "Customer" context conforms to the model and language of the upstream "Supplier" context without trying to translate it.
17. **Anti-Corruption Layer (ACL)**: A defensive layer of code between two Bounded Contexts that translates models from one context to another, protecting the internal model from being "corrupted" by external influences.
18. **Open Host Service (OHS)**: A pattern where a Bounded Context defines a standardized, open protocol (like a REST API) for other contexts to integrate with it.
19. **Published Language**: A well-documented, shared language (e.g., JSON schema, Avro) used for communication across Bounded Contexts, often in conjunction with an Open Host Service.
20. **Separate Ways**: A relationship where two Bounded Contexts have no integration at all and evolve independently.
21. **Subdomain**: A logical partitioning of the overall business domain based on functionality.
22. **Supporting Subdomain**: A part of the business that is not the core competency but is necessary to support the Core Domain. It's often not complex.
23. **Generic Subdomain**: A non-unique part of the business that can be solved by off-the-shelf software or common solutions (e.g., authentication, email notifications).

---

### Part 3: Tactical Design

Tactical Design focuses on the "micro" level—designing high-quality domain models within a single Bounded Context using a set of building-block patterns.

24. **Entity**: A domain object defined by its unique identity and continuous lifecycle, rather than its attributes (e.g., a User, an Order).
25. **Value Object**: A domain object defined by its attributes, not a unique ID. They are typically immutable, and their equality is based on their values (e.g., an Address, a DateRange, Money).
26. **Immutable**: A characteristic of an object whose state cannot be modified after it is created. Any "modification" results in a new object. A key feature of Value Objects.
27. **Aggregate**: A cluster of associated domain objects (Entities and Value Objects) that are treated as a single unit for data changes. It is the boundary for transactional consistency.
28. **Aggregate Root**: A specific entity within an Aggregate that serves as the single entry point for all external access. It is responsible for enforcing the aggregate's invariants.
29. **Invariant**: A business rule or condition that must always be true for an Aggregate to be in a consistent state.
30. **Repository**: An interface that provides a collection-like abstraction for accessing Aggregate Roots, decoupling the domain model from data persistence technology.
31. **Factory**: An object responsible for creating complex objects or Aggregates, ensuring they are created in a valid state.
32. **Domain Service**: An object that holds domain logic that doesn't naturally belong to any single Entity or Value Object, often coordinating across multiple aggregates. Services are stateless.
33. **Domain Event**: An object that represents something significant that has already happened in the domain (e.g., `OrderPlaced`, `UserRegistered`). Used for decoupling logic.
34. **Module / Package**: A way to organize domain objects into highly cohesive groups within a Bounded Context to reduce complexity.

---

### Part 4: Architecture & Supporting Patterns

These patterns and architectural styles support the successful implementation of DDD.

35. **Layered Architecture**: A classic architecture pattern separating code into layers: User Interface (UI), Application, Domain, and Infrastructure.
36. **Application Service**: A service in the Application Layer that orchestrates domain objects to fulfill a specific use case. It contains no business logic itself.
37. **Infrastructure Layer**: The layer providing technical capabilities for other layers, such as database access (Repository implementations), message queues, and external API clients.
38. **Dependency Inversion Principle (DIP)**: A principle stating that high-level modules should not depend on low-level modules; both should depend on abstractions. Crucial for decoupling the Domain Layer from the Infrastructure Layer.
39. **Hexagonal Architecture / Ports and Adapters**: An architectural style that isolates the application core (domain) from external concerns (UI, database) by communicating through "Ports" (interfaces) and "Adapters" (implementations).
40. **CQRS (Command Query Responsibility Segregation)**: An architectural pattern that separates write operations (Commands) from read operations (Queries) into different models and paths.
41. **Event Sourcing**: A persistence pattern where the state of an object is not stored directly. Instead, the full sequence of Domain Events that led to its state is stored.
42. **Event Storming**: A collaborative workshop technique where developers and domain experts discover the domain by brainstorming Domain Events on a timeline.
43. **Specification**: A pattern that encapsulates a business rule for validation or selection into a separate, composable object.
44. **Unit of Work**: An object that tracks changes to business objects during a transaction and coordinates the writing of these changes to the database.
45. **DTO (Data Transfer Object)**: A simple object used to transfer data between layers or services, containing no business logic.
46. **Side-Effect-Free Functions**: Functions that do not modify any external state. Methods on Value Objects should be side-effect-free.
47. **Idempotent**: The quality of an operation where executing it multiple times has the same effect as executing it once. Important for Command and Event handlers.
48. **Consistency Boundary**: A boundary within which all invariants must be consistent after a transaction. In DDD, the Aggregate is the consistency boundary.
49. **Saga**: A pattern for managing data consistency across multiple services in a distributed transaction, typically by choreographing a sequence of local transactions using events.
50. **Refactoring Toward Deeper Insight**: The continuous process of refining the domain model and code as the team's understanding of the domain deepens.
