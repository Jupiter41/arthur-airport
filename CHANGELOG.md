# Changelog — Arthur International Airport Digital Twin

All notable changes to this project are documented in this file.

---

## Sprint 10 — Polish and Hardening (2026-03-24)

### Added
- **Unit test suite** — 256 tests covering all state machines, FSMs, and pure-logic modules
  (flight FSM, weather FSM, passenger flows, connection risk, security model, conveyor pipeline,
  DG screening, incident cascade rules, lifecycle, protocols, runway queue)
- **Integration test suite** — REST endpoint tests for all 7 services + gateway proxy routes,
  idempotency tests, cascade depth verification, resilience/restart recovery tests
- **CI pipeline** — `.github/workflows/ci.yml` with lint (ruff + eslint), unit tests (pytest),
  and Docker Compose build stages
- **CHANGELOG.md** — this file
- **Smoke test script** — `scripts/smoke-test.sh` for clean-machine verification
- **Sprint 10 lessons learned** — `docs/lessons-learned/sprint-10.md`

### Changed
- Updated SKILL.md files with discovered gotchas from implementation
- Verified all README links resolve correctly
- Updated TODO.md with all Sprint 10 tasks marked complete

---

## Sprint 9 — Observability (Completed)

### Added
- Prometheus scraping for all 9 service targets
- 5 Grafana dashboards (sim overview, flight ops, passenger/baggage, weather/incidents, API/system)
- Alerting rules: SimulationPaused, CriticalIncidentActive, ConveyorZoneOffline
- Domain-specific metrics per service (flight delays, passenger queues, baggage throughput, etc.)

### Fixed
- Metric timing/placement gaps for transient operational states

---

## Sprint 8 — React Dashboard (Completed)

### Added
- **Flight Board** — FIDS panels, boarding bars, detail drawers, runway status, critical banners
- **Baggage Tracker** — SVG conveyor map, zone coloring, loading bars, flagged panel
- **Passenger Flow** — zone heatmap, security queue cards, connection risk list
- **Incident Console** — incident cards, cascade tree visualizer, protocol bar, alert feed,
  injection modal, report download
- **Ground Ops** — SVG airfield schematic, runway arrows, holding stack, weather compass
- Zustand stores for all domains + useWebSocket/useApi hooks

### Fixed
- Duplicate WebSocket connections in dev mode (React StrictMode)
- Payload shape inconsistencies between gateway and dashboard
- Null/missing-field handling in real-time updates

---

## Sprint 7 — API Gateway (Completed)

### Added
- Express/TypeScript gateway unifying all 6 service APIs behind `/api/v1/`
- JWT authentication (`POST /auth/token` + Bearer middleware)
- WebSocket fan-out from all Kafka topics with subscription filtering
- `/api/v1/airport` aggregate endpoint (Promise.allSettled)
- `/api/v1/health/services` service health aggregation
- Rate limiting per route tier (200/min default, 50/min injection, 10/min reset)

### Fixed
- Proxy body forwarding for POST/PATCH requests
- Graceful degradation when upstream services are down

---

## Sprint 6 — Incident Service (Completed)

### Added
- Incident lifecycle management (create → contain → resolve)
- 5 hazard types: runway_incursion, baggage_fire, security_breach, severe_weather, system_failure
- Cascade engine with rule-based child spawning (max depth = 5)
- Emergency protocol activation (RUNWAY_STOP, BAGGAGE_HOLD, ZONE_LOCKDOWN, etc.)
- TTR auto-resolution countdown
- Incident report generation
- WebSocket real-time alerts

### Fixed
- Cascade cycle prevention via tracking set
- Protocol/protocols payload shape normalization

---

## Sprint 5 — Passenger Service + ML Forecasting (Completed)

### Added
- Passenger departure flow: checked_in → security_queue → airside → at_gate → boarded
- Passenger arrival flow: deplaning → baggage_claim → departed_airport
- Connection risk monitoring (MCT 45 min, 4-tier risk levels)
- Security checkpoint throughput model with slowdown factor
- LightGBM queue forecasting (trains after day 3, hot-reload on retrain)
- Congestion detection with consecutive-tick counter
- Zone density tracking rebuilt from Neo4j on startup

### Fixed
- Terminal distribution fallback for flights without gate assignment
- In-memory security queue rebuild on restart
- Boarding catch-up logic for mid-simulation startup

---

## Sprint 4 — Baggage Service (Completed)

### Added
- Conveyor pipeline (induction → screening → sorting → make-up → loading)
- DG screening per IATA class with configurable detection rates
- System failure → zone halt/resume behavior
- Flight cancellation → baggage offload + carousel return
- Zone throughput backpressure model

### Fixed
- Stuck-flow startup via robust induction rules
- Fast-track transitions for already-departed-flight baggage

---

## Sprint 3 — Flight Service (Completed)

### Added
- 9-state flight FSM (scheduled → boarding → departed → airborne → approach → landed → taxiing → at_gate)
- Runway slot assignment with priority queue (emergency priority, weather-dependent capacity)
- Gate conflict detection and nearest-available resolution
- Turnaround delay propagation with buffer subtraction
- Flight hold/release manual controls

### Fixed
- Timezone normalization for ISO datetime comparisons
- Re-enqueue behavior for runway queue
- Cypher aggregation/duplication issues

---

## Sprint 2 — Weather Service (Completed)

### Added
- 4-state weather FSM (CAVOK → VMC → IMC → LIFR)
- Transition matrix with gradual-improvement constraint (max 1-step jumps)
- METAR/TAF string generation
- Runway capacity calculation with crosswind/tailwind reductions
- Weather history chain in Neo4j

### Fixed
- Simulation-time query logic
- Event deduplication for weather history

---

## Sprint 1 — Simulation Orchestrator (Completed)

### Added
- Simulation clock loop with configurable speed (1x–3600x)
- Deterministic day seeding (flights, passengers, baggage)
- Bimodal departure slot distribution (peaks at 07:30 and 17:30)
- Airport graph structure seeded in Neo4j (3 terminals, 42 gates, 2 runway pairs)
- Control API (pause, resume, speed, reset, inject)
- Probabilistic incident injection per sim-hour

### Fixed
- Bulk insert performance for large Neo4j datasets
- Departures-only passenger generation alignment

---

## Sprint 0 — Infrastructure Skeleton (Completed)

### Added
- Docker Compose with 15 containers (6 services + gateway + dashboard + Neo4j + Kafka + Zookeeper + Kafka UI + Prometheus + Grafana)
- FastAPI service template with /health, /ready, /metrics
- Prometheus scrape configuration
- Grafana datasource provisioning
