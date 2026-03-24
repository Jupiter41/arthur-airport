# SKILL — Arthur Airport Digital Twin
## Master project skill

Read this file when you are new to the project or starting a task that spans multiple services.
For narrower tasks, go directly to the relevant skill file listed at the bottom.

---

## Mental model

The airport digital twin has three layers:

```
SIMULATION LAYER         sim-orchestrator drives time + seeds data
       ↓ (Kafka events)
DOMAIN LAYER             6 FastAPI services each own one domain
       ↓ (REST + WS)
PRESENTATION LAYER       api-gateway + React dashboard
```

Every entity (flight, passenger, baggage) lives as a **node in Neo4j**. Every state change
travels as a **Kafka event**. The dashboard never polls — it reacts to pushed WebSocket events
that the gateway fans out from Kafka.

---

## The simulation clock contract

This is the most important thing to understand. All services live in simulated time.

```python
# WRONG — never do this
from datetime import datetime
now = datetime.now()

# RIGHT — always do this
# Listen to sim.clock topic, extract sim_time from SimClockTick payload
sim_time: datetime = event.payload["sim_time"]
```

The sim-orchestrator emits one `SimClockTick` per simulated minute. Default speed is 60× — so
one real second = one sim minute. All time-based logic (state transitions, TTR countdowns,
forecast windows) reacts to these ticks, not to wall-clock time.

---

## Domain ownership

Each service owns exactly one set of Neo4j nodes and is the **only writer** to them:

| Service | Owns | Never writes to |
|---|---|---|
| flight-service | `Flight`, `Gate`, `Runway` | Passenger, Baggage |
| passenger-service | `Passenger` | Flight, Baggage |
| baggage-service | `Baggage` | Flight, Passenger |
| weather-service | `WeatherState` | everything else |
| incident-service | `Incident` | everything else |
| sim-orchestrator | seeds all nodes on startup | nothing after day 1 except new days |

If you need data from another domain, read it from Neo4j (read-only) or wait for its Kafka event.

---

## Kafka event envelope

Every event on every topic has this wrapper:

```json
{
  "event_id": "uuid-v4",
  "event_type": "FlightStatusChanged",
  "schema_version": "1.0",
  "produced_at": "2024-06-15T14:32:00.000Z",
  "sim_time": "2024-06-15T14:32:00.000Z",
  "producer": "flight-service",
  "payload": { ... }
}
```

Always validate `event_type` before processing. Always use `sim_time` from the envelope, never
`produced_at`, for business logic.

---

## Neo4j connection pattern (Python)

```python
from neo4j import AsyncGraphDatabase

driver = AsyncGraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "art-digital-twin"))
)

async def get_flight(flight_id: str) -> dict:
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:Flight {id: $id}) RETURN f",
            id=flight_id
        )
        record = await result.single()
        return dict(record["f"]) if record else None
```

---

## FastAPI service skeleton

Every Python service follows this structure:

```
{service-name}/
├── main.py              # FastAPI app, lifespan, router registration
├── routers/
│   └── {domain}.py      # endpoint handlers
├── models/
│   ├── domain.py        # Pydantic domain models
│   └── events.py        # Kafka event Pydantic models
├── services/
│   └── {domain}.py      # business logic (state machines, rules)
├── db/
│   └── neo4j.py         # Neo4j queries
├── kafka/
│   ├── producer.py      # Kafka producer
│   └── consumer.py      # Kafka consumer (runs as background task)
├── requirements.txt
└── Dockerfile
```

---

## Standard FastAPI lifespan pattern

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_neo4j()
    await init_kafka_producer()
    asyncio.create_task(run_kafka_consumer())
    yield
    # shutdown
    await close_neo4j()
    await close_kafka_producer()

app = FastAPI(title="flight-service", lifespan=lifespan)
```

---

## Standard health endpoints (required on every service)

```python
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ready")
async def ready():
    neo4j_ok = await check_neo4j()
    kafka_ok = await check_kafka()
    if not neo4j_ok or not kafka_ok:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready", "neo4j": neo4j_ok, "kafka": kafka_ok}
```

---

## Cascade depth tracking

When producing a Kafka event that is itself a response to another event, always carry the
cascade depth forward:

```python
child_depth = parent_event.get("cascade_depth", 0) + 1
if child_depth > CASCADE_MAX_DEPTH:  # default 5
    # emit alert only, do not create child incident
    return
```

---

## Further reading

| Topic | File |
|---|---|
| FastAPI + Neo4j + Kafka patterns | `docs/skills/python-service.SKILL.md` |
| Neo4j schema + Cypher queries | `docs/skills/neo4j.SKILL.md` |
| Kafka topics + consumer setup | `docs/skills/kafka.SKILL.md` |
| Simulation clock + cascade rules | `docs/skills/simulation.SKILL.md` |
| LightGBM forecasting model | `docs/skills/forecasting.SKILL.md` |
| Per-service state machines | `services/{name}/SKILL.md` |

---

## Testing gotchas

- **All services share the `services/` top-level package name.** You cannot `import services.state_machine` from two different services in the same test session without clearing `sys.modules`. Use the `import_service_module()` helper in `tests/conftest.py`.
- **Some service modules import `db.neo4j` at module level.** If the `neo4j` pip package is not installed (e.g., in CI unit tests), you must pre-install mock modules in `sys.modules` before importing the service module. See `tests/unit/test_incident_lifecycle.py` for the pattern.
- **Pure-logic files are the best unit test targets.** State machines, transition validators, formatters, capacity calculators — anything in `services/*.py` that does not import from `db/` or `kafka/` can be tested without Docker.
- **Integration tests auto-skip when infra is down.** REST and resilience tests use `pytest.mark.skipif` with an HTTP reachability check, so `pytest` always passes in CI even without Docker.
