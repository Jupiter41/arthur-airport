# Sprint 5 — Lessons learned

**Goal:** passenger-service with full departure/arrival flow, security checkpoint model,
MCT connection monitoring, ML queue-depth forecasting (LightGBM), congestion detection,
Kafka consumer/producer, REST API, and WebSocket.

---

## Issues encountered

### 1. LightGBM requires libgomp1 in slim Docker images

The passenger-service container crashed immediately at startup with
`ImportError: libgomp.so.1: cannot open shared object file` when importing `lightgbm`.
LightGBM depends on OpenMP for parallel tree evaluation, and `python:3.11-slim` does not
include `libgomp1` by default.

**Symptom:** Container enters crash loop on import. No FastAPI startup logs.

**Fix:** Added `libgomp1` to the Dockerfile's `apt-get install` line.

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 && rm -rf /var/lib/apt/lists/*
```

**Rule:** When adding ML libraries that depend on C/Fortran backends (LightGBM, XGBoost,
scikit-learn with OpenMP), always verify runtime dependencies in the Docker target image.
Slim images strip many libraries.

### 2. Neo4j Cypher `NOT IN` syntax — Community Edition vs Enterprise

The query `WHERE p.status NOT IN ['departed_airport', 'boarded']` caused a
`SyntaxError` in Neo4j 5 Community Edition. The correct syntax is
`WHERE NOT p.status IN [...]`.

**Symptom:** FastAPI returns 500 on first tick. Cypher `SyntaxError` in logs.

**Fix:** Replaced all occurrences of `x NOT IN [...]` with `NOT x IN [...]`.

```cypher
-- WRONG (Neo4j 5 CE)
WHERE p.status NOT IN ['departed_airport', 'boarded']

-- CORRECT
WHERE NOT p.status IN ['departed_airport', 'boarded']
```

**Rule:** Always use `NOT x IN [...]` syntax for Cypher exclusion filters. The `x NOT IN`
syntax is not universally supported across Neo4j editions.

### 3. Terminal distribution — all passengers routed to terminal A

When passengers moved from `checked_in` to `security_queue`, the
`get_terminal_from_gate()` function was used to determine the target terminal. Since most
flights lack gate assignments at check-in cutoff time (T-45), the function defaulted to
terminal A for all of them. 100% of security queue passengers ended up in terminal A.

**Symptom:** `flow/summary` showed `queue_depth: 98000+` for terminal A, `0` for B and C.

**Fix:** Added `get_terminal_for_flight()` which falls back to a hash-based distribution
(`hash(flight_id) % 3`) when no gate is assigned. This provides ~33% per terminal even
when gate assignments haven't been made yet.

```python
def get_terminal_for_flight(gate_id, terminal_id, flight_id):
    terminal = get_terminal_from_gate(gate_id, terminal_id)
    if terminal != "A" or (gate_id and gate_id.startswith("A")):
        return terminal
    if flight_id:
        return ["A", "B", "C"][hash(flight_id) % 3]
    return "A"
```

**Rule:** Never assume that relationships or properties exist at the time a state
transition triggers. Use deterministic fallbacks (hash-based distribution) rather than
defaulting everything to a single bucket.

### 4. In-memory security queues empty after restart

The `SecurityCheckpoint` class tracks passenger queues in-memory (Python lists). On service
restart, the zone density was rebuilt from Neo4j but the security queues were not.
`queue_depth` and `wait_minutes` reported 0 for all terminals despite 100K+ passengers in
`security_queue` status in Neo4j.

**Symptom:** `flow/summary` showed `by_status.security_queue: 102880` (from Neo4j) but
`security.terminal_*.queue_depth: 0` and `wait_minutes: 0.0`.

**Fix:** Added `rebuild_security_from_neo4j()` that runs at startup (in the lifespan,
after zone density rebuild). It queries all `security_queue` passengers and enqueues them
into the in-memory `SecuritySystem` based on their `location_zone`.

```python
async def rebuild_security_from_neo4j():
    pax_list = await get_passengers_by_status("security_queue")
    for pax in pax_list:
        zone = pax.get("location_zone") or ""
        terminal = zone.split("-")[-1]
        if terminal not in ("A", "B", "C"):
            terminal = get_terminal_for_flight(...)
        _security.enqueue(terminal, pax["id"], bool(pax.get("special_assistance")))
        _security_enqueued.add(pax["id"])
```

**Rule:** Every in-memory data structure that supplements Neo4j must be rebuildable from
Neo4j on startup. The `restart` contract: if the service restarts mid-simulation, it must
converge to the same state as if it had been running continuously.

### 5. Boarding pipeline not triggering for airborne flights

The `_advance_boarding()` function only boarded passengers when `flight_status` was in
`("boarding", "scheduled", "delayed")`. When the service started mid-simulation, hundreds
of flights were already `airborne` — their passengers were stuck at `at_gate` status
indefinitely.

**Symptom:** 12K passengers in `at_gate` with 0 in `boarded`. No boarding progress despite
sim clock advancing.

**Fix:** Added a check for already-departed flights: if `flight_status in ("airborne",
"departed", "taxiing")`, bulk-board all remaining passengers immediately.

**Rule:** State machine transitions must account for catch-up scenarios where the service
starts after the triggering event has already passed. This is the same principle as
Sprint 4's "fast-track" pattern for baggage.

### 6. Missing `airside_at` field in Neo4j query

The `get_passengers_by_status("airside")` query returned `dwell_minutes` but not
`airside_at`. The `should_move_to_at_gate()` function uses both to calculate dwell
elapsed time. Without `airside_at`, the dwell check was bypassed (treated as None →
immediate gate move).

**Symptom:** Passengers transitioned from airside to gate immediately, ignoring the
25-minute mean dwell time.

**Fix:** Added `p.airside_at AS airside_at` to the query RETURN clause.

**Rule:** When a state transition depends on a timestamp + duration pair, ensure both
fields are persisted in Neo4j and returned by the query. Cross-check every field
referenced in the state machine against the query's RETURN clause.

---

## What went well

- **Zone density tracker** worked on first attempt — `rebuild_from_neo4j()` ran cleanly
  and the heatmap endpoint returned correct per-zone counts immediately.
- **ML forecasting pipeline** (features → buffer → flush → train → predict → hot-reload)
  compiled and ran without issues. The day-1 fallback (35% of expected passengers)
  produced reasonable 14.6-minute wait estimates.
- **Security throughput model** (190 pax/hr/lane with slowdown factor) drained queues at
  the expected rate of ~12 pax/min/terminal. The progressive drain is visible in
  consecutive `flow/summary` calls.
- **Kafka consumer** handles all 6 event types without errors after the Cypher fixes.
  Idempotency tracking and event deduplication work correctly.

---

## Patterns confirmed

- **Rebuildable in-memory state:** This sprint reinforced Sprint 4's lesson that every
  in-memory cache must be rebuildable from Neo4j. Added to the startup checklist: zone
  density, security queues, ML model loading.
- **Mid-simulation startup:** Services must handle accumulation from unbounded simulation
  time. Filter queries should be inclusive, with fast-track paths for already-completed
  transitions.
- **Hash-based distribution:** When deterministic allocation is needed without a lookup
  table (no gate → no terminal), `hash(id) % N` provides acceptable even distribution.
