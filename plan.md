# Fix Plan — Flight Cancellations, Missing Gate Passengers, Empty Carousels

## Problem Statement

Three interrelated symptoms:

1. **Most departure flights get cancelled** — delay_minutes hits 180 because passengers
   don't board fast enough. The flight-service FSM cancels at ≥180 min delay.
2. **Passengers don't appear at gates** in the passenger flow dashboard.
3. **Arrival carousel is always empty** — no arrival passengers exist in Neo4j.

## Root-Cause Analysis

### RC-1: No arrival Passenger nodes (→ empty carousels)

The seeder (`sim-orchestrator/services/seeder.py`) only generates Passenger nodes for
departure flights. Arrival flights get synthetic `pax_count` from baggage generation but
zero Passenger nodes. When the deplaning handler fires on `FlightStatusChanged → at_gate`,
it finds no passengers to move through deplaning → baggage_claim → carousel.

### RC-2: Deplaning status filter too strict (→ empty carousels)

Even when arrival passengers exist, `_on_flight_status_changed` in passenger-service only
moves passengers whose status is `checked_in` or `airborne`. Arrival passengers start as
`airborne` (good) but some may still be `booked` if the flight lands quickly. The filter
should include `booked` and `boarded` too.

### RC-3: Passenger pipeline too slow (→ mass cancellations)

The core cause of cancellations. The passenger-service tick handler can't keep up with 60×
sim speed because each tick performs:

| Operation | DB calls per tick | Bottleneck |
|---|---|---|
| `get_passengers_by_status("booked")` | 1 query, returns ~30K rows | Full table scan |
| `get_passengers_by_status("checked_in")` | 1 query, returns ~10K rows | Full table scan |
| `_sync_security_from_db()` | 1 query | Re-fetches all security_queue pax |
| `set_passenger_dwell(pid, dwell)` | **N individual writes** per tick | 18–54 writes/tick |
| `emit_passenger_status_changed(…)` | **N Kafka produce calls** | Serialization + flush |
| `get_passengers_by_status("airside")` | 1 query, returns ~5K rows | Full table scan |
| `get_passengers_by_status("at_gate")` | 1 query, returns ~5K rows | Full table scan |
| `get_passengers_by_status("deplaning")` | 1 query | Returns ~15K rows |
| `get_passengers_by_status("baggage_claim")` | 1 query | Returns ~15K rows |
| `_on_flight_status_changed` (deplaning) | **N individual writes** | 200 writes/flight |

**Result:** A single tick takes 2–5 seconds. At 60× speed the clock emits one tick per
second. The consumer falls 1–4 ticks behind per tick processed, growing an 8+ hour lag.
Passengers never reach boarding before the 180-min cancellation threshold.

### RC-4: Double loop bug in security advancement

`_advance_checkin_to_security` has two `for flight_id, pax_group in flights.items()` loops.
The first loop does nothing useful (just checks the cap and breaks), the second does the
actual work but never checks the cap. This bug was partially fixed in a previous pass but
needs clean resolution.

### RC-5: Missing Neo4j index on `Flight.scheduled_time`

The windowed queries that filter `f.scheduled_time <= $before` lack an index, making them
sequential scans.

## Fix Plan

### Phase 1 — Data Correctness (RC-1, RC-2, RC-4)

**1.1 Seed arrival passengers**
- File: `services/sim-orchestrator/services/passengers.py`
  - Add `initial_status` parameter (default `"booked"`).
- File: `services/sim-orchestrator/services/seeder.py`
  - Call `generate_passengers(arrival_flights, …, initial_status="airborne")`.
- Already done in previous pass. Verify correctness.

**1.2 Broaden deplaning eligibility**
- File: `services/passenger-service/kafka/consumer.py`, function `_on_flight_status_changed`
  - Accept statuses `("airborne", "booked", "boarded", "checked_in")` for deplaning.
  - **Batch the deplaning write** — collect IDs, call `bulk_update_status` once.
- Already partially done. Needs batching.

**1.3 Fix double-loop in security**
- File: `services/passenger-service/kafka/consumer.py`, function `_advance_checkin_to_security`
  - Remove the orphan first loop. Single loop with cap check at top.
- Already done. Verify.

### Phase 2 — Performance (RC-3, RC-5)

The goal: bring per-tick latency under 500ms so the consumer keeps up at 60× speed.

**2.1 Add Neo4j composite index**
- File: `services/passenger-service/db/neo4j.py`
  - Add index on `Flight.scheduled_time` (already added, verify).
  - Add composite index on `(Passenger.status, Passenger.flight_id)` for the heavily-used
    `get_passengers_by_status` join pattern.

**2.2 Batch `set_passenger_dwell` — eliminate per-passenger writes**
- File: `services/passenger-service/db/neo4j.py`
  - New function: `bulk_set_dwell(items: list[dict])` — one UNWIND query.
- File: `services/passenger-service/kafka/consumer.py`, function `_drain_security_queues`
  - Collect `(pid, dwell)` pairs, call `bulk_set_dwell` once instead of N writes.

**2.3 Batch deplaning writes**
- File: `services/passenger-service/kafka/consumer.py`, function `_on_flight_status_changed`
  - Collect all deplaning passenger IDs per zone, single `bulk_update_status` call.

**2.4 Throttle per-passenger Kafka events during tick processing**
- File: `services/passenger-service/kafka/producer.py`
  - In tick batch mode, only emit a sample (~5%) of `PassengerStatusChanged` events.
  - Dashboard uses REST for authoritative data; these events are real-time hints.
- Already implemented. Keep.

**2.5 Skip stale clock ticks when consumer is behind**
- File: `services/passenger-service/kafka/consumer.py`, `run_consumer`
  - Batch-consume up to 50 messages. Process non-tick events. Process only the latest tick.
- Already implemented. Keep.

**2.6 Time-window expensive queries**
- `get_passengers_by_status("booked", scheduled_before=…)` — only within 3h.
- `get_passengers_by_status("checked_in", scheduled_before=…)` — only within 2h.
- Already implemented. Keep.

**2.7 Run non-critical tick work on reduced frequency**
- ML training, congestion checks, Prometheus gauge updates: every 5th tick only.
- Connection risk checks: every 10th tick.

### Phase 3 — Tuning

**3.1 Security throughput**
- Default lanes: 6 per terminal (already done).
- Admission cap: 50 pax/min entering security (already done).
- This gives ~18 pax/min/terminal draining × 3 terminals = 54 pax/min out of security,
  matching the ~50 pax/min admission.

**3.2 Check-in throughput**
- Raise MAX_CHECKIN_PER_TICK to 200 (already done).

### Phase 4 — Documentation

**4.1** Update `docs/architecture/DATA_MODEL.md` §5 with new indexes.
**4.2** Add performance tuning section to `services/passenger-service/SKILL.md`.

## Verification Criteria

After `docker compose down -v && docker compose up --build`:
1. Wait ~5 minutes (sim reaches ~10:00).
2. `curl localhost:8002/api/v1/flow/summary` — sim_time lag < 30 min from sim clock.
3. `curl localhost:8001/api/v1/flights?limit=200` — cancelled count < 10% of departures.
4. `by_status` includes `deplaning` and `baggage_claim` with non-zero counts.
5. `at_gate` count > 0 with gate-prefixed zones visible in heatmap.
