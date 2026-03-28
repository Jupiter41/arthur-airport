# sim-orchestrator

> 📄 **Specification:** [docs/services/sim-orchestrator/SPEC.md](../../docs/services/sim-orchestrator/SPEC.md)
> 🧠 **Skill file:** [SKILL.md](./SKILL.md)

**Language:** Python 3.11 · **Framework:** FastAPI + asyncio · **Port:** 8006

The conductor of the entire digital twin. Drives the virtual simulation clock, seeds all airport data on startup, and coordinates probabilistic event injection. **Start this last** — it waits for all domain services to be healthy before beginning.

---

## Architecture

```
sim-orchestrator/
├── main.py              # FastAPI app, lifespan, hour/day callbacks
├── metrics.py           # Prometheus: tick latency, events produced, speed
├── routers/
│   └── sim.py           # Control API: status, speed, pause, resume, reset, inject
├── kafka/
│   └── producer.py      # Emits SimClockTick, FlightScheduleSeeded, InjectIncident
├── services/
│   ├── clock.py         # Virtual clock loop: async tick emission at configurable speed
│   ├── schedule.py      # Flight schedule: bimodal distribution + paired arrivals
│   ├── passengers.py    # Passenger generation: names, PNRs, connections, special assist
│   ├── baggage.py       # Baggage generation: weight, DG flags, per-passenger counts
│   ├── seeder.py        # Day seeding orchestration (idempotent)
│   ├── injector.py      # Probabilistic incident evaluation with suppression window
│   └── fixtures.py      # Fixture loading/caching (airlines, destinations, aircraft)
├── db/
│   ├── neo4j.py         # Driver init, constraints/indexes
│   └── seed.py          # Airport structure seed (terminals, gates, runways)
└── models/
    └── __init__.py
```

## How the simulation works

### 1. Virtual clock

The orchestrator runs an async loop that advances `sim_time` by 1 minute per iteration and emits a `SimClockTick` to the `sim.clock` Kafka topic. All services consume this topic to drive their state machines.

```
real elapsed time × speed_multiplier = simulated elapsed time
```

| Speed preset | Multiplier | 1 real second =  |
| ------------ | ---------- | ---------------- |
| Real time    | 1×         | 1 sim second     |
| Fast         | 10×        | 10 sim seconds   |
| **Default**  | **60×**    | **1 sim minute** |
| Compressed   | 600×       | 10 sim minutes   |
| Fast-forward | 3600×      | 1 sim hour       |

### 2. Daily seeding

At startup (and at 23:30 each sim-day), the orchestrator generates:

- **420 flights** (210 departures + 210 arrivals) with bimodal departure distribution (peaks at 07:30 and 17:30)
- **~30,000 passengers** (load factor ~ Beta(8,2) ≈ 80%)
- **~36,000 baggage items** (Poisson λ=1.2 bags/passenger, weight ~ Normal(18kg, 4kg))

Passengers include 20% connecting and 5% special assistance. Baggage includes 0.2% dangerous goods.

### 3. Probabilistic incident injection

Each simulated hour, the injector evaluates per-event-type probabilities and rolls the dice:

| Event type       | Base probability/hr | Severity range  |
| ---------------- | ------------------- | --------------- |
| runway_incursion | 0.005               | high–critical   |
| baggage_fire     | 0.008               | medium–high     |
| security_breach  | 0.010               | medium–critical |
| system_failure   | 0.015               | low–high        |

Modifiers: ×1.8 during peak hours (07–09, 17–19), ×0.3 suppression if an incident occurred < 2 hours ago.

## Running

```bash
# Full stack (sim-orchestrator waits for all services)
docker compose up --build

# Just the orchestrator (requires Neo4j + Kafka + domain services)
cd services/sim-orchestrator
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8006 --reload
```

API docs at **http://localhost:8006/docs**

## Key endpoints

| Method | Path                   | Description                                      |
| ------ | ---------------------- | ------------------------------------------------ |
| GET    | `/api/v1/sim/status`   | Full simulation state (time, speed, day, events) |
| PATCH  | `/api/v1/sim/speed`    | Change speed multiplier at runtime               |
| POST   | `/api/v1/sim/pause`    | Pause clock (no ticks emitted)                   |
| POST   | `/api/v1/sim/resume`   | Resume after pause                               |
| POST   | `/api/v1/sim/reset`    | Full reset: wipe Neo4j, reseed day 1             |
| POST   | `/api/v1/sim/inject`   | Manually inject a hazardous event                |
| GET    | `/api/v1/sim/schedule` | Current day's flight schedule                    |
| GET    | `/api/v1/sim/metrics`  | Internal metrics (tick latency, events count)    |

### Scenario API

| Method | Path                             | Description                                      |
| ------ | -------------------------------- | ------------------------------------------------ |
| GET    | `/api/v1/scenarios`             | List scenarios with `is_base` metadata           |
| GET    | `/api/v1/scenarios/{name}`      | Fetch one scenario definition                     |
| POST   | `/api/v1/scenarios`             | Create a new custom scenario                      |
| PUT    | `/api/v1/scenarios/{name}`      | Update a custom scenario (base scenarios blocked) |
| DELETE | `/api/v1/scenarios/{name}`      | Delete a custom scenario                          |
| POST   | `/api/v1/scenarios/{name}/fork` | Fork any scenario into a new custom one           |
| POST   | `/api/v1/scenarios/{name}/run`  | Run one scenario                                  |

## Kafka topics

| Direction | Topic              | Events                                           |
| --------- | ------------------ | ------------------------------------------------ |
| Produces  | `sim.clock`        | `SimClockTick` every sim-minute                  |
| Produces  | `flights.schedule` | `FlightScheduleSeeded` on each day seed          |
| Produces  | `incidents.inject` | `InjectIncident` from probabilistic engine       |
| Produces  | `weather.events`   | `WeatherStateChanged` (initial CAVOK on startup) |

## Testing

```bash
python -m pytest tests/unit/ -k sim -v
```

## Environment variables

| Variable               | Default               | Description             |
| ---------------------- | --------------------- | ----------------------- |
| `SIM_START_TIME`       | `2024-06-15T06:00:00` | Simulation start time   |
| `SIM_SPEED_MULTIPLIER` | `60`                  | Default speed           |
| `DAILY_FLIGHT_TARGET`  | `420`                 | Total daily movements   |
| `AIRPORT_CONFIG_PATH`  | `/app/config/airport.yaml` | Airport config file path |
| `NEO4J_URI`            | `bolt://neo4j:7687`   | Neo4j connection        |
| `KAFKA_BROKERS`        | `kafka:9092`          | Kafka bootstrap servers |

## Airport Config Workflow

The orchestrator reads airport settings from `config/airport.yaml` (mounted in Docker as `/app/config/airport.yaml`).

Validate config before startup:

```bash
python scripts/helper_validate_airport_config.py --path config/airport.yaml
```

Full customization guide: [HOW_TO_CREATE_AIRPORT.md](../../HOW_TO_CREATE_AIRPORT.md)
