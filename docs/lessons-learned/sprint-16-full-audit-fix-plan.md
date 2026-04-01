# Sprint 16 — Full Audit & Verification Fix Plan

**Date:** 2026-04-01  
**Scope:** Deep audit of all ROADMAP "done" items, spec compliance, cross-service bugs  
**Method:** Static code analysis, unit test execution, spec-vs-code comparison

---

## Summary of Findings

### Unit Tests Baseline

- **450 passed, 1 failed** (test_flight_state_machine.py)
- Dashboard build: **PASS** (after `npm install`)
- Ruff lint: **PASS**

---

## Critical Bugs (Must Fix)

### BUG-1: DG class type mismatch prevents baggage_fire auto-trigger

- **Location:** `services/incident-service/kafka/consumer.py:459`
- **Issue:** `dg_class != 3` compares string `"3"` to integer `3` — always True → fire never triggers
- **Impact:** Entire baggage_fire auto-trigger chain is broken
- **Fix:** Change `if dg_class != 3:` to `if str(dg_class) != "3":`

### BUG-2: BaggageFlagged event field name mismatch

- **Location:** `services/incident-service/kafka/consumer.py:464`
- **Issue:** Reads `payload.get("zone_id")` but BaggageFlagged emits `scan_zone`
- **Impact:** Fire location always defaults to "baggage-handling" instead of actual zone
- **Fix:** Change to `payload.get("scan_zone", "baggage-handling")`

### BUG-3: System failure location key mismatch (incident→baggage)

- **Location:** `services/incident-service/kafka/consumer.py:574` + `services/baggage-service/kafka/consumer.py:133`
- **Issue:** Incident-service generates `"terminal-A-power"`, `"terminal-B-power"` but baggage-service expects `"power-A"`, `"power-B"`, `"power-C"`
- **Impact:** Power outage incidents never halt conveyor zones
- **Fix:** Align incident-service location names to match baggage-service FAILURE_IMPACT keys

### BUG-4: Double probabilistic incident injection

- **Location:** `services/sim-orchestrator/services/injector.py` + `services/incident-service/kafka/consumer.py:526`
- **Issue:** Both sim-orchestrator AND incident-service independently run probabilistic event generation → incidents fire at ~2× intended rate
- **Impact:** Incident frequency is double what spec intends; simulation balance is off
- **Fix:** Remove probabilistic generation from sim-orchestrator injector (incident-service has the richer implementation with weather awareness)

### BUG-5: Flight state machine test failure (`arrived` state)

- **Location:** `tests/unit/test_flight_state_machine.py:118`
- **Issue:** Test expects 10 states but code has 11 (includes `arrived` terminal state for departures reaching destination)
- **Impact:** 1 failing unit test
- **Fix:** Add `"arrived"` to expected states set in test

---

## Moderate Bugs (Should Fix)

### BUG-6: Flight list endpoint missing `terminal`, `from`, `to` query params

- **Location:** `services/flight-service/routers/flights.py:29`
- **Spec:** GET /flights supports terminal, from, to params
- **Fix:** Add query params and pass through to Neo4j query

### BUG-7: Gates endpoint missing `status` query param

- **Location:** `services/flight-service/routers/flights.py:106`
- **Spec:** GET /gates supports terminal AND status filtering
- **Fix:** Add status query param

### BUG-8: Special-assistance passengers get unnecessary dwell time

- **Location:** `services/passenger-service/kafka/consumer.py:772`
- **Spec:** SA passengers skip dwell and route directly to gate
- **Fix:** Set dwell_minutes=0 for SA passengers in the drain callback

### BUG-9: sim-orchestrator weather/throughput modifiers not applied

- **Location:** `services/sim-orchestrator/services/injector.py:73-77`
- **Issue:** Weather and throughput multipliers are loaded but not applied (commented as "will be enhanced")
- **Impact:** With BUG-4 fix (removing sim-orchestrator injection), this becomes moot
- **Resolution:** N/A after BUG-4 fix, but leaving note for documentation

---

## Minor Issues (Nice to Fix)

### MINOR-1: Flight type/route category not filterable in dashboard

- **Spec (Gap 3-7):** Flight table should display type and route category as filterable columns
- **Status:** Displayed and sortable, but no filter dropdown
- **Fix:** Add filter controls for flight_type

### MINOR-2: Runways endpoint returns raw array instead of object

- **Location:** `services/flight-service/routers/flights.py:96`
- **Spec:** Response should be `{ runways: [...] }` not just `[...]`
- **Fix:** Wrap in object (verifying no dashboard breakage)

### MINOR-3: WebSocket connect frame missing `active_flights` count

- **Location:** `services/flight-service/main.py:120`
- **Spec:** Connect frame includes `{ type: "connected", sim_time, active_flights }`
- **Fix:** Add active_flights count to connect frame

### MINOR-4: METAR cloud coding simplified

- **Location:** `services/weather-service/services/metar.py:38`
- **Issue:** Only BKN/OVC, not full FEW/SCT/BKN/OVC mapping by oktas
- **Fix:** Expand cloud layer coding

---

## Implementation Order

1. BUG-1 + BUG-2 (incident-service baggage_fire chain) — critical
2. BUG-3 (power outage key alignment) — critical
3. BUG-4 (remove duplicate injection from sim-orchestrator) — critical
4. BUG-5 (test fix) — quick
5. BUG-6 + BUG-7 (missing query params) — moderate
6. BUG-8 (SA dwell skip) — moderate
7. MINOR-2 + MINOR-3 (response shape fixes) — minor
8. Run full test suite + ruff + npm build
