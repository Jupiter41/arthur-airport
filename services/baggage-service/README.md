# baggage-service

> 📄 **Specification:** [docs/services/baggage-service/SPEC.md](../../docs/services/baggage-service/SPEC.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8003

Tracks every baggage item through the full handling chain: drop-off → screening → sorting → loading → in-hold → carousel → collected. Models conveyor throughput, dangerous goods detection, and system failure impact.

## Responsibilities

- Baggage state machine across 11 states
- Conveyor zone throughput simulation (1,800 items/hr sorting matrix)
- DG detection model with per-class detection rates
- Cascading response to flight cancellations (offload + return to carousel)

## Quick start

```bash
docker compose up baggage-service
```

API docs at **http://localhost:8003/docs**

## Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/baggage` | List items (filterable) |
| GET | `/api/v1/baggage/{id}` | Item detail + scan history |
| GET | `/api/v1/baggage/tag/{tag}` | Look up by 10-digit barcode |
| GET | `/api/v1/flow/summary` | Conveyor system summary |
| GET | `/api/v1/flow/map` | Zone map with item counts |
| GET | `/api/v1/flagged` | All flagged DG items |
| WS  | `/ws/baggage` | Real-time baggage event stream |

## Kafka

| Direction | Topic | Events |
|---|---|---|
| Consumes | `sim.clock` | Advances conveyor simulation |
| Consumes | `flights.events` | Delays/cancellations → hold/offload |
| Consumes | `incidents.events` | System failures → zone offline |
| Produces | `baggage.events` | Status changes + DG flags |

## Status

- [ ] Scaffolding
- [ ] Neo4j models
- [ ] Conveyor simulation engine
- [ ] DG detection model
- [ ] REST endpoints
- [ ] WebSocket stream
- [ ] Tests
