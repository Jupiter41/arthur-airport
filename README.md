# Arthur International Airport — Digital Twin

> **IATA:** `ART` · **ICAO:** `KART` · **Location:** fictional mid-size hub  
> **Throughput:** ~18M passengers/year · **Runways:** 2 (09L/27R · 09R/27L) · **Terminals:** 3 (A, B, C)

A high-fidelity airport digital twin built on a microservices architecture with fully simulated, fake data. Models real-time flight operations, passenger flows, baggage handling, weather impacts, and hazardous incident propagation — including cascading delay effects across all systems.

---

## Purpose

This project serves as:
- A **portfolio reference** for event-driven microservices design
- A **teaching example** for graph data modelling, real-time streaming, and simulation engines
- A **playground** for incident response and cascading failure visualization

All data is 100% synthetic. No real airport, airline, or passenger data is used.

---

## Architecture at a glance

```
┌─────────────────────────────────────────────────────────┐
│                    React Dashboards                      │
│  Flight Board · Baggage Tracker · Passenger Flow        │
│  Incident Console · Ground Ops View                     │
└───────────────────┬─────────────────────────────────────┘
                    │ REST + WebSocket
┌───────────────────▼─────────────────────────────────────┐
│                   API Gateway (Node.js)                  │
└──┬──────────┬──────────┬──────────┬──────────┬──────────┘
   │          │          │          │          │
 Flight  Passenger  Baggage  Weather  Incident  (FastAPI services)
   │          │          │          │          │
└─────────────────────────────────────────────────────────┐
│                  Kafka Event Bus                         │
│  flights · passengers · baggage · weather · incidents   │
└─────────────────────────────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────────┐
│              Neo4j Graph Database                        │
│  Nodes: Flight · Gate · Passenger · Baggage · Runway    │
└─────────────────────────────────────────────────────────┘
```

---

## Repository structure

```
airport-digital-twin/
├── README.md                      ← you are here
├── docker-compose.yml
├── docs/
│   ├── architecture/
│   │   ├── OVERVIEW.md            ← system design & ADRs
│   │   ├── DATA_MODEL.md          ← Neo4j graph schema
│   │   ├── EVENT_BUS.md           ← Kafka topics & event schemas
│   │   └── SIMULATION.md         ← simulation engine design
│   ├── services/
│   │   ├── flight-service/SPEC.md
│   │   ├── passenger-service/SPEC.md
│   │   ├── baggage-service/SPEC.md
│   │   ├── weather-service/SPEC.md
│   │   ├── incident-service/SPEC.md
│   │   ├── sim-orchestrator/SPEC.md
│   │   └── api-gateway/SPEC.md
│   ├── dashboards/
│   │   ├── FLIGHT_BOARD.md
│   │   ├── BAGGAGE_TRACKER.md
│   │   ├── PASSENGER_FLOW.md
│   │   ├── INCIDENT.md
│   │   └── GROUND_OPS.md
│   └── infra/
│       ├── MONITORING.md
│       └── DOCKER.md
├── services/
│   ├── flight-service/            ← Python / FastAPI
│   ├── passenger-service/         ← Python / FastAPI
│   ├── baggage-service/           ← Python / FastAPI
│   ├── weather-service/           ← Python / FastAPI
│   ├── incident-service/          ← Python / FastAPI
│   ├── sim-orchestrator/          ← Python
│   └── api-gateway/               ← Node.js / Express
└── dashboards/
    └── art-dashboard/             ← React + TypeScript
```

---

## Quickstart

### Prerequisites

- Docker ≥ 24 and Docker Compose ≥ 2.20
- Node.js ≥ 20 (for dashboard development only)
- Python ≥ 3.11 (for service development only)

### Run everything

```bash
git clone https://github.com/your-org/airport-digital-twin.git
cd airport-digital-twin
docker compose up --build
```

### Service URLs (after startup)

| Service | URL |
|---|---|
| API Gateway | http://localhost:3000 |
| Flight Service | http://localhost:8001/docs |
| Passenger Service | http://localhost:8002/docs |
| Baggage Service | http://localhost:8003/docs |
| Weather Service | http://localhost:8004/docs |
| Incident Service | http://localhost:8005/docs |
| Sim Orchestrator | http://localhost:8006/docs |
| React Dashboard | http://localhost:5173 |
| Neo4j Browser | http://localhost:7474 |
| Kafka UI | http://localhost:8080 |
| Grafana | http://localhost:3001 |
| Prometheus | http://localhost:9090 |

---

## Simulated airport profile

| Attribute | Value |
|---|---|
| Airport name | Arthur International Airport |
| IATA / ICAO | ART / KART |
| City | Arthur City (fictional) |
| Terminals | 3 (A, B, C) |
| Gates | 42 total (A1–A14, B1–B14, C1–C14) |
| Runways | 2 (09L/27R · 09R/27L) |
| Annual passengers | ~18,000,000 (simulated) |
| Daily flights | ~420 movements (simulated) |
| Airlines | 12 fictional carriers |
| Baggage carousels | 6 (one per pier) |

---

## Key simulation features

- **High-fidelity time engine** — configurable simulation speed (1×, 10×, 60×, 3600×)
- **Weather state machine** — CAVOK → VMC → IMC → LIFR with realistic transition probabilities
- **Cascading delay propagation** — a delayed inbound flight triggers gate reassignment, crew hold, baggage reroute, and passenger notification in sequence
- **Dual-trigger hazardous events** — manually injectable via API or probabilistically fired by the simulation engine
- **Five hazard types** — runway incursion, baggage fire, security breach, severe weather, system failure

---

## Documentation index

| Document | Description |
|---|---|
| [Architecture Overview](docs/architecture/OVERVIEW.md) | System design, technology choices, ADRs |
| [Data Model](docs/architecture/DATA_MODEL.md) | Neo4j graph schema, entity definitions |
| [Event Bus](docs/architecture/EVENT_BUS.md) | Kafka topics, Avro schemas, consumer groups |
| [Simulation Engine](docs/architecture/SIMULATION.md) | Time model, weather FSM, cascade logic |

---

## License

MIT — all data is fictional and for educational purposes only.
