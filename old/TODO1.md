# TODO — Redesign and hardening backlog (from sprint lessons)

Derived from:

- docs/lessons-learned/sprint-0.md to docs/lessons-learned/sprint-9.md

BEFORE WRITING ANY CODE

Read these files in order:

TODO1.md — this backlog and prioritization
CLAUDE.md — architecture rules and constraints
docs/skills/SKILL.md — cross-cutting patterns
docs/lessons-learned/\*.md — all accumulated lessons

Focus especially on:

System-wide consistency
Failure recovery behavior
Test coverage of critical logic
Developer experience (DX)
Clean reproducibility

GOAL

Do all the tasks in P4 and P5 only.
Don't forget to run tests as you go.
Then mark them as complete here.

## P0 — reliability and correctness

- [x] Replace module-level mutable runtime state with class-based state holders in `weather-service`, `flight-service`, and `incident-service`.
  - Why: repeated `global`/`UnboundLocalError` failures in multiple sprints.
  - Done when: no service runtime path depends on Python `global` for mutable shared state.

- [x] Add startup catch-up logic for all services that process timeline transitions (`flight`, `baggage`, `passenger`).
  - Why: services may start mid-simulation with already-advanced entity states.
  - Done when: restart during active simulation converges to correct state without manual reset.

- [x] Enforce strict event envelope validation and logging at all Kafka consumers.
  - Why: malformed envelopes (for example missing `sim_time`) were silently dropped.
  - Done when: invalid envelopes are counted, logged, and exported as metrics; valid events still process.

- [x] Add integration tests for idempotency and duplicate event handling on all consumers.
  - Why: several services rely on in-memory dedup sets and event-order assumptions.
  - Done when: replaying duplicate messages does not create duplicate state mutations/events.

- [x] Add restart-rebuild tests for every in-memory structure (queues, zone maps, runway queue, alert caches).
  - Why: Neo4j is source of truth; in-memory state must be rebuildable.
  - Done when: cold restart test suite passes with no divergence in aggregate state.

## P1 — data model and event flow redesign

- [x] Implement incident-to-flight impact linking (`AFFECTS`) with clear ownership and write path.
  - Why: incident reports currently show zero affected flights in many cases.
  - Done when: incident reports return non-zero affected flights where runway/gate impact is expected.

- [x] Implement delayed incident cascades using `delay_sim_min` and a pending-cascade scheduler.
  - Why: cascade rules currently fire instantly.
  - Done when: cascades occur at configured simulated delay and remain deterministic across restarts.

- [x] Add protocol lifecycle manager with global override rules (including `FULL_EVACUATION` precedence).
  - Why: protocol conflicts are not currently resolved globally.
  - Done when: active protocol state is queryable and override semantics are enforced.

- [x] Replace weather `ceiling_ft = -1` sentinel with proper nullable modeling.
  - Why: sentinel values add conversion risk and query ambiguity.
  - Done when: storage/query paths handle null ceiling consistently without sentinel conversions.

- [x] Add `previous_category` persistence for weather transitions in Neo4j.
  - Why: simplifies transition analytics without replaying event history.
  - Done when: transition history endpoint can return previous/new category per state transition directly.

## P2 — query and schema hardening

- [x] Build a Cypher compatibility checklist and lint script for Neo4j Community constraints.
  - Why: repeated syntax/behavior issues (`NOT x IN`, OPTIONAL MATCH aggregation, EXISTS scope).
  - Done when: CI runs query validation against Neo4j Community and blocks incompatible patterns.

- [x] Add schema contract tests for required node properties and relationship names from `DATA_MODEL.md`.
  - Why: missing properties and relationship-name drift caused downstream failures.
  - Done when: CI fails if any required property/relationship is absent or renamed.

- [x] Pre-create all Kafka topics in infrastructure bootstrap.
  - Why: avoid `UNKNOWN_TOPIC_OR_PART` startup noise and uncertain auto-create behavior.
  - Done when: no service logs missing-topic warnings during clean startup.

## P3 — gateway and dashboard redesign

- [x] Add short-TTL cache (5-10s) for gateway aggregate endpoint `/api/v1/airport`.
  - Why: each request fans out to multiple upstream services.
  - Done when: upstream request volume drops measurably with no stale-data regressions.

- [x] Upgrade gateway WebSocket snapshot to include multi-service bootstrap state, not only `sim_time`.
  - Why: faster and safer client resync on reconnect.
  - Done when: dashboard reconnect restores usable state before first incremental events arrive.

- [x] Move rate limiting from per-IP to per-token (keep per-IP fallback).
  - Why: better fairness in shared network environments.
  - Done when: token-scoped limits are enforced and observable in metrics.

- [x] Replace dashboard REST `fetch + useEffect` with React Query for hydration/caching/refetch.
  - Why: reduce boilerplate and improve stale/loading/error handling.
  - Done when: all main dashboards use React Query with consistent query keys and retry policy.

- [x] Replace large WebSocket event `if/else` chains with registry-based dispatchers.
  - Why: easier extensibility and lower maintenance risk.
  - Done when: adding a new event type requires only handler registration.

- [x] Add unit tests for Zustand reducers/stores and component tests for critical dashboard flows.
  - Why: sprint 8 identified testing gap.
  - Done when: CI includes store reducer coverage and API-mocked component flow tests.

## P4 — observability and operations

- [x] Standardize metric updates at mutation sites plus periodic reconciliation.
  - Why: tick-only metric updates missed transient states.
  - Done when: alert-critical metrics are emitted immediately on state change in all services.

- [x] Add metric contract tests (names, labels, and cardinality guards).
  - Why: prevent dashboard/alert drift and high-cardinality regressions.
  - Done when: CI validates expected metric families and bounded label dimensions.

- [x] Add Kafka consumer freshness probe (last-message timestamp) for gateway readiness.
  - Why: boolean "connected" is insufficient for real readiness.
  - Done when: readiness fails when consumer stalls beyond threshold.

- [x] Add recording rules for high-frequency dashboard aggregates.
  - Why: reduce query-time CPU in Prometheus and Grafana.
  - Done when: top dashboard queries read from recording rules with equivalent outputs.

## P5 — developer experience and process

- [x] Add lint rule/check for module-level augmented assignment misuse (`+=`, `-=`, etc.) in functions.
  - Why: recurring Python scoping bug pattern across sprints.
  - Done when: CI flags potential `UnboundLocalError` patterns before merge.

- [x] Add "mid-simulation startup" and "restart convergence" checklists to service SKILL docs.
  - Why: this failure mode appears repeatedly in domain services.
  - Done when: each service SKILL has explicit startup-convergence guidance and tests linked.

- [x] Add a reusable test harness for accelerated sim-speed alert validation.
  - Why: alert timing differs significantly at high simulation speed.
  - Done when: harness can run key alert scenarios at 1x and high speed with deterministic assertions.

- [x] Add a nice icon to the overall dashboard page and service-specific pages.
  - Why: polish and easier visual identification.
  - Done when: dashboard tabs show distinct icons representing the airport theme.
