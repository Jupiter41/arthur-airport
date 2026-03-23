# sim-orchestrator

> 📄 **Specification:** [docs/services/sim-orchestrator/SPEC.md](../../docs/services/sim-orchestrator/SPEC.md)

**Language:** Python 3.11 · **Framework:** FastAPI + asyncio · **Port:** 8006

The conductor of the entire digital twin. Drives the virtual simulation clock, seeds all airport data on startup, and coordinates probabilistic event injection. **Start this last** — it waits for all domain services to be healthy before beginning.

## Responsibilities

- Virtual clock: broadcasts `SimClockTick` every simulated minute to all services
- Seeds flight schedule (420 movements/day), passengers (~30K/day), and baggage on startup and each day boundary
- Evaluates probabilistic hazardous event injection each simulated hour
- Exposes operator control API (pause, resume, reset, speed change)

## Simulation speeds

| Preset | Real time per sim minute |
|---|---|
| 1× | 60 seconds |
| 10× | 6 seconds |
| **60× (default)** | **1 second** |
| 600× | 100ms |
| 3600× | ~17ms |

## Quick start

```bash
docker compose up  # starts everything in correct order
```

API docs at **http://localhost:8006/docs**

## Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/sim/status` | Full simulation state |
| PATCH | `/api/v1/sim/speed` | Change speed multiplier |
| POST | `/api/v1/sim/pause` | Pause clock |
| POST | `/api/v1/sim/resume` | Resume clock |
| POST | `/api/v1/sim/reset` | Full reset + reseed |
| POST | `/api/v1/sim/inject` | Inject hazardous event |
| GET | `/api/v1/sim/schedule` | Current day flight schedule |

## Kafka

| Direction | Topic | Events |
|---|---|---|
| Produces | `sim.clock` | `SimClockTick` every sim minute |
| Produces | `flights.schedule` | Daily schedule seed |
| Produces | `incidents.inject` | Probabilistic event triggers |

## Status

- [ ] Scaffolding
- [ ] Virtual clock loop
- [ ] Airport structure seed
- [ ] Schedule + pax + baggage generation
- [ ] Probabilistic event injection
- [ ] Control API
- [ ] Tests
