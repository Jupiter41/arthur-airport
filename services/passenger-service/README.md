# passenger-service

> 📄 **Specification:** [docs/services/passenger-service/SPEC.md](../../docs/services/passenger-service/SPEC.md)
> 🧠 **Skill file:** [SKILL.md](./SKILL.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8002

Tracks every passenger from check-in to boarding (departures) or landing to airport exit (arrivals). Manages security queue simulation, connection risk monitoring, and LightGBM-based queue depth forecasting.

---

## Architecture

```
passenger-service/
├── main.py              # FastAPI app, lifespan, WebSocket endpoint
├── metrics.py           # Prometheus metric definitions
├── models/
│   └── domain.py        # Pydantic models: PassengerSummary, FlowSummary, etc.
├── routers/
│   └── passengers.py    # REST endpoints: list, flow, heatmap, connections, alerts
├── kafka/
│   ├── consumer.py      # PassengerConsumerState, tick pipeline, event handlers
│   └── producer.py      # Emits PassengerStatusChanged, PassengerAlert, etc.
├── services/
│   ├── state_machine.py # Departure + arrival flow — pure logic, no I/O
│   ├── security.py      # SecurityCheckpoint + SecuritySystem queue model
│   ├── connections.py   # Connection risk detection and time-to-connection
│   └── zones.py         # Zone density tracking (for heatmap)
├── ml/
│   ├── features.py      # Feature column definitions for queue forecasting
│   ├── training.py      # LightGBM training pipeline + parquet flush
│   ├── inference.py     # Prediction + day-1 fallback + hot-reload
│   └── congestion.py    # Congestion threshold tracking by terminal
└── db/
    └── neo4j.py         # Passenger CRUD, search, status/location updates
```

## Responsibilities

- **Passenger state machine:** `checked_in → security_queue → airside → at_gate → boarded` (departures) and `airborne → deplaning → baggage_claim → departed_airport` (arrivals)
- **Security throughput model:** 3 checkpoints (one per terminal), 4 lanes each, 180 pax/hr/lane base rate with congestion slowdown
- **Special assistance lane:** fixed 20 pax/hr, immune to congestion, reduced rate during security breaches
- **Connection risk detection:** watches passengers with connecting flights, alerts at `at_risk` (delay > 45 min), moves to `missed_connection` when delay exceeds MCT
- **Zone density tracking:** per-zone passenger counts for the heatmap dashboard
- **LightGBM queue depth forecasting:** 12-feature model trained on simulated history after 3 sim-days, predicts queue depth 90 minutes ahead, triggers congestion alerts when actual exceeds forecast by 30%

## Running

```bash
# Full stack (recommended)
docker compose up --build

# Just this service (requires Neo4j + Kafka running)
docker compose up neo4j zookeeper kafka
cd services/passenger-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

API docs at **http://localhost:8002/docs**

## Key endpoints

| Method | Path                          | Description                                              |
| ------ | ----------------------------- | -------------------------------------------------------- |
| GET    | `/api/v1/passengers`          | List passengers (filterable by status, flight, terminal) |
| GET    | `/api/v1/passengers/{id}`     | Full passenger detail + timeline                         |
| GET    | `/api/v1/passengers/search`   | Search by PNR or name                                    |
| GET    | `/api/v1/flow/summary`        | Live airport-wide flow summary with queue forecast       |
| GET    | `/api/v1/flow/heatmap`        | Zone density for heatmap dashboard                       |
| GET    | `/api/v1/flow/forecast`       | Queue depth prediction per terminal                      |
| GET    | `/api/v1/connections/at-risk` | All at-risk connecting passengers                        |
| GET    | `/api/v1/alerts`              | Active alerts                                            |
| WS     | `/ws/passengers`              | Real-time passenger event stream                         |

## Kafka topics

| Direction | Topic               | Events                                                                   |
| --------- | ------------------- | ------------------------------------------------------------------------ |
| Consumes  | `sim.clock`         | `SimClockTick` — drains security queues, advances passenger states       |
| Consumes  | `flights.events`    | `FlightStatusChanged` — detects delays, updates connection risk          |
| Consumes  | `incidents.events`  | `IncidentCreated` — zone lockdowns, security freezes                     |
| Produces  | `passengers.events` | `PassengerStatusChanged`, `PassengerAlert`, `SecurityCongestionDetected` |

## ML forecasting

The service includes a **LightGBM** model for predicting security queue depth:

- **Training data:** accumulated from simulation history (deque buffer → parquet → retrain)
- **Retrain cadence:** every 3 simulated days (configurable via `FORECAST_RETRAIN_EVERY_N_DAYS`)
- **Day-1 fallback:** `forecast = expected_pax_next_90min × 0.35` (before enough training data)
- **Features:** 12 columns including hour, day-of-week, departures next 90 min, current queue depth, weather category
- **Hot-reload:** models are reloaded after each retrain cycle

## Testing

```bash
python -m pytest tests/unit/ -k passenger -v
```

## Environment variables

| Variable                        | Default             | Description             |
| ------------------------------- | ------------------- | ----------------------- |
| `NEO4J_URI`                     | `bolt://neo4j:7687` | Neo4j connection        |
| `KAFKA_BROKERS`                 | `kafka:9092`        | Kafka bootstrap servers |
| `SECURITY_LANES_OPEN`           | `4`                 | Lanes per terminal      |
| `FORECAST_RETRAIN_EVERY_N_DAYS` | `3`                 | Retrain cadence         |
| `FORECAST_FALLBACK_QUEUE_RATIO` | `0.35`              | Day-1 fallback ratio    |
