# Project timeline — Arthur International Airport Digital Twin

Five phases from abstract simulation to prescriptive intelligence.
Each phase builds on the previous — new capabilities layer on top without replacing what came before.

---

```
Abstract ──────────────────────────────────────────────── World-accurate
Descriptive ─────────────────────────────────────────────── Prescriptive

  ●─────────────●─────────────●─────────────●─────────────●
Phase 1       Phase 2       Phase 3       Phase 4       Phase 5
Operations    Spatial       Digital       Geospatial    Prescriptive
Simulator     Simulator     Twin          Twin          Twin
```

---

## Phase 1 — Airport operations simulator

### _What is happening, and why_

The foundation. A fully event-driven simulation of airport operations with no spatial
awareness — entities (flights, passengers, baggage) exist as abstract state machines
connected by a Kafka event bus and persisted in a Neo4j graph.

**What you can do:**

- Simulate 420 flights/day with realistic state machines and cascading delays
- Inject hazardous incidents (runway incursion, baggage fire, security breach, system failure)
- Watch cascade trees propagate across services in real time
- Forecast security queue depth 90 minutes ahead using a trained LightGBM model
- Run predefined and custom scenarios with reproducible outcomes
- Observe the full system on 5 React dashboards: flight board, baggage tracker,
  passenger flow, incident console, ground ops

**Key capabilities added in this phase:**

- Event-driven microservices (FastAPI × 6, Node.js × 1)
- Neo4j graph database for entity relationships
- Kafka event bus — 9 topics, fully typed event schemas
- LightGBM security queue forecasting with 12 features
- Prometheus + Grafana observability stack
- Docker-compose single-command deployment

**What is deliberately absent:**

- No physical positions — gates are labels, not coordinates
- No real distances — taxi time is a flat buffer
- No distinction between domestic and international flights
- No real-world airport or weather data

**Stack:** Python / FastAPI · Node.js / TypeScript · React · Neo4j · Kafka · LightGBM ·
Prometheus · Grafana · Docker

**Milestone:** `docker compose up` → full simulation running, all dashboards live,
incidents cascading, LightGBM model trained after 3 sim-days.

**Documentation:** `CHANGELOG.md` (sprints and releases) · `docs/architecture/` · `docs/services/`

---

## Phase 2 — Spatially-aware simulator

### _Where things are, and how long it takes to get there_

The airport acquires a physical presence. Gates, runways, taxiways, and conveyor belts
are no longer abstract labels — they have positions, distances, and adjacency relationships.
Time-based operations become physically grounded.

**What changes from Phase 1:**

- Taxi time computed from real gate-to-runway distance using the airport layout grid
- Turnaround modelled as a dependency graph of parallel tasks (deplaning, cleaning,
  fueling, baggage loading, boarding) rather than a flat buffer
- Baggage conveyor has spatial topology — a bag checked in Terminal C for a gate in
  Terminal A travels through an inter-terminal belt and incurs a real time penalty
- Flight type distinction (domestic / international short / international long / cargo /
  charter) drives different turnaround targets, gate requirements, and passenger processing
- Passenger walking times between zones based on physical distance, including cross-terminal
  connectors — connection risk calculation becomes spatially accurate

**Key capabilities added:**

- `fixtures/layout.json` — full airport grid with x/y coordinates for every node
- `compute_taxi_time(runway, gate)` — Euclidean distance on normalised 1000×1000 grid
- `TurnaroundPlan` — task dependency graph with per-task durations and critical path
- `FlightType` enum — domestic, international_short, international_long, cargo, charter
- Inter-terminal conveyor belt routing with distance-based transfer times
- Passenger zone walking times feeding the MCT and connection risk models

**What is still absent:**

- No real-world map — the layout is a schematic grid, not geographic coordinates
- No real destination airports — destinations are still drawn from a fictional pool
- No real weather data

**Milestone:** taxi times vary by gate position · a bag checked in Terminal C for a flight
at gate A03 takes 12 minutes longer than one for C02 · turnaround critical path visible
in the ground ops dashboard.

---

## Phase 3 — Operational digital twin

### _A living mirror of a real operation_

The simulation acquires the infrastructure of a true digital twin: a scenario engine
for reproducible test cases, interactive simulation controls, a community HOW-TO for
creating custom airports, and real-world data sources for weather and flight schedules.

**What changes from Phase 2:**

- Scenario engine: YAML-defined scenarios with seed overrides, timed event injections,
  and expected outcome assertions — runnable from CLI, results auto-documented
- Scenario library: 8 named scenarios covering peak-hour storms, double disruptions,
  connection crises, and cascade recovery
- Settings UI: interactive panel exposing all simulation parameters (speed, weather lock,
  incident probabilities, security lanes, demand multipliers) with live effect
- Airport config system: `config/airport.yaml` lets anyone fork the repo and simulate
  a different airport by changing a single file — no code changes required
- Real weather option: live METAR from AVWX API replaces the synthetic FSM
- Real schedule option: OurAirports CSV loader replaces the synthetic bimodal generator

**Key capabilities added:**

- `scenarios/runner.py` — CLI: `run`, `compare`, `list` commands
- `scenarios/definitions/*.yaml` — sharable, version-controlled scenario files
- `scenarios/results/` — auto-captured metrics, event logs, dashboard screenshots
- Settings dashboard panel (`/settings` route)
- `config/airport.yaml` — identity, infrastructure, airlines, simulation parameters
- `HOW_TO_CREATE_AIRPORT.md` — community guide

**Milestone:** `python scenarios/runner.py run morning-peak-storm --capture` produces a
fully documented, reproducible result with Grafana screenshots · a new airport (e.g.
Heathrow) can be simulated by editing `config/airport.yaml` only.

---

## Phase 4 — Geospatial digital twin

### _Anchored in the real world_

The airport is placed on the actual globe. Real destination airports replace fictional ones.
Airborne flights have real-world positions interpolated along great-circle routes. The
ground ops dashboard becomes a Mapbox 3D view. A new world map dashboard shows the
entire KART fleet in flight simultaneously.

**What changes from Phase 3:**

- KART placed at 38.75°N, 27.08°W (fictional mid-Atlantic island, no real airport within 300 km)
- Airport rendered in Mapbox GL JS with 8 custom layers: satellite base → apron → runways
  (3D fill-extrusion) → taxiways → terminal buildings (colour-coded 3D extrusion) →
  gate status → route arcs → live aircraft icons
- Real destination pool: 200 airports drawn from OurAirports CC0 database, filtered to
  200–12,000 km from KART, weighted by airport size
- Flight duration derived from real great-circle distance + aircraft cruise speed +
  altitude overhead per range category
- Live aircraft positioning: `great_circle_point(lat1, lon1, lat2, lon2, fraction)` gives
  real-world position for every airborne flight at the current sim time
- Route arcs: 60-point great-circle LineStrings rendered as dashed white lines
- World map dashboard (`/world`): seamless zoom from globe → regional → airport → gate

**Key capabilities added:**

- `public/geojson/` — static GeoJSON files for runways, taxiways, terminals, gates, apron
- `GET /flights/live-positions` — GeoJSON FeatureCollection updated each SimClockTick
- `compute_aircraft_position(flight, sim_time)` — lat/lon/altitude/heading interpolation
- `compute_flight_duration(distance_km, aircraft_type)` — real distance → flight time
- World map dashboard with zoom-level-dependent layer visibility
- Antimeridian-aware great-circle rendering

**Key technical constraint:** Mapbox requires a free account token (`VITE_MAPBOX_TOKEN`).
Offline fallback to Leaflet.js + OpenStreetMap if token is absent.

**Milestone:** watch 34 aircraft icons moving along great-circle arcs on a satellite globe ·
zoom in to see the 3D airport with live gate status · click any aircraft to see its
flight detail.

---

## Phase 5 — Prescriptive digital twin

### _Not just what is happening — what should be done_

The system transitions from describing and predicting airport state to actively recommending
decisions. Machine learning models move beyond forecasting into optimization. Real-time
data streams replace simulated inputs. The twin becomes a tool an operations manager could
actually use to make better decisions.

**What changes from Phase 4:**

- Real-time weather integration: live METAR feeds replace the FSM entirely, so the
  simulation mirrors actual current conditions at a chosen real airport
- Real schedule integration: historical and live flight schedules from OpenSky Network
  or FlightAware replace the synthetic bimodal generator
- What-if analysis: an operator can pause the simulation, propose a decision (e.g.
  "close runway 09L for maintenance"), and see the projected impact on delays,
  passenger flow, and baggage throughput before committing
- Optimization recommendations: the system detects emerging bottlenecks (security queues
  building, gate conflicts forming, baggage throughput degrading) and proactively suggests
  interventions (open an extra security lane, pre-assign an alternate gate, hold a departure)
  with projected outcome metrics for each option
- Multi-airport support: the scenario engine can simulate disruption propagation across
  a network of airports (KART + its top 5 feeder airports), modelling knock-on effects
  of a hub disruption on the wider network
- Autonomous mode: at high simulation speeds, the system can apply its own recommendations
  automatically, demonstrating fully autonomous airport operations management

**Key capabilities added:**

- `GET /analysis/what-if` — propose a decision, get projected outcomes
- `GET /analysis/recommendations` — active bottleneck detections with suggested actions
- Real weather adapter: `WeatherSource.LIVE` mode polling AVWX or CheckWX
- Real schedule adapter: OpenSky Network REST API integration
- Network simulation: multi-airport cascade modelling
- Autonomous mode toggle in sim controls

**Decision support example:**

```
RECOMMENDATION — 14:32 sim time

Detected: Security-B wait time trending to 32 min in next 45 min
          (LightGBM confidence: 87%)

Option A: Open 1 additional lane in Terminal B
  → Projected wait peak: 19 min   Cost: +1 staff hour
  → Recommended

Option B: Do nothing
  → Projected wait peak: 38 min
  → 14 flights at risk of late boarding

Option C: Issue early gate calls for B07, B09, B12
  → Reduces gate pressure, does not address queue root cause
```

**Milestone:** the system detects a forming cascade, generates a recommendation with
projected outcomes, and — in autonomous mode — applies it and demonstrates measurably
better outcomes than the baseline run.

---

## Capability progression

| Capability                         | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
| ---------------------------------- | :-----: | :-----: | :-----: | :-----: | :-----: |
| Flight / pax / baggage simulation  |   ✅    |   ✅    |   ✅    |   ✅    |   ✅    |
| Incident cascades + alerts         |   ✅    |   ✅    |   ✅    |   ✅    |   ✅    |
| ML queue forecasting               |   ✅    |   ✅    |   ✅    |   ✅    |   ✅    |
| Physical taxi + conveyor distances |    —    |   ✅    |   ✅    |   ✅    |   ✅    |
| Flight type distinction            |    —    |   ✅    |   ✅    |   ✅    |   ✅    |
| Reproducible scenario engine       |    —    |    —    |   ✅    |   ✅    |   ✅    |
| Custom airport config              |    —    |    —    |   ✅    |   ✅    |   ✅    |
| Real weather data                  |    —    |    —    |   ✅    |   ✅    |   ✅    |
| 3D airport on world map            |    —    |    —    |    —    |   ✅    |   ✅    |
| Real destination airports          |    —    |    —    |    —    |   ✅    |   ✅    |
| Live aircraft positioning          |    —    |    —    |    —    |   ✅    |   ✅    |
| What-if analysis                   |    —    |    —    |    —    |    —    |   ✅    |
| Proactive recommendations          |    —    |    —    |    —    |    —    |   ✅    |
| Real flight schedules              |    —    |    —    |    —    |    —    |   ✅    |
| Autonomous operations              |    —    |    —    |    —    |    —    |   ✅    |

---

## Notes on scope

**Phase 1 is the only fully specced phase.** All architecture decisions, data models, API
contracts, service specs, dashboard specs, Kafka schemas, simulation rules, and skill files
are written and live in `docs/`. Sprint history and delivery notes in `CHANGELOG.md` provide a task-by-task
implementation plan with verifiable gate conditions.

**Phases 2–5 are directional.** `NOTE.md` contains detailed technical design for each
phase including code examples, data models, and implementation notes. They are not
sprint-planned yet — that happens after Phase 1 is complete and validated.

**Each phase is independently useful.** Phase 1 is a strong portfolio project on its own.
Phase 4 is the visual showpiece. Phase 5 is the research and production-systems story.
Stop at whichever phase matches the project's goals.
