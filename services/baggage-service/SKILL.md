# SKILL — baggage-service

## Conveyor pipeline · DG detection · System failures · Offload logic

> Full specification: `docs/services/baggage-service/SPEC.md`
> Read `docs/skills/SKILL.md` and `docs/skills/python-service.SKILL.md` first.

---

## Baggage state machine

```
dropped_off
    │ induction belt (T-90min before departure)
    ▼
inducted
    │ screening unit (~2 min/item)
    ▼
screening ──── DG detected or false positive ────► flagged
    │ (clear)                                           │
    ▼                                           held_for_review
sorting                                                │
    │ make-up area assignment                ┌─────────┴──────────┐
    ▼                                   cleared (→ loaded)   rejected (→ offloaded)
loaded
    │ flight departed
    ▼
in_hold
    │ flight landed + at_gate
    ▼
arrived
    │ carousel assigned, T+20min
    ▼
on_carousel
    │ passenger collects
    ▼
collected

(flight cancelled at any point)
loaded / in_hold → offloaded → on_carousel (return to passenger)
```

---

## Zone state model

Maintain in-memory zone state — rebuilt from Neo4j on startup:

```python
from dataclasses import dataclass

@dataclass
class ZoneState:
    zone_id: str
    status: str        # "normal" | "degraded" | "offline"
    items: int         # current item count in this zone
    throughput_per_hr: int

_zones: dict[str, ZoneState] = {}

# Zone throughput capacities (from SPEC.md)
ZONE_THROUGHPUT = {
    "induction-A": 600, "induction-B": 600, "induction-C": 600,
    "screening-unit-1": 300, "screening-unit-2": 300,
    "screening-unit-3": 300, "screening-unit-4": 300,
    "screening-unit-5": 300, "screening-unit-6": 300,
    "sorting-matrix": 1800,
    **{f"make-up-{t}-{n}": 150 for t in "ABC" for n in range(1, 6)},
    **{f"arrival-belt-{n}": 200 for n in range(1, 7)},
}
```

On each SimClockTick, drain each zone:

```python
def drain_zone(zone: ZoneState) -> int:
    if zone.status == "offline":
        return 0
    capacity = zone.throughput_per_hr
    if zone.status == "degraded":
        capacity = int(capacity * 0.5)
    items_to_advance = min(zone.items, int(capacity / 60))
    zone.items -= items_to_advance
    return items_to_advance
```

---

## DG detection model

```python
import random

DETECTION_RATES = {"2": 0.88, "3": 0.91, "8": 0.95, "9": 0.72}
FALSE_POSITIVE_RATE = float(os.getenv("DG_FALSE_POSITIVE_RATE", "0.003"))

def screen_item(baggage_id: str, is_dg: bool,
                dg_class: str | None) -> str:
    """Returns: 'clear' | 'flagged' | 'false_positive'"""
    if is_dg and dg_class:
        rate = DETECTION_RATES.get(dg_class, 0.80)
        if random.random() < rate:
            return "flagged"
    # False positive on clean items
    if random.random() < FALSE_POSITIVE_RATE:
        return "false_positive"
    return "clear"
```

When result is `"flagged"` and `dg_class == "3"` (flammable liquid):

- Emit `BaggageFlagged` immediately
- Probabilistically emit `InjectIncident` (baggage_fire) to `incidents.inject`
  if the item is already in a make-up zone (i.e. `status == "sorting"` or `"loaded"`)

---

## Flight cancellation → offload

```python
async def offload_flight_baggage(flight_id: str, sim_time: datetime):
    # Find all baggage loaded on this flight
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight {id: $fid}) "
            "WHERE b.status IN ['loaded', 'in_hold'] "
            "RETURN b.id AS bid, b.tag AS tag",
            fid=flight_id
        )
        bags = [{"id": r["bid"], "tag": r["tag"]}
                async for r in result]

    # Assign a return carousel (round-robin 1-6)
    carousel = (hash(flight_id) % 6) + 1

    for bag in bags:
        await update_baggage_status(
            bag["id"], "offloaded",
            scan_zone=f"arrival-belt-{carousel}",
            sim_time=sim_time
        )
        await produce_baggage_status_changed(
            bag["id"], bag["tag"],
            previous="loaded", new="offloaded",
            sim_time=sim_time
        )
```

---

## System failure impact

```python
FAILURE_IMPACT = {
    "conveyor-sorting":       ["sorting-matrix"],
    "conveyor-induction-A":   ["induction-A"],
    "conveyor-induction-B":   ["induction-B"],
    "conveyor-induction-C":   ["induction-C"],
    "power-A":                ["induction-A"] + [f"screening-unit-{n}" for n in (1, 2)],
    "power-B":                ["induction-B"] + [f"screening-unit-{n}" for n in (3, 4)],
    "power-C":                ["induction-C"] + [f"screening-unit-{n}" for n in (5, 6)],
    "screening-unit-1":       ["screening-unit-1"],
    # ... etc
}

async def on_incident_created(payload: dict, sim_time: datetime):
    if payload.get("type") != "system_failure":
        return
    location = payload.get("location", "")
    affected = FAILURE_IMPACT.get(location, [])
    for zone_id in affected:
        if zone_id in _zones:
            _zones[zone_id].status = "offline"
```

---

## Kafka produced events

| Event                  | Trigger                                    |
| ---------------------- | ------------------------------------------ |
| `BaggageStatusChanged` | Any status transition                      |
| `BaggageFlagged`       | DG detected or false positive at screening |

## Kafka topics consumed

| Topic              | Event                              | Action                                  |
| ------------------ | ---------------------------------- | --------------------------------------- |
| `sim.clock`        | `SimClockTick`                     | Drain conveyor zones                    |
| `flights.events`   | `FlightStatusChanged` (delayed)    | Hold make-up bags                       |
| `flights.events`   | `FlightCancelled`                  | Offload all loaded bags                 |
| `incidents.events` | `IncidentCreated` (system_failure) | Set affected zones to offline           |
| `incidents.events` | `IncidentStatusChanged` (resolved) | Restore zones to normal                 |
| `incidents.events` | `IncidentCreated` (baggage_fire)   | Flag all items in affected make-up zone |

---

## Gotchas

- **Scan history is append-only.** Never overwrite the last scan — add a new record each time. Use a `scans` list property on the Baggage node or a separate `BaggageScan` node pattern.
- **Zone queues back up upstream.** When `sorting-matrix` is full, items in `screening` cannot advance. Model this as `items_to_advance = min(zone.items, downstream_capacity)`.
- **`in_hold` bags cannot be offloaded mid-flight.** Only offload when `flight.status` transitions to `cancelled`. If flight is `airborne`, bags stay in `in_hold` until landing, then normal arrival flow.
- **False positives still produce `BaggageFlagged`.** The distinction (`flag_reason: "false_positive"` vs `"dangerous_goods_detected"`) is in the payload — both go through the same review process.
- **DG class 3 + make-up zone = potential fire.** Only trigger the probabilistic fire if the item is in `sorting` or `loaded` status, not just any DG class 3 item anywhere in the system.
