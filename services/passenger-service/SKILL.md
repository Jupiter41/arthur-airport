# SKILL — passenger-service

## State machine · Queue model · Forecasting · Connection risk

> Full specification: `docs/services/passenger-service/SPEC.md`
> Read `docs/skills/SKILL.md`, `docs/skills/python-service.SKILL.md`, and `docs/skills/forecasting.SKILL.md` first.

---

## State machine (departure flow)

```
checked_in
  │ trigger: sim_time >= flight.scheduled_time - 45min (check-in cutoff)
  ▼
security_queue
  │ trigger: per-tick queue drain at effective_throughput rate
  ▼
airside
  │ trigger: sim_time >= gate_open_time (T-30min) + sampled dwell_minutes
  ▼
at_gate
  │ trigger: boarding call at T-20min
  ▼
boarded  ← progressive, 10 pax/min boarding rate
```

## State machine (arrival flow)

```
airborne → deplaning (flight landed + taxiing)
         → baggage_claim (T+15min after at_gate)
         → departed_airport (baggage collected OR T+45min timeout)
```

Special assistance passengers (`special_assistance: true`) skip the main security queue
entirely. They use a dedicated lane: fixed 20 pax/hr, always open, immune to congestion.

---

## Security throughput model

```python
def effective_throughput(open_lanes: int,
                          actual_queue: int,
                          forecast_queue: int) -> float:
    base = open_lanes * 180.0  # pax/hr per lane
    # Peak slowdown: if actual > 130% of forecast, throughput degrades
    if forecast_queue > 0 and actual_queue > forecast_queue * 1.3:
        slowdown = min(1.0, forecast_queue / actual_queue)
        return base * slowdown
    return base

def queue_wait_minutes(queue_depth: int, throughput_per_hr: float) -> float:
    if throughput_per_hr <= 0:
        return 999.0
    return (queue_depth / throughput_per_hr) * 60.0

def items_to_drain_this_tick(throughput_per_hr: float) -> int:
    # 1 tick = 1 sim-minute
    return max(0, int(throughput_per_hr / 60))
```

---

## Congestion detection

```python
_ticks_over_threshold: dict[str, int] = {"A": 0, "B": 0, "C": 0}
THRESHOLD_MIN  = int(os.getenv("SECURITY_CONGESTION_WAIT_THRESHOLD_MIN", "20"))
CONSECUTIVE    = int(os.getenv("SECURITY_CONGESTION_CONSECUTIVE_TICKS", "5"))

def check_congestion(terminal: str, wait_minutes: float) -> bool:
    if wait_minutes > THRESHOLD_MIN:
        _ticks_over_threshold[terminal] += 1
    else:
        _ticks_over_threshold[terminal] = 0

    if _ticks_over_threshold[terminal] >= CONSECUTIVE:
        _ticks_over_threshold[terminal] = 0  # reset after firing
        return True
    return False

# In on_clock_tick:
for terminal in ("A", "B", "C"):
    wait = queue_wait_minutes(_queue_depth[terminal],
                               effective_throughput(
                                   _lanes_open[terminal],
                                   _queue_depth[terminal],
                                   predict(terminal, features) or 0
                               ))
    if check_congestion(terminal, wait):
        await produce_congestion_event(terminal, wait, sim_time)
```

---

## Connection risk logic

```python
MCT_MINUTES = int(os.getenv("MIN_CONNECTION_TIME_MIN", "45"))

def connection_risk(inbound_delay_min: int,
                    time_to_connection_min: int) -> str:
    if time_to_connection_min < MCT_MINUTES:
        return "missed"
    if (inbound_delay_min > 30
            or time_to_connection_min < MCT_MINUTES + 15):
        return "at_risk"
    if inbound_delay_min > 15:
        return "watch"
    return "ok"
```

Run this check on every `FlightStatusChanged` for delayed flights.
Emit `PassengerAlert (connection_at_risk)` on transition to `at_risk`.
Emit `PassengerAlert (connection_missed)` + set `passenger.status = missed_connection` on `missed`.

---

## Zone density tracking (hot path — do NOT query Neo4j per tick)

```python
from collections import defaultdict

_zone_density: dict[str, int] = defaultdict(int)

def move_passenger(old_zone: str | None, new_zone: str):
    if old_zone:
        _zone_density[old_zone] = max(0, _zone_density[old_zone] - 1)
    _zone_density[new_zone] += 1

# Rebuild from Neo4j on service startup:
async def rebuild_zone_density():
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (p:Passenger) WHERE p.location_zone IS NOT NULL "
            "RETURN p.location_zone AS zone, count(p) AS n"
        )
        async for record in result:
            _zone_density[record["zone"]] = record["n"]
```

---

## Dwell time sampling

```python
import random

def sample_dwell_minutes() -> int:
    raw = random.gauss(mu=25, sigma=12)
    return int(max(5, min(90, raw)))
```

Called once per passenger when they transition to `airside`. Stored on the passenger node
as `dwell_minutes`. Do not re-sample on subsequent ticks.

---

## Kafka produced events

| Event                        | Trigger                                                  |
| ---------------------------- | -------------------------------------------------------- |
| `PassengerStatusChanged`     | Any status or location_zone transition                   |
| `PassengerAlert`             | Gate change, connection risk level change, zone lockdown |
| `SecurityCongestionDetected` | wait > 20 sim-min for 5 consecutive ticks                |

## Kafka topics consumed

| Topic              | Event                                     | Action                                                 |
| ------------------ | ----------------------------------------- | ------------------------------------------------------ |
| `sim.clock`        | `SimClockTick`                            | Drain queues, advance state machines, check congestion |
| `flights.events`   | `FlightStatusChanged`                     | Detect delays, update connection risk                  |
| `flights.events`   | `FlightGateAssigned`                      | Issue gate change PassengerAlert to affected pax       |
| `flights.events`   | `FlightCancelled`                         | Mark all on-flight pax as disrupted                    |
| `incidents.events` | `IncidentCreated`                         | Security breach → freeze zone queues                   |
| `incidents.events` | `IncidentStatusChanged`                   | Resume frozen zones on resolve                         |
| `baggage.events`   | `BaggageStatusChanged` (status=collected) | Advance arrival pax to departed_airport                |

---

## Gotchas

- **Dwell time is per-passenger, not per-flight.** Sample individually for each passenger — do not use a shared value for all passengers on the same flight.
- **Check-in is batched.** All passengers on a flight move to `security_queue` together at T-45 min regardless of individual check-in time.
- **Forecast model needs `weather_category`.** Cache the latest value from `weather.events`. Never call weather-service over HTTP.
- **`adjacent_terminal_congested`** is derived from your own `_zone_density` state — not an external call.
- **SA lane capacity is fixed at 20 pax/hr.** It is never affected by the slowdown factor and never contributes to main queue depth.
- **On `security_breach` incident**: freeze main lanes to 0 throughput. SA lane drops to 10 pax/hr but stays open.
