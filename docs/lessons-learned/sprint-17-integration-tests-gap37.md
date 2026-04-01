# Sprint 17 — Cross-Service Integration Tests & GAP-3-7 Completion

**Date:** 2026-04-01  
**Scope:** Integration test coverage for BUG-1 through BUG-4 identified in sprint-16 audit; complete GAP-3-7 flight type filter  
**Ref:** `docs/lessons-learned/sprint-16-full-audit-report.md` §6

---

## 1. Summary

Following the sprint-16 audit that found and fixed 4 critical cross-service bugs, this sprint adds dedicated tests to prevent regressions and completes the one partially-done ROADMAP item identified in the audit.

**Deliverables:**

- 25 new unit tests validating cross-service event contracts (`tests/unit/test_event_chain_contracts.py`)
- Integration test suite for live event chain validation (`tests/integration/test_event_chains.py`)
- Flight type filter dropdown in dashboard FIDSPanel (completes GAP-3-7)

---

## 2. Unit Tests: Event Chain Contract Validation

File: `tests/unit/test_event_chain_contracts.py`

These are **static analysis tests** — they parse service source code to verify cross-service contract alignment without requiring Neo4j or Kafka. This ensures regressions are caught at CI time.

### Test Classes

| Class                                       | Bug     | What it validates                                                                                                            |
| ------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `TestBug1DGClassTypeComparison`             | BUG-1   | `str(dg_class) != "3"` handles both string and int; no bare `dg_class != 3` in AST                                           |
| `TestBug2BaggageFlaggedFieldName`           | BUG-2   | incident-service reads `scan_zone` (not `zone_id`); field exists in producer payload                                         |
| `TestBug3SystemFailureLocationAlignment`    | BUG-3   | `_pick_location("system_failure")` keys ⊆ baggage `FAILURE_IMPACT` keys; no `terminal-X-power` format                        |
| `TestBug4NoDuplicateProbabilisticInjection` | BUG-4   | sim-orchestrator `_on_hour_boundary` has no injection; incident-service has weather modifiers; base probabilities match spec |
| `TestEventEnvelopeContract`                 | General | All producers include `event_id` and `sim_time`; all consumers check idempotency                                             |
| `TestTopicSubscriptionAlignment`            | General | Consumer subscriptions match EVENT_BUS.md §2 topic catalogue                                                                 |

### Design Decisions

- **AST parsing for BUG-1**: Rather than just `grep`-ing for `str(dg_class)`, we parse the AST to verify no `Compare` node exists with a bare `Name("dg_class")` compared to `Constant(3)`. This catches semantic regressions even if the surrounding code changes.
- **Non-baggage locations excluded in BUG-3**: `check-in-system` and `fids-system` are legitimate system failure locations that don't affect baggage conveyors. The test correctly excludes them from the FAILURE_IMPACT alignment check.

---

## 3. Integration Tests: Live Event Chain Validation

File: `tests/integration/test_event_chains.py`

These require the full stack running (`docker compose up --build`) and validate actual Kafka event propagation between services.

### Test Classes

| Class                                | Chain validated                                                                         |
| ------------------------------------ | --------------------------------------------------------------------------------------- |
| `TestBug1Bug2DGFireChain`            | Inject baggage_fire → verify incident created with correct location                     |
| `TestBug3SystemFailureConveyorChain` | Inject power-A failure → verify baggage zones offline → resolve → verify zones restored |
| `TestBug4ProbabilisticRate`          | Verify probabilistic incident count is not doubled                                      |
| `TestWeatherFlightCascade`           | Weather degradation → severe_weather incident                                           |
| `TestIncidentFlightReaction`         | Runway incursion → cascade propagation → flight delays                                  |
| `TestLiveEventSchemaValidation`      | Verify live data matches EVENT_BUS.md and DATA_MODEL.md schemas                         |

### Polling Pattern

Integration tests use a `_poll_until(predicate, description)` helper that retries up to 30 seconds. This handles the async nature of Kafka event propagation without introducing `sleep()` calls.

---

## 4. Dashboard: Flight Type Filter (GAP-3-7 Complete)

File: `dashboards/art-dashboard/src/pages/FlightBoard/FlightBoardPage.tsx`

The sprint-16 audit noted GAP-3-7 was "displayed and sortable, but not filterable via dropdown." Added:

- `FLIGHT_TYPE_OPTIONS` constant with all 5 flight types plus "All types" default
- `<select>` dropdown in each FIDSPanel header
- `typeFilter` state with `useMemo` filtering before sort
- Page reset on filter change
- Filtered count display: "Departures (42/210)" when filtered

---

## 5. Verification

| Check                      | Result     |
| -------------------------- | ---------- |
| Unit tests (476 total)     | All passed |
| New event chain tests (25) | All passed |
| Ruff lint                  | Clean      |
| TypeScript strict          | No errors  |
| npm build (dashboard)      | Success    |

---

## 6. Key Insight

The sprint-16 audit revealed that **cross-service event contracts are the most fragile part of a microservice architecture**. Each service worked correctly in isolation, but:

- Type coercion mismatches (string vs int) at JSON boundaries
- Field name mismatches between producer and consumer
- Location key format disagreements between services
- Duplicate behavior from redundant implementations

These are all **integration boundary issues** that unit tests within a single service cannot catch. The static analysis tests added here bridge this gap by parsing source code across service boundaries — catching contract misalignments at CI time without requiring live infrastructure.
