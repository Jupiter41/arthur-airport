# Arthur International Airport — Digital Twin
## Agent instructions (OpenAI / Codex)

---

## What this project is

A high-fidelity airport digital twin for Arthur International Airport (IATA: ART / ICAO: KART).
Everything is simulated — 100% fake data. 7 microservices, event-driven via Kafka, graph data in
Neo4j, React frontend. Spec-first: all contracts are documented in `docs/` before code is written.

---

## Before you write any code

1. Read `docs/architecture/OVERVIEW.md` — system map, ADRs, communication rules
2. Read the spec for the service you're working on: `docs/services/{name}/SPEC.md`
3. Read the relevant skill file: `docs/skills/` or `services/{name}/SKILL.md`

Do not implement anything that contradicts the spec. If you need to deviate, state it explicitly.

---

## Hard rules

- **No direct HTTP calls between services.** Use Kafka. Only the API gateway calls services over HTTP.
- **No `datetime.now()` in business logic.** Use `sim_time` from `SimClockTick` Kafka events.
- **Every state change → Kafka event.** No silent mutations.
- **Neo4j is the source of truth.** In-memory state must be rebuildable from Neo4j on restart.
- **All data is fake.** No real airport, airline, or passenger data anywhere.

---

## Stack

- Python 3.11 + FastAPI for all domain services (ports 8001–8006)
- Node.js 20 + TypeScript + Express for the API gateway (port 3000)
- React 18 + TypeScript + Vite for the dashboard (port 5173)
- Neo4j 5 for graph entity storage (bolt: 7687)
- Apache Kafka 3 for async events (broker: 9092)
- LightGBM for passenger queue forecasting (passenger-service only)
- Docker + docker-compose for the full stack

---

## Key files

| Purpose | Path |
|---|---|
| System architecture | `docs/architecture/OVERVIEW.md` |
| Graph schema | `docs/architecture/DATA_MODEL.md` |
| Kafka topics + schemas | `docs/architecture/EVENT_BUS.md` |
| Simulation rules | `docs/architecture/SIMULATION.md` |
| Service specs | `docs/services/{name}/SPEC.md` |
| Skill files | `docs/skills/*.SKILL.md` · `services/*/SKILL.md` |
| Docker config | `docs/infra/DOCKER.md` |

---

## Running

```bash
python scripts/docker_storage.py up  # full stack, bounded cache + free-space guard
docker compose up neo4j kafka    # infra only (for local service dev)
docker compose down -v           # full reset
```

For local rebuilds, use `python scripts/docker_storage.py build [service]` or
`up [service]`. Do not bypass the storage guard with `compose up --build` during
routine development. See `docs/infra/DOCKER_STORAGE.md`. Never automatically
prune volumes or reset Docker Desktop to recover disk space.

---

## Code style

**Python:** PEP8, type hints everywhere, Pydantic models for all I/O, async FastAPI handlers,
`confluent-kafka` for Kafka, `neo4j` driver for graph queries.

**TypeScript:** strict mode, no `any`, `kafkajs` for Kafka, `ws` for WebSocket, thin gateway
(no business logic).

**React:** functional components only, Zustand for global state, React Query for REST,
native WebSocket API, Tailwind for styling.
