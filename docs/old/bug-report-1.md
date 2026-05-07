# Bug Report 1 — Stuck state machines, broken dashboard metrics

**Date:** 2026-03-24  
**Severity:** Critical (Bugs 1–2), High (Bugs 3–5)  
**Services affected:** passenger-service, baggage-service, flight-service, React dashboard

---

## Summary

Two independent root causes caused the passenger and baggage state machines to appear stuck.
Passengers accumulated in `security_queue` indefinitely (34,055 observed in one session), and
baggage reached make-up zones but never registered as `loaded` on flights. These two issues
cascaded into three downstream symptoms: zero progress bars on flight details, a TypeError crash
in the incident dashboard, and zero runway movement rate.

---

## Bug 1 — Baggage never transitions from make-up to loaded (visibly)

### Root cause

The baggage conveyor pipeline sets `status = "loaded"` when a bag **enters** a make-up zone
(on the sorting-matrix exit handler). However, when the bag **exits** the make-up zone on the
next tick, the exit handler was a no-op (`pass`). This meant:

1. The `LOADED_ON` relationship (created at seed time) never received a `loaded_at` timestamp.
2. If the sorting-matrix exit handler's `_find_bag_current_zone()` lookup returned `None`
   (e.g. due to a race condition or zone being full), the status update was silently skipped
   and the bag remained stuck in `sorting` status forever.
3. No `BaggageStatusChanged` event was emitted when bags exited make-up, so downstream
   consumers (flight-service, dashboard) never saw the loaded transition.

### Files changed

| File | Change |
|---|---|
| `services/baggage-service/kafka/consumer.py` | Make-up exit handler now sets `status = "loaded"`, emits `BaggageStatusChanged`, and sets `loaded_at` on `LOADED_ON`. Sorting-matrix exit handler also sets `loaded_at`. |
| `services/baggage-service/db/neo4j.py` | Added `set_loaded_on_timestamp()` function to update the `LOADED_ON` relationship. |

### Verification

```cypher
-- After fix, loaded_at should be populated:
MATCH (b:Baggage)-[r:LOADED_ON]->(f:Flight)
WHERE r.loaded_at IS NOT NULL
RETURN count(b) AS loaded_with_timestamp
-- Expected: > 0 and growing during boarding windows
```

---

## Bug 2 — Passenger forecast features always zero, throughput guard missing

### Root cause A — Stale forecast features

The `_build_context_features()` function used hardcoded zeroes for `flights_next_90` and
`pax_next_90` instead of using real data from `get_departure_flights_in_window()`. The actual
query was performed in `_ml_tick()` but the results were stored in local variables that were
never shared with `_build_context_features()`.

This meant the LightGBM fallback forecast (`expected_pax_next_90min × 0.35`) always returned
`0` because `expected_pax_next_90min` was always `0`. With `forecast_queue = 0`, the slowdown
formula was never triggered — `effective_throughput` always returned full base rate (720 pax/hr).

While this didn't cause a zero throughput, it meant the congestion detection system was blind:
the forecast never detected upcoming surges, so no `SecurityCongestionDetected` events were
ever emitted.

### Root cause B — Tick ordering

The `_on_clock_tick` handler ran `_ml_tick` (which queries flight data) as step 7, but
`_drain_security_queues` (which needs the forecast) ran as step 2. This meant the forecast
used in the drain was always one tick stale.

### Root cause C — No throughput floor

The `drain_per_tick` method could return 0 in edge cases (e.g. during service restart when
the throughput calculation hadn't stabilized). There was no minimum drain guard to ensure at
least 1 passenger is processed per tick when the queue is non-empty and lanes aren't frozen.

### Files changed

| File | Change |
|---|---|
| `services/passenger-service/kafka/consumer.py` | Added `_cached_flights_next_90` and `_cached_pax_next_90` module-level caches, populated by `_ml_tick()` and consumed by `_build_context_features()`. Reordered tick steps: ML data collection runs first, then security drain and congestion check. |
| `services/passenger-service/services/security.py` | Added throughput floor guard in `drain_per_tick()`: when `drain == 0`, `queue_depth > 0`, and `not frozen`, force `drain = 1`. |

### Verification

```cypher
-- Security queue should drain to realistic levels:
MATCH (p:Passenger)
RETURN p.status AS status, count(p) AS n
ORDER BY n DESC
-- Expected: security_queue < 500 during off-peak
```

---

## Bug 3 — TypeError in incident dashboard: `.length` on undefined

### Root cause

The incident-service API returns `protocol` (a single string) on incident objects, but the
React dashboard's `Incident` TypeScript type defines `protocols: string[]` (an array). When
the API response was stored directly in Zustand without normalization, `incident.protocols`
was `undefined`. The `IncidentCard` component called `incident.protocols.length` which threw:

```
TypeError: Cannot read properties of undefined (reading 'length')
```

The same pattern existed in `ProtocolBar` and `CascadeTree` components.

### Files changed

| File | Change |
|---|---|
| `dashboards/art-dashboard/src/stores/incidentStore.ts` | Added `normalizeIncident()` function that maps `protocol` (string) → `protocols` (array) and ensures `cascade_depth`, `cascade_tree` have defaults. Applied in `setIncidents` and `upsertIncident`. |
| `dashboards/art-dashboard/src/pages/IncidentConsole/IncidentConsolePage.tsx` | Added nullish coalescing (`?? []`) on all `protocols` and `children` array accesses. |

---

## Bug 4 — Flight detail progress bar always 0%

### Root cause

The `GET /flights/{flight_id}` endpoint in flight-service queries Neo4j for passenger and
baggage counts via `LOADED_ON` and `ON_FLIGHT` relationships. The counts were correct in
the query but returned as flat fields (`pax_boarded`, `baggage_loaded`) without the nested
structure expected by the SPEC (`passengers: { total, boarded, at_gate, ... }`,
`baggage: { total_items, loaded, in_sorting, flagged }`).

More importantly, `baggage_loaded` was always 0 because the `LOADED_ON` relationship existed
but the bag status never reached `"loaded"` due to Bug 1. Fixing Bug 1 directly fixes the
baggage count.

### Files changed

| File | Change |
|---|---|
| `services/flight-service/db/neo4j.py` | Enhanced `get_flight_by_id()` query to count per-status breakdowns: `pax_at_gate`, `pax_airside`, `pax_security`, `pax_connections_at_risk`, `baggage_in_sorting`, `baggage_flagged`. Returns nested `passengers` and `baggage` objects matching the SPEC. |

---

## Bug 5 — Runway movement rate always 0 mvt/hr

### Root cause

The flight board dashboard reads `rw.capacity_per_hour` and `rw.current_rate` from the
runway API response. However, the `GET /runways` endpoint only returned `id`, `status`,
`current_use`, `ils`, `arrivals_queued`, and `departures_queued` — it never included
`capacity_per_hour` or `current_rate`. These fields were `undefined` in the response,
rendering as `0/0 mvts/hr` in the dashboard.

The `RunwayQueue` class had `_arrival_rate` and `_departure_rate` properties that were
correctly updated by `WeatherStateChanged` events, but this data was never exposed via
the REST endpoint.

Also, the API returned `id` but the dashboard expected `runway_id`.

### Files changed

| File | Change |
|---|---|
| `services/flight-service/services/runway_queue.py` | Added `arrival_rate`, `departure_rate`, `capacity_per_hour`, and `current_rate` properties. Added `_recent_assignments` list to track movements in a 60-minute sliding window. |
| `services/flight-service/routers/flights.py` | `GET /runways` now includes `capacity_per_hour`, `current_rate`, and `runway_id` from the `RunwayQueue`. |

---

## Fix dependency order

```
Bug 2 (passenger drain) ─── fixes zone density accumulation and forecast features
   │
Bug 1 (baggage loading) ─── fixes LOADED_ON timestamp and loaded status
   │
Bug 4 (flight progress)  ── now works because Bugs 1+2 produce correct counts
   │
Bug 3 (incident crash)   ── independent: frontend null-safety + normalization
   │
Bug 5 (runway rate)       ── independent: exposes existing data via REST endpoint
```

---

## Lessons learned

1. **Cache derived data at the module level, not in local variables.** The `_ml_tick` function
   computed correct flight/pax data but stored it in locals. The `_build_context_features`
   function needed the same data but couldn't access it. Solution: module-level `_cached_*`
   variables updated once per tick.

2. **Tick step ordering matters.** Data producers (ML data collection) must run before data
   consumers (security drain that uses forecasts). The original ordering had the ML step at
   position 7 and the security drain at position 2.

3. **Exit handlers must be explicit.** A `pass` in a zone exit handler silently drops context.
   Even if the status was set during the entry handler, the exit handler should verify/confirm
   the transition and emit the corresponding Kafka event.

4. **API field names must match exactly.** The flight-service returned `id` for runways but the
   dashboard expected `runway_id`. The incident-service returned `protocol` (singular) but
   the dashboard expected `protocols` (array). Type safety at the API boundary prevents these.

5. **Always add a throughput floor.** In throughput-based drain models, always ensure at least
   1 item is processed per tick when the queue is non-empty and the system isn't intentionally
   frozen. This prevents edge-case stalls during service restarts or model initialization.
