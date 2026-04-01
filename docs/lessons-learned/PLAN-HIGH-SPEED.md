# Plan: Fix simulation speed issues at all speeds

## Revised from original draft — handles 60×, 600×, 3600×, and beyond

---

## Why the original plan is insufficient at 3600×

The delta-aware tick approach correctly solves the **throughput scaling bug** but misses
three deeper constraints that make 3600× fundamentally different from 600×:

### Constraint 1 — Neo4j write throughput

At 3600×, the simulation advances 60 sim-minutes per real second. In 60 sim-minutes:

- ~420 passengers transition between zones
- ~180 baggage items change status
- ~12 flights change state
- ~3 incidents may fire and cascade

Each of these is currently an individual async Neo4j write. Neo4j handles ~500–2,000
simple writes/second on a local Docker container. At 3600×, the system demands ~600
writes/real-second — at the edge of what's possible, and with zero headroom for
any query complexity.

**Result:** Neo4j falls behind, the asyncio event loop backs up, the Kafka consumer
lag grows, and the simulation loses coherence even with delta-aware processing.

### Constraint 2 — Kafka consumer group lag

At 3600× with 10 ticks/sec (step=6 sim-min), Kafka still receives:

- 10 `SimClockTick` messages/sec
- Burst events from all 6 services responding to each tick

The api-gateway WebSocket fan-out, which must consume and relay every event, becomes
a bottleneck. At this speed, the dashboard becomes meaningless anyway — 60 sim-minutes
pass in 1 real second, faster than any human can observe.

### Constraint 3 — Causal ordering within a sim-minute

When `step_minutes = 6`, a single tick spans 6 sim-minutes of logical time. Within
those 6 minutes, events that are causally ordered (flight departs → baggage transitions
to `in_hold` → passenger transitions to `boarded`) must still happen in sequence.
Computing delta=6 and applying it to all operations simultaneously breaks causality.

---

## Revised solution: three simulation modes

Rather than trying to make one tick-processing model work at all speeds, define three
distinct operating modes with explicit tradeoffs. The clock controls which mode is active
and consumers adapt accordingly.

```
Mode 1: REALTIME    speed 1×–60×       tick = 1 sim-min    Neo4j: per-event writes
Mode 2: FAST        speed 60×–600×     tick = 1 sim-min    Neo4j: batched writes
Mode 3: BULK        speed 600×–∞       tick = N sim-min    Neo4j: periodic snapshot
```

The mode is broadcast in every `SimClockTick` payload so all consumers adapt without
configuration changes.

---

## Mode 1 — REALTIME (1×–60×, current behaviour, no changes needed)

Tick interval: 1,000ms → 17ms. Step = 1 sim-minute.
Delta = 1 always. Neo4j writes per-event. Kafka events per state change.
This is the fully correct, high-fidelity mode. No changes required here.

---

## Mode 2 — FAST (60×–600×, delta-aware, batched Neo4j writes)

### Clock changes

Same as original plan: cap at MAX_TICKS_PER_SEC = 10, step = 1 sim-min always
(since 600× / 60 = 10 ticks/sec, no multi-minute steps needed in this range).

```python
MAX_TICKS_PER_SEC = 10

def compute_step(speed: int) -> int:
    if speed <= 60 * MAX_TICKS_PER_SEC:   # <= 600
        return 1  # 1 sim-min per tick, rate-limited to 10/sec
    else:
        return speed // (60 * MAX_TICKS_PER_SEC)  # BULK mode
```

### Consumer changes (delta-aware, same as original plan)

Track `_last_tick_sim_time`, compute delta, multiply all rate caps. This is correct
at this speed range because:

- Step = 1 sim-min → delta = 1 normally, may be 2–3 on occasional skips
- Neo4j write demand ≈ 100–300 writes/sec — manageable

**Additional change: write batching**

Accumulate Neo4j writes in a list during the tick handler, then execute them in a
single transaction at the end of each tick instead of one `await session.run()` per event:

```python
# In each service's tick handler
async def on_clock_tick(payload: dict, sim_time: datetime):
    pending_writes: list[tuple[str, dict]] = []

    # Accumulate writes instead of executing immediately
    for passenger in passengers_to_advance:
        pending_writes.append((UPDATE_PASSENGER_CQL, {"id": ..., "status": ...}))

    # Execute all in one transaction
    async with get_driver().session() as session:
        async with session.begin_transaction() as tx:
            for cql, params in pending_writes:
                await tx.run(cql, params)
            await tx.commit()

    # Produce Kafka events after Neo4j commit
    for event in events_to_produce:
        produce_event(...)
```

This reduces Neo4j round-trips from N per tick to 1 per tick.

---

## Mode 3 — BULK (600×–∞, in-memory simulation, periodic Neo4j sync)

At speeds above 600×, the architecture shifts: **Neo4j becomes a checkpoint store,
not a live operational database**. All state transitions happen in memory.
Neo4j is synced every `SYNC_INTERVAL_SIM_MINUTES` (default: 60).

### Clock changes

```python
MAX_TICKS_PER_SEC  = 10
SYNC_INTERVAL_SIM_MIN = 60  # sync Neo4j every 60 sim-minutes in BULK mode

def compute_tick_params(speed: int) -> dict:
    if speed <= 600:
        return {
            "step_minutes": 1,
            "sleep_s": max(1.0 / MAX_TICKS_PER_SEC, 60.0 / speed),
            "mode": "FAST" if speed > 60 else "REALTIME",
        }
    else:
        step = speed // (60 * MAX_TICKS_PER_SEC)  # e.g. 3600 // 600 = 6
        return {
            "step_minutes": step,
            "sleep_s": step * 60.0 / speed,       # always ~100ms
            "mode": "BULK",
        }
```

Updated `SimClockTick` payload includes mode and step:

```python
payload = {
    "sim_time":         _sim_time.isoformat(),
    "real_time":        datetime.utcnow().isoformat(),
    "speed_multiplier": _speed_multiplier,
    "step_minutes":     step_minutes,   # NEW — how many sim-minutes this tick covers
    "mode":             mode,           # NEW — "REALTIME" | "FAST" | "BULK"
    "tick_number":      _tick_number,
    "day_of_sim":       _sim_day,
}
```

**Multi-minute step: internal loop for boundary detection**

When `step_minutes > 1`, the clock must still detect hour and day boundaries correctly.
Iterate internally over each intermediate minute before emitting the tick:

```python
async def advance_sim_time(step: int):
    global _sim_time, _sim_day

    for minute_offset in range(step):
        candidate = _sim_time + timedelta(minutes=minute_offset + 1)

        # Hour boundary check (for weather FSM, probabilistic events)
        if candidate.minute == 0:
            _pending_hourly_events.append(candidate)

        # Day boundary at 23:30
        if candidate.hour == 23 and candidate.minute == 30:
            asyncio.create_task(seed_day(_sim_day + 1))

        # Midnight
        prev = candidate - timedelta(minutes=1)
        if candidate.date() != prev.date():
            _sim_day += 1

    _sim_time += timedelta(minutes=step)
    # Emit all pending hourly events that occurred in this step
    for hourly_time in _pending_hourly_events:
        await emit_hourly_events(hourly_time)
    _pending_hourly_events.clear()
```

### Consumer changes in BULK mode

Consumers receive `step_minutes` in the tick payload and use it as `delta`:

```python
async def on_clock_tick(payload: dict, sim_time: datetime):
    delta   = payload.get("step_minutes", 1)
    mode    = payload.get("mode", "REALTIME")
    is_bulk = mode == "BULK"

    # All rate calculations use delta
    pax_to_drain   = int(effective_throughput / 60 * delta)
    bags_to_advance = int(zone_throughput / 60 * delta)
    ttr_decrement  = delta

    # In BULK mode: skip Neo4j writes, update in-memory state only
    # In REALTIME/FAST mode: write to Neo4j per-event (or batched)
    if is_bulk:
        _apply_to_memory(transitions)
    else:
        await _write_to_neo4j_batched(transitions)
        _produce_kafka_events(events)
```

### Periodic Neo4j sync in BULK mode

Each service tracks whether it owes a Neo4j sync. Sync triggers:

- Every `SYNC_INTERVAL_SIM_MINUTES` sim-minutes have elapsed since last sync
- When speed drops from BULK to FAST (mode transition)
- On graceful shutdown

```python
_last_sync_sim_time: datetime | None = None
SYNC_INTERVAL_SIM_MIN = int(os.getenv("BULK_SYNC_INTERVAL_MIN", "60"))

async def maybe_sync_neo4j(sim_time: datetime, mode: str):
    global _last_sync_sim_time

    # Always sync on mode transition out of BULK
    force_sync = (mode != "BULK" and
                  _last_mode == "BULK")

    if not force_sync and _last_sync_sim_time is not None:
        elapsed = (sim_time - _last_sync_sim_time).total_seconds() / 60
        if elapsed < SYNC_INTERVAL_SIM_MIN:
            return

    await _bulk_write_all_state_to_neo4j()
    _last_sync_sim_time = sim_time
    _last_mode = mode
```

**Bulk write pattern** — write all in-memory state to Neo4j using `UNWIND`:

```python
async def _bulk_write_all_state_to_neo4j():
    # Passenger bulk update
    pax_updates = [
        {"id": p.id, "status": p.status, "zone": p.location_zone}
        for p in _passengers.values()
    ]
    async with get_driver().session() as session:
        await session.run(
            """
            UNWIND $updates AS u
            MATCH (p:Passenger {id: u.id})
            SET p.status = u.status,
                p.location_zone = u.zone
            """,
            updates=pax_updates
        )
```

### Kafka events in BULK mode

In BULK mode, emitting a Kafka event per state transition is both unnecessary
(the dashboard can't display them faster than ~1/sec) and expensive. Instead:

- **Summary events only:** emit one `BulkStateSnapshot` per service per sync interval
  instead of individual `PassengerStatusChanged` events
- **Alerts still fire immediately:** `IncidentAlert` with `severity=critical` bypasses
  the bulk mode and produces to Kafka immediately regardless of mode

```python
# New event type for BULK mode summaries
{
  "event_type": "BulkStateSnapshot",
  "payload": {
    "service": "passenger-service",
    "sim_time": "...",
    "summary": {
      "by_status": {"checked_in": 1200, "security_queue": 340, "airside": 890, ...},
      "connections_at_risk": 7,
      "security_wait_by_terminal": {"A": 12, "B": 18, "C": 8}
    }
  }
}
```

The api-gateway consumes `BulkStateSnapshot` and uses it to update the WebSocket
clients with summary data. Individual flight/passenger events are suppressed.

---

## Speed mode decision table

```
Speed      Mode       step_min  Neo4j writes  Kafka events    Dashboard
─────────────────────────────────────────────────────────────────────────
1×–60×     REALTIME   1         per-event     per-event       fully live
60×–600×   FAST       1         batched/tick  per-event       fully live
600×–3600× BULK       1–6       every 60 sim  summary only    summary mode
3600×+     BULK       6+        every 60 sim  summary only    summary mode
```

---

## In-memory state model for BULK mode

Each service must be able to run its full simulation logic without any Neo4j reads
during BULK mode. This requires each service to load all relevant state into memory
at startup (or on transition to BULK) and maintain it locally.

### passenger-service in-memory state

```python
@dataclass
class PassengerState:
    id:            str
    flight_id:     str
    status:        str
    location_zone: str
    special_assistance: bool
    connection:    bool
    dwell_minutes_remaining: int

# Keyed by passenger_id — loaded from Neo4j at startup
_passengers: dict[str, PassengerState] = {}

# Keyed by terminal: "A" | "B" | "C"
_security_queues: dict[str, deque[str]] = {
    "A": deque(), "B": deque(), "C": deque()
}
```

### baggage-service in-memory state

```python
@dataclass
class BaggageState:
    id:        str
    flight_id: str
    status:    str
    zone_id:   str

_baggage:       dict[str, BaggageState] = {}
_zone_queues:   dict[str, deque[str]]   = {}  # zone_id → ordered queue of baggage_ids
```

---

## Files to change (revised)

### sim-orchestrator / `services/clock.py`

- Add `MAX_TICKS_PER_SEC = 10`
- Add `compute_tick_params(speed)` returning `{step_minutes, sleep_s, mode}`
- Add internal loop in `advance_sim_time()` for boundary detection across multi-min steps
- Add `step_minutes` and `mode` fields to `SimClockTick` payload

### All consumer services (passenger, baggage, incident, flight, weather)

- Read `step_minutes` and `mode` from tick payload (not computed from time diff)
- Add `is_bulk = mode == "BULK"` branching in tick handler
- Multiply all per-tick rates by `step_minutes`
- In BULK mode: update in-memory state only, skip Neo4j + Kafka per-event writes
- Add `maybe_sync_neo4j()` called at end of every tick handler
- Add `_bulk_write_all_state_to_neo4j()` per service

### passenger-service

- `services/security.py` — `drain(delta)` accepts step_minutes
- `kafka/consumer.py` — BULK mode branching, in-memory queue management

### baggage-service

- `services/conveyor.py` — `advance_tick(sim_time, delta)` accepts step_minutes
- `kafka/consumer.py` — BULK mode branching

### incident-service

- `services/lifecycle.py` — `tick_ttr(sim_time, delta)` decrements by step_minutes

### weather-service

- `kafka/consumer.py` — detect hour boundaries within a multi-minute step using the
  `_pending_hourly_events` pattern from the clock

### api-gateway

- `kafka/consumer.ts` — consume `BulkStateSnapshot` events
- `websocket.ts` — in BULK mode, send summary frames to dashboard clients every 2 real seconds
  instead of forwarding every individual event

---

## Implementation order

```
1. Clock: add step_minutes + mode to payload             ← unblocks everything
2. passenger-service: delta-aware drain + BULK branching ← highest impact
3. baggage-service: delta-aware conveyor + BULK          ← second highest impact
4. incident-service: delta TTR                           ← simple change
5. flight-service: delta delay accumulation              ← mostly time-based already
6. weather-service: multi-minute boundary detection      ← edge case, low risk
7. api-gateway: BulkStateSnapshot handling               ← dashboard summary mode
```

---

## Explicit constraints

These constraints apply regardless of implementation. Document them in `README.md`:

| Constraint                        | Value            | Reason                                                                 |
| --------------------------------- | ---------------- | ---------------------------------------------------------------------- |
| Maximum fully-accurate speed      | 600×             | Above this, Neo4j write throughput becomes a bottleneck                |
| Maximum recommended demo speed    | 3600×            | Above this, sim advances faster than dashboard refresh rate            |
| Hard speed cap                    | 7200×            | Above this, step_minutes > 12 and causal ordering breaks within a tick |
| Neo4j sync interval in BULK       | every 60 sim-min | Balance between write load and state freshness                         |
| Minimum dashboard refresh in BULK | 2 real seconds   | Human perception limit                                                 |
| Alert events                      | always immediate | Regardless of speed or mode, critical alerts never batch               |

Add to `CLAUDE.md` and `docs/skills/simulation.SKILL.md`:

```
SPEED CONSTRAINT: at speeds above 600×, the system enters BULK mode.
Neo4j writes become periodic (every 60 sim-minutes), Kafka events are summarised,
and the dashboard shows aggregate snapshots rather than individual state changes.
Individual event accuracy is not guaranteed in BULK mode. Use FAST mode (≤600×)
when per-event correctness matters.
```

---

## Testing

```bash
# Test FAST mode (600×) — should handle with no queue explosion
curl -X PATCH http://localhost:3000/api/v1/sim/speed -d '{"speed_multiplier": 600}'
# Run for 5 real minutes (~50 sim-hours)
# Check: security_queue_depth < 500 per terminal

# Test BULK mode (3600×) — Neo4j sync every 60 sim-minutes
curl -X PATCH http://localhost:3000/api/v1/sim/speed -d '{"speed_multiplier": 3600}'
# Run for 2 real minutes (~120 sim-hours = ~5 sim-days)
# Check: no OOM, no Kafka lag > 1000 messages, Neo4j writes every ~1 real second

# Test mode transition: BULK → FAST — Neo4j must sync immediately on transition
curl -X PATCH http://localhost:3000/api/v1/sim/speed -d '{"speed_multiplier": 3600}'
# wait 30 real seconds
curl -X PATCH http://localhost:3000/api/v1/sim/speed -d '{"speed_multiplier": 60}'
# Check: Neo4j state is consistent within 5 real seconds of transition

# Cypher verification after any speed test
MATCH (p:Passenger)
RETURN p.status, count(p) ORDER BY count(p) DESC
# No single status > 5000 pax

MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight)
RETURN count(b)   # > 0
```
