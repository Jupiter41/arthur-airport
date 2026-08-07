# flight-service

> 📄 **Specification:** [docs/services/flight-service/SPEC.md](../../docs/services/flight-service/SPEC.md)
> 🧠 **Skill file:** [SKILL.md](./SKILL.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8001

Owns the full lifecycle of every flight movement at KART — from schedule ingestion through gate assignment, runway allocation, airborne state, and arrival/departure completion.

---

## Architecture

```
flight-service/
├── main.py              # FastAPI app, lifespan, WebSocket endpoint
├── metrics.py           # Prometheus metric definitions
├── models/
│   └── domain.py        # Pydantic models: FlightSummary, FlightDetail, enums
├── routers/
│   └── flights.py       # REST endpoints: list, detail, cascade, hold/release
├── kafka/
│   ├── consumer.py      # FlightConsumerState, clock/weather/incident handlers
│   └── producer.py      # Emits FlightStatusChanged, FlightGateAssigned, etc.
├── services/
│   ├── state_machine.py # 9-state FSM: pure logic, no I/O
│   ├── runway_queue.py  # Priority heap for runway slot scheduling
│   ├── gate_resolver.py # Gate conflict detection and fallback reassignment
│   └── turnaround.py    # Delay propagation to outbound rotation flights
└── db/
    └── neo4j.py         # All Cypher queries: flights, gates, runways
```

## Responsibilities

- **Flight state machine:** `scheduled → boarding → departed → airborne → approach → landed → taxiing → at_gate` (9 states, 2 terminal: `at_gate`, `cancelled`)
- **Runway queue management:** priority heap with weather-dependent capacity (32/hr CAVOK → 8/hr LIFR)
- **Gate conflict resolution:** when a delay causes overlapping gate use, finds the nearest available gate in the same terminal (fallback to other terminals)
- **Turnaround delay propagation:** inbound arrival delay cascades to the paired outbound departure after subtracting the turnaround buffer (30 min narrow-body, 45 min wide-body), max depth 5
- **Reacts to weather and incident events** from Kafka to adjust capacity and hold flights

## Running

```bash
# Full stack (recommended)
docker compose up --build

# Just this service (requires Neo4j + Kafka running)
docker compose up neo4j zookeeper kafka
cd services/flight-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

API docs available at **http://localhost:8001/docs** once running.

## Key endpoints

| Method | Path                           | Description                                                 |
| ------ | ------------------------------ | ----------------------------------------------------------- |
| GET    | `/api/v1/flights`              | List all flights (filterable by status, direction, airline) |
| GET    | `/api/v1/flights/{id}`         | Flight detail + passenger counts + baggage counts           |
| GET    | `/api/v1/flights/{id}/cascade` | Cascade tree of delay effects                               |
| GET    | `/api/v1/runways`              | Runway status with queue depth and capacity                 |
| GET    | `/api/v1/gates`                | Gate occupancy (filterable by terminal)                     |
| POST   | `/api/v1/flights/{id}/hold`    | Manually hold a flight                                      |
| POST   | `/api/v1/flights/{id}/release` | Release a held flight                                       |
| WS     | `/ws/flights`                  | Real-time flight event stream                               |

## Kafka topics

| Direction | Topic              | Events                                                                                 |
| --------- | ------------------ | -------------------------------------------------------------------------------------- |
| Consumes  | `sim.clock`        | `SimClockTick` — advances flight state machine each sim-minute                         |
| Consumes  | `weather.events`   | `WeatherStateChanged` — adjusts runway capacity                                        |
| Consumes  | `incidents.events` | `IncidentCreated/StatusChanged` — holds/reroutes flights                               |
| Consumes  | `flights.schedule` | `FlightScheduleSeeded` — loads new day's flights                                       |
| Produces  | `flights.events`   | `FlightStatusChanged`, `FlightGateAssigned`, `FlightRunwayAssigned`, `FlightCancelled` |

## Testing

```bash
# Unit tests (no external deps)
python -m pytest tests/unit/ -k flight -v

# Integration tests (requires full stack)
docker compose up -d
python -m pytest tests/integration/ -k flight -v
```

## Environment variables

| Variable            | Default             | Description                  |
| ------------------- | ------------------- | ---------------------------- |
| `NEO4J_URI`         | `bolt://neo4j:7687` | Neo4j connection             |
| `NEO4J_USER`        | `neo4j`             | Neo4j username               |
| `NEO4J_PASSWORD`    | `art-digital-twin`  | Neo4j password               |
| `KAFKA_BROKERS`     | `kafka:9092`        | Kafka bootstrap servers      |
| `LOG_LEVEL`         | `INFO`              | Logging level                |

Cascade depth is no longer an env var — it comes from
`operations.cascade_max_depth` in `config/airport.yaml` (D6, default 5).
