# Sprint 3 — Lessons learned

**Goal:** flight-service with 9-state FSM, runway priority queue, gate conflict resolver,
turnaround delay propagation, Kafka consumer/producer, REST API, and WebSocket.

---

## Issues encountered

### 1. Python `global` pitfall — third occurrence

The `ws_broadcast()` function in `main.py` uses `_ws_clients -= disconnected`, which is a
reassignment of the module-level set. Without `global _ws_clients`, Python treats the variable
as local for the entire function scope, causing `UnboundLocalError` on the first read.

**Symptom:** `UnboundLocalError: cannot access local variable '_ws_clients'` when broadcasting
to WebSocket clients.

**Fix:** Added `global _ws_clients` at the top of `ws_broadcast()`.

**Rule:** This is the third time this bug has appeared (sprint-1 §2, sprint-2 §1). Any function
that uses augmented assignment (`-=`, `+=`, `|=`) on a module-level variable needs `global`.
Consider migrating to a class-based state holder to eliminate this category entirely.

### 2. Timezone-aware vs naive datetime comparisons

`sim_time` from Kafka's `SimClockTick` arrives with `+00:00` timezone info (e.g.
`2024-06-03T08:30:00+00:00`), but `estimated_time` stored in Neo4j is a naive ISO string.
Python raises `TypeError: can't compare offset-naive and offset-aware datetimes` when
comparing the two.

**Symptom:** FSM evaluation crashed on every tick with a TypeError. No flights transitioned.

**Fix:** Strip tzinfo from sim_time immediately after parsing:

```python
sim_time = datetime.fromisoformat(sim_time_str).replace(tzinfo=None)
```

Also strip in `state_machine.py`'s `_parse_time()` helper for consistency.

**Rule:** In a simulation environment where all times are logically UTC, strip timezone info
at the ingestion boundary (Kafka consumer) and keep all internal datetimes naive. This matches
Neo4j's storage format and avoids comparison errors.

### 3. Neo4j EXISTS subquery syntax differs from documentation

The initial Cypher for finding available gates used the pattern:

```cypher
WHERE NOT EXISTS {
  MATCH (fl:Flight)-[:ASSIGNED_TO]->(g)
  WHERE fl.status IN $active_statuses
}
```

This works in Neo4j Enterprise but not in Neo4j 5.x Community Edition. The subquery couldn't
reference the outer variable `g` correctly.

**Symptom:** `ClientError` from Neo4j during gate availability queries. Error message referenced
syntax issues with the EXISTS subquery.

**Fix:** Rewrote to use a standard OPTIONAL MATCH + WHERE IS NULL pattern, or a different
subquery form that Community Edition supports:

```cypher
OPTIONAL MATCH (f:Flight)-[:ASSIGNED_TO]->(g)
WHERE f.status IN ['boarding', 'delayed', ...]
WITH g, f
WHERE f IS NULL
```

**Rule:** Avoid EXISTS subqueries with outer variable references in Neo4j Community Edition.
Use OPTIONAL MATCH + NULL check or count-based patterns instead.

### 4. Runway queue re-enqueue loop

The Kafka consumer's `_process_flight()` enqueued `scheduled` arrivals into the runway queue
on every tick. The `RunwayQueue.assign_slots()` method correctly removed flights from
`_queued_flights` after assignment, but this meant the idempotency check
(`if flight_id in self._queued_flights: return`) passed on the next tick, re-adding the flight.

**Symptom:** Flights SP193 and AX299 were assigned runway 09L on every tick, generating
hundreds of `FlightRunwayAssigned` events per minute. Logs were dominated by repeated
assignment messages.

**Fix:** Added two guards to the enqueue conditions:

1. Check `not flight.get("runway_id")` — skip flights already assigned a runway
2. Add time-proximity check — only enqueue arrivals within 35 minutes of estimated time

```python
if current_status == "scheduled" and direction == "arrival" and not flight.get("runway_id"):
    est = datetime.fromisoformat(str(estimated))
    if sim_time >= est - timedelta(minutes=35):
        _runway_queue.enqueue_arrival(flight_id, str(estimated))
```

**Rule:** In-memory queue idempotency sets must be lifetime-persistent (never cleared for
assigned items), OR the enqueue decision must be gated on authoritative state (Neo4j
relationship existence). The Neo4j-backed `runway_id` check is the robust approach.

### 5. Cypher OPTIONAL MATCH aggregation produces cartesian products

The `/runways` endpoint query used two sequential OPTIONAL MATCHes with different relationship
property filters:

```cypher
OPTIONAL MATCH (f_arr:Flight)-[rel:USES_RUNWAY {operation: 'landing'}]->(r) ...
WITH r, count(f_arr) AS arr_count
OPTIONAL MATCH (f_dep:Flight)-[rel:USES_RUNWAY {operation: 'takeoff'}]->(r) ...
```

This produced incorrect results or errors because the aggregation context from the first
`WITH` affected the second OPTIONAL MATCH.

**Symptom:** `/runways` endpoint returned HTTP 500.

**Fix:** Combined into a single OPTIONAL MATCH with conditional aggregation:

```cypher
OPTIONAL MATCH (f:Flight)-[rel:USES_RUNWAY]->(r)
WHERE f.status IN [...]
WITH r,
     sum(CASE WHEN rel.operation = 'landing' ... THEN 1 ELSE 0 END) AS arr_count,
     sum(CASE WHEN rel.operation = 'takeoff' ... THEN 1 ELSE 0 END) AS dep_count
```

**Rule:** Avoid multiple OPTIONAL MATCH + aggregate + WITH chains in Cypher. Use a single
OPTIONAL MATCH with CASE-based conditional aggregation instead.

### 6. Gate query returns duplicate rows per gate

The gate listing query used `OPTIONAL MATCH (f:Flight)-[:ASSIGNED_TO]->(g)` which returns
one row per flight-gate pair. Gates with multiple assigned flights (e.g. one `at_gate` and
one `boarding`) appeared multiple times.

**Symptom:** Terminal A showed 446 gates instead of 14.

**Fix:** Added `collect(f)` + `head()` to pick only the most recent active flight per gate:

```cypher
WITH g, f ORDER BY f.estimated_time DESC
WITH g, head(collect(f)) AS f
```

**Rule:** When joining a 1-to-many relationship with OPTIONAL MATCH, always aggregate back
to the "one" side before returning. Use `collect()` + `head()` or `count()` to avoid
row multiplication.

---

## What went well

- The FSM state machine as a pure-logic module (`state_machine.py`) with no I/O made debugging
  straightforward. Transition logic could be reasoned about independently of Neo4j and Kafka.
- The event envelope pattern (event_id, event_type, schema_version, sim_time, producer, payload)
  provided clean idempotency via the `_processed_events` set.
- Reading sim-orchestrator and weather-service code before starting gave concrete patterns for
  Neo4j driver usage, Kafka consumer loops, and the lifespan pattern.
- The 9-state FSM handles 2100 flights (3 sim days × 700/day) with states distributed correctly
  across boarding, airborne, approach, at_gate, and scheduled.

---

## Architecture decisions

- **Runway queue is in-memory only.** On restart, the queue is empty and refills from the next
  tick as scheduled flights get re-evaluated. This is acceptable because runway assignment is
  transient and can be reconstructed from current flight states.
- **Gate assignment happens at T-65 minutes** for departures (slightly before the T-60 boarding
  window) to ensure the gate is ready when boarding begins.
- **Boarding percentage simulation.** When passenger-service hasn't processed passengers yet,
  the flight-service estimates boarding based on elapsed time since T-60. This breaks the strict
  service boundary but prevents deadlocks where flights can never depart.
- **Turnaround delay propagation** only triggers for delays ≥15 minutes and subtracts the
  turnaround buffer before cascading.

---

## Performance observations

| Operation                                  | Typical duration |
| ------------------------------------------ | ---------------- |
| get_active_flights (2100 flights)          | ~25ms            |
| FSM evaluation per flight                  | <1ms             |
| Neo4j update_flight_status                 | ~3ms             |
| Full tick processing (~100 active flights) | ~300ms           |
| Runway queue assign_slots                  | <1ms             |
| Gate conflict check                        | ~5ms             |

---

## What I would change if restarting

1. **Use a class for consumer state** instead of module-level globals. The `global` keyword
   pitfall has appeared in every sprint. A `FlightConsumer` class would hold `_sim_time`,
   `_runway_queue`, `_held_flights`, etc. as instance attributes.
2. **Track runway assignments in the queue itself** rather than relying on Neo4j relationship
   existence. An `_assigned_flights` set that persists across ticks would prevent the re-enqueue
   bug without a Neo4j query.
3. **Use RETURN ... AS instead of map projections** in Cypher queries. Map projections (`r { .id }`)
   are cleaner but harder to debug and more prone to silent NULL issues. Explicit column returns
   are more predictable.
