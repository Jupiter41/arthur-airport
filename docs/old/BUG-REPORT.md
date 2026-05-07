# Bug report — Sprint 9 human testing

## For Claude Opus 4.6 via Copilot

Before fixing anything, read these files in order:

1. `CLAUDE.md` — architecture rules
2. `docs/services/baggage-service/SPEC.md` + `services/baggage-service/SKILL.md`
3. `docs/services/passenger-service/SPEC.md` + `services/passenger-service/SKILL.md`
4. `docs/services/flight-service/SPEC.md` + `services/flight-service/SKILL.md`
5. `docs/architecture/DATA_MODEL.md` — Neo4j relationships
6. `docs/architecture/EVENT_BUS.md` — Kafka event schemas

Do not fix anything until you have read all six files above.

---

## Root cause hypothesis (confirm before fixing)

The user suspects — and the evidence strongly supports — that **passenger and baggage state
machines are stuck**. Passengers accumulate in `security_queue` forever (34,055 pax in one
terminal) instead of draining to `airside`. Baggage reaches `make-up` zones but never
transitions to `loaded` on a flight. This causes all downstream metrics and UI elements
to show stale or zero values.

There are likely **two independent root causes**:

1. **Baggage:** the `LOADED_ON` relationship between `Baggage` and `Flight` is never created.
   Items reach the make-up zone but the Neo4j write that creates the relationship and sets
   `status = "loaded"` is missing or broken. The conveyor map shows 0 items on the belt
   from make-up to aircraft because there is no code path that executes this transition.

2. **Passengers:** the security queue drain logic is either not executing on each
   `SimClockTick`, or the `effective_throughput` calculation produces 0 (e.g. because
   `forecast_queue` is 0 on day 1 and the slowdown formula divides by zero), causing
   `items_to_drain_this_tick` to always return 0. Passengers enter `security_queue` via
   the batch check-in cutoff but never leave it.

Fix bug 1 and bug 2 first — bugs 3, 4, 5, and 6 are all downstream symptoms of the same
stuck state machines.

---

## Bug 1 — Baggage never transitions from make-up to loaded

### Observed behaviour

The baggage tracker shows 0% loading progress on all flights. The conveyor map shows
items present in `make-up-{A/B/C}-{n}` zones but 0 items on any flight. The
`LOADED_ON` relationship between `Baggage` and `Flight` nodes is never created in Neo4j.

Verify with:

```cypher
MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight)
RETURN count(b) AS loaded_count
// Expected: > 0 after a few sim-minutes
// Actual:   0
```

### Expected behaviour (from `docs/services/baggage-service/SPEC.md §2`)

State machine: `sorting → loaded`. When a bag reaches a make-up carousel assigned to a
departing flight, its status must transition to `loaded` and a `LOADED_ON` relationship
must be created between the `Baggage` node and the `Flight` node.

### What to look for and fix in `services/baggage-service/`

Check `services/conveyor.py` (or equivalent). The `drain_zone()` function must:

- Know which make-up zone serves which flight
- When draining items from `make-up-{terminal}-{n}` into the aircraft hold:
  - Set `baggage.status = "loaded"`
  - Create `(b:Baggage)-[:LOADED_ON {loaded_at: sim_time}]->(f:Flight)` in Neo4j
  - Emit `BaggageStatusChanged` event with `previous: "sorting"`, `new: "loaded"`

Also check the gate-to-make-up assignment logic. Each flight must be assigned to a specific
make-up carousel when boarding begins. If this assignment is missing, the conveyor has no
target flight to load bags onto and the transition never fires.

The fix likely needs to be in `services/baggage-service/db/neo4j.py` — add a function:

```python
async def load_baggage_onto_flight(baggage_id: str, flight_id: str,
                                    sim_time: datetime):
    async with get_driver().session() as session:
        await session.run(
            """
            MATCH (b:Baggage {id: $bid})
            MATCH (f:Flight {id: $fid})
            SET b.status = 'loaded',
                b.last_scan_zone = $zone,
                b.last_scan_at = $at
            MERGE (b)-[r:LOADED_ON]->(f)
            SET r.loaded_at = $at
            """,
            bid=baggage_id, fid=flight_id,
            zone=f"make-up-hold",
            at=sim_time.isoformat()
        )
```

---

## Bug 2 — Passengers stuck in security_queue, zone densities are absurd

### Observed behaviour

```
security_queue: 34,055 pax   ← should never exceed ~800 across all terminals
airside:           302 pax
boarded:           842 pax

check-in-A:          0 pax   0%
security-A:     52,669 pax   43,890.8%  ← impossible (capacity is 120)
airside-A:      52,109 pax   6,513.6%   ← impossible
gates-A:        52,109 pax   6,514%     ← impossible
```

Security wait time: 0 in two terminals, >2,800 min in one terminal.

### Root causes to check

**Root cause A — Division by zero in slowdown formula:**

From `docs/skills/forecasting.SKILL.md` and `services/passenger-service/SKILL.md`:

```python
def effective_throughput(open_lanes, actual_queue, forecast_queue):
    base = open_lanes * 180.0
    if forecast_queue > 0 and actual_queue > forecast_queue * 1.3:
        slowdown = min(1.0, forecast_queue / actual_queue)
        return base * slowdown
    return base
```

On day 1, `forecast_queue = 0` (model not yet trained, fallback formula may also return 0
if `expected_pax_next_90min` is 0). If the condition is `forecast_queue > 0`, throughput
correctly returns `base`. But if somewhere in the code `forecast_queue` is used as a divisor
without this guard, you get `ZeroDivisionError` or `throughput = 0`.

Verify: add a log statement to print `effective_throughput` on every tick. If it prints 0,
this is the bug. The fix is to ensure `items_to_drain_this_tick` never returns 0 when there
are lanes open:

```python
def items_to_drain_this_tick(open_lanes: int, actual_queue: int,
                              forecast_queue: int) -> int:
    throughput = effective_throughput(open_lanes, actual_queue, forecast_queue)
    # Minimum drain: always process at least 1 pax per tick if queue > 0
    # regardless of forecast model state
    if actual_queue > 0 and throughput <= 0:
        throughput = open_lanes * 180.0  # fall back to base rate
    return max(0, int(throughput / 60))
```

**Root cause B — Zone density tracker not being decremented:**

From `services/passenger-service/SKILL.md`:

```python
def move_passenger(old_zone: str | None, new_zone: str):
    if old_zone:
        _zone_density[old_zone] = max(0, _zone_density[old_zone] - 1)
    _zone_density[new_zone] += 1
```

If `move_passenger` is called with `old_zone=None` when a passenger transitions from
`security_queue` to `airside` (i.e. the old zone is not being passed correctly), the
`security_queue` zone counter is never decremented. This explains the accumulation to
34,055+ and the >43,000% load percentages.

Check every call site of `move_passenger` (or equivalent). Ensure `old_zone` is always
the passenger's current `location_zone` value read from Neo4j or in-memory state
**before** the transition, not `None`.

**Root cause C — Passenger state machine not being evaluated on every tick:**

Check `kafka/consumer.py` in `passenger-service`. The `on_clock_tick` handler must iterate
all passengers in `security_queue` and drain them. If it is only processing passengers
for flights departing in the current tick window, passengers for flights departing later
(or already departed) are never processed.

The security queue drain should process **all** passengers currently in `security_queue`
status, not just those associated with a specific flight or time window.

### What to fix

1. In `services/security.py` (or equivalent): add the guard against zero throughput shown above
2. In the state machine tick handler: ensure `move_passenger(old_zone, new_zone)` always
   receives the passenger's actual current zone as `old_zone`
3. In `db/neo4j.py`: when updating `passenger.status` and `passenger.location_zone`,
   read the old `location_zone` value first, pass it to `move_passenger`, then write
   the new value
4. Add a rebuild-from-Neo4j call at startup to initialise `_zone_density` correctly
   (see `services/passenger-service/SKILL.md` — `rebuild_zone_density()`)

---

## Bug 3 — TypeError in incident dashboard: `Cannot read properties of undefined (reading 'length')`

### Observed behaviour

```
TypeError: Cannot read properties of undefined (reading 'length')
    at Ug (index-BAF9IBrl.js:87:418)
```

This is a minified React component crash. The component is trying to call `.length` on
a value that is `undefined` instead of an array.

### Root cause

The incident dashboard cascade tree visualizer renders `incident.cascade_tree.children`
(or a similar array property). When an incident exists but has no cascade events yet
(depth = 0, children = []), the API may return:

```json
{ "cascade_tree": null }
// or
{ "cascade_tree": { "children": null } }
// instead of
{ "cascade_tree": { "children": [] } }
```

### What to fix

**In `incident-service` (`routers/incidents.py` or equivalent):**
Ensure `cascade_tree` always returns an object with `children: []` even when there are
no child incidents. Never return `null` for array fields:

```python
def build_cascade_tree(incident_id: str, records: list) -> dict:
    # Always return children as a list, never None
    return {
        "id": incident_id,
        "type": ...,
        "children": []   # empty list, not null
    }
```

**In the React dashboard (`src/pages/IncidentDashboard.tsx` or equivalent):**
Add defensive null checks before accessing any array property received from the API.
Use optional chaining and nullish coalescing:

```typescript
// WRONG — crashes if cascade_tree or children is undefined
const depth = incident.cascade_tree.children.length

// RIGHT — safe regardless of API response shape
const children = incident?.cascade_tree?.children ?? []
const depth = children.length

// Also fix any map/filter calls on potentially undefined arrays:
const cascadeNodes = incident?.cascade_tree?.children ?? []
cascadeNodes.map(child => ...)   // safe
```

Apply this pattern to every field in the incident object that is expected to be an array:
`affected_entity_ids`, `cascade_events`, `protocols_activated`, `affected_flights`,
`timeline`. All of these should default to `[]` if absent.

---

## Bug 4 — Flight detail progress bar always 0 (passengers and baggage)

### Observed behaviour

The flight detail drawer and the flight board loading progress bars show:

- Passengers: `0 / 142 boarded (0%)`
- Baggage: `0 / 186 loaded (0%)`

Even when the flight status correctly shows `boarding` and individual passenger statuses
are changing.

### Root cause

The progress values are derived from counts that live in two different services:

- Passenger boarded count: owned by `passenger-service`
- Baggage loaded count: owned by `baggage-service`

The `flight-service` `GET /flights/{id}` endpoint (from `docs/services/flight-service/SPEC.md §5`)
returns:

```json
"passengers": { "total": 142, "boarded": 98, ... },
"baggage":    { "total": 186, "loaded": 124, ... }
```

These counts are either:
a) Queried from Neo4j via cross-domain read (allowed — read-only from another domain's nodes)
b) Maintained as counters in `flight-service` memory, updated by consuming
`PassengerStatusChanged` and `BaggageStatusChanged` events from Kafka

If the flight-service is not consuming `passengers.events` and `baggage.events`, or if the
Neo4j query is not counting correctly (e.g. because `LOADED_ON` relationships don't exist
— see Bug 1), these counts will always be 0.

### What to fix

**Option A (recommended):** flight-service consumes `passengers.events` and `baggage.events`
and maintains in-memory counters per flight:

```python
# In flight-service kafka/consumer.py
_flight_pax_boarded: dict[str, int] = defaultdict(int)
_flight_bag_loaded:  dict[str, int] = defaultdict(int)

async def on_passenger_status_changed(payload: dict, sim_time: datetime):
    if payload.get("new_status") == "boarded":
        flight_id = payload.get("flight_id")
        if flight_id:
            _flight_pax_boarded[flight_id] += 1

async def on_baggage_status_changed(payload: dict, sim_time: datetime):
    if payload.get("new_status") == "loaded":
        flight_id = payload.get("flight_id")
        if flight_id:
            _flight_bag_loaded[flight_id] += 1
```

Then return these counts in `GET /flights/{id}`.

**Option B:** query Neo4j directly from flight-service:

```cypher
// Boarded passengers for flight
MATCH (p:Passenger {status: 'boarded'})-[:ON_FLIGHT]->(f:Flight {id: $fid})
RETURN count(p) AS boarded_count

// Loaded baggage for flight
MATCH (b:Baggage {status: 'loaded'})-[:LOADED_ON]->(f:Flight {id: $fid})
RETURN count(b) AS loaded_count
```

Note: Option B only works once Bug 1 is fixed (LOADED_ON relationships exist).

---

## Bug 5 — Runway movement rate (mvt/hour) always 0 in flight dashboard

### Observed behaviour

The flight board status bar shows `0 mvt/hr` for both runways regardless of simulation state.

### Root cause

The `runway_capacity_per_hour` Prometheus metric or the `GET /runways` API response field
is always returning 0. This is likely because:

a) The `current_capacity_per_hour` value on the runway queue manager is never updated
when `WeatherStateChanged` events arrive, or
b) The field is computed but not persisted to the runway state object that the REST
endpoint reads from

### What to fix

In `flight-service/services/runway_queue.py` (or equivalent), ensure that when a
`WeatherStateChanged` event is received, the capacity is updated:

```python
_runway_capacity: dict[str, dict] = {
    "09L": {"arrival": 32, "departure": 32},
    "09R": {"arrival": 32, "departure": 32},
}

async def on_weather_changed(payload: dict, sim_time: datetime):
    arrival_rate   = payload.get("recommended_arrival_rate",   32)
    departure_rate = payload.get("recommended_departure_rate", 32)
    for runway_id in _runway_capacity:
        _runway_capacity[runway_id]["arrival"]   = arrival_rate
        _runway_capacity[runway_id]["departure"] = departure_rate
```

Then in `GET /runways`, include `capacity_per_hour` from `_runway_capacity`:

```python
return {
    "id": runway_id,
    "arrival_rate_per_hour":   _runway_capacity[runway_id]["arrival"],
    "departure_rate_per_hour": _runway_capacity[runway_id]["departure"],
    ...
}
```

The React component reading this field should use the correct key name — verify it matches
exactly what the API returns.

---

## Fix order recommendation

Fix in this sequence — each fix unblocks the next:

```
1. Bug 2 first  → fixes passenger state machine → zone densities become realistic
2. Bug 1 second → fixes baggage loading → LOADED_ON relationships created
3. Bug 4 third  → now that bugs 1+2 are fixed, counts will be non-zero
4. Bug 3 fourth → defensive null checks in React (independent, fix any time)
5. Bug 5 last   → cosmetic metric fix (independent of state machines)
```

After fixing bugs 1 and 2, restart `passenger-service` and `baggage-service`, then run:

```cypher
// Verify passengers are draining
MATCH (p:Passenger)
RETURN p.status AS status, count(p) AS n
ORDER BY n DESC

// Expected: no single status should have > 5000 pax
// security_queue should drain below 500 during off-peak

// Verify baggage is loading
MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight)
RETURN count(b) AS loaded
// Expected: > 0 and growing
```

Also check Grafana after the fix:

- `security_queue_depth` per terminal should stay below 200 during normal ops
- `baggage_in_system{status="loaded"}` should grow during boarding windows
- `zone_load_pct{zone_id="security-B"}` should stay below 100%
