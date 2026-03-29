# Sprint 1 — Lessons learned

**Goal:** sim-orchestrator clock + seeding. Neo4j populated with 420 flights, ~35k passengers,
~42k baggage. Clock ticking on Kafka. REST control API operational.

---

## Issues encountered

### 1. MERGE + re-MATCH is disastrously slow for bulk inserts

The initial implementation used separate UNWIND queries per batch: one to CREATE/MERGE nodes,
then a second to MATCH the newly created node + MATCH the target node + MERGE the relationship.
For ~42,000 baggage items, this meant 3 sequential queries per batch of 2,000 — each re-scanning
indexes just to find nodes created moments ago.

**Symptom:** Baggage generation hung for 10+ minutes. The container never reached healthy state.

**Fix:** Combine node creation and relationship creation into a single Cypher query:

```cypher
UNWIND $items AS b
MATCH (pax:Passenger {id: b.passenger_id})
MATCH (f:Flight {id: b.flight_id})
CREATE (bag:Baggage { ... })
CREATE (pax)-[:CARRIES]->(bag)
CREATE (bag)-[:LOADED_ON]->(f)
```

One query per batch instead of three. Seeding went from >10 minutes to ~2 seconds.

**Rule:** For bulk seed operations where we know IDs are fresh, use `CREATE` (not `MERGE`) and
combine node + relationship creation in one UNWIND query.

### 2. Python `global` pitfall with list truncation

The clock loop tracked tick latencies in a module-level list `_tick_latencies`. The loop appended
to it and periodically truncated with `_tick_latencies = _tick_latencies[-500:]`. Python sees the
`= assignment` and treats `_tick_latencies` as a local variable for the entire function scope —
even the `.append()` call earlier in the function.

**Symptom:** `UnboundLocalError: cannot access local variable '_tick_latencies'` on the first
tick. The clock loop crashed silently (asyncio task exception never retrieved).

**Fix:** Add `_tick_latencies` to the `global` declaration:

```python
global _sim_time, _sim_day, _tick_number, _events_produced, _tick_latencies
```

**Rule:** If a function both reads and reassigns a module-level variable, it must be declared
`global`. Appending alone doesn't require it, but reassigning (`= expr`) does.

### 3. Passenger generation for all flights vs departures only

The initial seeder called `generate_passengers(flights)` with all 420 flights. The spec says
passengers are only generated for departures (arrival passengers aren't at the airport). This
doubled the expected passenger count from ~35k to ~71k.

**Symptom:** 71,850 passengers generated instead of ~35,000.

**Fix:** Filter departures before passing to passenger generation:

```python
departure_flights = [f for f in flights if f["direction"] == "departure"]
```

**Rule:** Read the spec carefully on which subset of entities feeds into the next generation
stage. "Generate passengers for all flights" ≠ "generate passengers for departure flights."

### 4. CREATE vs MERGE requires restart protection

Switching from `MERGE` to `CREATE` for performance means re-running the seeder on a restart
(without DB wipe) creates duplicate nodes. The service must detect whether the day has already
been seeded and skip re-seeding.

**Fix:** Added `_day_already_seeded()` check that queries Neo4j for flights with matching date
prefix before running `seed_day()`.

### 5. Relationship naming must match DATA_MODEL.md exactly

The initial implementation used `BOOKED_ON` for the Passenger→Flight relationship. The spec in
DATA_MODEL.md defines this as `ON_FLIGHT`. Other services consuming the graph will query by spec
relationship names, so any deviation would silently return empty results.

**Fix:** Renamed to `ON_FLIGHT` to match spec.

**Rule:** Always cross-reference DATA_MODEL.md §3 (Relationship catalogue) before naming any
Neo4j relationship.

### 6. Node properties must include all spec fields, even if initially NULL

DATA_MODEL.md defines properties like `actual_time`, `delay_reason` (Flight), `carousel`,
`last_scan_at` (Baggage), `connection_flight_id`, `checked_in_at`, `boarded_at` (Passenger),
`created_at` (Airport), and `last_assigned_at` (Gate). Even if these are NULL at seed time, they
must be present so downstream services can SET them without needing to know if the property key
exists.

**Fix:** Added all missing properties with NULL defaults in seed/generation code.

### 7. `severe_weather` is not a probabilistic event

The event types table in SIMULATION.md shows `severe_weather` with "driven by weather FSM" in the
probability column. This means it's not injected by the orchestrator's probabilistic evaluator —
it's handled by the weather-service FSM transitions. The events.json fixture correctly omits it
from `base_probabilities`.

### 8. Hardcoded config should come from fixtures

The injector initially hardcoded `PEAK_HOURS = {7, 8, 9, 17, 18, 19}` and
`suppression_window = 2`. The events.json fixture already declares these as `peak_hours` and
`suppression_window_hours`. Using the fixture values makes the injector configurable without
code changes.

---

## What went well

- The bimodal schedule generation (`numpy.random.normal` with two peaks) produces realistic
  traffic patterns on the first try — morning and evening rushes, quieter midday.
- The `Beta(8, 2)` load factor distribution gives a natural spread of passenger counts per flight
  (70–100% occupancy, mean ~80%), avoiding uniform-looking data.
- Full seeding (airport + 420 flights + 35k passengers + 42k baggage) completes in ~4 seconds
  with combined UNWIND queries — fast enough to run on every container restart.
- The clock loop recovers gracefully from slow tick processing via drift compensation
  (`actual_sleep = max(0, sleep_s - tick_elapsed / 1000)`).
- Deterministic seeding via `rng_seed = 42 + sim_day` means every reset produces identical data,
  making debugging reproducible.

---

## Performance numbers

| Operation                              | Duration  | Volume                                      |
| -------------------------------------- | --------- | ------------------------------------------- |
| Airport structure seed                 | ~300ms    | 1 Airport, 3 Terminals, 42 Gates, 4 Runways |
| Schedule generation                    | ~150ms    | 420 flights (210+210)                       |
| Passenger generation                   | ~2s       | 35,394 passengers                           |
| Baggage generation                     | ~2s       | 42,355 baggage items                        |
| Total startup (incl. Neo4j/Kafka wait) | ~5s       | 78,216 nodes total                          |
| Clock tick latency                     | 0.1ms avg | 1 tick/second at 60x                        |
