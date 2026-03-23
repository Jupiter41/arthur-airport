# passenger-service

> 📄 **Specification:** [docs/services/passenger-service/SPEC.md](../../docs/services/passenger-service/SPEC.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8002

Tracks every passenger from check-in to boarding (departures) or landing to airport exit (arrivals). Manages security queue simulation and connection risk monitoring.

## Responsibilities

- Passenger state machine: `checked_in → security_queue → airside → at_gate → boarded`
- Security throughput model (180 pax/hr/lane per terminal)
- Connection risk detection (watch / at_risk / missed)
- Zone density tracking for the heatmap dashboard

## Quick start

```bash
docker compose up passenger-service
```

API docs at **http://localhost:8002/docs**

## Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/passengers` | List passengers (filterable) |
| GET | `/api/v1/passengers/{id}` | Full passenger detail + timeline |
| GET | `/api/v1/flow/summary` | Live airport-wide flow summary |
| GET | `/api/v1/flow/heatmap` | Zone density for heatmap |
| GET | `/api/v1/connections/at-risk` | All at-risk connecting pax |
| WS  | `/ws/passengers` | Real-time passenger event stream |

## Kafka

| Direction | Topic | Events |
|---|---|---|
| Consumes | `sim.clock` | Drains queues, advances state |
| Consumes | `flights.events` | Detects delays, gate changes |
| Consumes | `incidents.events` | Zone lockdowns |
| Produces | `passengers.events` | Status changes + alerts |

## Status

- [ ] Scaffolding
- [ ] Neo4j models
- [ ] State machine + queue model
- [ ] Connection risk engine
- [ ] REST endpoints
- [ ] WebSocket stream
- [ ] Tests
