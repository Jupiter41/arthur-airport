# Arthur International Airport — Digital Twin

![CI](https://github.com/arthur-airport/arthur-airport/actions/workflows/ci.yml/badge.svg)

> **IATA:** `ART` · **ICAO:** `KART` · **Location:** fictional mid-size hub
> **Throughput:** ~18M passengers/year · **Runways:** 2 (09L/27R · 09R/27L) · **Terminals:** 3 (A, B, C)

A high-fidelity airport digital twin built on a microservices architecture with simulation-first behavior and optional real-data adapters. Models real-time flight operations, passenger flows, baggage handling, weather impacts, and hazardous incident propagation — including cascading delay effects and a LightGBM forecasting model for security queue prediction.

This project is **spec-first and agent-ready**: every service, data model, and API contract is fully documented before any code is written, and the repository is structured so that AI coding agents (Claude Code, Cursor, GitHub Copilot, OpenAI Codex) can navigate, implement, and extend the codebase with minimal manual explanation.

## Current maturity

This repository now includes major roadmap delivery work beyond the initial simulator baseline:

- Gap 0 documentation hardening completed
- Gap 0.5 dashboard upgrades completed (sorting, history/archive/export foundations)
- Gap 1 spatial layout implementation completed in core services
- Scenario engine and scenario lifecycle workflows delivered (create/edit/delete/fork for custom scenarios)
- Geospatial world-map dashboard delivered (`/world`) with Mapbox and tokenless fallback path
- Airport config system fully integrated across the stack

Follow project evolution in:

- [TIMELINE.md](TIMELINE.md) for phase-by-phase vision and capability layering
- [QUICKSTART.md](QUICKSTART.md) for a quick start and dashboard overview
- [ROADMAP.md](ROADMAP.md) for gap tracking and implementation status
- [CHANGELOG.md](CHANGELOG.md) for sprint-level delivered work
- [docs/lessons-learned/](docs/lessons-learned/) for implementation reports and postmortems

---

## Purpose

- A **portfolio reference** for event-driven microservices design at scale
- A **teaching example** for graph data modelling, real-time streaming, simulation engines, and ML forecasting
- A **playground** for incident response, cascading failure visualization, and hazardous event simulation
- A **reference implementation** for agent-assisted development workflows with SKILL.md files

Default runtime behavior is synthetic/simulated. The repo also includes optional external-data adapters (for example OpenSky ADS-B overlay and weather live/historical modes) plus offline fixture generation from open datasets (OurAirports/OpenFlights/IEM).

---

## Airport Config System

The simulation is **config-driven**: customize every airport property by editing a single `config/airport.yaml` file without touching code.

### What you can configure

**Airport Identity:**

- Name, IATA code, ICAO code, timezone

**Infrastructure:**

- Number of terminals (1–26, named A–Z)
- Gates per terminal
- Runway pairs (quantity, length, ILS capability)

**Simulation Defaults:**

- Daily flight volume
- Passenger load factor distribution
- Peak hours (for incident injection modifiers)

**Airline Overrides:**

- Customize airline codes, names, market shares, and hub terminals

**Flight Type Distribution:**

- Control the mix of domestic, international short/long, cargo, and charter flights
- Values must sum to 1.0 (e.g., `domestic: 0.42, cargo: 0.08, charter: 0.04`)

### Quick start with custom airport — the 60-second version

1. **Edit** `config/airport.yaml`:

   ```yaml
   identity:
     name: "London Heathrow"
     iata: "LHR"
     icao: "EGLL"
     timezone: "Europe/London"
   infrastructure:
     terminals: 5
     gates_per_terminal: [28, 32, 26, 60, 10]
     runways:
       - id: "09L/27R"
         length_m: 3902
         ils: true
   ```

2. **Validate** your config:

   ```bash
   python scripts/helper_validate_airport_config.py --path config/airport.yaml
   ```

3. **Run** the stack:
   ```bash
   docker compose up --build
   ```

The sim-orchestrator will load your config, seed the airport, and start the simulation.

### Verify runtime behavior

```bash
# Get a JWT token
TOKEN=$(curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)

# Check active airport identity
curl http://localhost:3000/api/v1/airport \
  -H "Authorization: Bearer $TOKEN" | jq '.airport'

# Should output something like:
# {
#   "name": "London Heathrow",
#   "iata": "LHR",
#   "icao": "EGLL",
#   "timezone": "Europe/London"
# }
```

### Full customization guide

For detailed configuration options, constraints, and advanced features, see **[HOW_TO_CREATE_AIRPORT.md](HOW_TO_CREATE_AIRPORT.md)**.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        React Dashboards                          │
│  Flight Board · Baggage Tracker · Passenger Flow (+ forecast)   │
│  Incident Console · Ground Ops · World Map · History            │
│  Scenarios · ML Training · Settings · Debug                     │
└─────────────────────────┬────────────────────────────────────────┘
                          │ REST + WebSocket
┌─────────────────────────▼────────────────────────────────────────┐
│                    API Gateway  (Node.js / Express)              │
│         JWT auth · rate limiting · Kafka → WS fan-out           │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬─────────────────────┘
   │      │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼      ▼
Flight  Pax   Baggage Weather Incident SimOrch Analysis
:8001  :8002  :8003   :8004   :8005   :8006  :8007
   │      │      │      │      │      │      │
   └──────┴──────┴──────┴──────┴──────┴──────┘
                          │
               ┌──────────▼──────────┐
               │    Kafka Event Bus   │
               │  10 topics · schemas │
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

Each service is independently deployable, has its own README with setup instructions, and a detailed specification document. Click the links below to go directly to the area you're interested in.

| Service                                              | Port | What it does                                                                                                                                                                                                                                                                                                                                             | Docs                                                                                           |
| ---------------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **[flight-service](services/flight-service/)**       | 8001 | Manages the full lifecycle of every flight at KART through a 9-state finite state machine. Handles runway slot scheduling via a priority-based queue, resolves gate conflicts when delays cause overlapping assignments, and propagates turnaround delays to paired outbound flights up to 5 cascading hops.                                             | [SPEC](docs/services/flight-service/SPEC.md) · [SKILL](services/flight-service/SKILL.md)       |
| **[passenger-service](services/passenger-service/)** | 8002 | Tracks every passenger from check-in to boarding (departures) or landing to exit (arrivals). Simulates 3 terminal security checkpoints with congestion slowdown, detects at-risk connecting passengers, publishes zone density for the heatmap dashboard, and runs a **LightGBM forecasting model** that predicts security queue depth 90 minutes ahead. | [SPEC](docs/services/passenger-service/SPEC.md) · [SKILL](services/passenger-service/SKILL.md) |
| **[baggage-service](services/baggage-service/)**     | 8003 | Simulates the full baggage handling chain through an in-memory conveyor pipeline with 30+ zones. Each zone has a throughput cap (600–1800 items/hr). Includes a probabilistic DG (dangerous goods) screening model with per-IATA-class detection rates, and handles flight-cancellation offload routing.                                                 | [SPEC](docs/services/baggage-service/SPEC.md) · [SKILL](services/baggage-service/SKILL.md)     |
| **[weather-service](services/weather-service/)**     | 8004 | Runs a 4-state weather finite state machine (CAVOK → VMC → IMC → LIFR) with probabilistic hourly transitions. Samples realistic meteorological parameters, generates ICAO-format METAR and TAF strings, and computes runway capacity reductions from weather and wind conditions.                                                                        | [SPEC](docs/services/weather-service/SPEC.md) · [SKILL](services/weather-service/SKILL.md)     |
| **[incident-service](services/incident-service/)**   | 8005 | Manages hazardous events from creation to resolution. Features a **rule-based cascade engine** that spawns child incidents (e.g. runway_incursion → ground_stop → gate_congestion), emergency protocol activation with override semantics, alert generation, and automated incident report creation.                                                     | [SPEC](docs/services/incident-service/SPEC.md) · [SKILL](services/incident-service/SKILL.md)   |
| **[sim-orchestrator](services/sim-orchestrator/)**   | 8006 | The conductor — drives a virtual clock at configurable speed, seeds realistic daily schedules (420 flights, ~30K passengers, ~36K baggage items), and evaluates probabilistic hazardous event injection each simulated hour. See the [Simulation deep-dive](#simulation-deep-dive) section below.                                                        | [SPEC](docs/services/sim-orchestrator/SPEC.md) · [SKILL](services/sim-orchestrator/SKILL.md)   |
| **[api-gateway](services/api-gateway/)**             | 3000 | Node.js/Express gateway — proxies REST to upstream services, fans out Kafka events to dashboard WebSocket clients, handles stub JWT auth, and provides an aggregate `/airport` endpoint.                                                                                                                                                                 | [SPEC](docs/services/api-gateway/SPEC.md) · [SKILL](services/api-gateway/SKILL.md)             |
| **[dashboard](dashboards/art-dashboard/)**           | 5173 | React + TypeScript SPA with operator views: Flight Board, Passenger Flow, Baggage Tracker, Ground Ops, Incident Console, World Map, History, Scenarios, and Settings. Uses Zustand for state, React Query for REST, and native WebSocket for real-time updates.                                                                                          | [Flight Board](docs/dashboards/FLIGHT_BOARD.md) · [All dashboards](docs/dashboards/)           |

### Simulation features

- **Configurable time engine** — 1×, 10×, 60× (default), 600×, 3600× speed
- **4-state weather FSM** — CAVOK → VMC → IMC → LIFR with probabilistic hourly transitions
- **Cascading delay propagation** — inbound delay → gate conflict → baggage hold → connecting pax alert → turnaround outbound, up to 5 hops
- **5 hazard types** — runway incursion, baggage fire, security breach, severe weather, system failure — each with a defined cascade tree, TTR range, and emergency protocol
- **Dual-trigger incidents** — manually injectable via API or probabilistically fired by the sim engine
- **LightGBM security queue forecasting** — 12-feature model trained on simulated history, predicts queue depth 90 sim-minutes ahead, triggers congestion incidents when demand exceeds forecast by 30%
- **Special events calendar** — configurable demand multipliers per sim day (marathons, peaks, conferences)

---

## Simulation deep-dive

> For full technical details, see [docs/architecture/SIMULATION.md](docs/architecture/SIMULATION.md)
> For architectural diagrams, see [docs/architecture/ARCHITECTURE_DIAGRAM.md](docs/architecture/ARCHITECTURE_DIAGRAM.md)

The simulation is the heart of the digital twin. By default it is self-contained and does not require external feeds. Optional adapters can be enabled for specific domains (for example ADS-B overlay and weather live/historical sources).

### What is simulated

| Domain              | What's modelled                                                     | Hypothesis / model                                                                                                                            |
| ------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **Flights**         | 420 daily movements through a 9-state lifecycle FSM                 | Bimodal departure distribution (peaks 07:30, 17:30). Turnaround = 90 min. Delay auto-cancels at 180 min.                                      |
| **Passengers**      | ~30,000/day through check-in → security → airside → gate → boarding | Load factor ~ Beta(8,2) ≈ 80%. Security throughput = 180 pax/hr/lane. Dwell time ~ Normal(25, 12) min. 20% connecting, 5% special assistance. |
| **Baggage**         | ~36,000 items/day through a 30+ zone conveyor pipeline              | Per-passenger bags ~ Poisson(λ=1.2). Weight ~ Normal(18kg, 4kg). DG rate = 0.2%. Zone throughput from IATA standards.                         |
| **Weather**         | 4-state FSM with realistic meteorological parameter sampling        | Markov chain with hourly transitions. Visibility, wind, ceiling, QNH sampled per category. METAR/TAF in ICAO format.                          |
| **Incidents**       | 5 hazard types with cascade trees up to depth 5                     | Per-type base probability/hr. Modifiers: ×1.8 peak, ×0.3 suppression. TTR sampled from type-specific ranges.                                  |
| **Runway capacity** | 6–64 movements/hr depending on weather + wind                       | Category-based base cap. Crosswind > 25kt → ×0.85. Tailwind > 10kt → ×0.70. IMC/LIFR → single runway.                                         |

### How cascading effects work

The cascade engine is what makes the simulation feel realistic. A single event (e.g. a weather change) can ripple across the entire airport:

```
Weather degrades to IMC
  → Runway capacity drops from 32/hr to 18/hr (weather-service)
    → Departure queue builds up (flight-service)
      → Gate assignments overlap (flight-service → gate conflict)
        → Passengers get gate-change alerts (passenger-service)
      → Connecting passengers miss MCT (passenger-service → missed_connection)
    → Holding stack for arrivals (flight-service)
  → incident-service creates severe_weather incident
    → Cascade: capacity_reduction → holding_stack → ground_delay → flight_delays_cascade
```

Each service reacts independently to Kafka events — there are no orchestrated workflows. The emergent behaviour arises from the event-driven architecture.

### Implementation example: security queue forecasting

The passenger-service includes a LightGBM model for predicting queue depth:

1. **Feature collection** (`ml/features.py`): 12 features including `hour_of_day`, `departures_next_90min`, `current_queue_depth`, `weather_category`, `incidents_active`
2. **Training** (`ml/training.py`): rows accumulated in a deque (max 10K per terminal), flushed to Parquet hourly, model retrained every 3 sim-days using temporal split validation
3. **Inference** (`ml/inference.py`): model predicts queue depth 90 minutes ahead. Before enough data exists (day 1–3), a simple fallback formula is used: `forecast = expected_pax × 0.35`
4. **Congestion detection** (`ml/congestion.py`): when actual queue depth exceeds forecast by 30%, a `SecurityCongestionDetected` event is emitted, which the incident-service may escalate

---

## Quickstart

### Prerequisites

- **Docker** ≥ 24 and **Docker Compose** ≥ 2.20 (required for full stack)
- **Python** ≥ 3.11 (required to validate airport config; optional for service development)
- **Node.js** ≥ 20 (optional, for dashboard development only)
- ~4 GB disk space for Docker images and volumes

### Run the full stack

```bash
git clone https://github.com/Jupiter41/arthur-airport.git
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
| Analysis Service (OpenAPI)  | http://localhost:8007/docs | —                        |
| Neo4j Browser               | http://localhost:7474      | neo4j / art-digital-twin |
| Kafka UI                    | http://localhost:8080      | —                        |
| Grafana                     | http://localhost:3001      | admin / art-grafana      |
| Prometheus                  | http://localhost:9090      | —                        |

### Default credentials

All credentials are for **local development only**. Never reuse these in production.

| Service         | Username | Password               | Notes                                            |
| --------------- | -------- | ---------------------- | ------------------------------------------------ |
| Neo4j           | `neo4j`  | `art-digital-twin`     | Browser at `:7474`, Bolt at `:7687`              |
| Grafana         | `admin`  | `art-grafana`          | Web UI at `:3001`                                |
| API Gateway JWT | —        | `art-digital-twin-dev` | `JWT_SECRET` env var; used to sign/verify tokens |
| Kafka UI        | —        | —                      | No auth (dev mode)                               |
| Prometheus      | —        | —                      | No auth (dev mode)                               |

To obtain a JWT token for the API gateway:

```bash
curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token
```

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

Context files for AI tools include:

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
├── HOW_TO_CREATE_AIRPORT.md          ← airport customization guide
├── CHANGELOG.md                       ← version history by sprint
├── CLAUDE.md                          ← agent context for Claude Code
├── AGENTS.md                          ← agent context for OpenAI / Codex
├── CONTRIBUTING.md
├── LICENSE
├── docker-compose.yml
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
│   ├── sim-orchestrator/              ← Python / FastAPI  (port 8006)
│   ├── analysis-service/              ← Python / FastAPI  (port 8007)
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

| Document                                                           | Description                                                             |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| [Architecture Overview](docs/architecture/OVERVIEW.md)             | System design, technology choices, 6 ADRs                               |
| [Architecture Diagrams](docs/architecture/ARCHITECTURE_DIAGRAM.md) | Mermaid diagrams: system overview, event flow, state machines, cascades |
| [Data Model](docs/architecture/DATA_MODEL.md)                      | Neo4j graph schema, Cypher query patterns                               |
| [Event Bus](docs/architecture/EVENT_BUS.md)                        | 9 Kafka topics, full JSON event schemas                                 |
| [Simulation Engine](docs/architecture/SIMULATION.md)               | Time model, weather FSM, cascade rules, special events                  |
| [Monitoring](docs/infra/MONITORING.md)                             | 47 Prometheus metrics, 5 Grafana dashboards, alerting rules             |
| [Docker](docs/infra/DOCKER.md)                                     | Full docker-compose.yml, Dockerfile templates, useful commands          |

Additional planning and implementation history:

- [ROADMAP.md](ROADMAP.md) — long-horizon gaps, priorities, and acceptance targets
- [TIMELINE.md](TIMELINE.md) — phased progression from operations simulator to prescriptive twin
- [CHANGELOG.md](CHANGELOG.md) — sprint-by-sprint release notes
- [docs/lessons-learned/](docs/lessons-learned/) — implementation reports, decisions, and fixes

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

## Testing

```bash
# Run unit tests (no external dependencies required)
pip install pytest
python -m pytest tests/unit/ -v

# Run integration tests (requires full stack running)
docker compose up --build -d
pip install pytest requests
python -m pytest tests/integration/ -v

# Run resilience tests (restarts services — requires full stack)
python -m pytest tests/integration/test_resilience.py -v -s
```

CI runs automatically on push/PR via `.github/workflows/ci.yml`.

---

## License

MIT — all data is fictional and for educational purposes only.
