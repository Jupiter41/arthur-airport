# Arthur International Airport — Digital Twin Roadmap

Future development roadmap, design gaps, and long-term vision. Organised by priority.

---

## Current limitations

The current simulation is **operationally correct but spatially blind**. It models what happens (flights delay, bags get screened, passengers queue) but not _where_ or _how long it physically takes to get there_. The gaps below define what "Phase 1 completeness" currently lacks.

---

## Gap 0 — Better documentation

As the project grew in complexity, files are spread across many places and responsibilities are not clearly defined. Better documentation is needed to onboard new contributors and maintain a shared understanding of the system.

> **Status: DONE** — documentation has been improved across the codebase, with docstrings, service READMEs, and an updated repo README.
>
> Still pending: add an endpoint list / routes to the API gateway README.

### Tasks

- [x] **GAP-0-1** — Add docstrings to all public functions and classes across every service (purpose, inputs, outputs, side effects).
- [x] **GAP-0-2** — Create a high-level architecture diagram showing how services, databases, and message queues interact (draw.io or Mermaid in the repo root).
- [x] **GAP-0-3** — Write a `README.md` for each service explaining its role, how to run it locally, and how to run its tests.
- [x] **GAP-0-4** — Update the root `README.md` to include a project overview, goals, and a getting-started guide with links to each service README.
- [x] **GAP-0-5** — Document each simulation model: what is simulated, assumptions made, the statistical/physical model used, and a worked example.
- [x] **GAP-0-6** — Add a full endpoint reference (method, path, request/response schema) to the API gateway README.

---

## Gap 0.5 — Better dashboards

The current dashboards lack sorting, grouping, archive, a clear history of simulation runs, and richer data visualisation.

### Tasks

- [x] **GAP-05-0** — Add a plane icon to the website's favicon.
- [x] **GAP-05-1** — Add column sorting and grouping to all data tables in the dashboards.
- [x] **GAP-05-2** — Implement an archive view showing past simulation runs with summary metrics.
- [x] **GAP-05-3** — Add a simulation history timeline so users can scrub through past events.
- [x] **GAP-05-4** — Improve chart visualisations: add tooltips, zoom, and better colour coding by severity.
- [x] **GAP-05-5** — Add a per-page export button (CSV and JSON) for any data currently shown on screen.
- [x] **GAP-05-6** — Add a global export that dumps the full simulation run to a single JSON/CSV archive.

---

## Gap 1 — No physical layout

The airport has no spatial model. Gates, runways, taxiways, terminals, and carousels are abstract labels (`"gate-B07"`, `"runway-09L"`) with no position, distance, or adjacency relationship.

**What this means in practice:** a bag dropped at check-in desk `C12` destined for gate `A03` travels the same simulated distance as a bag going to gate `C02` next door. A plane landing on `09L` and taxiing to `B07` takes the same time as one going to `C14` on the opposite side.

**Real layout:**

```
                    KART — Arthur International Airport
                         Top-down schematic (not to scale)

        NORTH
          │
    ┌─────┴──────────────────────────────────────────────────────┐
    │                        TERMINAL A                          │
    │  [A01][A02][A03][A04][A05][A06][A07][A08][A09][A10][A11]  │
    │                    (North pier)                            │
    └────────────────────────────┬───────────────────────────────┘
                                 │  Taxiway Alpha
    ┌────────────────────────────┴───────────────────────────────┐
    │                        TERMINAL B                          │
    │  [B01][B02][B03][B04][B05][B06][B07][B08][B09][B10][B11]  │
    │                    (Central pier)                          │
    └────────────────────────────┬───────────────────────────────┘
                                 │  Taxiway Bravo
    ┌────────────────────────────┴───────────────────────────────┐
    │                        TERMINAL C                          │
    │  [C01][C02][C03][C04][C05][C06][C07][C08][C09][C10][C11]  │
    │                    (South pier)                            │
    └────────────────────────────┬───────────────────────────────┘
                                 │
         ════════════════════════╪═════════════════════════ RWY 09L/27R
         ════════════════════════╪═════════════════════════ RWY 09R/27L
                            SOUTH
```

Gate distances from runway 09L threshold (approximate):

- Terminal A: A01=800m, A07=1,100m, A14=1,400m
- Terminal B: B01=1,600m, B07=1,900m, B14=2,200m
- Terminal C: C01=2,400m, C07=2,700m, C14=3,000m

### Tasks

- [ ] **GAP-1-1** — Define a `position` property (x, y on a normalised 0–1000 grid, 1 unit ≈ 1 m) on `Gate`, `Runway`, and `Terminal` nodes in Neo4j and populate it for all existing nodes.
- [ ] **GAP-1-2** — Write a `taxi_time_minutes(runway_id, gate_id, positions)` utility function using Euclidean distance, splitting distance into taxiway (15 km/h) and apron (5 km/h) segments.
- [ ] **GAP-1-3** — Replace the current fixed taxi-time constant in `flight-service` with calls to the new utility, keyed on the flight's assigned runway and gate.
- [ ] **GAP-1-4** — Add a `layout.json` fixture to `sim-orchestrator` encoding all runway thresholds, taxiway segments, and gate positions on the normalised grid.
- [ ] **GAP-1-5** — Add walking-time computation between terminal zones (check-in → security → airside → gate) based on the distances in the layout fixture.
- [ ] **GAP-1-6** — Feed walking times into the connection risk model so cross-terminal connections (e.g. C-pier arrival → A-pier departure) are penalised correctly.
- [ ] **GAP-1-7** — Write unit tests for the taxi-time and walking-time functions covering same-terminal, adjacent-terminal, and far-terminal cases.
- [ ] **GAP-1-8** — Add a visualization of the airport layout to the dashboard, showing real-time positions of planes and bags as they move through the system.

---

## Gap 2 — Turnaround time is a flat buffer, not a sequence

The current model applies a flat buffer (30 min narrow-body, 45 min wide-body). Real turnaround is a sequenced set of parallel tasks with hard dependencies.

**Real turnaround sequence (Boeing 737-800, 35-min target):**

```
Wheels stop
    │
    ├── T+0   Jetbridge connects / stairs positioned
    ├── T+2   Passenger deplaning begins                    ← 12–15 min
    ├── T+3   Catering truck connects (aft)
    ├── T+4   Baggage offload begins (fwd hold)             ← 10–12 min
    ├── T+5   Fuel truck connects
    ├── T+10  Cleaning crew boards
    ├── T+14  Baggage offload complete
    ├── T+15  Baggage loading begins (new flight)           ← 10–12 min
    ├── T+16  Deplaning complete
    ├── T+18  Cleaning complete
    ├── T+20  New passenger boarding begins                 ← 20–25 min
    ├── T+25  Fueling complete
    ├── T+27  Catering complete
    ├── T+33  Boarding complete (door close)
    ├── T+35  Pushback begins
    └── T+38  Wheels moving → taxi to runway
```

The critical path is: baggage offload → baggage loading → boarding → door close.

### Tasks

- [x] **GAP-2-1** — Define the `TurnaroundTask` dataclass (`name`, `starts_after`, `duration_min`, `status`) and the `TurnaroundPlan` container.
- [x] **GAP-2-2** — Define the narrow-body task list (`NARROW_BODY_TURNAROUND`) and the wide-body task list (`WIDE_BODY_TURNAROUND`) as module-level constants.
- [x] **GAP-2-3** — Implement a `TurnaroundScheduler` that, given a set of tasks with dependencies, resolves the critical path and computes the minimum turnaround time via topological sort.
- [x] **GAP-2-4** — Implement a `TurnaroundRunner` that advances task states tick-by-tick during the simulation and emits a Kafka event for each task state change (`turnaround.task.started`, `turnaround.task.completed`).
- [x] **GAP-2-5** — Replace the flat buffer logic in `flight-service` with `TurnaroundRunner`, instantiating a plan at wheels-stop and deriving the ready-for-departure time from the critical path completion.
- [x] **GAP-2-6** — Propagate delays into the task graph: when `baggage-service` reports a baggage delay, extend the `baggage_offload` task duration and recompute the critical path.
- [x] **GAP-2-7** — Expose current turnaround progress (`tasks`, `critical_path_slack`, `estimated_ready_time`) on the flight detail endpoint and the ground ops dashboard.
- [x] **GAP-2-8** — Write unit tests covering: on-time turnaround, baggage delay propagation, fueling delay that is absorbed by slack, and a delay that exceeds slack and pushes departure.

---

## Gap 3 — No flight type distinction

All flights are treated identically. In reality, domestic, international, long-haul, cargo, and charter flights have very different operational profiles.

| Flight type              | Turnaround | Bags avg      | Passengers            | Gate requirements     |
| ------------------------ | ---------- | ------------- | --------------------- | --------------------- |
| Domestic short-haul      | 25–35 min  | 1.0           | No customs            | Any gate              |
| International short-haul | 35–50 min  | 1.2           | Customs + passport    | International gate    |
| Long-haul (>6 h)         | 60–90 min  | 1.5           | Customs + immigration | Wide-body + jetbridge |
| Cargo                    | 90–180 min | N/A (freight) | None                  | Cargo apron           |
| Charter                  | 45–60 min  | 1.3           | Group check-in        | Any gate              |

### Tasks

- [x] **GAP-3-1** — Define `FlightType` (`domestic`, `international_short`, `international_long`, `cargo`, `charter`) and `RouteCategory` (`short_haul`, `medium_haul`, `long_haul`) enums.
- [x] **GAP-3-2** — Add `flight_type` and `route_category` fields to the `Flight` Neo4j node and populate them in the synthetic flight generator based on route distance and destination.
- [x] **GAP-3-3** — Map each `FlightType` to its corresponding `TurnaroundPlan` template (from Gap 2) so narrow-body domestic, wide-body long-haul, and cargo all get distinct task graphs.
- [x] **GAP-3-4** — Adjust the bags-per-passenger multiplier in `baggage-service` per flight type (1.0 domestic → 1.5 long-haul).
- [x] **GAP-3-5** — Route international arrivals through passport control and customs steps in the passenger flow model; domestic arrivals go directly to baggage claim.
- [x] **GAP-3-6** — Enforce gate compatibility constraints in the gate-assignment logic: international flights only assigned to international-capable gates, wide-body flights only to gates with jetbridge clearance.
- [x] **GAP-3-7** — Update the dashboard flight table to display flight type and route category as filterable columns.
- [x] **GAP-3-8** — Write tests for gate assignment rejecting an international flight assigned to a domestic gate, and a wide-body rejected from a narrow-body-only stand.

---

## Gap 4 — Baggage conveyor has no spatial model

Bags travel from check-in to gate with a fixed throughput rate, but the layout of the conveyor — which check-in zones feed which screening units, which make-up carousels serve which gates — is not modelled. A bag checked at zone C12 for gate A03 crosses two terminal boundaries; the current model treats this as instantaneous.

**KART baggage conveyor layout:**

```
CHECK-IN ZONES (per terminal)
  Terminal A: zones A1–A8  → induction belt A  → screening units 1–2
  Terminal B: zones B1–B8  → induction belt B  → screening units 3–4
  Terminal C: zones C1–C8  → induction belt C  → screening units 5–6
                                    │
                              MAIN SORT BELT
                            (connects all three)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            make-up A (1–5)  make-up B (1–5)  make-up C (1–5)
            (gates A01–A14)  (gates B01–B14)  (gates C01–C14)
                                    │
                          INTER-TERMINAL BELT
                         (for cross-terminal bags)
                              transfer time: +8 min

ARRIVAL CAROUSELS:
  Carousel 1–2: Terminal A arrivals
  Carousel 3–4: Terminal B arrivals
  Carousel 5–6: Terminal C arrivals
```

**Time model per segment:**

| Segment                                         | Duration   |
| ----------------------------------------------- | ---------- |
| Check-in desk → induction belt                  | 2 min      |
| Induction belt → screening unit (same terminal) | 3 min      |
| Screening                                       | 2 min/item |
| Screening → sorting matrix                      | 2 min      |
| Sorting matrix → make-up (same terminal)        | 4 min      |
| Sorting matrix → make-up (adjacent terminal)    | 8 min      |
| Sorting matrix → make-up (far terminal)         | 12 min     |
| Loading from make-up to aircraft hold           | 5–8 min    |

### Tasks

- [ ] **GAP-4-1** — Model the conveyor topology as a directed graph in Neo4j: `CheckInZone → InductionBelt → ScreeningUnit → SortMatrix → MakeUpCarousel → Gate`.
- [ ] **GAP-4-2** — Assign each check-in zone to its home terminal's induction belt and each gate to its make-up carousel in the fixture data.
- [ ] **GAP-4-3** — Implement a `bag_conveyor_time(checkin_zone, gate_id, topology)` function that walks the conveyor graph and sums segment durations, applying the inter-terminal penalty when the bag crosses a terminal boundary.
- [ ] **GAP-4-4** — Replace the current fixed bag-travel-time constant in `baggage-service` with calls to the new function.
- [ ] **GAP-4-5** — Model make-up carousel capacity: each carousel has a maximum throughput (bags/min); when exceeded, bags queue and the loading start time for the flight is delayed.
- [ ] **GAP-4-6** — Emit a `baggage.conveyor.delay` Kafka event when a bag misses its make-up deadline, triggering the Gap 2 propagation logic in `flight-service`.
- [ ] **GAP-4-7** — Model arrival carousels: bags from an arriving flight appear on the correct carousel (A→carousel 1–2, B→3–4, C→5–6) after a fixed offload delay.
- [ ] **GAP-4-8** — Add conveyor segment load (bags currently in transit per segment) as a Prometheus metric, and display it on the baggage dashboard as a live heat-map.
- [ ] **GAP-4-9** — Write unit tests covering: same-terminal bag (no inter-terminal penalty), cross-terminal bag (full penalty), carousel overflow causing flight delay.

---

## Roadmap — development phases

```
Phase 1 (current)   Operational correctness
                    ✅ All 7 services running
                    ✅ Kafka event bus
                    ✅ Neo4j graph model
                    ✅ LightGBM forecasting
                    ⬜ Fix gaps 1–4 above

Phase 2             Scenario engine
                    Predefined + user-created scenarios
                    Visual, documented, reproducible

Phase 3             Physical environment
                    Spatial model, layout, real distances

Phase 4             Simulation settings UI
                    Interactive controls, parameter tuning

Phase 5             Real-world data integration
                    Live weather, real schedules, historical data

Phase 6             Geospatial digital twin
                    Mapbox 2D/2.5D + CesiumJS 3D globe
```

---

## Phase 2 — Scenario engine

A scenario is a **named, reproducible sequence of events** injected into the simulation at defined sim-time offsets, producing a documented expected outcome.

```yaml
# scenarios/runway-incursion-peak-hour.yaml

name: "Runway incursion during morning peak"
description: >
  A vehicle enters runway 09L at 08:15 during the peak departure bank.
  Tests cascade propagation: ground stop → holding stack → gate congestion
  → cascading departure delays. Expected: 12–18 flights delayed 20–45 min.

sim_speed: 60
start_time: "2024-06-15T07:30:00"
duration_sim_minutes: 120

seed_overrides:
  weather: CAVOK
  daily_flights: 420
  load_factor: 0.85

events:
  - at_sim_offset_minutes: 45
    type: runway_incursion
    severity: critical
    location: runway-09L
    trigger: manual

  - at_sim_offset_minutes: 80
    type: system_failure
    severity: medium
    location: conveyor-sorting
    trigger: manual

expected_outcomes:
  - metric: flights_delayed_current
    condition: ">= 10"
    within_sim_minutes: 15
  - metric: holding_stack_depth
    condition: ">= 4"
    within_sim_minutes: 10
  - metric: cascade_depth_max
    condition: ">= 3"
    within_sim_minutes: 5
```

### Scenario library (proposed)

| Scenario                     | Description                                 | Key metric                  |
| ---------------------------- | ------------------------------------------- | --------------------------- |
| `morning-peak-storm`         | LIFR weather hits during 07:30 peak bank    | Holding stack depth         |
| `runway-incursion-peak`      | Vehicle on 09L at 08:15                     | Cascade depth + total delay |
| `baggage-fire-chain`         | DG class 3 ignites in make-up B during peak | Zone downtime               |
| `security-breach-terminal-b` | Breach triggers terminal lockdown at 14:00  | Boarding delays             |
| `double-disruption`          | Storm + conveyor failure simultaneously     | System saturation           |
| `connection-crisis`          | 3 delayed inbounds + 2 connecting banks     | Missed connections          |
| `full-capacity-day`          | 1.3× pax multiplier (special event day)     | Security queue depth        |
| `cascade-recovery`           | Incident resolves → measure recovery time   | Time-to-normal              |

### Scenario runner architecture

```
scenarios/
├── runner.py
├── definitions/
│   ├── morning-peak-storm.yaml
│   ├── runway-incursion-peak.yaml
│   └── ...
├── results/
│   └── {scenario-name}/{timestamp}/
│       ├── metrics.json
│       ├── events.jsonl
│       ├── report.md
│       └── screenshots/
└── comparisons/
    └── compare.py
```

```bash
python scenarios/runner.py run runway-incursion-peak --speed 600
python scenarios/runner.py run morning-peak-storm --capture
python scenarios/runner.py compare results/morning-peak-storm/2024-06-15/ results/morning-peak-storm/2024-06-16/
python scenarios/runner.py list
```

---

## Phase 3 — Physical environment

Add a `layout.json` to `sim-orchestrator` fixtures defining all physical positions on a normalised 1000×1000 grid (1 unit ≈ 1 metre). See Gap 1 for the taxi-time computation details.

Zone distances at KART (approximate):

| Route                   | Distance | Walk time                 |
| ----------------------- | -------- | ------------------------- |
| Check-in A → Security A | 120 m    | ~1.5 min                  |
| Security A → Airside A  | 80 m     | ~1.0 min                  |
| Airside A → Gate A01    | 50 m     | ~0.7 min                  |
| Airside A → Gate A14    | 300 m    | ~3.5 min                  |
| Airside A → Gate B01    | 400 m    | ~5.0 min (cross-terminal) |
| Airside A → Gate C01    | 700 m    | ~8.5 min (cross-terminal) |

Special assistance: multiply all walking times × 2.5.

---

## Phase 4 — Simulation settings UI

A dedicated settings panel in the React dashboard exposing all simulation parameters as interactive controls, each change sending a `PATCH` to the sim-orchestrator via the API gateway.

```
┌─────────────────────────────────────────────────────────────┐
│  Simulation Settings                             [Apply]    │
├─────────────────────────┬───────────────────────────────────┤
│  TIME & SPEED           │  DEMAND                          │
│  Speed:  [====●====] 60×│  Daily flights:     [420  ▲▼]   │
│  Day:    3              │  Load factor mean:  [0.80 ▲▼]   │
│  Paused: [ ]            │  Special event:     [None  ▼]   │
│                         │  Pax multiplier:    [1.00 ▲▼]   │
├─────────────────────────┼───────────────────────────────────┤
│  WEATHER                │  INCIDENTS                       │
│  Lock to: [CAVOK ▼]     │  Runway incursion:  [●] 0.005/h │
│  Or: FSM  [●]           │  Baggage fire:      [●] 0.008/h │
│  Wind:    [15 kt ▲▼]    │  Security breach:   [●] 0.010/h │
│  Gust:    [ ] enabled   │  System failure:    [●] 0.015/h │
│                         │  Suppression win:   [2h    ▲▼]  │
├─────────────────────────┼───────────────────────────────────┤
│  SECURITY               │  BAGGAGE                         │
│  Lanes open:  A[4▲▼]    │  Screening units:   [6  ▲▼]    │
│               B[3▲▼]    │  Sorting capacity:  [1800▲▼]   │
│               C[4▲▼]    │  DG false pos rate: [0.003▲▼]  │
│  MCT:    [45 min ▲▼]    │                                  │
└─────────────────────────┴──────────────────────────────────┘
```

---

## Phase 5 — Real-world data integration

### Weather (live)

Replace the FSM with real METAR data:

```python
async def fetch_real_metar(icao: str = "EHAM") -> WeatherParams:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://avwx.rest/api/metar/{icao}",
            headers={"Authorization": f"Bearer {AVWX_TOKEN}"}
        )
    data = resp.json()
    return WeatherParams(
        category=classify_category(data["visibility"], data["ceiling"]),
        wind_speed_kt=data["wind_speed"]["value"],
        ...
    )
```

### Flight schedules (historical CSV)

| Source              | Format    | Coverage           | License       |
| ------------------- | --------- | ------------------ | ------------- |
| OpenSky Network     | CSV       | Global, historical | CC BY 4.0     |
| Eurocontrol NEST    | CSV       | European, detailed | Research only |
| FlightAware AeroAPI | JSON REST | Global, live       | Commercial    |
| OurAirports         | CSV       | Airports + routes  | Public domain |

---

## Phase 6 — Geospatial digital twin (Mapbox)

This phase transforms the project from an abstract operational simulation into a **true geospatial digital twin** anchored in the real world.

### 6.1 — Placing KART in the real world

```
KART — Arthur International Airport
Coordinates: 38.7500° N, 27.0833° W  (fictional Azores-adjacent, open ocean)
Elevation:   48 m AMSL
Magnetic variation: 8.5° W

Real-world bounding box:
  SW corner: 38.7420° N, 27.1100° W
  NE corner: 38.7600° N, 27.0400° W
  Airport footprint: ~3.2 km × 1.8 km
```

### 6.2 — Mapbox GL JS integration

Layer stack (bottom to top):

```
layer 7: aircraft icons (live)
layer 6: flight route arcs
layer 5: gate labels + status
layer 4: terminal buildings (fill)
layer 3: taxiways (line)
layer 2: runways (fill-extrusion)
layer 1: apron surface (fill)
layer 0: Mapbox satellite base
```

Static GeoJSON files checked into the repo:

```
public/geojson/
├── runways.geojson
├── taxiways.geojson
├── terminals.geojson
├── gates.geojson
└── apron.geojson
```

### 6.3 — Real destination airports

Replace fictional destinations with real airports from the OurAirports public-domain database (CC0), filtered to large/medium airports with IATA codes, 200–12,000 km from KART, weighted 5:1 large vs medium.

Example routes from KART:

| Route      | Distance | Duration (A320 / B77W) |
| ---------- | -------- | ---------------------- |
| KART → LHR | 2,142 km | 3 h 10 min             |
| KART → JFK | 4,956 km | 6 h 45 min             |
| KART → GRU | 5,218 km | 7 h 05 min             |
| KART → CDG | 2,070 km | 3 h 05 min             |
| KART → NBO | 7,431 km | 9 h 20 min             |

Distance thresholds: < 1,500 km → short-haul · 1,500–4,000 km → medium-haul · > 4,000 km → long-haul.

### 6.4 — Live aircraft positioning

Position interpolated along the great-circle arc using elapsed fraction of flight time, updated every simulated minute from WebSocket.

```python
def compute_aircraft_position(flight: dict, sim_time: datetime) -> dict:
    elapsed_min = (sim_time - departed_at).total_seconds() / 60
    fraction    = max(0.0, min(1.0, elapsed_min / total_min))
    lat, lon    = great_circle_point(KART_LAT, KART_LON,
                                      flight["destination_lat"],
                                      flight["destination_lon"], fraction)
    altitude_ft = compute_altitude(fraction, flight["aircraft_type"])
    heading     = compute_bearing(lat, lon,
                                   flight["destination_lat"],
                                   flight["destination_lon"])
    return { "lat": lat, "lon": lon, "altitude_ft": altitude_ft,
             "heading_deg": heading, ... }
```

### 6.5 — Flight route arcs

Each airborne flight's great-circle route rendered as a dashed line, fading from full opacity at the aircraft to transparent at the destination. Updated from WebSocket each simulated-minute tick.

### 6.6 — World map view (`/world`)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Arthur Airport — World View         SIM: Day 1 · 14:32  ART  IMC  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   [Mapbox satellite globe]                                          │
│                                                                     │
│   ✈ AX412 ──────────────────────────────────────> LHR              │
│       ↖ KART                       ✈ BK217 ──────────────> JFK     │
│                                                                     │
│   ✈ KV388 ──────> CDG                                              │
│                                                                     │
└────────────────────────┬───────────────────────────────────────────┘
│ AIRBORNE: 34  │ ENROUTE > 6H: 8  │ APPROACHING: 4  │ LONGEST: AX801 BKK 9h12m │
└─────────────────────────────────────────────────────────────────────┘
```

Zoom behaviour: zoom 2–8 → world view · zoom 9–12 → regional, airport outline · zoom 13+ → runways, taxiways, gate status.

### 6.7 — Implementation notes

- **Mapbox token:** set `VITE_MAPBOX_TOKEN` in the dashboard `.env`.
- **GeoJSON accuracy:** draw airport files in QGIS or geojson.io at the KART coordinates; runway headings must match the 8.5° W magnetic variation.
- **Antimeridian:** allow longitudes outside −180/+180 (e.g. 190° instead of −170°) — Mapbox wraps correctly.
- **Performance:** use `source.setData()` for full GeoJSON replace rather than per-feature updates.
- **Aircraft icon sprite:** top-down SVG silhouette pointing north (0°) so `icon-rotate: heading_deg` aligns correctly.
- **Offline fallback:** if Mapbox token is missing, fall back to Leaflet.js + OpenStreetMap.

---

## Phase 6.8 — 3D Globe View (CesiumJS)

While the Mapbox 2D/2.5D map gives an excellent ground-level airport view, a true spherical globe renderer elevates the project into genuine digital twin territory. This section describes a dedicated **3D world view** built on CesiumJS — an open-source WebGL globe engine designed specifically for geospatial visualisation.

The globe view runs alongside the existing Mapbox view. Users switch between them from the top navigation bar. Both share the same live data feed.

### Why CesiumJS over Mapbox for the globe

| Capability         | Mapbox GL JS                      | CesiumJS                                         |
| ------------------ | --------------------------------- | ------------------------------------------------ |
| Earth curvature    | Flat / Mercator projection        | True WGS-84 ellipsoid                            |
| Flight arcs        | Flat great-circle lines           | Curved paths over sphere surface                 |
| Altitude           | Simulated via fill-extrusion only | True 3D altitude (FL350 visible)                 |
| Aircraft at cruise | Icons always on surface           | Aircraft float above terrain at correct altitude |
| Terrain            | Flat satellite tiles              | Quantized-mesh 3D terrain                        |
| Day / night        | Not available                     | Real-time solar terminator                       |
| Atmosphere         | Not available                     | Rayleigh scattering sky glow                     |
| Long routes        | Correct but looks flat            | Visually obvious arc over the horizon            |

### Setup

```bash
npm install cesium
```

```typescript
// vite.config.ts — copy Cesium assets to public/cesium
import { viteStaticCopy } from "vite-plugin-static-copy";

export default {
  plugins: [
    viteStaticCopy({
      targets: [
        { src: "node_modules/cesium/Build/Cesium/Workers", dest: "cesium" },
        { src: "node_modules/cesium/Build/Cesium/ThirdParty", dest: "cesium" },
        { src: "node_modules/cesium/Build/Cesium/Assets", dest: "cesium" },
        { src: "node_modules/cesium/Build/Cesium/Widgets", dest: "cesium" },
      ],
    }),
  ],
};
```

```typescript
// src/globe/GlobeView.tsx
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_TOKEN;

const viewer = new Cesium.Viewer("cesiumContainer", {
  imageryProvider: new Cesium.IonImageryProvider({ assetId: 2 }),
  terrainProvider: Cesium.createWorldTerrain(),
  skyAtmosphere: new Cesium.SkyAtmosphere(),
  baseLayerPicker: false,
  geocoder: false,
  animation: false,
  timeline: false,
  fullscreenButton: false,
});

// Start looking at KART from orbit altitude
viewer.camera.flyTo({
  destination: Cesium.Cartesian3.fromDegrees(-27.0833, 38.75, 8_000_000),
  duration: 3,
});
```

### Airport footprint in 3D

```typescript
// Runways clamped to terrain
const runways = await Cesium.GeoJsonDataSource.load(
  "/geojson/runways.geojson",
  {
    clampToGround: true,
    fill: Cesium.Color.fromCssColorString("#2a2a2a").withAlpha(0.95),
    stroke: Cesium.Color.WHITE,
    strokeWidth: 1.5,
  },
);
viewer.dataSources.add(runways);

// Terminal buildings extruded to real height
const terminals = await Cesium.GeoJsonDataSource.load(
  "/geojson/terminals.geojson",
);
terminals.entities.values.forEach((entity) => {
  if (entity.polygon) {
    entity.polygon.extrudedHeight = entity.properties.height_m.getValue();
    entity.polygon.material =
      Cesium.Color.fromCssColorString("#4a90d9").withAlpha(0.85);
    entity.polygon.closeTop = true;
  }
});
viewer.dataSources.add(terminals);
```

### Aircraft at true altitude

Each airborne aircraft is positioned at its computed altitude (FL350 = 35,000 ft) above the WGS-84 ellipsoid. A vertical line descends to the surface so the shadow footprint is visible.

```typescript
function addAircraftEntity(viewer: Cesium.Viewer, pos: AircraftPosition) {
  const cartesian = Cesium.Cartesian3.fromDegrees(
    pos.lon,
    pos.lat,
    pos.altitude_ft * 0.3048, // feet → metres
  );

  viewer.entities.add({
    id: pos.flight_id,
    position: cartesian,
    orientation: Cesium.Transforms.headingPitchRollQuaternion(
      cartesian,
      new Cesium.HeadingPitchRoll(Cesium.Math.toRadians(pos.heading_deg), 0, 0),
    ),
    model: {
      uri: "/models/aircraft_737.glb",
      minimumPixelSize: 24,
      maximumScale: 20000,
      silhouetteColor: Cesium.Color.WHITE,
      silhouetteSize: 1.0,
    },
    label: {
      text: pos.flight_number,
      font: "12px Arial",
      fillColor: Cesium.Color.WHITE,
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 2,
      distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 5e6),
    },
    // Vertical shadow stick to the surface
    polyline: {
      positions: [
        cartesian,
        Cesium.Cartesian3.fromDegrees(pos.lon, pos.lat, 0),
      ],
      width: 1,
      material: Cesium.Color.WHITE.withAlpha(0.25),
      arcType: Cesium.ArcType.NONE,
    },
  });
}
```

### Great-circle arc rendering

Flight routes are drawn as 3D polylines that follow the sphere surface, with altitude ramping up to represent the cruise profile. A straight line in 3D Cartesian space traces a geodesic — the arc curvature over the horizon is automatic.

```typescript
function buildRouteArc(flight: Flight, nPoints = 80): Cesium.Cartesian3[] {
  const positions: Cesium.Cartesian3[] = [];
  for (let i = 0; i <= nPoints; i++) {
    const frac = i / nPoints;
    const [lat, lon] = greatCirclePoint(
      KART_LAT,
      KART_LON,
      flight.destination_lat,
      flight.destination_lon,
      frac,
    );
    const altM = computeAltitude(frac, flight.aircraft_type) * 0.3048;
    positions.push(Cesium.Cartesian3.fromDegrees(lon, lat, altM));
  }
  return positions;
}

viewer.entities.add({
  id: `route-${flight.id}`,
  polyline: {
    positions: buildRouteArc(flight),
    width: 1.5,
    arcType: Cesium.ArcType.NONE,
    material: new Cesium.PolylineGlowMaterialProperty({
      glowPower: 0.15,
      color: Cesium.Color.fromCssColorString("#3498db").withAlpha(0.6),
    }),
  },
});
```

### Day / night terminator

CesiumJS computes the solar terminator in real time. Enabling `globe.enableLighting` creates a natural day/night distinction, and the simulation clock drives the terminator position.

```typescript
viewer.scene.globe.enableLighting = true;

// Sync Cesium clock to simulation time
ws.onmessage = (event) => {
  const envelope = JSON.parse(event.data);
  if (envelope.event_type === "SimClockTick") {
    viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(envelope.sim_time);
    viewer.clock.shouldAnimate = false; // we drive time ourselves
  }
};

viewer.scene.skyAtmosphere.show = true;
viewer.scene.skyAtmosphere.brightnessShift = 0.1;
viewer.scene.sun = new Cesium.Sun();
viewer.scene.moon = new Cesium.Moon();
```

### Camera modes

| Mode         | Camera position                             | Use case                      |
| ------------ | ------------------------------------------- | ----------------------------- |
| Orbit        | 8,000 km above KART, free rotation          | Overview of all active routes |
| Track flight | Follows selected aircraft at 50 km trailing | Monitor a specific long-haul  |
| Airport      | Zoomed to KART at 5 km, 45° tilt            | Ground ops detail view        |

```typescript
function trackFlight(viewer: Cesium.Viewer, flightId: string) {
  const entity = viewer.entities.getById(flightId);
  if (!entity) return;

  viewer.scene.postUpdate.addEventListener(() => {
    const pos = entity.position?.getValue(viewer.clock.currentTime);
    if (!pos) return;
    viewer.camera.lookAt(
      pos,
      new Cesium.HeadingPitchRange(
        Cesium.Math.toRadians(180), // look forward
        Cesium.Math.toRadians(-15), // slight downward pitch
        50_000, // 50 km back
      ),
    );
  });
}
```

### CZML streaming for bulk updates

For simulation replay or high-speed playback, CZML (Cesium Language) allows the server to stream all aircraft positions as a time-series rather than per-tick REST calls.

```python
# flight-service: generate CZML for all airborne flights
def generate_czml(flights: list[dict]) -> list[dict]:
    packets = [{"id": "document", "name": "KART Live", "version": "1.0"}]
    for flight in flights:
        coords = []
        for minute in range(int(flight["flight_duration_minutes"])):
            frac = minute / flight["flight_duration_minutes"]
            lat, lon = great_circle_point(...)
            alt_m    = compute_altitude(frac, flight["aircraft_type"]) * 0.3048
            coords.extend([minute * 60, lon, lat, alt_m])
        packets.append({
            "id":    flight["id"],
            "label": {"text": {"string": flight["flight_number"]}},
            "model": {"gltf": "/models/aircraft_737.glb"},
            "position": {
                "epoch":               flight["actual_departure"],
                "cartographicDegrees": coords,
                "interpolationAlgorithm": "LAGRANGE",
            },
            "orientation": {"velocityReference": "#position"},
        })
    return packets
```

```typescript
// Client: load CZML and stream live updates
const czml = new Cesium.CzmlDataSource();
await czml.load("/api/v1/flights/czml");
viewer.dataSources.add(czml);

czmlSocket.onmessage = (event) => {
  czml.process(JSON.parse(event.data));
};
```

### glTF aircraft models

| File                      | Represents                  | Applies to types       |
| ------------------------- | --------------------------- | ---------------------- |
| `aircraft_narrowbody.glb` | Generic 150-seat narrowbody | A320, A321, B738, B739 |
| `aircraft_widebody.glb`   | Generic twin-aisle widebody | B77W, A333, A332, A359 |
| `aircraft_regional.glb`   | Regional turboprop / jet    | E195, DH8D, AT75       |
| `aircraft_cargo.glb`      | Freighter silhouette        | B744F, B77F            |

Models must be oriented with the nose pointing toward +Y (north) in model space and centred on the aircraft's centre of gravity. CesiumJS applies heading rotation automatically via the `orientation` property.

### Zoom-level transitions

| Zoom / Altitude  | Renderer     | What is shown                               |
| ---------------- | ------------ | ------------------------------------------- |
| > 3,000 km       | CesiumJS     | Full globe, all route arcs, KART as a dot   |
| 500–3,000 km     | CesiumJS     | Regional view, KART footprint appears       |
| 50–500 km        | CesiumJS     | Airport outline, terrain visible            |
| < 50 km → switch | Mapbox GL JS | Ground detail: gates, taxiways, live status |

The transition is triggered by a camera altitude threshold. A short crossfade blends the two renderers. Users can also force a specific view from the navigation bar toggle.

### 3D dashboard layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Arthur Airport — 3D Globe           SIM: Day 3 · 09:47  ART  VMC  │
├──────┬──────────────────────────────────────────────────────┬───────┤
│ MAP  │                                                      │ ORBIT │
│ 2D ▷ │   [CesiumJS full-screen 3D globe]                    │ TRACK │
│ 3D ● │                                                      │ APRON │
│      │   🌍 Day/night terminator visible                    │ ───── │
│      │                                                      │ FILTER│
│      │   ✈ AX412 (B77W) — FL350 — 4h12m remaining          │ ───── │
│      │     arc visible over North Atlantic curvature         │ Wide ☑│
│      │                                                      │ Narr ☑│
│      │   ● KART footprint (zoom 13+ for gate detail)        │ Cargo☑│
└──────┴──────────────────────────────────────────────────────┴───────┘
│ AIRBORNE: 38 │ AT FL350+: 14 │ CROSSING TERMINATOR: 3 │ LONGEST: AX801 BKK 9h12m │
└─────────────────────────────────────────────────────────────────────┘
```

### Performance considerations

- Update entity positions using `entity.position = new Cesium.ConstantPositionProperty(cartesian)` rather than removing and re-adding entities each tick.
- Use CZML streaming for bulk updates when flight count exceeds 100.
- Level-of-detail: show glTF aircraft models only within 2,000 km; beyond that, use billboard sprites.
- Disable terrain at zoom levels below zoom 9 — it adds GPU cost without visual benefit at global scale.
- Throttle updates to once per simulated minute, matching the existing WebSocket cadence.

---

## HOW-TO — Create your own airport

Minimum configuration to customise:

```yaml
# config/airport.yaml

identity:
  name: "Heathrow International Airport"
  iata: "LHR"
  icao: "EGLL"
  timezone: "Europe/London"

infrastructure:
  terminals: 5
  gates_per_terminal: [28, 32, 26, 60, 0]
  runways:
    - id: "09L/27R"
      length_m: 3902
      ils: true
    - id: "09R/27L"
      length_m: 3660
      ils: true

simulation:
  daily_flight_target: 1300
  load_factor_mean: 0.88
  peak_hours: [6, 7, 8, 17, 18, 19, 20]

airlines:
  - code: "BA"
    name: "British Artex Airways"
    market_share: 0.45
    hub_terminal: "T5"
```

The `sim-orchestrator` reads this file at startup and generates all fixtures dynamically. No other code changes are needed.

---

## Priority order summary

| Priority | Phase                                   | Effort | Impact                            |
| -------- | --------------------------------------- | ------ | --------------------------------- |
| 1        | Fix Gap 2 — turnaround task graph       | Medium | High — makes delays realistic     |
| 2        | Fix Gap 3 — flight type distinction     | Low    | Medium — domestic vs intl realism |
| 3        | Phase 2 — scenario engine + YAML runner | High   | High — makes project demonstrable |
| 4        | Fix Gap 1 — spatial layout (taxi times) | Medium | Medium — physical realism         |
| 5        | Fix Gap 4 — conveyor spatial model      | Medium | Medium — baggage realism          |
| 6        | Gap 0.5 — better dashboards             | Medium | High — usability                  |
| 7        | Phase 4 — settings UI                   | Medium | High — interactive demonstrations |
| 8        | Phase 3 — full physical environment     | High   | High — wow factor                 |
| 9        | Phase 5 — real weather API              | Low    | Medium — easy win                 |
| 10       | Phase 5 — real schedule CSV loader      | Medium | High — real-world credibility     |
| 11       | Phase 6.1–6.7 — Mapbox geospatial twin  | High   | High — visual credibility         |
| 12       | Phase 6.8 — CesiumJS 3D globe           | Medium | High — wow factor (globe)         |
| 13       | HOW-TO + airport config system          | Medium | High — community adoption         |
| 14       | Adapt README & LICENSE & CONTRIBUTING   | Medium | High — community adoption & legal |
