# weather-service

> 📄 **Specification:** [docs/services/weather-service/SPEC.md](../../docs/services/weather-service/SPEC.md)
> 🧠 **Skill file:** [SKILL.md](./SKILL.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8004

Runs the airport weather state machine (CAVOK → VMC → IMC → LIFR), generates synthetic METAR/TAF strings, and broadcasts runway capacity impacts to all consuming services.

---

## Architecture

```
weather-service/
├── main.py              # FastAPI app, lifespan, WebSocket endpoint
├── metrics.py           # Prometheus metric definitions
├── models/
│   └── domain.py        # Pydantic models: WeatherCurrent, history, impact
├── routers/
│   └── weather.py       # REST endpoints: current, METAR, TAF, history, impact
├── kafka/
│   ├── consumer.py      # WeatherConsumerState, tick handler, hourly FSM eval
│   └── producer.py      # Emits WeatherStateChanged, METARIssued
├── services/
│   ├── fsm.py           # 4-state weather FSM with transition matrix
│   ├── parameters.py    # WeatherParams dataclass + per-category sampling
│   ├── capacity.py      # Runway capacity calculation from weather parameters
│   └── metar.py         # METAR and TAF string generation (ICAO format)
└── db/
    └── neo4j.py         # Weather state persistence, history queries
```

## How the simulation works

1. **FSM evaluation (hourly):** on each simulated hour tick, the weather FSM samples the next state from a 4×4 transition matrix. Transitions that skip more than 1 severity step are rejected (weather improves/degrades gradually).

2. **Parameter sampling:** on each state change, meteorological parameters (visibility, wind, ceiling, temperature, QNH, phenomena) are sampled from distributions consistent with the new category.

3. **Capacity calculation:** runway capacity is computed from the weather category and wind parameters. Crosswind > 25kt and tailwind > 10kt further reduce rates.

4. **METAR/TAF generation:** realistic ICAO-format strings are generated from the sampled parameters.

### Transition matrix (per simulated hour)

| From → To | CAVOK | VMC  | IMC  | LIFR |
| --------- | ----- | ---- | ---- | ---- |
| CAVOK     | 0.85  | 0.13 | 0.02 | 0.00 |
| VMC       | 0.20  | 0.65 | 0.14 | 0.01 |
| IMC       | 0.05  | 0.30 | 0.55 | 0.10 |
| LIFR      | 0.00  | 0.05 | 0.35 | 0.60 |

### Runway capacity impact

| Category | Arrivals/hr | Departures/hr | Runways | Notes               |
| -------- | ----------- | ------------- | ------- | ------------------- |
| CAVOK    | 32          | 32            | 2       | Full operations     |
| VMC      | 28          | 28            | 2       | Near-full           |
| IMC      | 18          | 16            | 1       | ILS runway 09L only |
| LIFR     | 8           | 6             | 1       | CAT III ILS only    |

## Running

```bash
# Full stack
docker compose up --build

# Just this service
docker compose up neo4j zookeeper kafka
cd services/weather-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8004 --reload
```

API docs at **http://localhost:8004/docs**

## Key endpoints

| Method | Path                      | Description                              |
| ------ | ------------------------- | ---------------------------------------- |
| GET    | `/api/v1/weather/current` | Current conditions + runway impact       |
| GET    | `/api/v1/weather/metar`   | Raw METAR string (plain text)            |
| GET    | `/api/v1/weather/taf`     | Current TAF (plain text)                 |
| GET    | `/api/v1/weather/history` | Rolling state history (up to 48 sim-hrs) |
| GET    | `/api/v1/weather/impact`  | Operational impact summary               |
| WS     | `/ws/weather`             | Real-time weather event stream           |

## Kafka topics

| Direction | Topic            | Events                                                  |
| --------- | ---------------- | ------------------------------------------------------- |
| Consumes  | `sim.clock`      | `SimClockTick` — triggers FSM evaluation every sim-hour |
| Produces  | `weather.events` | `WeatherStateChanged` (with capacity), `METARIssued`    |

## Testing

```bash
python -m pytest tests/unit/ -k weather -v
```
