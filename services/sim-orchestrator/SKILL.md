# SKILL — sim-orchestrator

## Startup sequence · Clock loop · Schedule seeding · Probabilistic injection

> Full specification: `docs/services/sim-orchestrator/SPEC.md`
> Read `docs/skills/SKILL.md`, `docs/skills/simulation.SKILL.md`, and `docs/skills/kafka.SKILL.md` first.

---

## Startup sequence (order is strict)

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Wait for Neo4j
    await wait_for_neo4j(max_attempts=12, delay_s=5)

    # 2. Wait for Kafka
    await wait_for_kafka(max_attempts=12, delay_s=5)

    # 3. Seed airport structure if not already present
    if not await airport_exists():
        await seed_airport_structure()

    # 4. Seed Day 1 schedule + passengers + baggage
    await seed_day(sim_day=1)

    # 5. Set initial weather
    await emit_initial_weather()

    # 6. Start clock loop as background task
    asyncio.create_task(run_clock_loop())

    yield
    _running = False
```

Do not start the clock until ALL of these steps complete. If Neo4j or Kafka are not ready,
retry with exponential backoff — do not crash on first failure.

---

## Clock loop

```python
import asyncio
from datetime import datetime, timedelta

_running:          bool     = True
_paused:           bool     = False
_sim_time:         datetime = SIM_START_TIME
_speed_multiplier: int      = 60
_sim_day:          int      = 1
_tick_number:      int      = 0

SIM_START_TIME = datetime.fromisoformat(
    os.getenv("SIM_START_TIME", "2024-06-15T06:00:00")
)

async def run_clock_loop():
    global _sim_time, _sim_day, _tick_number

    while _running:
        if not _paused:
            _sim_time    += timedelta(minutes=1)
            _tick_number += 1

            await emit_clock_tick()

            # Hourly: evaluate probabilistic event injection
            if _sim_time.minute == 0:
                await evaluate_probabilistic_events()

            # Daily: seed next day at 23:30 sim time
            if _sim_time.hour == 23 and _sim_time.minute == 30:
                await seed_day(sim_day=_sim_day + 1)

            # Day boundary
            prev = _sim_time - timedelta(minutes=1)
            if _sim_time.date() != prev.date():
                _sim_day += 1

        sleep_s = 60.0 / _speed_multiplier
        await asyncio.sleep(sleep_s)
```

---

## SimClockTick payload

```python
async def emit_clock_tick():
    payload = {
        "sim_time":         _sim_time.isoformat(),
        "real_time":        datetime.utcnow().isoformat(),
        "speed_multiplier": _speed_multiplier,
        "tick_number":      _tick_number,
        "day_of_sim":       _sim_day,
    }
    produce(
        topic="sim.clock",
        key="tick",
        event_type="SimClockTick",
        sim_time=_sim_time,
        payload=payload,
    )
```

---

## Airport structure seed (run once)

```python
TERMINALS = ["A", "B", "C"]
GATES_PER_TERMINAL = 14

async def seed_airport_structure():
    async with get_driver().session() as session:
        # Airport node
        await session.run(
            "MERGE (a:Airport {icao: 'KART'}) "
            "SET a.iata='ART', a.name='Arthur International Airport', "
            "    a.total_gates=42",
        )
        # Terminals + gates
        for t in TERMINALS:
            await session.run(
                "MERGE (t:Terminal {id: $tid}) "
                "SET t.name=$name, t.gate_count=$gc, t.open=true "
                "WITH t MATCH (a:Airport {icao:'KART'}) MERGE (a)-[:HAS_TERMINAL]->(t)",
                tid=f"T-{t}", name=f"Terminal {t}", gc=GATES_PER_TERMINAL,
            )
            for n in range(1, GATES_PER_TERMINAL + 1):
                gate_id = f"{t}{n:02d}"
                await session.run(
                    "MERGE (g:Gate {id: $gid}) "
                    "SET g.terminal_id=$tid, g.status='available', g.pier=$pier "
                    "WITH g MATCH (t:Terminal {id:$tid}) MERGE (t)-[:HAS_GATE]->(g)",
                    gid=gate_id, tid=f"T-{t}", pier=t,
                )
        # Runways
        for rwy in ["09L", "27R", "09R", "27L"]:
            await session.run(
                "MERGE (r:Runway {id: $id}) "
                "SET r.status='open', r.current_use='idle', r.ils=($id IN ['09L','27R']) "
                "WITH r MATCH (a:Airport {icao:'KART'}) MERGE (a)-[:HAS_RUNWAY]->(r)",
                id=rwy,
            )
```

---

## Schedule generation (bimodal distribution)

```python
import numpy as np
from datetime import date, time

def sample_departure_slots(n: int, sim_date: date) -> list[datetime]:
    """Sample n departure times from a bimodal distribution with peaks at 07:30 and 17:30."""
    peak1 = np.random.normal(loc=7.5,  scale=1.5, size=n // 2)
    peak2 = np.random.normal(loc=17.5, scale=1.5, size=n - n // 2)
    hours = np.concatenate([peak1, peak2])
    hours = np.clip(hours, 5.0, 23.0)
    slots = []
    for h in sorted(hours):
        hour = int(h)
        minute = int((h - hour) * 60)
        # Round to nearest 5 minutes
        minute = round(minute / 5) * 5
        if minute == 60:
            hour += 1
            minute = 0
        slots.append(datetime.combine(sim_date, time(hour=min(hour, 23), minute=minute)))
    return slots
```

After generating departure slots, for each departure generate a paired arrival:

- Same aircraft registration
- Arrival time = departure time - 90 minutes (turnaround buffer)
- Origin = this departure's destination (previous leg)

---

## Passenger generation per flight

```python
from scipy.stats import beta as beta_dist

LOAD_FACTOR_ALPHA = 8
LOAD_FACTOR_BETA  = 2  # mean ~0.80

def generate_passengers(flight: dict, fixtures: dict) -> list[dict]:
    seat_cap    = flight["seat_capacity"]
    load_factor = beta_dist.rvs(LOAD_FACTOR_ALPHA, LOAD_FACTOR_BETA)
    pax_count   = round(seat_cap * load_factor)

    passengers = []
    for i in range(pax_count):
        has_bags = True  # assign baggage count separately
        pax = {
            "id": str(uuid4()),
            "name": f"{random.choice(fixtures['first_names'])} "
                    f"{random.choice(fixtures['surnames'])}",
            "pnr": generate_pnr(),
            "nationality": weighted_choice(fixtures["nationalities"]),
            "flight_id": flight["id"],
            "status": "checked_in",
            "connection": random.random() < 0.20,
            "special_assistance": random.random() < 0.05,
            "seat": generate_seat(seat_cap, i),
        }
        passengers.append(pax)
    return passengers

def generate_pnr() -> str:
    import string
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=6))
```

---

## Probabilistic event injection (per simulated hour)

```python
BASE_PROBABILITIES = {
    "runway_incursion": 0.005,
    "baggage_fire":     0.008,
    "security_breach":  0.010,
    "system_failure":   0.015,
}

PEAK_HOURS = {7, 8, 9, 17, 18, 19}

async def evaluate_probabilistic_events():
    context = await build_injection_context()
    for event_type, base_prob in BASE_PROBABILITIES.items():
        prob = base_prob
        if _sim_time.hour in PEAK_HOURS:
            prob *= 1.8
        if context["weather_category"] in ("IMC", "LIFR"):
            if event_type == "runway_incursion":
                prob *= 2.0
        if context["baggage_throughput_pct"] > 0.80:
            if event_type in ("baggage_fire", "system_failure"):
                prob *= 1.5
        if context["recent_incident"]:
            prob *= 0.3  # suppression window

        if random.random() < prob:
            location = pick_location(event_type)
            produce(
                topic="incidents.inject",
                key=event_type,
                event_type="InjectIncident",
                sim_time=_sim_time,
                payload={
                    "type": event_type,
                    "severity": pick_severity(event_type),
                    "location": location,
                    "trigger": "probabilistic",
                },
            )
```

---

## Kafka produced events

| Event                  | Topic              | When                        |
| ---------------------- | ------------------ | --------------------------- |
| `SimClockTick`         | `sim.clock`        | Every simulated minute      |
| `FlightScheduleSeeded` | `flights.schedule` | On day seed                 |
| `InjectIncident`       | `incidents.inject` | Probabilistic event trigger |

---

## Mid-simulation startup & restart convergence

When this service starts (or restarts) while the simulation is already running:

1. **Resume sim_time from Neo4j** — on startup, the orchestrator reads the last persisted `sim_time` from the `SimState` node. The clock loop resumes from that point.
2. **Speed / pause state** — `sim_speed_multiplier` and `sim_paused` are persisted in Neo4j and restored on restart.
3. **Day boundary** — `sim_day_number` is recalculated from the current `sim_time`.
4. **Event injection** — probabilistic event injection resumes based on sim_time; some events may have been skipped during downtime, but this is acceptable (they are probabilistic).
5. **No catch-up ticking** — the orchestrator does NOT fast-forward through missed ticks. It resumes at the stored sim_time and continues forward.
6. **Service health check** — before resuming the clock, the orchestrator checks `/ready` on all domain services.

**Tests:** `tests/integration/test_resilience.py::TestAllServicesRestart::test_full_restart`

---

## Gotchas

- **Wait for ALL domain services to be healthy before starting the clock.** Check `/ready` on each service with a timeout before calling `asyncio.create_task(run_clock_loop())`.
- **Seed Day N+1 at 23:30 sim-time**, not at midnight. Flight-service needs 30 sim-minutes to load the new schedule before the day boundary.
- **Probabilistic events are evaluated on hour boundary only** (`sim_time.minute == 0`). Never evaluate mid-tick.
- **Speed change is safe mid-loop** — just update `_speed_multiplier`. The new sleep duration applies on the next iteration.
- **`POST /sim/reset` is destructive** — wipe all Neo4j data with `MATCH (n) DETACH DELETE n`, reset `_sim_time` and `_sim_day`, then re-run the full startup sequence. Require `{"confirm": true}` in the request body.
- **`numpy` and `scipy` are needed for schedule generation** — add to requirements.txt: `numpy>=1.26`, `scipy>=1.13`.
