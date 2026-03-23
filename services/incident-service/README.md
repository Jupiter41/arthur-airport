# incident-service

> 📄 **Specification:** [docs/services/incident-service/SPEC.md](../../docs/services/incident-service/SPEC.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8005

Owns the full lifecycle of hazardous events at KART. Manages cascade propagation, emergency protocol activation, alert generation, and automated incident report creation. Supports both manual injection and probabilistic simulation.

## Incident types

| Type | Base probability/hr |
|---|---|
| Runway incursion | 0.005 |
| Baggage fire / DG alert | 0.008 |
| Security breach | 0.010 |
| Severe weather | driven by weather FSM |
| System failure | 0.015 |

## Quick start

```bash
docker compose up incident-service
```

API docs at **http://localhost:8005/docs**

## Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/incidents` | All incidents (filterable) |
| GET | `/api/v1/incidents/{id}` | Full detail + cascade tree |
| POST | `/api/v1/incidents/inject` | Manually inject an event |
| POST | `/api/v1/incidents/{id}/contain` | Mark as contained |
| POST | `/api/v1/incidents/{id}/resolve` | Mark as resolved |
| GET | `/api/v1/incidents/{id}/report` | Auto-generated incident report |
| GET | `/api/v1/alerts` | Active alert feed |
| WS  | `/ws/incidents` | Real-time incident + alert stream |

## Kafka

| Direction | Topic | Events |
|---|---|---|
| Consumes | `sim.clock` | Evaluates probabilistic firing + TTR |
| Consumes | `incidents.inject` | Manual injection requests |
| Consumes | `weather.events` | Auto-creates severe_weather incident |
| Produces | `incidents.events` | Created, status changed, cascaded |
| Produces | `incidents.alerts` | Real-time alert notifications |

## Status

- [ ] Scaffolding
- [ ] Incident lifecycle + Neo4j model
- [ ] Cascade engine
- [ ] Probabilistic event firing
- [ ] Emergency protocol activation
- [ ] Report generator
- [ ] REST endpoints
- [ ] WebSocket stream
- [ ] Tests
