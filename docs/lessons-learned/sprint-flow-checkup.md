# Lessons Learned — Sprint: Flow Checkup (Stuck Boarding & Missing Departures)

**Date**: 2025-01  
**Scope**: passenger-service, flight-service  
**Symptom**: All departing flights stuck in `boarding`; passengers never reached `departed_airport` status; baggage appeared stuck as a downstream effect.

---

## Root Causes

### 1. Missing `departed` handler in passenger-service (Critical)

**File**: `services/passenger-service/kafka/consumer.py` — `_on_flight_status_changed()`

The passenger-service consumed `flights.events` and handled multiple flight status transitions (`boarding`, `at_gate`, `arrived`) but had **no handler for `new_status == "departed"`** on departure flights. When a flight transitioned from `boarding` → `departed`, no code existed to move its boarded passengers to `departed_airport`.

**Impact**: Every passenger that successfully boarded stayed in `boarded` status forever. Over time, thousands of passengers accumulated as `boarded` even though their flights had long since departed and arrived.

**Fix**: Added a handler block in `_on_flight_status_changed()`:
```python
elif new_status == "departed" and direction == "departure":
    # Bulk-transition all boarded passengers to departed_airport
    boarded_passengers = await db.get_passengers_by_flight_and_status(flight_id, "boarded")
    if boarded_passengers:
        await db.bulk_update_status(boarded_passengers, "departed_airport")
        for pid in boarded_passengers:
            await db.remove_passenger(pid)  # remove from gate/terminal
            await emit_passenger_status_changed(pid, "boarded", "departed_airport", flight_id)
```

### 2. Boarding window too short for wide-body aircraft (Timing)

**Files**: `services/passenger-service/services/state_machine.py`

| Constant | Before | After | Rationale |
|---|---|---|---|
| `BOARDING_CALL_MINUTES` | 20 | 35 | At 10 pax/min, T-20 allows max 200 pax. Wide-body (300-410 seats × 0.8 load = 240-328 pax) could never reach 95% threshold. T-35 allows 350 pax. |
| `GATE_OPEN_MINUTES` | 30 | 50 | Passengers need to arrive at gate before boarding starts. Widened to give airside→gate pipeline time. |

The warm-start threshold in `consumer.py` was also updated from `minutes_until <= 30` to `minutes_until <= 50` to match `GATE_OPEN_MINUTES`.

**Impact**: Flights accumulated delay minutes waiting for an unreachable 95% boarding threshold, then eventually departed via grace logic with reduced load factors.

---

## How We Diagnosed

1. **Neo4j queries** — `MATCH (p:Passenger) RETURN p.status, count(*)` showed 9,693 passengers stuck as `boarded` despite their flights having `arrived` status.
2. **Per-flight drill-down** — `MATCH (p:Passenger {status:'boarded'})-[:ON_FLIGHT]->(f) RETURN f.flight_number, f.status, count(p)` revealed passengers were `boarded` on flights that were already `arrived`.
3. **Code trace** — Searched `_on_flight_status_changed` for all handled statuses; `departed` was missing.
4. **Boarding math** — 10 pax/min × 20 min = 200 pax max; wide-body aircraft with 240-328 passengers could never reach 95%.

---

## Validation

After deploying fixes and full stack restart (`docker compose down -v && docker compose up --build`):

| Metric | Before Fix | After Fix |
|---|---|---|
| `departed_airport` passengers (at ~08:40 sim) | ~10,342 | ~16,381 |
| Stuck `boarded` passengers | ~9,693 | ~1,366 (only actively boarding flights) |
| Boarding flights | Accumulating, stuck | 18 (healthy churn) |
| Baggage `in_hold` | Low | 40,518 (flowing correctly) |

Passenger-service logs confirmed the handler firing: `"Flight X departed: 231 passengers departed_airport"`.

---

## Key Takeaways

1. **Every FSM status transition must have a consumer-side handler.** When adding a new flight status (like `departed`), audit all downstream consumers to ensure they react to it.
2. **Capacity math matters.** Boarding rates and timing windows must be validated against the largest aircraft in the fleet, not just averages.
3. **Stuck-state queries are the fastest diagnostic.** `MATCH (entity) RETURN entity.status, count(*)` immediately reveals pipeline blockages.
4. **Downstream symptoms mislead.** Baggage appeared broken, but the real issue was upstream: passengers never departed, so bags never entered `in_hold`. Always trace from the source.
