# SKILL — Kafka
## Topics · Schemas · Producer/Consumer patterns

---

## Topic catalogue

| Topic | Producer | Key | Partitions |
|---|---|---|---|
| `sim.clock` | sim-orchestrator | — | 1 |
| `flights.schedule` | sim-orchestrator | `flight_id` | 1 |
| `flights.events` | flight-service | `flight_id` | 6 |
| `passengers.events` | passenger-service | `passenger_id` | 6 |
| `baggage.events` | baggage-service | `baggage_tag` | 6 |
| `weather.events` | weather-service | — | 1 |
| `incidents.events` | incident-service | `incident_id` | 3 |
| `incidents.alerts` | incident-service | `incident_id` | 3 |
| `incidents.inject` | api-gateway (manual) | — | 1 |

Consumer groups: `flight-svc`, `pax-svc`, `bag-svc`, `weather-svc`, `inc-svc`, `api-gateway`

Full event schemas → `docs/architecture/EVENT_BUS.md`

---

## Event envelope (every message on every topic)

```python
{
    "event_id": "uuid-v4",           # unique per event — use for dedup
    "event_type": "FlightStatusChanged",
    "schema_version": "1.0",
    "produced_at": "ISO8601",        # wall clock — do not use for business logic
    "sim_time": "ISO8601",           # simulation time — ALWAYS use this
    "producer": "flight-service",
    "payload": { ... }               # event-specific fields
}
```

---

## Producer setup (Python / confluent-kafka)

```python
from confluent_kafka import Producer
import json, os
from datetime import datetime
from uuid import uuid4

producer = Producer({
    "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
    "client.id": "flight-service",
    "acks": "all",                   # wait for all ISR replicas
    "retries": 3,
})

def produce(topic: str, key: str, event_type: str,
            sim_time: datetime, payload: dict):
    envelope = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": "1.0",
        "produced_at": datetime.utcnow().isoformat(),
        "sim_time": sim_time.isoformat(),
        "producer": "flight-service",
        "payload": payload,
    }
    producer.produce(
        topic=topic,
        key=key.encode("utf-8"),
        value=json.dumps(envelope).encode("utf-8"),
        callback=lambda err, msg: print(f"[Kafka] ERROR {err}") if err else None,
    )
    producer.poll(0)  # trigger callbacks without blocking

# flush before shutdown
def flush():
    producer.flush(timeout=10)
```

---

## Consumer setup (Python / confluent-kafka + asyncio)

```python
from confluent_kafka import Consumer
import asyncio, json, os

def make_consumer(group_id: str, topics: list[str]) -> Consumer:
    c = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": group_id,
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })
    c.subscribe(topics)
    return c

async def consume_loop(consumer: Consumer, dispatch):
    loop = asyncio.get_event_loop()
    try:
        while True:
            msg = await loop.run_in_executor(None, consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"[Consumer] Error: {msg.error()}")
                continue
            try:
                envelope = json.loads(msg.value().decode("utf-8"))
                await dispatch(envelope)
            except Exception as e:
                # log and continue — never crash the consumer loop
                print(f"[Consumer] Processing error: {e}")
    finally:
        consumer.close()
```

---

## Dispatch pattern (match on event_type)

```python
async def dispatch(envelope: dict):
    event_type = envelope.get("event_type")
    payload    = envelope.get("payload", {})
    sim_time   = datetime.fromisoformat(envelope["sim_time"])

    match event_type:
        case "SimClockTick":
            await on_clock_tick(payload, sim_time)
        case "FlightStatusChanged":
            await on_flight_status_changed(payload, sim_time)
        case "WeatherStateChanged":
            await on_weather_changed(payload, sim_time)
        case "IncidentCreated":
            await on_incident_created(payload, sim_time)
        case _:
            pass  # always ignore unknown event types — never raise
```

---

## Idempotency pattern

Consumers must handle duplicate delivery gracefully. Use the `event_id` field:

```python
_processed: set[str] = set()   # in production: use Redis or Neo4j

async def on_flight_status_changed(payload: dict, sim_time: datetime,
                                    event_id: str):
    if event_id in _processed:
        return  # duplicate — skip
    _processed.add(event_id)
    # ... process
```

---

## Topic naming conventions

- Domain events: `{domain}.events` — e.g. `flights.events`, `baggage.events`
- Schedules/seeds: `{domain}.schedule`
- Alerts (high priority, all consumers): `incidents.alerts`
- Commands (external input): `incidents.inject`
- Dead letter queues: `{topic}.dlq` — e.g. `flights.events.dlq`

---

## Waiting for Kafka readiness (health check)

```python
from confluent_kafka.admin import AdminClient

async def kafka_is_ready() -> bool:
    try:
        admin = AdminClient({
            "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092")
        })
        loop = asyncio.get_event_loop()
        meta = await loop.run_in_executor(
            None, lambda: admin.list_topics(timeout=3)
        )
        return meta is not None
    except Exception:
        return False
```

---

## Gotchas

- **`consumer.poll()` is blocking** — always wrap in `run_in_executor` inside async code or use a dedicated thread.
- **Never share a `Consumer` instance across coroutines** — it is not thread-safe.
- **`auto.offset.reset: latest` on first run** means you miss events produced before the consumer first joined. This is intentional — services catch up from Neo4j state, not from replaying all Kafka history.
- **`producer.poll(0)` after produce** — this is required to trigger delivery callbacks and flush internal buffers. Without it, messages may be silently dropped on high-throughput bursts.
- **`acks: all` is important** — for a single-broker dev cluster this adds minor latency but ensures no message loss during container restarts.
- **DLQ messages are not auto-retried.** Log them and alert — implement retry logic explicitly if needed.
- **Topic auto-creation is enabled** (`KAFKA_AUTO_CREATE_TOPICS_ENABLE: true` in docker-compose). In production, disable this and create topics with correct partition counts explicitly.
