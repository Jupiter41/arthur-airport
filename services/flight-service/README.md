# flight-service

> 📄 **Specification:** [docs/services/flight-service/SPEC.md](../../docs/services/flight-service/SPEC.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8001

Owns the full lifecycle of every flight movement at KART — from schedule ingestion through gate assignment, runway allocation, airborne state, and arrival/departure completion.

## Responsibilities

- Flight state machine: `scheduled → boarding → airborne → landed → at_gate`
- Runway queue management and gate conflict resolution
- Turnaround delay propagation (inbound delay → outbound flight)
- Reacts to weather and incident events from Kafka

## Quick start

```bash
# From repo root
docker compose up flight-service
```

API docs available at **http://localhost:8001/docs** once running.

## Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/flights` | List all flights (filterable) |
| GET | `/api/v1/flights/{id}` | Flight detail + pax + baggage |
| GET | `/api/v1/flights/{id}/cascade` | Cascade effects of this flight |
| GET | `/api/v1/runways` | Runway status |
| GET | `/api/v1/gates` | Gate occupancy |
| WS  | `/ws/flights` | Real-time flight event stream |

## Kafka

| Direction | Topic | Events |
|---|---|---|
| Consumes | `sim.clock` | Advances state machine |
| Consumes | `weather.events` | Applies capacity constraints |
| Consumes | `incidents.events` | Holds/reroutes flights |
| Produces | `flights.events` | All flight state changes |

## Status

- [ ] Scaffolding
- [ ] Neo4j models
- [ ] State machine
- [ ] Kafka consumer/producer
- [ ] REST endpoints
- [ ] WebSocket stream
- [ ] Tests
