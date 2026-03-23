# Architecture overview

**Project:** Arthur International Airport Digital Twin  
**Version:** 1.0  
**Status:** Specification

---

## 1. Goals

The system models the operational state of Arthur International Airport (IATA: `ART`) in real time using fully simulated data. Three core concerns drive every design decision:

1. **Observability** — any operator should be able to see the full airport state (flights, passengers, baggage, weather, incidents) from a single dashboard at any point in time.
2. **Fidelity** — the simulation must propagate real-world causal relationships: a weather event degrades runway capacity, which delays flights, which cascades into gate conflicts, crew holds, baggage reroutes, and passenger disruption.
3. **Teachability** — every component should be independently understandable. A developer reading one service spec should be able to implement it without reading all others.

---

## 2. System context

```
External world (simulated)
  ├── Weather engine       → produces weather state changes
  ├── Airline schedules    → seed flight timetables
  └── Incident injector    → fires hazardous events (manual or probabilistic)

Airport Digital Twin
  ├── 6 domain microservices  (Python / FastAPI)
  ├── 1 API gateway            (Node.js / Express)
  ├── 1 simulation orchestrator
  ├── Kafka event bus          (async inter-service communication)
  ├── Neo4j graph database     (entity state + relationships)
  ├── Prometheus + Grafana     (metrics + dashboards)
  └── React frontend           (5 operator dashboards)
```

---

## 3. Service map

| Service | Language | Responsibility |
|---|---|---|
| `flight-service` | Python / FastAPI | Flight lifecycle: scheduled → boarding → airborne → landed |
| `passenger-service` | Python / FastAPI | Passenger flow: check-in → security → gate → boarded |
| `baggage-service` | Python / FastAPI | Baggage flow: drop-off → sorting → carousel |
| `weather-service` | Python / FastAPI | Weather state machine, METAR simulation, runway impact |
| `incident-service` | Python / FastAPI | Hazard lifecycle, alert generation, cascade triggering |
| `sim-orchestrator` | Python | Simulation clock, schedule seeding, event injection |
| `api-gateway` | Node.js / Express | REST aggregation, WebSocket fan-out, auth (JWT stub) |

---

## 4. Communication patterns

### Synchronous (REST)
Used exclusively between the API gateway and external clients (dashboards, developers). No service-to-service REST calls — all cross-domain communication is async via Kafka.

### Asynchronous (Kafka)
Every state change in any domain produces a Kafka event. Other services consume relevant topics and update their own state independently. This decouples producers from consumers and enables replay.

```
flight-service   → topic: flights.events
passenger-service→ topic: passengers.events
baggage-service  → topic: baggage.events
weather-service  → topic: weather.events
incident-service → topic: incidents.events
                   topic: incidents.alerts
```

### Real-time push (WebSocket)
The API gateway subscribes to all Kafka topics and fans out relevant events to connected dashboard clients over WebSocket. Dashboards never poll — they react to pushed events.

---

## 5. Data stores

### Neo4j (primary entity store)
All airport entities and their relationships live in Neo4j. The graph model is the single source of truth for structural state (which flight is at which gate, which passenger is on which flight, which baggage belongs to which passenger).

See [DATA_MODEL.md](DATA_MODEL.md) for the full schema.

### In-process state (per service)
Each service maintains a small in-memory state cache (Python dict / Redis optional) for hot-path reads (e.g. current runway status, active queue lengths). This cache is always derived from Neo4j and Kafka — it can be rebuilt on restart.

### Kafka (event log)
Kafka is the system's event log. Every domain event is persisted in Kafka with a configurable retention (default: 7 days simulated time). This enables time-travel replay and audit.

---

## 6. Simulation clock

The simulation orchestrator controls a virtual clock that can run at configurable speeds:

| Speed | 1 simulated minute = |
|---|---|
| 1× (real time) | 1 real second |
| 10× | 6 real seconds |
| 60× (default) | 1 real second |
| 3600× (fast-forward) | 1 real millisecond |

All services consume the `sim.clock` Kafka topic to advance their internal time. No service has a wall-clock dependency.

---

## 7. Technology decisions (ADRs)

### ADR-001 — Neo4j for entity storage

**Decision:** Use Neo4j as the primary database.  
**Rationale:** Airport entities are naturally a graph. A flight (`Flight`) connects to a gate (`Gate`), which belongs to a terminal (`Terminal`). A passenger (`Passenger`) is assigned to a flight and carries baggage (`Baggage`). Neo4j's Cypher query language makes these traversals trivial (e.g. "find all passengers whose baggage is on a delayed flight departing from Terminal B"). A relational schema would require 6+ joins for the same query.  
**Trade-off:** Neo4j has a steeper learning curve than Postgres. Mitigated by keeping the schema simple and documenting every query pattern in DATA_MODEL.md.

### ADR-002 — Kafka for all inter-service events

**Decision:** All cross-service communication uses Kafka topics.  
**Rationale:** Decouples services completely. The incident service can cascade a baggage fire alert to flight, passenger, and baggage services simultaneously without knowing their APIs. New services (e.g. a future retail service) can subscribe without touching existing code.  
**Trade-off:** Adds operational complexity (Kafka cluster, schema registry). Acceptable for a portfolio project demonstrating production patterns.

### ADR-003 — Python / FastAPI for domain services

**Decision:** All domain microservices are written in Python using FastAPI.  
**Rationale:** FastAPI provides automatic OpenAPI documentation (essential for a teaching project), async support via ASGI, and excellent ecosystem support for Kafka (confluent-kafka-python) and Neo4j (neo4j-driver).  
**Trade-off:** Python is slower than Go or Rust for CPU-bound work. Not a concern here — simulation logic is I/O-bound and the dataset is small.

### ADR-004 — Node.js / Express for the API gateway

**Decision:** The API gateway is Node.js.  
**Rationale:** Node.js excels at I/O multiplexing and WebSocket fan-out — exactly the gateway's job. Having one service in a different language also demonstrates polyglot microservices.  
**Trade-off:** Two language runtimes in the monorepo. Mitigated by keeping the gateway thin (no business logic).

### ADR-005 — SpacetimeDB as optional real-time entity layer

**Decision:** SpacetimeDB is specified as an optional replacement/complement for Neo4j for entity state.  
**Rationale:** SpacetimeDB is designed for real-time multiplayer simulations — its subscription model and reducer pattern map naturally to the digital twin's needs. It would eliminate the need for the Kafka → WebSocket fan-out in the gateway.  
**Trade-off:** SpacetimeDB is early-stage software. The spec documents both paths; the reference implementation uses Neo4j + Kafka.

### ADR-006 — All simulation data is fake

**Decision:** No real airport, airline, passenger, or flight data is used anywhere.  
**Rationale:** Avoids GDPR concerns, airline data licensing, and real-world incident sensitivity. The simulation is entirely self-contained.  
**Implementation:** The sim-orchestrator seeds all data on startup from a configurable `fixtures/` directory containing fake airline codes, flight numbers, passenger names, and aircraft registrations.

---

## 8. Non-functional requirements

| Concern | Target |
|---|---|
| Simulated throughput | 420 flight movements/day, 18M pax/year (scaled to sim time) |
| WebSocket latency | < 200ms from Kafka event to dashboard render |
| API response time | < 100ms p95 for all GET endpoints |
| Service startup time | < 10s per service (Docker cold start) |
| Fault tolerance | Each service restarts independently; state recoverable from Neo4j + Kafka |
| Observability | All services expose `/metrics` (Prometheus), `/health`, `/ready` |

---

## 9. Security (stub)

Authentication is stubbed for portfolio purposes. The API gateway issues a static JWT on `/auth/token` (no real credentials). All endpoints accept this token via `Authorization: Bearer <token>`. In a production system, this would be replaced with an OAuth2 provider.

No real personal data exists in the system. All passenger names, IDs, and records are randomly generated.
