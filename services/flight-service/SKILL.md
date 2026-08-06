# SKILL — flight-service

## State machine · Runway queue · Gate conflicts · Turnaround tracker

> Full specification: `docs/services/flight-service/SPEC.md`
> Read `docs/skills/SKILL.md` and `docs/skills/python-service.SKILL.md` first.

---

## State machine transitions

```
scheduled ──(T-60min)──► boarding ──(T-0, 95% boarded)──► departed ──(+5min)──► airborne
                              │                                                       │
                         (hold/delay)                                           (ETA-20min)
                              ▼                                                       ▼
                           delayed ◄──────────────────────────────────────── approach
                              │                                                       │
                         (≥180min or manual)                                  (ETA, runway ok)
                              ▼                                                       ▼
                          cancelled                                               landed
                                                                                     │
                                                                               (ATA+2min)
                                                                                     ▼
                                                                                 taxiing
                                                                                     │
                                                                               (ATA+8min, gate ok)
                                                                                     ▼
                                                                                  at_gate
```

A flight enters `delayed` from `boarding` or `approach` when its forward transition cannot
execute. It exits back to `boarding` or `approach` when the blocker resolves.

---

## Transition conditions (implement these exactly)

```python
from datetime import datetime, timedelta

def should_transition(flight: dict, sim_time: datetime,
                      runway_available: bool, gate_available: bool,
                      boarded_pct: float) -> str | None:
    etd = datetime.fromisoformat(flight["estimated_time"])
    status = flight["status"]

    match status:
        case "scheduled":
            if sim_time >= etd - timedelta(minutes=60):
                return "boarding"
        case "boarding":
            if sim_time >= etd and boarded_pct >= 0.95:
                return "departed"
            if flight["delay_minutes"] >= 180:
                return "cancelled"
        case "departed":
            if sim_time >= etd + timedelta(minutes=5):
                return "airborne"
        case "airborne":
            eta = datetime.fromisoformat(flight["estimated_time"])
            if sim_time >= eta - timedelta(minutes=20):
                return "approach"
        case "approach":
            eta = datetime.fromisoformat(flight["estimated_time"])
            if sim_time >= eta and runway_available:
                return "landed"
        case "landed":
            ata = datetime.fromisoformat(flight["actual_time"])
            if sim_time >= ata + timedelta(minutes=2):
                return "taxiing"
        case "taxiing":
            ata = datetime.fromisoformat(flight["actual_time"])
            if sim_time >= ata + timedelta(minutes=8) and gate_available:
                return "at_gate"
    return None
```

---

## Runway queue manager

```python
from heapq import heappush, heappop
from dataclasses import dataclass, field

@dataclass(order=True)
class RunwayQueueItem:
    priority: tuple           # (estimated_time, flight_id)
    flight_id: str = field(compare=False)
    operation: str = field(compare=False)  # "landing" or "takeoff"

_arrival_queue:   list[RunwayQueueItem] = []
_departure_queue: list[RunwayQueueItem] = []

def assign_runway_slots(capacity_per_hour: int, sim_time: datetime):
    slots = int(capacity_per_hour / 60)  # slots available this tick
    assigned = 0
    while _arrival_queue and assigned < slots:
        item = heappop(_arrival_queue)
        asyncio.create_task(assign_runway(item.flight_id, "09L", sim_time))
        assigned += 1
```

Arrivals take priority over departures during IMC/LIFR.

---

## Gate conflict resolver

When an inbound flight is delayed and its gate is needed:

```cypher
MATCH (t:Terminal {id: $terminal_id})-[:HAS_GATE]->(g:Gate)
WHERE g.status = 'available'
  AND NOT exists((g)<-[:ASSIGNED_TO]-(:Flight {status: 'boarding'}))
RETURN g.id ORDER BY g.id LIMIT 1
```

After reassigning, produce `FlightGateAssigned` with `reason: "cascade_delay_reassignment"`.

---

## Turnaround tracker

Populated at schedule seed time. Every aircraft has exactly two legs per day.

```python
# aircraft_registration → {inbound_flight_id, outbound_flight_id}
_turnaround_map: dict[str, dict] = {}

# Body-class classification is shared — import, do not redefine.
from _common.aircraft import WIDE_BODY_TYPES

async def propagate_turnaround(flight_id: str, delay_min: int,
                                depth: int, sim_time: datetime):
    if depth >= int(os.getenv("CASCADE_MAX_DEPTH", "5")):
        return
    reg = await get_aircraft_registration(flight_id)
    outbound_id = _turnaround_map.get(reg, {}).get("outbound_flight_id")
    if not outbound_id:
        return
    aircraft_type = await get_aircraft_type(flight_id)
    buffer = 45 if aircraft_type in WIDE_BODY_TYPES else 30
    propagated = max(0, delay_min - buffer)
    if propagated > 0:
        await delay_flight(outbound_id, propagated, depth + 1, sim_time)
```

---

## Kafka events produced

| Event type             | Topic            | When                            |
| ---------------------- | ---------------- | ------------------------------- |
| `FlightStatusChanged`  | `flights.events` | Any status transition           |
| `FlightGateAssigned`   | `flights.events` | Gate assignment or reassignment |
| `FlightRunwayAssigned` | `flights.events` | Runway slot allocated           |
| `FlightCancelled`      | `flights.events` | Cancellation                    |

## Kafka topics consumed

| Topic              | Event                   | Action                                  |
| ------------------ | ----------------------- | --------------------------------------- |
| `sim.clock`        | `SimClockTick`          | Advance all state machines              |
| `weather.events`   | `WeatherStateChanged`   | Update capacity, hold/release flights   |
| `incidents.events` | `IncidentCreated`       | Hold flights on affected runway or gate |
| `incidents.events` | `IncidentStatusChanged` | Resume held flights on resolve          |
| `flights.schedule` | `FlightScheduleSeeded`  | Persist new flights to Neo4j            |

---

## Mid-simulation startup & restart convergence

When this service starts (or restarts) while the simulation is already running:

1. **Rebuild in-memory state from Neo4j** — `FlightConsumerState.rebuild_from_neo4j()` loads incident-impacted runway/gate sets. Flights in transient states (`boarding`, `taxiing`, `approach`) are picked up on the next tick.
2. **Runway queue rebuilds automatically** — the queue is refilled from Neo4j on each `_on_clock_tick` by querying flights in `approach` or `departed` status.
3. **Gate conflict resolver is stateless** — no rebuild needed; it evaluates conflicts per-tick.
4. **Turnaround tracker** — in-flight turnaround timers are lost on restart, but new turnarounds are started on the next `at_gate` transition.
5. **Metric reconciliation** — `_on_clock_tick` resets all gauges (`flights_active`, `flights_delayed_current`) from Neo4j counts, so metrics self-correct within one tick.
6. **Idempotency** — duplicate `SimClockTick` events are safe; the transition evaluator is deterministic given current state.

**Tests:** `tests/integration/test_resilience.py::TestServiceRestart::test_flight_service_restart`, `TestRestartRebuild::test_flight_service_incident_impacts_rebuild`

---

## Gotchas

- **Gate occupancy is tracked via the `ASSIGNED_TO` relationship**, not `Gate.status`. Always query the relationship, not just the property.
- **Remove `ASSIGNED_TO` when a flight departs** — airborne flights have no gate.
- **State machine runs per-flight independently** — iterate all active flights on every tick.
- **`actual_time` is only set on landed/departed** — do not read it on earlier states or it will be null.
- **Boarding progress comes from passenger-service** — flight-service does not own passenger counts. Read from Neo4j via a cross-domain query or maintain a local counter updated by Kafka events.

### Testing notes

- **`evaluate_transition()` is a pure function** — it takes a flight dict, sim_time, and context flags and returns the next status or `None`. Perfect for unit testing without any infrastructure.
- **Runway queue uses `heapq`** — test ordering by verifying that emergency flights dequeue before scheduled flights regardless of enqueue order.
- **Boundary conditions to test:** boarding at exactly 95% threshold, delay at exactly 180 minutes, and time windows at exact minute boundaries (T-60, T-0, ETA-20).
