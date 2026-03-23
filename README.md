# Arthur International Airport — Digital Twin

> **IATA:** `ART` · **ICAO:** `KART` · **Location:** fictional mid-size hub
> **Throughput:** ~18M passengers/year · **Runways:** 2 (09L/27R · 09R/27L) · **Terminals:** 3 (A, B, C)

A high-fidelity airport digital twin built on a microservices architecture with fully simulated, fake data. Models real-time flight operations, passenger flows, baggage handling, weather impacts, and hazardous incident propagation — including cascading delay effects and a LightGBM forecasting model for security queue prediction.

This project is **spec-first and agent-ready**: every service, data model, and API contract is fully documented before any code is written, and the repository is structured so that AI coding agents (Claude Code, Cursor, GitHub Copilot, OpenAI Codex) can navigate, implement, and extend the codebase with minimal manual explanation.

---

## Purpose

- A **portfolio reference** for event-driven microservices design at scale
- A **teaching example** for graph data modelling, real-time streaming, simulation engines, and ML forecasting
- A **playground** for incident response, cascading failure visualization, and hazardous event simulation
- A **reference implementation** for agent-assisted development workflows with SKILL.md files

All data is 100% synthetic. No real airport, airline, or passenger data is used.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        React Dashboards                          │
│  Flight Board · Baggage Tracker · Passenger Flow (+ forecast)   │
│  Incident Console (cascade tree) · Ground Ops View              │
└─────────────────────────┬────────────────────────────────────────┘
                          │ REST + WebSocket
┌─────────────────────────▼────────────────────────────────────────┐
│                    API Gateway  (Node.js / Express)              │
│         JWT auth · rate limiting · Kafka → WS fan-out           │
└──┬──────────┬──────────┬──────────┬──────────┬───────────────────┘
   │          │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼          ▼
Flight   Passenger  Baggage   Weather   Incident   Sim-Orch
FastAPI   FastAPI   FastAPI   FastAPI   FastAPI     Python
   │          │          │          │          │          │
   └──────────┴──────────┴──────────┴──────────┴──────────┘
                          │
               ┌──────────▼──────────┐
               │    Kafka Event Bus   │
               │  9 topics · schemas  │
               └──────────┬──────────┘
                          │
               ┌──────────▼──────────┐
               │  Neo4j Graph DB      │
               │  Nodes · Relations   │
               └─────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
     Prometheus        Grafana        LightGBM
    (metrics)        (dashboards)   (pax forecast)
```

### Key architectural rules

1. **No direct HTTP between services** — all cross-domain communication is async via Kafka
2. **No wall-clock time in business logic** — every service runs on `sim_time` from `SimClockTick` events
3. **Every state change produces a Kafka event** — no silent mutations
4. **Neo4j is the single source of truth** — in-memory caches are always rebuildable from Neo4j
5. **The spec is authoritative** — deviate from the spec only by updating it first

---

## Services

| Service             | Language          | Port | Responsibility                                                            |
| ------------------- | ----------------- | ---- | ------------------------------------------------------------------------- |
| `flight-service`    | Python / FastAPI  | 8001 | Flight lifecycle · runway queue · gate conflicts · turnaround propagation |
| `passenger-service` | Python / FastAPI  | 8002 | Passenger flow · security queues · connection risk · LightGBM forecast    |
| `baggage-service`   | Python / FastAPI  | 8003 | Conveyor simulation · DG detection · system failure impact                |
| `weather-service`   | Python / FastAPI  | 8004 | Weather FSM · METAR/TAF generation · runway capacity                      |
| `incident-service`  | Python / FastAPI  | 8005 | Hazard lifecycle · cascade engine · emergency protocols · reports         |
| `sim-orchestrator`  | Python            | 8006 | Virtual clock · schedule seeding · probabilistic event injection          |
| `api-gateway`       | Node.js / Express | 3000 | REST proxy · WebSocket fan-out · JWT auth · rate limiting                 |

### Simulation features

- **Configurable time engine** — 1×, 10×, 60× (default), 600×, 3600× speed
- **4-state weather FSM** — CAVOK → VMC → IMC → LIFR with probabilistic hourly transitions
- **Cascading delay propagation** — inbound delay → gate conflict → baggage hold → connecting pax alert → turnaround outbound, up to 5 hops
- **5 hazard types** — runway incursion, baggage fire, security breach, severe weather, system failure — each with a defined cascade tree, TTR range, and emergency protocol
- **Dual-trigger incidents** — manually injectable via API or probabilistically fired by the sim engine
- **LightGBM security queue forecasting** — 12-feature model trained on simulated history, predicts queue depth 90 sim-minutes ahead, triggers congestion incidents when demand exceeds forecast by 30%
- **Special events calendar** — configurable demand multipliers per sim day (marathons, peaks, conferences)

---

## Quickstart

### Prerequisites

- Docker ≥ 24 and Docker Compose ≥ 2.20
- Python ≥ 3.11 (for local service development only)
- Node.js ≥ 20 (for dashboard development only)

### Run the full stack

```bash
git clone https://github.com/your-org/arthur-airport.git
cd arthur-airport
docker compose up --build
```

The sim-orchestrator seeds all data and starts the virtual clock automatically.
The full stack is ready in ~60–90 seconds on first run.

### Service URLs

| Service                     | URL                        | Credentials              |
| --------------------------- | -------------------------- | ------------------------ |
| React Dashboard             | http://localhost:5173      | —                        |
| API Gateway                 | http://localhost:3000      | —                        |
| Flight Service (OpenAPI)    | http://localhost:8001/docs | —                        |
| Passenger Service (OpenAPI) | http://localhost:8002/docs | —                        |
| Baggage Service (OpenAPI)   | http://localhost:8003/docs | —                        |
| Weather Service (OpenAPI)   | http://localhost:8004/docs | —                        |
| Incident Service (OpenAPI)  | http://localhost:8005/docs | —                        |
| Sim Orchestrator (OpenAPI)  | http://localhost:8006/docs | —                        |
| Neo4j Browser               | http://localhost:7474      | neo4j / art-digital-twin |
| Kafka UI                    | http://localhost:8080      | —                        |
| Grafana                     | http://localhost:3001      | admin / art-grafana      |
| Prometheus                  | http://localhost:9090      | —                        |

### Useful commands

```bash
# Restart a single service after a code change
docker compose up --build --no-deps flight-service

# Full reset — wipe all data and reseed
docker compose down -v && docker compose up --build

# Tail logs for one service
docker compose logs -f passenger-service

# Manually inject a critical runway incursion
TOKEN=$(curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)

curl -X POST http://localhost:3000/api/v1/incidents/inject \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type":"runway_incursion","severity":"critical","location":"runway-09L"}'

# Change simulation speed to 10× real-time
curl -X PATCH http://localhost:3000/api/v1/sim/speed \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"speed_multiplier": 10}'
```

---

## Developing with AI coding agents

This repository is structured for **agent-assisted development**. Every service has a spec, a skill file, and a clearly bounded domain. An agent that reads the right files before writing code will produce correct, consistent implementations without needing to read the entire codebase.

### How it works

The `agents/` folder at the repo root contains all context files for AI tools. Run the deploy script once to place them at the locations each tool expects:

```bash
bash agents/deploy.sh
```

This creates:

```
CLAUDE.md                          ← Claude Code reads on repo open
AGENTS.md                          ← OpenAI Codex / ChatGPT agents
.cursorrules                       ← Cursor IDE
.github/copilot-instructions.md    ← GitHub Copilot

docs/skills/
├── SKILL.md                       ← master project skill (start here)
├── python-service.SKILL.md        ← FastAPI · Neo4j · Kafka boilerplate
├── neo4j.SKILL.md                 ← Cypher patterns · schema · gotchas
├── kafka.SKILL.md                 ← topics · producer/consumer · idempotency
├── simulation.SKILL.md            ← clock contract · state machines · cascade rules
└── forecasting.SKILL.md           ← LightGBM · features · training pipeline

services/
├── flight-service/SKILL.md        ← state machine · runway queue · turnaround
├── passenger-service/SKILL.md     ← queue model · congestion · connection risk
├── baggage-service/SKILL.md       ← conveyor zones · DG detection · offload
├── weather-service/SKILL.md       ← FSM · METAR generation · capacity calc
├── incident-service/SKILL.md      ← cascade engine · protocols · TTR
├── sim-orchestrator/SKILL.md      ← startup sequence · clock loop · seeding
└── api-gateway/SKILL.md           ← proxy pattern · WS fan-out · aggregate
```

### Recommended workflow with Claude Code

```bash
# Open the repo in Claude Code
claude

# Claude reads CLAUDE.md automatically on startup.
# Then point it at the relevant spec and skill before asking it to implement:

> Read docs/services/flight-service/SPEC.md and services/flight-service/SKILL.md,
> then implement the flight state machine in services/flight-service/services/flight.py
```

### What each file teaches an agent

| File                                  | What it prevents                                                                                                          |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `CLAUDE.md`                           | Agent calling `datetime.now()`, making direct HTTP calls between services, ignoring the spec                              |
| `docs/skills/SKILL.md`                | Agent misunderstanding the 3-layer architecture or the sim clock contract                                                 |
| `docs/skills/python-service.SKILL.md` | Agent using Pydantic v1 syntax, blocking Kafka poll in async context, missing lifespan pattern                            |
| `docs/skills/neo4j.SKILL.md`          | Agent using `MERGE` incorrectly, storing Python datetimes directly, forgetting `IF NOT EXISTS` on constraints             |
| `docs/skills/kafka.SKILL.md`          | Agent sharing a Consumer across coroutines, forgetting `producer.poll(0)`, not handling duplicate delivery                |
| `docs/skills/simulation.SKILL.md`     | Agent using wall-clock time, getting TTR ranges wrong, misunderstanding cascade depth tracking                            |
| `docs/skills/forecasting.SKILL.md`    | Agent getting feature column order wrong, blocking the event loop during model training, OOM from unbounded training data |
| `services/*/SKILL.md`                 | Agent misimplementing the service-specific state machine or domain rules                                                  |

### Skill file format

Each SKILL.md follows a consistent structure:

```
# SKILL — {topic}
## {subtitle}

One paragraph explaining what this skill covers and when to read it.

---

## {Section: key concept}
Explanation + runnable code example

## {Section: patterns}
Copy-paste ready patterns for the most common tasks

## Gotchas
Bulleted list of things that will go wrong without this knowledge
```

You can extend the skill files as you implement each service — add discovered gotchas, paste
in working code patterns, note decisions that deviate from the spec. They become a living
knowledge base for both humans and agents.

---

## Repository structure

```
arthur-airport/
├── README.md
├── CLAUDE.md                          ← agent context (generated by agents/deploy.sh)
├── AGENTS.md                          ← agent context (generated by agents/deploy.sh)
├── .cursorrules                       ← agent context (generated by agents/deploy.sh)
├── CONTRIBUTING.md
├── LICENSE
├── docker-compose.yml
│
├── agents/                            ← source of truth for all agent/skill files
│   ├── deploy.sh                      ← run once to place files at correct locations
│   ├── CLAUDE.md
│   ├── AGENTS.md
│   ├── cursorrules
│   ├── copilot-instructions.md
│   ├── skills/                        ← project-wide skill files
│   └── services/                      ← per-service skill files
│
├── docs/
│   ├── architecture/
│   │   ├── OVERVIEW.md                ← system design & ADRs
│   │   ├── DATA_MODEL.md              ← Neo4j graph schema
│   │   ├── EVENT_BUS.md               ← Kafka topics & event schemas
│   │   └── SIMULATION.md             ← simulation engine & forecasting
│   ├── services/
│   │   └── {name}/SPEC.md             ← one spec per service (7 total)
│   ├── dashboards/
│   │   └── *.md                       ← one spec per dashboard (5 total)
│   ├── skills/                        ← deployed skill files (read by agents)
│   └── infra/
│       ├── MONITORING.md              ← Prometheus metrics · Grafana dashboards
│       └── DOCKER.md                  ← docker-compose spec · Dockerfiles
│
├── services/
│   ├── flight-service/                ← Python / FastAPI  (port 8001)
│   ├── passenger-service/             ← Python / FastAPI  (port 8002)
│   ├── baggage-service/               ← Python / FastAPI  (port 8003)
│   ├── weather-service/               ← Python / FastAPI  (port 8004)
│   ├── incident-service/              ← Python / FastAPI  (port 8005)
│   ├── sim-orchestrator/              ← Python            (port 8006)
│   └── api-gateway/                   ← Node.js / Express (port 3000)
│
├── dashboards/
│   └── art-dashboard/                 ← React + TypeScript (port 5173)
│
└── infra/
    ├── prometheus/
    └── grafana/
```

---

## Documentation index

| Document                                               | Description                                                    |
| ------------------------------------------------------ | -------------------------------------------------------------- |
| [Architecture Overview](docs/architecture/OVERVIEW.md) | System design, technology choices, 6 ADRs                      |
| [Data Model](docs/architecture/DATA_MODEL.md)          | Neo4j graph schema, Cypher query patterns                      |
| [Event Bus](docs/architecture/EVENT_BUS.md)            | 9 Kafka topics, full JSON event schemas                        |
| [Simulation Engine](docs/architecture/SIMULATION.md)   | Time model, weather FSM, cascade rules, special events         |
| [Monitoring](docs/infra/MONITORING.md)                 | 47 Prometheus metrics, 5 Grafana dashboards, alerting rules    |
| [Docker](docs/infra/DOCKER.md)                         | Full docker-compose.yml, Dockerfile templates, useful commands |

---

## Simulated airport profile

| Attribute         | Value                                      |
| ----------------- | ------------------------------------------ |
| Airport           | Arthur International Airport               |
| IATA / ICAO       | ART / KART                                 |
| Terminals         | 3 (A, B, C)                                |
| Gates             | 42 (A01–A14 · B01–B14 · C01–C14)           |
| Runways           | 2 (09L/27R · 09R/27L)                      |
| Daily flights     | ~420 movements                             |
| Daily passengers  | ~30,000                                    |
| Airlines          | 12 fictional carriers                      |
| Baggage carousels | 6                                          |
| Simulation speed  | 60× default (1 real second = 1 sim minute) |

---

## License

MIT — all data is fictional and for educational purposes only.
