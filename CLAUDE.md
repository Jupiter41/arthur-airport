# Arthur International Airport — Digital Twin

## Claude Code context

This is a **specification-first** project. All architecture, data models, API contracts, and
simulation rules are fully documented in `docs/` before any code is written. Always read the
relevant spec before implementing anything.

---

## Project identity

| Field       | Value                                                                |
| ----------- | -------------------------------------------------------------------- |
| Airport     | Arthur International Airport                                         |
| IATA / ICAO | ART / KART                                                           |
| Type        | High-fidelity airport digital twin — fully simulated, 100% fake data |
| Purpose     | Portfolio + teaching project                                         |

---

## Stack at a glance

| Layer                | Technology                                        |
| -------------------- | ------------------------------------------------- |
| Domain services (×6) | Python 3.11 · FastAPI · uvicorn                   |
| API gateway          | Node.js 20 · TypeScript · Express 5 · ws          |
| Frontend             | React 18 · TypeScript · Vite · Tailwind · Zustand |
| Graph database       | Neo4j 5 (Bolt: 7687, HTTP: 7474)                  |
| Event bus            | Apache Kafka 3 (broker: 9092)                     |
| Observability        | Prometheus (9090) · Grafana (3001)                |
| ML forecasting       | LightGBM (passenger-service only)                 |
| Container runtime    | Docker + docker-compose                           |

---

## Running the project

```bash
# Light mode (default) — core services only, fast build (~60s)
docker compose up --build

# Full mode — includes analysis-service + observability (Grafana, Prometheus, etc.)
docker compose --profile full up --build

# Observability only (add Grafana, Prometheus, Jaeger, Loki to light mode)
docker compose --profile observability up --build

# Start only infra (Neo4j + Kafka) — useful during service development
docker compose up neo4j zookeeper kafka kafka-ui

# Restart one service after a code change
docker compose up --build --no-deps flight-service

# Full reset (wipe all data, reseed)
docker compose down -v && docker compose up --build
```

## Service ports

| Service           | URL                                                                   |
| ----------------- | --------------------------------------------------------------------- |
| API Gateway       | http://localhost:3000 — OpenAPI at /docs not available (gateway only) |
| flight-service    | http://localhost:8001/docs                                            |
| passenger-service | http://localhost:8002/docs                                            |
| baggage-service   | http://localhost:8003/docs                                            |
| weather-service   | http://localhost:8004/docs                                            |
| incident-service  | http://localhost:8005/docs                                            |
| sim-orchestrator  | http://localhost:8006/docs                                            |
| cost-service      | http://localhost:8008/docs                                            |
| React dashboard   | http://localhost:5173                                                 |
| Neo4j Browser     | http://localhost:7474 (neo4j / art-digital-twin)                      |
| Kafka UI          | http://localhost:8080                                                 |
| Grafana           | http://localhost:3001 (admin / art-grafana)                           |
| Prometheus        | http://localhost:9090                                                 |

---

## Spec files — read these before implementing

| What you're working on | Read first                                |
| ---------------------- | ----------------------------------------- |
| Any service            | `docs/architecture/OVERVIEW.md`           |
| Neo4j schema           | `docs/architecture/DATA_MODEL.md`         |
| Kafka topics & events  | `docs/architecture/EVENT_BUS.md`          |
| Simulation rules       | `docs/architecture/SIMULATION.md`         |
| flight-service         | `docs/services/flight-service/SPEC.md`    |
| passenger-service      | `docs/services/passenger-service/SPEC.md` |
| baggage-service        | `docs/services/baggage-service/SPEC.md`   |
| weather-service        | `docs/services/weather-service/SPEC.md`   |
| incident-service       | `docs/services/incident-service/SPEC.md`  |
| sim-orchestrator       | `docs/services/sim-orchestrator/SPEC.md`  |
| api-gateway            | `docs/services/api-gateway/SPEC.md`       |
| Dashboards             | `docs/dashboards/*.md`                    |
| Docker / infra         | `docs/infra/DOCKER.md`                    |
| Monitoring             | `docs/infra/MONITORING.md`                |

## Skill files — patterns and gotchas

| Topic                    | File                                  |
| ------------------------ | ------------------------------------- |
| Project overview         | `docs/skills/SKILL.md`                |
| FastAPI service patterns | `docs/skills/python-service.SKILL.md` |
| Neo4j / Cypher patterns  | `docs/skills/neo4j.SKILL.md`          |
| Kafka producer/consumer  | `docs/skills/kafka.SKILL.md`          |
| Simulation engine rules  | `docs/skills/simulation.SKILL.md`     |
| LightGBM forecasting     | `docs/skills/forecasting.SKILL.md`    |
| Per-service patterns     | `services/{name}/SKILL.md`            |

---

## Architecture rules — never violate these

1. **No service calls another service directly over HTTP.** All cross-domain communication is async
   via Kafka. The only HTTP calls are from the API gateway to domain services (external-facing only).

2. **All services consume `sim.clock` for time.** No service reads `datetime.now()` for business
   logic. Always use the `sim_time` from the latest `SimClockTick`.

3. **Neo4j is the single source of truth for entity state.** In-memory caches are always derived
   from Neo4j and must be rebuildable on restart.

4. **Every state change produces a Kafka event.** Silent mutations are forbidden. If a flight
   changes status, a `FlightStatusChanged` event must be produced.

5. **All data is fake.** Never introduce real airport, airline, or passenger data.

6. **The spec is authoritative.** If the spec says a field exists, it exists. If you need to
   deviate from the spec, update the spec first.

---

## Common tasks

### Add a new Kafka event

1. Define the JSON schema in `docs/architecture/EVENT_BUS.md`
2. Add the producer in the relevant service
3. Add the consumer in all services that need to react
4. Update the topic catalogue table in EVENT_BUS.md

### Add a new REST endpoint

1. Add it to the relevant `docs/services/{name}/SPEC.md` first
2. Implement with a Pydantic response model
3. FastAPI auto-generates OpenAPI docs — verify at `/docs` after restart

### Add a new Neo4j node type

1. Add to `docs/architecture/DATA_MODEL.md` with all properties and types
2. Add uniqueness constraint and indexes (see DATA_MODEL.md §5)
3. Add to the relevant service's Neo4j initialization

### Inject a simulated incident (manual testing)

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)

# Inject a runway incursion
curl -X POST http://localhost:3000/api/v1/incidents/inject \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type":"runway_incursion","severity":"critical","location":"runway-09L"}'
```

---

## Environment variables (shared across all Python services)

```
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=art-digital-twin
KAFKA_BROKERS=kafka:9092
LOG_LEVEL=INFO
```

For service-specific env vars, see `docs/infra/DOCKER.md §2` or the individual SPEC.md.

---

## Testing conventions

- Unit tests: `pytest` with `pytest-asyncio` for async handlers
- Integration tests: spin up Neo4j + Kafka via `docker compose up neo4j kafka` then run tests
- No mocking of Neo4j or Kafka in integration tests — use real containers
- Test fixture data lives in `tests/fixtures/` per service
- All Kafka consumers must be tested for idempotency (duplicate message handling)
