# Sprint 10 — Lessons Learned

**Goal:** Portfolio-ready. Tests pass, CI runs, a stranger can clone and run in under 5 minutes.

---

## 1. Unit testing services with shared package names

### The `services/` module collision problem

- Every Python service has its own `services/` package (e.g., `services/flight-service/services/state_machine.py`, `services/baggage-service/services/conveyor.py`). When running tests that import from multiple services, Python's module cache (`sys.modules`) causes cross-contamination — importing `services.conveyor` after `services.state_machine` returns the cached flight-service module.
- **Solution:** the `import_service_module()` helper in `tests/conftest.py` clears all `sys.modules` entries matching `services.*` and `db.*` before each import, then temporarily prepends the correct service root to `sys.path`. This isolates each service's module namespace per test.
- **Rule of thumb:** if your monorepo has multiple Python packages with the same top-level name, you cannot rely on normal imports in tests. You need explicit module cache management.

### Mocking module-level imports

- `services/incident-service/services/lifecycle.py` imports `db.neo4j` at module level. Since `neo4j` (the pip package) is not installed in the test environment, the import fails before any test can run.
- **Solution:** pre-install mock modules in `sys.modules` (`sys.modules["db"] = mock_db_module`, `sys.modules["db.neo4j"] = mock_neo4j_module`) before calling `import_service_module`. The module loads successfully because Python finds the mock in its cache.
- **Lesson:** avoid module-level side effects (database connections, Kafka producers) in files that contain pure business logic. If lifecycle rules and database queries live in the same file, the file becomes untestable without mocking infrastructure. Separating pure logic from I/O makes testing trivial.

---

## 2. What to test and what not to test

### Pure-logic functions are the highest-value test targets

- State machines, transition validators, TTR samplers, cascade rule tables, capacity calculators, METAR formatters — these are deterministic, side-effect-free functions that encode the simulation's core rules.
- 256 unit tests cover all six services' business logic without needing Docker, Neo4j, or Kafka running. They run in under 2 seconds.

### Integration tests need the full stack

- REST endpoint tests and resilience tests require all containers healthy. Using `pytest.mark.skipif` with a reachability check prevents CI failures when infra is unavailable.
- Integration tests verify the wiring (routes, auth, Neo4j connectivity, Kafka event flow) but are slower and more fragile. They complement, not replace, unit tests.

### Idempotency is hard to test at unit level

- Kafka consumer idempotency (duplicate event handling) requires a running Neo4j to verify that duplicate writes don't create duplicate nodes. This is inherently an integration test.
- The integration test suite includes idempotency checks for incident injection — posting the same incident twice should not create two records when the deduplication logic is working.

---

## 3. CI pipeline design

### Separate lint, test, and build jobs

- The CI pipeline has four jobs: `lint-python` (ruff), `lint-node` (eslint — non-blocking), `unit-tests` (pytest), and `docker-build` (compose build, depends on the first three).
- Keeping them separate gives clear feedback on what failed. A lint failure doesn't block developers from seeing test results.

### Node.js lint is non-blocking

- The gateway's eslint config may have style rules that don't affect correctness. Making it non-blocking (`|| true`) prevents cosmetic issues from blocking the entire pipeline while still surfacing warnings.

### Docker build as a final gate

- `docker compose build` without `up` validates that all Dockerfiles and dependency installs work. This catches missing pip packages, bad COPY paths, and Node.js build errors without needing to run the full stack.

---

## 4. Biggest architectural lessons (retrospective)

### Module-level side effects are the enemy of testability

- Services that import database drivers or Kafka producers at module scope force every test to either install those packages or mock them. The cleanest services separate pure logic (state machines, rules, formatters) from I/O (database queries, event production) at the file level.
- If redesigning from scratch: enforce a rule that `services/*.py` files contain only pure functions with no imports from `db/` or `kafka/`. I/O glue lives in `handlers/` files that import from both.

### The spec-first approach paid off

- Having complete SPEC.md files before coding meant every state machine, every transition condition, and every cascade rule was documented. Tests could be written directly from the spec without reading the implementation — a strong indicator of good specification.
- The Kafka event bus spec (`EVENT_BUS.md`) and data model (`DATA_MODEL.md`) served as contracts between services that never drifted because they were the implementation's source of truth.

### Cascade depth limit is non-negotiable

- The `CASCADE_MAX_DEPTH = 5` limit prevents runaway event storms. Testing confirmed that no cascade chain exceeds 5 hops, and the cascade engine correctly stops producing child incidents at the limit. Without this, a single runway incursion could generate an unbounded number of incidents at high sim speed.

---

## 5. Scaling limitations discovered

### Single-instance services

- All services run as single containers. There is no horizontal scaling, no consumer group balancing, no read replicas. This is fine for a portfolio project but would be the first thing to address in production.

### Neo4j Community Edition

- No clustering, no read replicas, no enterprise metrics endpoint. Every service's Neo4j queries hit the same single instance. At high sim speeds (3600x), the query volume can cause latency spikes.

### Kafka single-broker

- One Kafka broker with default replication factor of 1. No fault tolerance for the event bus itself. Acceptable for local development, not for production.

---

## 6. What would be redesigned from scratch

1. **Separate pure logic from I/O at the file level** — every `services/*.py` file should be importable without any infrastructure dependencies.
2. **Use Python namespace packages** or unique top-level package names per service (e.g., `flight_service.state_machine` instead of `services.state_machine`) to avoid the module collision problem.
3. **Add a shared `airport_common` package** for Pydantic models, Kafka envelope validation, and Neo4j connection setup — duplicated across all services today.
4. **Use Testcontainers** for integration tests instead of requiring a pre-running Docker stack.

---

## 7. What went well

- **256 unit tests in <2 seconds** — fast feedback loop on all business logic.
- **Smoke test script** validates the full stack end-to-end: health checks, auth, proxy routes, incident injection, cascade propagation, and Neo4j data presence.
- **CI pipeline** catches regressions on every push without requiring Docker infrastructure.
- **CHANGELOG.md** provides a sprint-by-sprint narrative of what was built and why.
- **The spec-first methodology** meant tests could be derived from documentation, not reverse-engineered from code.
