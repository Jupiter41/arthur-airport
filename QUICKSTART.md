# Quick Start Guide

Get the Arthur International Airport digital twin running and explore its dashboards.

---

## 1. Install & Run

### Prerequisites

- **Docker** ≥ 24 and **Docker Compose** ≥ 2.20
- Ports 3000, 5173, 7474, 8001–8007, 9090, 3001 available

### Start the stack

```bash
docker compose up --build          # first run takes ~90 seconds
```

Once you see `sim-orchestrator` emitting clock ticks in the logs, the simulation is
running. Open your browser:

| URL                                     | What                                      |
| --------------------------------------- | ----------------------------------------- |- Runaway queue depth in Grafanisn't dfisplayed- 
| [localhost:5173](http://localhost:5173) | React dashboard (main operator interface) |
| [localhost:3001](http://localhost:3001) | Grafana (metrics & system dashboards)     |
| [localhost:7474](http://localhost:7474) | Neo4j Browser (graph data explorer)       |
| [localhost:8080](http://localhost:8080) | Kafka UI (raw event stream inspector)     |

> **Tip:** The simulation starts at Day 1, 00:00 at 60× speed. One real second =
> one simulated minute, so you'll see a full airport day in ~24 real minutes.

### Useful commands

```bash
docker compose up neo4j zookeeper kafka kafka-ui   # infra only (local dev)
docker compose up --build --no-deps flight-service  # rebuild one service
docker compose down -v                              # full reset (wipe all data)
```

---

## 2. Dashboard Pages

The React dashboard at [localhost:5173](http://localhost:5173) has 11 pages accessible
from the top navigation bar.

### Operator views

#### ✈️ Flights (`/`)

The main Flight Information Display. Shows every departure and arrival for the
current sim day in a sortable, filterable table. Each row shows flight number,
airline, origin/destination, status, gate, runway, delay, and passenger/baggage
counts.

- Click a row to open the **flight detail drawer** with full timeline, cascade tree,
  and turnaround progress.
- The **runway status strip** at the top shows queue depth, active movements, and
  weather-driven capacity.
- **Simulation controls** (play/pause, speed, reset) are always visible in the header.

#### 👥 Passengers (`/passengers`)

Real-time passenger flow across the three terminals. A colour-coded heatmap grid
shows density per zone: check-in → security → airside → gates.

- **Security queue cards** show queue depth, wait time, open lanes, and the LightGBM
  forecast (90 sim-minutes ahead).
- The **at-risk connections** panel lists passengers likely to miss their connection,
  ranked by urgency.
- Click any passenger for full detail: PNR, flight, status timeline, alerts, and
  baggage tracking.

#### 🧳 Baggage (`/baggage`)

Live view of the baggage handling system. An SVG conveyor diagram shows all 30+
zones colour-coded by utilisation (green → amber → red).

- **Flight loading progress** cards show bags loaded vs total for boarding flights,
  with pace warnings when loading is behind schedule.
- The **flagged items** panel surfaces dangerous goods detections and security holds.
- Search by bag tag or passenger name; the diagram highlights the bag's current
  position and path.

#### 🚨 Incidents (`/incidents`)

Incident management console. Active incidents appear as severity-coded cards
(critical = red, high = amber, medium = yellow).

- The **cascade visualizer** draws an interactive tree of downstream effects triggered
  by each incident (e.g., runway incursion → ground stop → gate congestion → delays).
- A live **alert feed** streams high-priority notifications.
- The **inject event** button opens a modal to manually fire a hazardous event
  (runway incursion, baggage fire, security breach, etc.) with a preview of expected
  cascade effects.
- Resolved incidents have downloadable Markdown reports.
- **Recommendations** (from the analysis engine) appear as actionable cards with
  projected outcomes and an `[Apply]` button.

#### 🛬 Ground Ops (`/ground-ops`)

ATC-style airfield overview. An SVG schematic shows the three terminal blocks with
gate occupancy, two runway strips with animated aircraft, and ground vehicle
positions.

- **Holding stack** panel lists aircraft waiting to land, with fuel state and
  estimated hold time.
- **Weather** panel shows live conditions with wind compass rose, METAR, and
  runway capacity gauge.
- Ground vehicles (fuel trucks, pushback tugs, catering, loaders) move visually
  between vehicle pools and gates.

#### 🗺️ World Map (`/world`)

Geospatial view of the flight network on a Mapbox 2D map and optional CesiumJS 3D
globe.

- Animated great-circle arcs show flights in progress coloured by status.
- Destination airports are plotted from real-world OurAirports data.
- An ADS-B overlay (toggle) shows real nearby aircraft from OpenSky Network.
- The **real flights nearby** panel lists live ADS-B traffic within the KART region.

### Simulation management

#### 📊 History (`/history`)

Browse past simulation events and archived daily summaries. Useful for
after-action review and scenario comparison.

#### 🧪 Scenarios (`/scenarios`)

Pre-built and custom simulation scenarios. Eight built-in scenarios cover situations
like cascade recovery, runway incursion during peak hour, and severe weather
progression. You can create, edit, fork, run, and compare scenarios.

#### 🧠 ML Training (`/ml`)

LightGBM model monitoring. Shows training status, feature importance, prediction
accuracy, and the training data pipeline for the security queue forecasting model.

#### ⚙️ Settings (`/settings`)

Simulation configuration: speed multiplier, weather source (simulated / historical /
live METAR), weather parameter overrides, autonomous mode toggle, and snapshot
management (save/restore simulation state).

#### 🛠️ Debug (`/debug`)

Developer power tools:

- **Entity injection** forms: create flights, passengers, or baggage on the fly.
- **Entity inspector**: click any entity to open a read/write property editor.
- **Cypher console**: run read-only Neo4j queries directly from the dashboard.
- **Kafka inspector**: live feed of raw Kafka messages per topic.

### Grafana dashboards

At [localhost:3001](http://localhost:3001) (login: `admin` / `art-grafana`), five
pre-built dashboards provide system-level metrics:

| Dashboard               | What it shows                                                 |
| ----------------------- | ------------------------------------------------------------- |
| **Sim Overview**        | Tick rate, sim-time drift, event throughput, service health   |
| **Flight Operations**   | Flights by status, delay distribution, runway utilisation     |
| **Pax & Baggage**       | Security queue depth, conveyor utilisation, forecast accuracy |
| **Weather & Incidents** | Weather category timeline, active incidents, cascade depth    |
| **Gateway & System**    | HTTP request rate, WebSocket connections, Kafka consumer lag  |

---

## 3. Example Use-Case

### Watch a weather disruption cascade through the airport

1. **Start the stack** and open the dashboard at [localhost:5173](http://localhost:5173).
   Wait for the simulation to reach around 06:00 sim-time (about 6 real minutes at 60×).

2. **Go to Settings** (`/settings`) and set a weather override:
   - Visibility: **800 m**
   - Ceiling: **200 ft**

   This forces IMC (Instrument Meteorological Conditions). The weather strip in the
   header turns amber.

3. **Switch to Flight Board** (`/`): watch runway capacity drop from ~32/hr to ~18/hr.
   Departures start queuing. Arrival holding stacks build. Delay badges change from
   green to amber to red.

4. **Open Ground Ops** (`/ground-ops`): see aircraft stacking in the holding pattern.
   Gate occupancy rises as turnarounds can't clear fast enough.

5. **Check Incidents** (`/incidents`): the incident-service auto-creates a
   `severe_weather` incident. Expand its cascade tree to see downstream effects
   rippling through flights, passengers, and baggage.

6. **Check Passengers** (`/passengers`): security queues build up as flights bunch.
   The forecast line diverges from actual queue depth. At-risk connections appear.

7. **Check the Recommendations**: the analysis engine suggests interventions like
   "open additional security lane in Terminal B" or "hold connecting flight AX412".
   Click `[Apply]` to execute one and watch the projected impact.

8. **Clear the weather** in Settings (set visibility and ceiling back to `null`).
   Watch the airport self-recover: delays resolve, queues drain, incidents close.

> **Tip:** For a scripted version, run a pre-built scenario:
>
> ```bash
> ./scripts/scenario-runner.sh run "Severe weather progression"
> ```

---

## Further Reading

| Topic                  | Document                                                           |
| ---------------------- | ------------------------------------------------------------------ |
| Architecture           | [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)     |
| Data model (Neo4j)     | [docs/architecture/DATA_MODEL.md](docs/architecture/DATA_MODEL.md) |
| Kafka events & topics  | [docs/architecture/EVENT_BUS.md](docs/architecture/EVENT_BUS.md)   |
| Simulation rules       | [docs/architecture/SIMULATION.md](docs/architecture/SIMULATION.md) |
| API route reference    | [docs/architecture/ROUTES.md](docs/architecture/ROUTES.md)         |
| Docker configuration   | [docs/infra/DOCKER.md](docs/infra/DOCKER.md)                       |
| Monitoring (Grafana)   | [docs/infra/MONITORING.md](docs/infra/MONITORING.md)               |
| Custom airport setup   | [HOW_TO_CREATE_AIRPORT.md](HOW_TO_CREATE_AIRPORT.md)               |
| Service specifications | [docs/services/](docs/services/)                                   |
| Roadmap                | [ROADMAP.md](ROADMAP.md)                                           |
| Changelog              | [CHANGELOG.md](CHANGELOG.md)                                       |
| Scripts & helpers      | [scripts/README.md](scripts/README.md)                             |
