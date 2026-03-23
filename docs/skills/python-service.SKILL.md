# SKILL — Python service patterns
## FastAPI · Neo4j · Kafka · Pydantic v2

Read this when implementing any of the 6 Python/FastAPI domain services.

---

## Requirements baseline

```txt
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
neo4j>=5.20.0
confluent-kafka>=2.4.0
prometheus-fastapi-instrumentator>=6.1.0
python-dotenv>=1.0.0
```

For passenger-service only, add:
```txt
lightgbm>=4.3.0
scikit-learn>=1.4.0
pandas>=2.2.0
joblib>=1.4.0
```

---

## Pydantic v2 patterns

### Domain model

```python
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional

class FlightStatus(str, Enum):
    SCHEDULED = "scheduled"
    BOARDING  = "boarding"
    DELAYED   = "delayed"
    DEPARTED  = "departed"
    AIRBORNE  = "airborne"
    APPROACH  = "approach"
    LANDED    = "landed"
    TAXIING   = "taxiing"
    AT_GATE   = "at_gate"
    CANCELLED = "cancelled"

class Flight(BaseModel):
    id: str
    flight_number: str
    status: FlightStatus
    gate_id: Optional[str] = None
    delay_minutes: int = 0
    estimated_time: datetime
    pax_count: int

    model_config = {"from_attributes": True}  # allows .model_validate(neo4j_record)
```

### Kafka event model

```python
from uuid import uuid4

class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    schema_version: str = "1.0"
    produced_at: datetime = Field(default_factory=datetime.utcnow)
    sim_time: datetime
    producer: str
    payload: dict

def make_event(event_type: str, sim_time: datetime, producer: str, payload: dict) -> str:
    envelope = EventEnvelope(
        event_type=event_type,
        sim_time=sim_time,
        producer=producer,
        payload=payload
    )
    return envelope.model_dump_json()
```

---

## Neo4j async driver patterns

### Initialisation

```python
from neo4j import AsyncGraphDatabase, AsyncDriver
from contextlib import asynccontextmanager
import os

_driver: AsyncDriver | None = None

async def init_neo4j():
    global _driver
    _driver = AsyncGraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"),
              os.getenv("NEO4J_PASSWORD", "art-digital-twin"))
    )
    await _driver.verify_connectivity()

async def close_neo4j():
    if _driver:
        await _driver.close()

def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _driver
```

### Query pattern

```python
async def get_flight_by_id(flight_id: str) -> Flight | None:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (f:Flight {id: $id}) RETURN f",
            id=flight_id
        )
        record = await result.single()
        if not record:
            return None
        return Flight.model_validate(dict(record["f"]))

async def update_flight_status(flight_id: str, new_status: str, sim_time: datetime):
    async with get_driver().session() as session:
        await session.run(
            """
            MATCH (f:Flight {id: $id})
            SET f.status = $status,
                f.updated_at = $updated_at
            """,
            id=flight_id,
            status=new_status,
            updated_at=sim_time.isoformat()
        )
```

### Relationship creation pattern

```python
async def assign_flight_to_gate(flight_id: str, gate_id: str, sim_time: datetime):
    async with get_driver().session() as session:
        await session.run(
            """
            MATCH (f:Flight {id: $flight_id})
            MATCH (g:Gate {id: $gate_id})
            MERGE (f)-[r:ASSIGNED_TO]->(g)
            SET r.assigned_at = $assigned_at
            """,
            flight_id=flight_id,
            gate_id=gate_id,
            assigned_at=sim_time.isoformat()
        )
```

---

## Kafka producer pattern

```python
from confluent_kafka import Producer
import json, os

_producer: Producer | None = None

def init_kafka_producer():
    global _producer
    _producer = Producer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "client.id": "flight-service",
    })

def produce_event(topic: str, key: str, event_type: str,
                  sim_time: datetime, payload: dict):
    message = make_event(event_type, sim_time, "flight-service", payload)
    _producer.produce(
        topic=topic,
        key=key.encode(),
        value=message.encode(),
        callback=_delivery_report
    )
    _producer.poll(0)  # non-blocking flush trigger

def _delivery_report(err, msg):
    if err:
        print(f"[Kafka] Delivery failed: {err}")
```

---

## Kafka consumer pattern

```python
from confluent_kafka import Consumer
import asyncio, json

async def run_kafka_consumer():
    consumer = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "flight-service",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(["sim.clock", "weather.events", "incidents.events"])

    loop = asyncio.get_event_loop()
    while True:
        # run blocking poll in executor to avoid blocking event loop
        msg = await loop.run_in_executor(None, consumer.poll, 1.0)
        if msg is None or msg.error():
            continue
        try:
            envelope = json.loads(msg.value().decode())
            await dispatch(envelope)
        except Exception as e:
            print(f"[Consumer] Error processing message: {e}")

async def dispatch(envelope: dict):
    match envelope["event_type"]:
        case "SimClockTick":
            await handle_clock_tick(envelope["payload"])
        case "WeatherStateChanged":
            await handle_weather_change(envelope["payload"])
        case "IncidentCreated":
            await handle_incident_created(envelope["payload"])
        case _:
            pass  # ignore unknown events — consumers must be lenient
```

---

## WebSocket pattern

```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import set

_ws_clients: set[WebSocket] = set()

@app.websocket("/ws/flights")
async def ws_flights(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # handle filter frames from client
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)

async def broadcast(event: dict):
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead
```

---

## Prometheus metrics pattern

```python
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Gauge, Histogram

# Register metrics at module level
flight_transitions = Counter(
    "flight_status_transitions_total",
    "Flight state transitions",
    ["from_status", "to_status"]
)
flights_delayed = Gauge(
    "flights_delayed_current",
    "Currently delayed flights"
)

# Instrument FastAPI
Instrumentator().instrument(app).expose(app)

# Usage in business logic
flight_transitions.labels(from_status="scheduled", to_status="boarding").inc()
```

---

## Gotchas

- **Neo4j returns integers as `int`, not `str`** — always cast explicitly when building Pydantic models from raw records.
- **`confluent_kafka.poll()` is blocking** — always run in `asyncio.get_event_loop().run_in_executor(None, ...)`.
- **Pydantic v2 uses `model_validate()` not `parse_obj()`** — old v1 patterns will fail silently if you mix them.
- **FastAPI lifespan replaces `@app.on_event("startup")`** — do not use the deprecated startup/shutdown events.
- **Neo4j datetime is `neo4j.time.DateTime`** — convert with `.to_native()` to get a Python `datetime`.
- **`session.run()` is lazy** — the query only executes when you call `await result.single()`, `await result.fetch(n)`, or `async for record in result`.
