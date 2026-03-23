# weather-service

> 📄 **Specification:** [docs/services/weather-service/SPEC.md](../../docs/services/weather-service/SPEC.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8004

Runs the airport weather state machine (CAVOK → VMC → IMC → LIFR), generates synthetic METAR/TAF strings, and broadcasts runway capacity impacts to all consuming services.

## Responsibilities

- 4-state weather FSM with probabilistic hourly transitions
- Realistic METAR parameter sampling per state
- METAR and TAF string generation (valid format)
- Runway capacity calculation including crosswind/tailwind reductions

## Quick start

```bash
docker compose up weather-service
```

API docs at **http://localhost:8004/docs**

## Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/weather/current` | Current conditions + runway impact |
| GET | `/api/v1/weather/metar` | Raw METAR string (plain text) |
| GET | `/api/v1/weather/taf` | Current TAF (plain text) |
| GET | `/api/v1/weather/history` | Rolling state history (up to 48 sim-hrs) |
| GET | `/api/v1/weather/impact` | Operational impact summary |
| WS  | `/ws/weather` | Real-time weather event stream |

## Kafka

| Direction | Topic | Events |
|---|---|---|
| Consumes | `sim.clock` | Triggers hourly FSM evaluation |
| Produces | `weather.events` | `WeatherStateChanged`, `METARIssued` |

## Status

- [ ] Scaffolding
- [ ] Weather FSM
- [ ] METAR/TAF generator
- [ ] Runway capacity calculator
- [ ] REST endpoints
- [ ] WebSocket stream
- [ ] Tests
