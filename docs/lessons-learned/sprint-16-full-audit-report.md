# Sprint 16 — Full Audit & Verification Report

**Date:** 2026-04-01  
**Scope:** Deep audit of all ROADMAP "done" items, spec compliance, cross-service integration  
**Method:** Static analysis, spec comparison, unit test execution, dashboard build verification

---

## 1. Executive Summary

A comprehensive audit of the entire Arthur Airport digital twin was performed, verifying all items marked "done" in ROADMAP.md against actual code, specs, and functional behavior.

**Key findings:**

- **4 critical bugs** found and fixed (broken cross-service event chains)
- **4 moderate issues** found and fixed (missing API params, spec deviations)
- **1 failing unit test** found and fixed
- All 451 unit tests now pass
- Ruff lint passes clean
- Dashboard TypeScript build passes clean

---

## 2. Changes Made

### Critical Bug Fixes

#### BUG-1: DG class type mismatch prevents baggage_fire auto-trigger

**File:** `services/incident-service/kafka/consumer.py:459`  
**Root cause:** `dg_class != 3` compared string `"3"` to integer `3` — always True, so the baggage fire trigger path was completely dead.  
**Fix:** Changed to `str(dg_class) != "3"`.  
**Impact:** The entire auto-triggered baggage fire chain (DG class 3 flagged → probabilistic fire) was broken since implementation.

#### BUG-2: BaggageFlagged event field name mismatch

**File:** `services/incident-service/kafka/consumer.py:464`  
**Root cause:** Code read `payload.get("zone_id")` but baggage-service emits field `scan_zone` in BaggageFlagged events.  
**Fix:** Changed to `payload.get("scan_zone", "baggage-handling")`.  
**Impact:** Fire location always defaulted to generic "baggage-handling" instead of the actual zone.

#### BUG-3: System failure location key mismatch (incident→baggage)

**File:** `services/incident-service/kafka/consumer.py:574`  
**Root cause:** Incident-service generated power failure locations as `"terminal-A-power"`, `"terminal-B-power"` but baggage-service's FAILURE_IMPACT map expects `"power-A"`, `"power-B"`.  
**Fix:** Changed location generation to emit `"power-A"`, `"power-B"` matching the baggage-service mapping.  
**Impact:** Power outage incidents never halted conveyor zones — a complete failure of the power-outage→conveyor-halt chain.

#### BUG-4: Double probabilistic incident injection

**Files:** `services/sim-orchestrator/main.py`, `services/sim-orchestrator/services/injector.py`  
**Root cause:** Both sim-orchestrator (via `evaluate_probabilistic_events` on hour boundary) AND incident-service (via its own `_evaluate_probabilistic_events`) independently generated probabilistic incidents, causing ~2× the intended incident rate.  
**Fix:** Removed probabilistic injection from sim-orchestrator's hour boundary callback. The incident-service implementation is retained as it has the richer modifier system (weather-aware probability adjustments).  
**Impact:** Incident frequency was roughly double the spec-defined rates.

### Moderate Bug Fixes

#### BUG-5: Flight state machine test failure

**File:** `tests/unit/test_flight_state_machine.py:118`  
**Root cause:** Test expected 10 FSM states but code has 11 (`arrived` is a terminal state for departures reaching their destination).  
**Fix:** Added `"arrived"` to the expected states set.

#### BUG-6: Flights endpoint missing spec query params

**Files:** `services/flight-service/routers/flights.py`, `services/flight-service/db/neo4j.py`  
**Root cause:** GET `/flights` was missing `terminal`, `from`, `to` query parameters per spec.  
**Fix:** Added `terminal` (filters via Gate→Terminal relationship in Neo4j), `from` and `to` (ISO 8601 time range filters on `scheduled_time`).

#### BUG-7: Gates endpoint missing status filter

**Files:** `services/flight-service/routers/flights.py`, `services/flight-service/db/neo4j.py`  
**Root cause:** GET `/gates` only supported `terminal` filter, but spec requires `status` filtering too.  
**Fix:** Added `status` query param with Cypher WHERE clause.

#### BUG-8: Special-assistance passengers receive unnecessary dwell time

**File:** `services/passenger-service/kafka/consumer.py:772`  
**Root cause:** `sample_dwell_minutes()` was called for ALL passengers exiting security, including special-assistance ones. Per spec, SA passengers should skip dwell and route directly to gate.  
**Fix:** SA passengers (identified from the `sa_drained` list) now receive `dwell_minutes=0`.

### Minor Fixes

#### MINOR-2: Runways endpoint response shape

**Files:** `services/flight-service/routers/flights.py`, `dashboards/art-dashboard/src/hooks/useQueries.ts`, `dashboards/art-dashboard/src/hooks/useApi.ts`  
**Root cause:** Endpoint returned raw array instead of `{ runways: [...] }` object per spec pattern used by other endpoints.  
**Fix:** Wrapped in object; updated dashboard to unwrap `.runways` with fallback for backward compatibility.

---

## 3. Issues Found But Not Fixed (Documented for Future)

| Issue                                                                       | Severity | Notes                                      |
| --------------------------------------------------------------------------- | -------- | ------------------------------------------ |
| Flight type not filterable in dashboard (Gap 3-7)                           | Minor    | Displayed and sortable, no filter dropdown |
| METAR cloud coding simplified (BKN/OVC only, not FEW/SCT/BKN/OVC)           | Minor    | Cosmetic deviation                         |
| Wind capacity uses speed as crosswind proxy, not runway-relative components | Minor    | Spec notes this is "simplified"            |
| Connection risk thresholds use strict `>` vs spec's inclusive bands         | Minor    | Edge case only                             |
| Security slowdown has 50% floor not in spec formula                         | Minor    | Defensive design choice                    |
| No user-controlled column grouping toggles in tables                        | Minor    | Grouping exists but not user-selectable    |
| WS connect frame missing `active_flights` count                             | Minor    | Cosmetic deviation                         |

---

## 4. ROADMAP Verification Summary

### Gap 0 — Documentation: **VERIFIED DONE** ✅

All GAP-0-1 through GAP-0-6 tasks are implemented. READMEs exist per service, architecture diagram in docs, docstrings present.

### Gap 0.5 — Better Dashboards: **VERIFIED DONE** ✅

- Favicon: done
- Column sorting: done (FlightBoard, via useSort)
- Archive/history: done (/history route with SimHistoryPage)
- Chart improvements: done (tooltips visible)
- Per-page export: done (CSV/JSON export menus on all pages)
- Global export: done (header bar export for full simulation)

### Gap 1 — Physical Layout: **VERIFIED DONE** ✅ (except GAP-1-8)

- GAP-1-1 through GAP-1-7: All implemented and tested
- layout.json fixture exists, taxi_time_minutes and walking_time_to_gate utilities work
- GAP-1-8 (dashboard visualization): Not done, correctly marked `[ ]` in ROADMAP

### Gap 2 — Turnaround Sequence: **VERIFIED DONE** ✅

All GAP-2-1 through GAP-2-8 implemented. TurnaroundTask, TurnaroundPlan, task graph with dependencies, tick-by-tick advancement, delay propagation, ground ops dashboard display. Tests comprehensive.

Note: No TurnaroundScheduler or TurnaroundRunner classes exist by those exact names, but the functionality (topological sort, tick advancement) is implemented in turnaround_plan.py.

### Gap 3 — Flight Type Distinction: **VERIFIED DONE** ✅ (with minor gap)

All GAP-3-1 through GAP-3-8 implemented. FlightType/RouteCategory enums, Neo4j population, turnaround mapping, bags-per-pax multiplier, customs routing, gate constraints, dashboard display. Tests exist.

- GAP-3-7 partially: type displayed and sortable but not filterable via dropdown

### Gap 4 — Baggage Conveyor: **PARTIALLY DONE** (matches ROADMAP)

- GAP-4-3, GAP-4-4, GAP-4-9: Done and tested
- GAP-4-1, GAP-4-2, GAP-4-5, GAP-4-6, GAP-4-7, GAP-4-8: Correctly marked `[ ]`

### Phase 2 — Scenario Engine: **VERIFIED DONE** ✅

8 YAML scenarios, full REST API, CLI runner, clock integration, result collection, gateway proxy.

### Phase 6 — Geospatial: **VERIFIED DONE** ✅

Mapbox world map, Leaflet fallback, destination coordinates, live aircraft positions, route arcs.

---

## 5. Tests Executed

| Suite                  | Result               |
| ---------------------- | -------------------- |
| Unit tests (pytest)    | 451 passed, 0 failed |
| Ruff lint              | All checks passed    |
| npm build (dashboard)  | Build successful     |
| TypeScript strict mode | No errors            |

---

## 6. Cross-Service Integration Analysis

The audit revealed that the four critical bugs (BUG-1 through BUG-4) represent a pattern: **cross-service event contracts were not being validated end-to-end**. Each service worked correctly in isolation, but the handoff points had type mismatches, field name mismatches, and duplicate behavior.

**Recommendation:** Add integration tests that specifically validate the full event chain:

1. Baggage DG class 3 flagged → incident-service receives → fire triggers
2. System failure at power-X → baggage-service zone goes offline → restore on resolve
3. Verify probabilistic incident rate matches spec base probabilities (not 2×)
