# SKILL — Simulation engine
## Clock contract · State machines · Cascade rules · Fixtures

---

## The clock contract

The sim-orchestrator emits one `SimClockTick` per simulated minute on `sim.clock`.

```json
{
  "event_type": "SimClockTick",
  "payload": {
    "sim_time": "2024-06-15T14:32:00Z",
    "real_time": "2024-06-15T10:15:03Z",
    "speed_multiplier": 60,
    "tick_number": 512,
    "day_of_sim": 1
  }
}
```

**Every service reacts to this tick.** On each tick, each service:
1. Checks if any of its entities have a time-based transition due
2. Executes the transition if so
3. Produces the appropriate Kafka event

### Never use wall-clock time

```python
# WRONG
from datetime import datetime
now = datetime.now()

# RIGHT
# extract from the SimClockTick payload
sim_time = datetime.fromisoformat(payload["sim_time"])
```

### Tracking sim_time in a service

Each service keeps a module-level variable updated on every tick:

```python
_current_sim_time: datetime | None = None

async def on_clock_tick(payload: dict, sim_time: datetime):
    global _current_sim_time
    _current_sim_time = sim_time
    await process_due_transitions(sim_time)

def get_sim_time() -> datetime:
    if _current_sim_time is None:
        raise RuntimeError("Sim clock not yet received")
    return _current_sim_time
```

---

## Flight state machine timing

All transitions are relative to the flight's `estimated_time` (ETD for departures, ETA for arrivals).

| Transition | Trigger condition |
|---|---|
| `scheduled` → `boarding` | `sim_time >= estimated_time - 60min` |
| `boarding` → `departed` | `sim_time >= estimated_time` AND boarding ≥ 95% |
| `departed` → `airborne` | `sim_time >= actual_departure + 5min` |
| `airborne` → `approach` | `sim_time >= estimated_arrival - 20min` |
| `approach` → `landed` | `sim_time >= estimated_arrival` AND runway available |
| `landed` → `taxiing` | `sim_time >= actual_arrival + 2min` |
| `taxiing` → `at_gate` | `sim_time >= actual_arrival + 8min` AND gate available |

A flight becomes `delayed` when it cannot transition on time due to weather, incident, or hold.

---

## Delay propagation rules

When an inbound flight is delayed:

```python
def propagate_turnaround_delay(inbound_delay_min: int,
                                aircraft_type: str) -> int:
    buffer = 45 if aircraft_type in WIDE_BODY_TYPES else 30
    propagated = max(0, inbound_delay_min - buffer)
    return propagated

WIDE_BODY_TYPES = {"B77W", "A333", "A332", "B748", "A380"}
```

Propagation stops when:
- `propagated_delay == 0` (absorbed by turnaround buffer)
- `cascade_depth >= CASCADE_MAX_DEPTH` (default: 5)

---

## Weather state machine

States: `CAVOK` → `VMC` → `IMC` → `LIFR`

Evaluated once per simulated hour. Jumps of more than one severity level are rejected:
- `LIFR` cannot jump directly to `CAVOK` or `VMC`
- `CAVOK` cannot jump directly to `LIFR`

Runway capacity by state:

```python
RUNWAY_CAPACITY = {
    "CAVOK": {"arrival": 32, "departure": 32, "runways": 2},
    "VMC":   {"arrival": 28, "departure": 28, "runways": 2},
    "IMC":   {"arrival": 18, "departure": 16, "runways": 1},
    "LIFR":  {"arrival": 8,  "departure": 6,  "runways": 1},
}
```

Wind reductions (applied on top of category capacity):

```python
def apply_wind_reduction(base_rate: int, crosswind_kt: int,
                          tailwind_kt: int) -> int:
    rate = base_rate
    if crosswind_kt > 35:
        rate = int(rate * 0.60)
    elif crosswind_kt > 25:
        rate = int(rate * 0.85)
    if tailwind_kt > 10:
        rate = int(rate * 0.70)
    return rate
```

---

## Incident TTR (time-to-resolve)

Each incident type has a TTR range in simulated minutes. The orchestrator samples from it on
incident creation:

```python
import random

TTR_RANGES = {
    "runway_incursion": (15, 45),
    "baggage_fire":     (20, 60),
    "security_breach":  (30, 90),
    "system_failure":   (10, 120),
    "severe_weather":   None,  # resolved by weather FSM
}

def sample_ttr(incident_type: str) -> int | None:
    r = TTR_RANGES.get(incident_type)
    return random.randint(*r) if r else None
```

The incident service counts down TTR on each `SimClockTick` and auto-resolves when it reaches 0.

---

## Probabilistic event injection

Evaluated once per simulated hour:

```python
BASE_PROBABILITIES = {
    "runway_incursion": 0.005,
    "baggage_fire":     0.008,
    "security_breach":  0.010,
    "system_failure":   0.015,
}

PEAK_HOURS = {7, 8, 9, 17, 18, 19}  # simulated hours

def effective_probability(event_type: str, context: dict) -> float:
    prob = BASE_PROBABILITIES[event_type]
    if context["sim_hour"] in PEAK_HOURS:
        prob *= 1.8
    if context["weather_category"] in ("IMC", "LIFR"):
        if event_type == "runway_incursion":
            prob *= 2.0
    if context["baggage_throughput_pct"] > 0.80:
        if event_type in ("baggage_fire", "system_failure"):
            prob *= 1.5
    if context["recent_incident"]:
        prob *= 0.3  # suppression window
    return prob
```

---

## Fixtures format

Fixtures live in `services/sim-orchestrator/fixtures/`.

### `airlines.json`
```json
[
  { "code": "AX", "name": "Artex Airways", "hub": "ART",
    "market_share": 0.22, "preferred_terminal": "B" }
]
```

### `events.json`
```json
{
  "events": [
    { "name": "ART City Marathon", "sim_days": [4, 5],
      "pax_multiplier": 1.18, "terminals_affected": ["A","B"] }
  ]
}
```

### `aircraft_types.json`
```json
[
  { "code": "B738", "name": "Boeing 737-800",
    "seat_capacity": 189, "wide_body": false,
    "turnaround_buffer_min": 30 },
  { "code": "B77W", "name": "Boeing 777-300ER",
    "seat_capacity": 396, "wide_body": true,
    "turnaround_buffer_min": 45 }
]
```

---

## Day boundary

At `sim_time == 23:30` the orchestrator:
1. Generates the next day's flight schedule
2. Seeds passengers and baggage for all next-day flights into Neo4j
3. Emits `FlightScheduleSeeded` to `flights.schedule`

This happens 30 sim-minutes before midnight so flight-service always has the next day ready.
