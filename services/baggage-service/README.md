# baggage-service

> 📄 **Specification:** [docs/services/baggage-service/SPEC.md](../../docs/services/baggage-service/SPEC.md)
> 🧠 **Skill file:** [SKILL.md](./SKILL.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8003

Tracks every baggage item through the full handling chain: drop-off → screening → sorting → loading → in-hold → carousel → collected. Models conveyor throughput, dangerous goods detection, and system failure impact.

---

## Architecture

```
baggage-service/
├── main.py              # FastAPI app, lifespan, WebSocket endpoint
├── metrics.py           # Prometheus metric definitions
├── models/
│   ├── domain.py        # Pydantic models: BaggageItem, FlowSummary, etc.
│   └── events.py        # Event envelope model and make_event helper
├── routers/
│   └── baggage.py       # REST endpoints: list, detail, tag lookup, flow, flagged
├── kafka/
│   ├── consumer.py      # BaggageConsumerState, tick advancement, event handlers
│   └── producer.py      # Emits BaggageStatusChanged, BaggageFlagged
├── services/
│   ├── conveyor.py      # ConveyorSystem: zone-based pipeline with throughput caps
│   ├── screening.py     # DG detection with per-class rates + false positives
│   └── offload.py       # Flight-cancel offload routines
└── db/
    └── neo4j.py         # Baggage CRUD, pipeline queries, flag/offload updates
```

## Responsibilities

- **Baggage state machine:** 11 states from `checked_in` through `collected`
- **Conveyor zone simulation:** in-memory pipeline with throughput caps per zone:
  - Induction: 600 items/hr per terminal (3 zones)
  - Screening: 300 items/hr per unit (6 units, 2 per terminal)
  - Sorting matrix: 1,800 items/hr (single)
  - Make-up: 150 items/hr per carousel (15 carousels)
  - Arrival belts: 200 items/hr per belt (6 belts)
- **DG detection model:** probabilistic screening with detection rates per IATA DG class (72–95%) and a 0.3% false positive rate
- **Zone degradation/offline:** system failures reduce throughput to 50% (degraded) or 0% (offline)
- **Flight cancellation offload:** when a flight is cancelled, loaded baggage is offloaded and rerouted to arrival carousel

## Running

```bash
# Full stack (recommended)
docker compose up --build

# Just this service
docker compose up neo4j zookeeper kafka
cd services/baggage-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8003 --reload
```

API docs at **http://localhost:8003/docs**

## Key endpoints

| Method | Path                        | Description                                         |
| ------ | --------------------------- | --------------------------------------------------- |
| GET    | `/api/v1/baggage`           | List items (filterable by status, flight, terminal) |
| GET    | `/api/v1/baggage/{id}`      | Item detail + scan history                          |
| GET    | `/api/v1/baggage/tag/{tag}` | Look up by 10-digit barcode tag                     |
| GET    | `/api/v1/flow/summary`      | Conveyor system throughput summary                  |
| GET    | `/api/v1/flow/map`          | Zone map with item counts and utilisation %         |
| GET    | `/api/v1/flagged`           | All flagged DG items                                |
| WS     | `/ws/baggage`               | Real-time baggage event stream                      |

## Kafka topics

| Direction | Topic              | Events                                                                        |
| --------- | ------------------ | ----------------------------------------------------------------------------- |
| Consumes  | `sim.clock`        | `SimClockTick` — advances conveyor zones each sim-minute                      |
| Consumes  | `flights.events`   | `FlightStatusChanged/FlightCancelled` — delays → hold, cancellation → offload |
| Consumes  | `incidents.events` | `IncidentCreated` — system failures set zones offline                         |
| Produces  | `baggage.events`   | `BaggageStatusChanged`, `BaggageFlagged`                                      |

## Testing

```bash
python -m pytest tests/unit/ -k baggage -v
```

## Environment variables

| Variable                 | Default             | Description                   |
| ------------------------ | ------------------- | ----------------------------- |
| `NEO4J_URI`              | `bolt://neo4j:7687` | Neo4j connection              |
| `KAFKA_BROKERS`          | `kafka:9092`        | Kafka bootstrap servers       |
| `DG_FALSE_POSITIVE_RATE` | `0.003`             | Screening false positive rate |
