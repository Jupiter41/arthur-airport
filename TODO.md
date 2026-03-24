# TODO — Implementation roadmap

Spec-first sprint plan. Each sprint has a clear **desired output** — a verifiable state the
system must reach before moving to the next sprint. Validate the output, iterate until it passes,
then move on.

Work with an agent by pointing it at the sprint tasks + the relevant spec and skill files.
Example prompt pattern:

```
Read docs/services/weather-service/SPEC.md and services/weather-service/SKILL.md,
then implement sprint 3 task 2: the weather FSM.
```

---

## Sprint 0 — Infrastructure skeleton

**Goal:** The full infrastructure layer runs locally. Every service can connect to Neo4j and Kafka.
No domain code yet — just the plumbing.

### Tasks

- [x] Write `docker-compose.yml` from `docs/infra/DOCKER.md §2`
- [x] Write `infra/prometheus/prometheus.yml` from `docs/infra/MONITORING.md §2`
- [x] Write `infra/prometheus/alerts.yml` from `docs/infra/MONITORING.md §4`
- [x] Write `infra/grafana/provisioning/datasources/prometheus.yml`
- [x] Write `infra/grafana/provisioning/dashboards/dashboards.yml`
- [x] Write minimal Python service scaffold (main.py + /health + /ready + /metrics + Dockerfile)
- [x] Copy scaffold to all 6 Python service directories
- [x] Write Node.js gateway scaffold (Express + /health + /ready + Dockerfile)
- [x] Write React dashboard scaffold (Vite + Tailwind + Dockerfile)

### Desired output

```bash
docker compose up --build

# All containers healthy
docker compose ps

# Neo4j reachable
curl http://localhost:7474

# Kafka reachable
docker compose exec kafka kafka-broker-api-versions --bootstrap-server localhost:9092

# All service health endpoints return 200
for port in 8001 8002 8003 8004 8005 8006 3000; do
  echo -n "port $port: "; curl -s http://localhost:$port/health
done

# Prometheus scraping all targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'
# expected: all "up"

# Grafana loads
curl -s http://localhost:3001/api/health | jq .database
# expected: "ok"
```

---

## Sprint 1 — sim-orchestrator: clock + seeding

**Goal:** The simulation clock runs. Every service receives `SimClockTick` events. Neo4j contains
a seeded airport structure and a full Day 1 flight schedule with passengers and baggage.

### Spec and skills

- `docs/services/sim-orchestrator/SPEC.md`
- `docs/architecture/SIMULATION.md`
- `services/sim-orchestrator/SKILL.md`
- `docs/skills/simulation.SKILL.md`
- `docs/skills/kafka.SKILL.md`

### Tasks

- [x] Write `fixtures/` JSON files — airlines, aircraft_types, destinations, first_names, surnames, nationalities, dg_classes, events
- [x] Implement `db/neo4j.py` — async driver init + constraint/index creation
- [x] Implement `db/seed.py` — airport structure seed (Airport, Terminals, Gates, Runways)
- [x] Implement `services/schedule.py` — bimodal departure slot sampling + flight generation
- [x] Implement `services/passengers.py` — passenger generation per flight (Beta load factor)
- [x] Implement `services/baggage.py` — baggage generation per passenger (Poisson lambda=1.2)
- [x] Implement `kafka/producer.py` — SimClockTick producer + FlightScheduleSeeded batch event
- [x] Implement `services/clock.py` — async clock loop with configurable speed
- [x] Implement `services/injector.py` — probabilistic event evaluation (per simulated hour)
- [x] Implement REST control API: GET /sim/status, PATCH /sim/speed, POST /sim/pause, POST /sim/resume, POST /sim/reset, POST /sim/inject, GET /sim/schedule, GET /sim/metrics
- [x] Update /ready to wait for Neo4j + Kafka healthy

### Desired output

```bash
# Neo4j seeded with correct counts
docker compose exec neo4j cypher-shell -u neo4j -p art-digital-twin \
  "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS total ORDER BY total DESC"
# expected: Flight~420, Passenger~29000+, Baggage~35000+, Gate 42, Terminal 3, Runway 4, Airport 1

# Clock ticking
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic sim.clock --max-messages 5
# expected: 5 SimClockTick JSON envelopes

# Control API
curl http://localhost:8006/api/v1/sim/status | jq .running   # true
curl -X POST http://localhost:8006/api/v1/sim/pause
curl http://localhost:8006/api/v1/sim/status | jq .paused    # true
curl -X POST http://localhost:8006/api/v1/sim/resume
```

---

## Sprint 2 — weather-service

**Goal:** The weather FSM runs, transitions between states, emits METAR events on Kafka, and
the REST endpoints return current conditions and history.

### Spec and skills

- `docs/services/weather-service/SPEC.md`
- `services/weather-service/SKILL.md`

### Tasks

- [x] Implement `db/neo4j.py` — WeatherState node CRUD + chain pointer update (atomic Cypher tx)
- [x] Implement `services/fsm.py` — 4-state FSM with transition matrix + rejection of >1-step jumps
- [x] Implement `services/parameters.py` — meteorological parameter sampling per state
- [x] Implement `services/metar.py` — METAR string builder + simplified TAF generator
- [x] Implement `services/capacity.py` — runway capacity calculator with crosswind/tailwind reductions
- [x] Implement `kafka/consumer.py` — consume sim.clock, evaluate hourly FSM transition
- [x] Implement `kafka/producer.py` — produce WeatherStateChanged + METARIssued (every 30 sim-min)
- [x] Implement REST endpoints: current, metar (plain text), taf (plain text), history, impact
- [x] Implement WS /ws/weather

### Desired output

```bash
# Current conditions with valid METAR
curl http://localhost:8004/api/v1/weather/current | jq '{category, metar_raw}'
curl http://localhost:8004/api/v1/weather/metar
# expected: valid METAR format e.g. "KART 150600Z 09005KT CAVOK 18/12 Q1018"

# Events on Kafka
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic weather.events --max-messages 3

# After 5 sim-hours at 600x speed, history shows at least one transition
curl "http://localhost:8004/api/v1/weather/history?hours=6" | jq '.states | length'
# expected: >= 2

# Runway capacity reflects current category
curl http://localhost:8004/api/v1/weather/impact | jq '{arrival_rate, departure_rate}'
```

---

## Sprint 3 — flight-service

**Goal:** Flights advance through the full state machine. Turnaround delays propagate. Gate
conflicts resolve. All flight events flow on Kafka.

### Spec and skills

- `docs/services/flight-service/SPEC.md`
- `services/flight-service/SKILL.md`
- `docs/skills/neo4j.SKILL.md`

### Tasks

- [x] Implement `db/neo4j.py` — Flight CRUD + gate/runway relationship management
- [x] Implement `services/state_machine.py` — 9-state FSM with all transition conditions
- [x] Implement `services/runway_queue.py` — priority heap + slot assignment per tick
- [x] Implement `services/gate_resolver.py` — conflict detection + nearest available gate query
- [x] Implement `services/turnaround.py` — aircraft registration map + delay propagation with buffer subtraction
- [x] Implement `kafka/consumer.py` — SimClockTick, WeatherStateChanged, IncidentCreated, IncidentStatusChanged
- [x] Implement `kafka/producer.py` — FlightStatusChanged, FlightGateAssigned, FlightRunwayAssigned, FlightCancelled
- [x] Implement REST endpoints: GET /flights, GET /flights/{id}, GET /flights/{id}/cascade, GET /runways, GET /gates, POST /flights/{id}/hold, POST /flights/{id}/release
- [x] Implement WS /ws/flights

### Desired output

```bash
# Flights advancing through states after 5 sim-minutes at 60x
curl "http://localhost:8001/api/v1/flights?status=boarding" | jq '.total'   # > 0
curl "http://localhost:8001/api/v1/flights?status=airborne" | jq '.total'   # > 0
curl "http://localhost:8001/api/v1/flights?status=delayed"  | jq '.total'   # > 0

# Runway queue populated
curl http://localhost:8001/api/v1/runways | jq '.[].arrivals_queued'

# Cascade tree on a delayed flight
FLIGHT_ID=$(curl -s "http://localhost:8001/api/v1/flights?status=boarding&limit=1" \
  | jq -r '.flights[0].id')
curl -X POST http://localhost:8001/api/v1/flights/$FLIGHT_ID/hold \
  -H 'Content-Type: application/json' -d '{"reason":"test","expected_duration_minutes":60}'
curl http://localhost:8001/api/v1/flights/$FLIGHT_ID/cascade | jq .

# Flight events streaming on Kafka
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic flights.events --max-messages 10 \
  | jq .event_type
```

---

## Sprint 4 — baggage-service

**Goal:** Baggage advances through the conveyor pipeline. DG items are detected and flagged.
System failures halt zones. Flight cancellations trigger offloads and carousel return.

### Spec and skills

- `docs/services/baggage-service/SPEC.md`
- `services/baggage-service/SKILL.md`

### Tasks

- [x] Implement `db/neo4j.py` — Baggage CRUD + append-only scan history
- [x] Implement `services/conveyor.py` — in-memory zone state + per-tick throughput drain
- [x] Implement `services/screening.py` — DG detection per class + false positive rate
- [x] Implement `services/offload.py` — cancellation handler + carousel assignment
- [x] Implement `kafka/consumer.py` — SimClockTick, FlightStatusChanged (delayed), FlightCancelled, IncidentCreated (system_failure), IncidentStatusChanged
- [x] Implement `kafka/producer.py` — BaggageStatusChanged, BaggageFlagged
- [x] Implement REST endpoints: GET /baggage, GET /baggage/{id}, GET /baggage/tag/{tag}, GET /flow/summary, GET /flow/map, GET /flagged
- [x] Implement WS /ws/baggage

### Desired output

```bash
# Baggage moving through zones
curl http://localhost:8003/api/v1/flow/summary | jq '.by_status'
# expected: non-zero in inducted, screening, sorting, loaded

# DG items flagged after a few sim-hours
curl http://localhost:8003/api/v1/flagged | jq '.flagged | length'
# expected: >= 1

# Zone map shows live counts
curl http://localhost:8003/api/v1/flow/map | jq '.zones[] | {zone_id, items}'

# System failure halts a zone
curl -X POST http://localhost:8006/api/v1/sim/inject \
  -H 'Content-Type: application/json' \
  -d '{"type":"system_failure","severity":"high","location":"conveyor-sorting"}'
sleep 3
curl http://localhost:8003/api/v1/flow/map \
  | jq '.zones[] | select(.zone_id=="sorting-matrix") | .status'
# expected: "offline"
```

---

## Sprint 5 — passenger-service + forecasting model

**Goal:** Passengers flow through the airport. Security queues build and drain with the slowdown
model active. LightGBM trains after day 3 and produces forecasts. Congestion incidents fire.

### Spec and skills

- `docs/services/passenger-service/SPEC.md`
- `services/passenger-service/SKILL.md`
- `docs/skills/forecasting.SKILL.md`

### Tasks

- [x] Implement `db/neo4j.py` — Passenger CRUD + bulk zone density query
- [x] Implement `services/state_machine.py` — departure + arrival state machines
- [x] Implement `services/security.py` — base throughput + slowdown factor + special assistance lane
- [x] Implement `services/connections.py` — MCT monitoring + 3-tier risk level transitions
- [x] Implement `services/zones.py` — in-memory density tracker rebuilt from Neo4j on startup
- [x] Implement `ml/features.py` — all 12 features including events.json lookup
- [x] Implement `ml/training.py` — deque buffer + parquet flush + LightGBM training pipeline
- [x] Implement `ml/inference.py` — predict + day-1 fallback + hot-reload after retrain
- [x] Implement `ml/congestion.py` — consecutive-tick counter + SecurityCongestionDetected emitter
- [x] Implement `kafka/consumer.py` — SimClockTick, FlightStatusChanged, FlightGateAssigned, FlightCancelled, IncidentCreated, BaggageStatusChanged (collected)
- [x] Implement `kafka/producer.py` — PassengerStatusChanged, PassengerAlert, SecurityCongestionDetected
- [x] Implement REST endpoints: GET /passengers, GET /passengers/{id}, GET /passengers/search, GET /flow/summary, GET /flow/heatmap, GET /flow/forecast, GET /connections/at-risk, GET /alerts
- [x] Implement WS /ws/passengers

### Desired output

```bash
# Passengers in zones
curl http://localhost:8002/api/v1/flow/summary | jq '.by_status'
# expected: non-zero in security_queue, airside, at_gate, boarded

# Security wait times in realistic range
curl http://localhost:8002/api/v1/flow/summary \
  | jq '.security | to_entries[] | {key, wait: .value.wait_minutes}'
# expected: 5-25 min range during peak hours

# At-risk connections
curl http://localhost:8002/api/v1/connections/at-risk | jq '.at_risk | length'

# After 3 sim-days at 3600x (~2 real minutes): model trained, forecast available
curl "http://localhost:8002/api/v1/flow/forecast?terminal=B&window=90" \
  | jq '{model_trained, congestion_risk}'
# expected: model_trained: true

# Congestion event on Kafka after peak hour
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic passengers.events --from-beginning \
  | jq 'select(.event_type=="SecurityCongestionDetected") | .payload.terminal'
```

---

## Sprint 6 — incident-service

**Goal:** All 5 incident types fire, cascade to the defined depth, activate emergency protocols,
auto-resolve after TTR, and generate downloadable incident reports.

### Spec and skills

- `docs/services/incident-service/SPEC.md`
- `services/incident-service/SKILL.md`

### Tasks

- [x] Implement `db/neo4j.py` — Incident CRUD + AFFECTS + SPAWNED relationships
- [x] Implement `services/lifecycle.py` — create, contain, resolve, TTR countdown
- [x] Implement `services/cascade.py` — rule table + depth-limited child creation
- [x] Implement `services/protocols.py` — protocol activation + alert generation
- [x] Implement `services/reports.py` — auto-generated report builder
- [x] Implement `kafka/consumer.py` — SimClockTick (TTR countdown), incidents.inject, WeatherStateChanged (IMC/LIFR auto-create), BaggageFlagged (DG class 3), SecurityCongestionDetected
- [x] Implement `kafka/producer.py` — IncidentCreated, IncidentStatusChanged, IncidentCascaded, IncidentAlert
- [x] Implement REST endpoints: GET /incidents, GET /incidents/{id}, POST /incidents/inject, POST /incidents/{id}/contain, POST /incidents/{id}/resolve, GET /incidents/{id}/report, GET /alerts
- [x] Implement WS /ws/incidents

### Desired output

```bash
# Inject runway incursion, verify cascade tree depth >= 2
curl -X POST http://localhost:8005/api/v1/incidents/inject \
  -H 'Content-Type: application/json' \
  -d '{"type":"runway_incursion","severity":"critical","location":"runway-09L"}'

sleep 5
INCIDENT_ID=$(curl -s "http://localhost:8005/api/v1/incidents?status=active" \
  | jq -r '.incidents[0].id')
curl http://localhost:8005/api/v1/incidents/$INCIDENT_ID \
  | jq '.cascade_tree | .. | .type? // empty'
# expected: runway_incursion, runway_closure_holding_stack, departure_ground_stop

# Auto-resolve after TTR (at 60x, a 15-min TTR = 15 real seconds)
sleep 50
curl "http://localhost:8005/api/v1/incidents?status=resolved" | jq '.total'
# expected: >= 1

# Incident report
curl http://localhost:8005/api/v1/incidents/$INCIDENT_ID/report \
  | jq '{total_flights_affected, cascade_events, protocols_activated}'

# All 5 types appear after running at 3600x for 30 real seconds
curl "http://localhost:8005/api/v1/incidents?limit=50" \
  | jq '[.incidents[].type] | group_by(.) | map({type: .[0], count: length})'
```

---

## Sprint 7 — api-gateway

**Goal:** All upstream services accessible through the gateway. WebSocket fans out events from
all Kafka topics. The /airport aggregate endpoint works. Auth and rate limiting work.

### Spec and skills

- `docs/services/api-gateway/SPEC.md`
- `services/api-gateway/SKILL.md`
- `docs/skills/kafka.SKILL.md`

### Tasks

- [ ] Implement JWT auth middleware (POST /auth/token + Bearer validation)
- [ ] Implement proxy routes for all 6 upstream services (http-proxy-middleware)
- [ ] Implement GET /api/v1/airport aggregate (Promise.allSettled pattern)
- [ ] Implement GET /api/v1/health/services
- [ ] Implement Kafka consumer — all 8 topics to internal event queue
- [ ] Implement WebSocket server — subscription filter frames + 15s heartbeat
- [ ] Implement rate limiting per route tier (express-rate-limit)
- [ ] Implement graceful degradation on upstream failure (partial response with null fields)

### Desired output

```bash
TOKEN=$(curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)

# Airport aggregate
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:3000/api/v1/airport | jq '{sim_time, weather, flights, incidents}'

# All proxied routes return 200
for svc in flights passengers baggage weather incidents; do
  echo "$svc: $(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $TOKEN" http://localhost:3000/api/v1/$svc)"
done

# Rate limiting triggers on 201st request
for i in $(seq 1 205); do
  curl -s -o /dev/null -w "%{http_code} " \
    -H "Authorization: Bearer $TOKEN" http://localhost:3000/api/v1/flights
done | tr ' ' '\n' | sort | uniq -c
# expected: some 200 and some 429

# WebSocket streams live events
# npm install -g wscat
wscat -c "ws://localhost:3000/ws" \
  -H "Authorization: Bearer $TOKEN" \
  --execute '{"action":"subscribe","topics":["flights","incidents","weather"]}'
```

---

## Sprint 8 — React dashboard

**Goal:** All 5 dashboards functional with live WebSocket data. Incident injection works.
Sim controls work. All animations render correctly.

### Spec and skills

- `docs/dashboards/FLIGHT_BOARD.md`
- `docs/dashboards/BAGGAGE_TRACKER.md`
- `docs/dashboards/PASSENGER_FLOW.md`
- `docs/dashboards/INCIDENT.md`
- `docs/dashboards/GROUND_OPS.md`

### Tasks

- [ ] Set up Zustand stores: simStore, flightStore, passengerStore, baggageStore, incidentStore, weatherStore
- [ ] Implement useWebSocket hook — connects to gateway, dispatches events to stores
- [ ] Implement useApi hooks — React Query wrappers per service
- [ ] Implement shared components: SimClock, WeatherStrip, IncidentBadge, StatusBadge, SimControls
- [ ] Implement Flight Board (/) — FIDS panels, FlightRow with boarding bar, FlightDetailDrawer, runway status, row flash animation, critical incident banner
- [ ] Implement Baggage Tracker (/baggage) — SVG conveyor map, zone colour coding, loading progress bars, flagged items panel, search + drawer
- [ ] Implement Passenger Flow (/passengers) — zone heatmap grid, CSS heat transitions, security queue cards, connection risk list, incident overlays
- [ ] Implement Incident Console (/incidents) — incident cards with pulse animation, cascade tree visualizer, protocol bar, alert feed, injection modal with confirmation preview, report download
- [ ] Implement Ground Ops (/ground-ops) — SVG airfield schematic, animated runway arrows, holding stack, weather compass rose, incident zone overlays

### Desired output

Open http://localhost:5173

- [ ] Flight board shows live flights — status updates flash on WebSocket events
- [ ] Inject runway_incursion via injection modal → red banner appears < 2 seconds
- [ ] Baggage tracker: inject system_failure (conveyor-sorting) → zone dims to gray on map
- [ ] Passenger flow heatmap shows heat building at peak hours — animated transitions visible
- [ ] Incident cascade tree shows depth-3 tree for a runway incursion
- [ ] Resolved incident report download produces readable content
- [ ] Ground ops airfield shows aircraft movement on runway strips
- [ ] Sim speed change via dropdown — clock visibly accelerates

---

## Sprint 9 — Observability

**Goal:** All Prometheus targets are up. All 5 Grafana dashboards built. At least 3 alerting rules
fire correctly under simulated conditions.

### Spec and skills

- `docs/infra/MONITORING.md`

### Tasks

- [ ] Verify all 9 Prometheus targets scrape successfully
- [ ] Build Grafana dashboard JSON — Simulation overview (7 panels)
- [ ] Build Grafana dashboard JSON — Flight operations (9 panels)
- [ ] Build Grafana dashboard JSON — Passenger and baggage (11 panels)
- [ ] Build Grafana dashboard JSON — Weather and incidents (10 panels)
- [ ] Build Grafana dashboard JSON — API gateway and system health (9 panels)
- [ ] Test SimulationPaused alert — pause sim for 3 real minutes
- [ ] Test CriticalIncidentActive alert — inject critical runway incursion
- [ ] Test ConveyorZoneOffline alert — inject system_failure conveyor-sorting
- [ ] Set Grafana home dashboard to sim-overview

### Desired output

```bash
# All targets up
curl -s http://localhost:9090/api/v1/targets \
  | jq '[.data.activeTargets[] | {job: .labels.job, health}]'
# expected: all health: "up"

# Key metrics present
curl -s "http://localhost:9090/api/v1/query?query=sim_tick_total" \
  | jq '.data.result[0].value[1]'  # > 0

curl -s "http://localhost:9090/api/v1/query?query=flights_delayed_current" \
  | jq '.data.result[0].value[1]'  # a number

# 5 dashboards loaded in Grafana
curl -s -u admin:art-grafana http://localhost:3001/api/search | jq '[.[].title]'

# At least one alert firing
curl -s http://localhost:9090/api/v1/alerts \
  | jq '.data.alerts[] | {alertname: .labels.alertname, state}'
```

---

## Sprint 10 — Polish and hardening

**Goal:** Portfolio-ready. Tests pass, CI runs, a stranger can clone and run in under 5 minutes.

### Tasks

#### Testing

- [ ] Unit tests for each state machine (pure logic, no I/O)
- [ ] Integration tests for each Kafka consumer handler
- [ ] Integration tests for each REST endpoint (against live Neo4j + Kafka)
- [ ] Idempotency tests — duplicate Kafka events produce no duplicate state changes
- [ ] Cascade depth limit test — chain that would exceed 5 hops stops at 5

#### Resilience

- [ ] Service restarts cleanly after docker compose restart — state recovers from Neo4j
- [ ] Kafka restart mid-sim — services reconnect and resume
- [ ] Neo4j restart mid-sim — services reconnect, in-memory caches rebuild

#### Documentation

- [ ] Update any SPEC.md files where implementation deviated from spec
- [ ] Update SKILL.md files with gotchas discovered during implementation
- [ ] Add CHANGELOG.md
- [ ] Verify all README links resolve

#### CI

- [ ] Write .github/workflows/ci.yml — lint (ruff + eslint) + unit tests + docker compose build

#### Final smoke test

- [ ] Clone repo on a clean machine
- [ ] Run bash agents/deploy.sh
- [ ] Run docker compose up --build
- [ ] Wait 90 seconds — open http://localhost:5173
- [ ] All 5 dashboards load with live data
- [ ] Inject one of each incident type — all cascade correctly
- [ ] Run at 3600x for 2 minutes — no errors, no OOM, no crashed containers

---

## Sprint order summary

| Sprint | Focus                   | Gate condition                                           |
| ------ | ----------------------- | -------------------------------------------------------- |
| 0      | Infrastructure skeleton | All containers healthy, Prometheus scraping              |
| 1      | sim-orchestrator        | Clock ticking, Neo4j seeded with 420 flights             |
| 2      | weather-service         | METAR events on Kafka, FSM transitioning                 |
| 3      | flight-service          | Flights advancing through FSM, cascades propagating      |
| 4      | baggage-service         | Conveyor pipeline running, DG detection working          |
| 5      | passenger-service + ML  | Pax flow live, LightGBM model trained and forecasting    |
| 6      | incident-service        | All 5 hazard types cascade correctly, reports generated  |
| 7      | api-gateway             | Unified REST + WebSocket, auth and rate limiting working |
| 8      | React dashboard         | All 5 dashboards live with real-time data                |
| 9      | Observability           | 5 Grafana dashboards built, alerting rules firing        |
| 10     | Polish and hardening    | Tests pass, CI green, clean clone and run in 5 min       |

Each sprint's desired output is the gate — do not start the next sprint until all checks pass.
