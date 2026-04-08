# Roadmap v2 — Arthur International Airport Digital Twin

Next development phases following the completion of the Phase 6 geospatial twin.
All previous roadmap items are considered done. This document covers what comes next.

Current state of the system:

- All 7 services running with full event-driven architecture
- Physical layout, turnaround task graph, flight type distinction
- Scenario engine (8 YAML scenarios, CLI runner, REST API)
- Simulation settings UI
- Real-world data: OurAirports destinations, OpenFlights airlines, METAR live + historical
- Geospatial twin: Mapbox 2D/2.5D + CesiumJS 3D globe with live aircraft positioning

---

## Phase 0 — Developer & operator tooling

### _Make the simulation fully controllable at runtime_

The simulation is currently observable but not fully interactive. Operators can pause,
change speed, and inject incidents. This phase adds a full debug and authoring layer —
a superpower mode for developers demonstrating the system and researchers building scenarios.

### 0.1 — Live entity editor (debug mode)

A dedicated debug panel (toggle via keyboard shortcut `Ctrl+D` or header button)
that exposes direct runtime manipulation of every entity type.

- [x] **P0-1-1** — Add a passenger injection form: select a flight, generate N passengers at a given status (checked_in / security_queue / airside / at_gate), inject directly into Neo4j and emit `PassengerStatusChanged` events.
- [x] **P0-1-2** — Add a flight injection form: create a new flight on the fly with custom origin, destination, aircraft type, gate assignment, and departure time. Must trigger the normal downstream seeding (passengers, baggage, turnaround plan).
- [x] **P0-1-3** — Add a baggage injection form: create N bags for a given flight at a specific conveyor zone status. Useful for testing the DG detection and loading pipelines in isolation.
- [x] **P0-1-4** — Add an entity inspector: click any flight, passenger, bag, or gate on any dashboard to open a read/write property editor. Changes write directly to Neo4j and produce the appropriate Kafka event.
- [x] **P0-1-5** — Add a Cypher console directly in the dashboard: a textarea that sends arbitrary read-only Cypher queries to Neo4j and renders the result as a table. Invaluable for debugging state during demonstrations.
- [x] **P0-1-6** — Add a Kafka event inspector: a live feed of raw Kafka messages per topic with JSON syntax highlighting and per-topic filter. More focused than Kafka UI for demo use.

### 0.2 — Weather source switcher

Allow switching weather source at runtime without restarting the simulation.

- [x] **P0-2-1** — Add a `WEATHER_SOURCE` setting to the sim-orchestrator settings UI: `simulated` (current FSM), `historical` (replay from Iowa State Mesonet CSV), `live` (Aviation Weather Center ADDS API).
- [x] **P0-2-2** — Implement `historical` mode: the weather-service reads from a loaded CSV file and replays METARs in chronological order, scaled to simulation speed. A file picker in the settings UI selects the CSV from `data/weather/`.
- [x] **P0-2-3** — Implement `live` mode: the weather-service polls the ADDS API every 30 real minutes and maps the METAR response to `WeatherParams`. The proxy ICAO station is configurable (e.g. EGLL for Atlantic weather conditions).
- [x] **P0-2-4** — Add a weather override panel: lock any individual parameter (visibility, wind speed, ceiling) to a fixed value regardless of the active source. Useful for controlled scenario testing.
- [x] **P0-2-5** — Add a weather history chart to the ground ops dashboard: a 12-hour sparkline showing category transitions (CAVOK/VMC/IMC/LIFR), coloured by severity. Switchable between simulated and real history.

### 0.3 — Simulation state snapshots

- [x] **P0-3-1** — Implement `POST /sim/snapshot`: serialise the full Neo4j graph + current sim*time + Kafka offset positions to a JSON file. Store in `snapshots/{name}*{timestamp}.json`.
- [x] **P0-3-2** — Implement `POST /sim/restore`: restore from a snapshot file, resetting all service in-memory state and Neo4j to the snapshot state. The simulation resumes from the snapshot sim_time.
- [x] **P0-3-3** — Expose snapshot/restore in the settings UI with a snapshot browser (list of saved snapshots with sim_time, day, active incidents).
- [x] **P0-3-4** — Integrate snapshots with the scenario engine: a scenario can specify `start_from_snapshot: "morning-peak"` instead of a fresh seed, enabling mid-day scenario injection without fast-forwarding.

---

## Phase 1 — Simulation engine fidelity

### _Close the remaining physical and operational gaps_

### 1.1 — ADS-B integration

ADS-B (Automatic Dependent Surveillance–Broadcast) is the real-world technology that
aircraft use to broadcast their position. Integrating ADS-B data serves two purposes:
validating our great-circle interpolation model against real tracks, and enabling a
hybrid mode where real aircraft serve as the "ground truth" and simulated aircraft
fill gaps.

- [x] **P1-1-1** — Integrate the OpenSky Network REST API (`/api/states/all`) as a live data source. Poll every 10 real seconds and store the latest state vectors (lat/lon/altitude/heading/callsign) in an in-memory cache (Redis not needed — scope is small).
- [x] **P1-1-2** — Add a `GET /flights/adsb-states` endpoint returning live ADS-B state vectors for aircraft within 1,000 km of KART coordinates, formatted as GeoJSON FeatureCollection.
- [x] **P1-1-3** — Add an ADS-B overlay toggle to the world map and globe views: render real aircraft as a separate icon layer (different colour from simulated fleet). Label them with real callsigns.
- [x] **P1-1-4** — Implement track comparison: for a simulated flight with the same route as a real flight (e.g. KART→LHR on same heading), overlay the real ADS-B track alongside the simulated great-circle arc. Compute and display the deviation in km.
- [x] **P1-1-5** — Use ADS-B historical tracks (from OpenSky Network Zenodo monthly dumps) to calibrate the great-circle interpolation model: measure actual track deviation from great-circle and add a correction factor per route region (North Atlantic tracks deviate significantly due to NAT track system). _(Plan written in docs/lessons-learned/phase-1-adsb-calibration-plan.md; implementation deferred to data science sprint.)_
- [x] **P1-1-6** — Add a "real flights nearby" panel to the ground ops dashboard: list ADS-B aircraft currently within the KART FIR boundary, with callsign, altitude, speed, and distance to KART.

### 1.2 — Noise and variability model

The current simulation produces suspiciously clean outcomes. Every flight departs
within its modelled delay budget; every passenger arrives at the gate on time; every
bag reaches its carousel. Real operations are noisier.

- [x] **P1-2-1** — Add per-flight crew readiness stochastic delay: 5% of flights experience a 5–15 min crew delay independent of other factors. Modelled as a Bernoulli draw at the boarding → departed transition.
- [x] **P1-2-2** — Add ATC slot allocation delays: during peak hours, 10% of departures receive a CTOT (Calculated Take-Off Time) slot that delays pushback by 5–30 min. Emit a new `FlightCTOTAssigned` Kafka event.
- [x] **P1-2-3** — Add passenger no-shows: 2–4% of booked passengers do not board. Their checked bags must be offloaded before departure (the "no-show bag check" procedure). Wire this into the turnaround task graph as a conditional task.
- [x] **P1-2-4** — Add equipment failures: 1% chance per flight of a minor ground equipment failure (jetbridge stuck, catering truck breakdown) adding 8–20 min to the relevant turnaround task.
- [x] **P1-2-5** — Add flight diversion events: 0.3% of arriving flights are diverted to an alternate airport (weather below CAT III minimums, medical emergency). The flight never arrives at KART; its passengers are rebooked; its bags are rerouted.
- [x] **P1-2-6** — Add holding fuel burn tracking: aircraft in the holding stack consume fuel at a rate of ~2,500 kg/hour. After 30 sim-minutes in holding, emit a `MinimumFuelWarning` alert. After 45 min, the flight declares PAN PAN and is given priority landing.

### 1.3 — Ground vehicle simulation

Model the physical vehicles that enable turnaround operations.

- [x] **P1-3-1** — Define a `GroundVehicle` Neo4j node: type (fuel truck, catering truck, pushback tug, baggage loader, stairs), status (available / dispatched / at_gate / returning), current_gate, home_base.
- [x] **P1-3-2** — Add a vehicle dispatch model: when a turnaround task requires a vehicle, the nearest available vehicle of the correct type is dispatched. Transit time from home base to gate is computed from the spatial layout model.
- [x] **P1-3-3** — Add vehicle contention: if all fuel trucks are occupied when a new flight arrives, the fueling task is delayed until one becomes available. This creates a realistic "ground vehicle crunch" effect during peak hours.
- [x] **P1-3-4** — Emit `GroundVehicleDispatched` and `GroundVehicleReturned` Kafka events on `ground.events` topic.
- [x] **P1-3-5** — Add ground vehicles to the ground ops dashboard: small icons moving between gates and vehicle pools on the airport schematic. Coloured by type.
- [x] **P1-3-6** — Add a ground vehicle utilisation metric to Grafana: `ground_vehicle_utilisation_pct` by type. Alert when any type exceeds 85% utilisation for more than 10 sim-minutes.

### 1.4 — Runway sequencing model

Replace the simple queue-and-assign model with a realistic runway sequencing engine.

- [x] **P1-4-1** — Implement wake turbulence separation: different aircraft type pairs require different separation minima (HEAVY behind SUPER: 6 NM; MEDIUM behind HEAVY: 5 NM). Build a separation matrix and enforce it in the runway queue manager.
- [x] **P1-4-2** — Implement runway alternation: in IMC, alternate arrivals and departures on a single runway to maximise throughput. The queue manager must interleave departure clearances between arrival sequences.
- [x] **P1-4-3** — Model runway occupancy time (ROT): after an aircraft lands, the runway is occupied for 40–90 seconds before the next aircraft can land. ROT varies by aircraft type and runway exit position.
- [x] **P1-4-4** — Add a runway throughput chart to the flight board: a real-time bar chart showing actual movements per hour vs theoretical capacity for each runway. Divergence indicates sequencing constraints.

---

## Phase 2 — Prescriptive digital twin

### _From observing state to recommending decisions_

This is the highest-value phase and the one that transforms the project from a
simulation into a genuine decision support system.

### 2.1 — Bottleneck detection engine

- [x] **P2-1-1** — Define a `Bottleneck` data model: zone/service affected, severity (warning/critical), root cause, estimated duration, affected entity count, time of detection.
- [x] **P2-1-2** — Implement security queue bottleneck detection (already partially done via LightGBM): escalate to a `Bottleneck` when the forecast predicts wait > 20 sim-min with confidence > 0.75.
- [x] **P2-1-3** — Implement gate utilisation bottleneck: detect when gate availability in a terminal drops below 2 free gates while flights are queued for assignment.
- [x] **P2-1-4** — Implement baggage throughput bottleneck: detect when make-up carousel utilisation exceeds 90% for more than 5 sim-minutes.
- [x] **P2-1-5** — Implement connection risk cluster detection: when 5+ connecting passengers share the same inbound delayed flight and the same connection flight, flag as a connection cluster requiring active intervention.
- [x] **P2-1-6** — Implement ground vehicle bottleneck: detect when vehicle type utilisation exceeds 85% and a new demand is about to arise in the next 15 sim-minutes.
- [x] **P2-1-7** — Expose all active bottlenecks at `GET /analysis/bottlenecks` with severity, root cause, and time-to-impact estimate.

### 2.2 — Recommendation engine

For each detected bottleneck, generate a ranked list of possible interventions with
projected outcome metrics.

- [x] **P2-2-1** — Define the `Recommendation` model: action type, description, expected impact (quantified), cost (staff hours / delay minutes avoided), confidence score, expiry sim-time (after which the recommendation is no longer actionable).
- [x] **P2-2-2** — Implement security queue recommendations:
  - Open additional lane(s): project new wait time vs current
  - Issue early gate calls for specific flights: reduces late gate arrivals
  - Redirect check-in to less congested terminal: reduces upstream feed
- [x] **P2-2-3** — Implement gate conflict recommendations:
  - Pre-assign alternate gate: estimated walk time delta for passengers
  - Delay inbound taxi to hold position: buys time for gate to vacate
  - Swap two departures between gates: evaluate feasibility and net delay
- [x] **P2-2-4** — Implement connection recovery recommendations:
  - Hold connecting flight N minutes: cost in delay vs passengers saved
  - Fast-track connection cluster through security: requires special assistance flag
  - Rebook on next departure: only if delay > MCT + 30 min
- [x] **P2-2-5** — Implement ground delay program (GDP) recommendation: when weather reduces runway capacity below 60% of normal, recommend a ground delay program specifying which flights to hold and for how long to avoid airborne holding.
- [x] **P2-2-6** — Expose recommendations at `GET /analysis/recommendations` — always returns the top 3 ranked by expected impact / cost ratio.
- [x] **P2-2-7** — Add a recommendation feed to the incident dashboard: each active recommendation shown as a card with projected outcomes and a `[Apply]` button.

### 2.3 — What-if analysis engine

- [x] **P2-3-1** — Implement `POST /analysis/what-if`: accepts a proposed action (same schema as a recommendation), forks the current simulation state into an in-memory shadow simulation, runs it forward N sim-minutes, and returns projected KPIs (delay minutes, missed connections, queue depths, cascade depth).
- [x] **P2-3-2** — The shadow simulation runs without producing Kafka events or Neo4j writes. It uses the in-memory BULK mode from the speed fix plan. Max projection horizon: 120 sim-minutes.
- [x] **P2-3-3** — Add a what-if UI panel to the incident dashboard: input form for the proposed action, projected outcome chart (before/after KPIs side by side), confidence interval display.
- [x] **P2-3-4** — Add multi-action comparison: run up to 3 proposed actions simultaneously and render their projected outcomes as a comparison table. The operator selects the best option before applying.
- [x] **P2-3-5** — Log all what-if queries and their outcomes (did the operator apply? did the projection match reality?) to a `analysis_log` collection. This data trains the recommendation engine's confidence scores over time.

### 2.4 — Autonomous operations mode

- [x] **P2-4-1** — Add an `autonomous_mode` toggle to the settings UI. When enabled, the recommendation engine applies the top recommendation automatically every 5 sim-minutes if its confidence score exceeds a configurable threshold (default: 0.80).
- [x] **P2-4-2** — Implement an autonomous action log: every auto-applied recommendation is logged with its timestamp, expected outcome, and actual outcome measured 30 sim-minutes later.
- [x] **P2-4-3** — Add an autonomous vs manual comparison scenario: run the same scenario twice — once with human operator, once with autonomous mode — and auto-generate a comparison report showing total delay minutes, missed connections, and cascade depth for each.
- [x] **P2-4-4** — Add safety guards: autonomous mode cannot apply actions that involve flight cancellation, runway closure, or terminal evacuation. Those always require human confirmation.

---

## Phase 2.5 — 3D models, 2D layouts & visual assets

### _From abstract diagrams to physically accurate representations_

The simulation already renders the airport geospatially (Mapbox + CesiumJS) but the
visual assets are placeholders — flat icons for aircraft, generic rectangles for
terminals, no physical representation of baggage infrastructure. This phase replaces
all placeholder visuals with accurate, reusable 3D and 2D assets that make the twin
genuinely look like what it models.

### 2.5.1 — 3D aircraft models (glTF/GLB)

Aircraft models are used in two renderers: CesiumJS (globe view, altitude accurate)
and Mapbox (airport surface, top-down). Each renderer needs a different LOD (Level of Detail).

- [ ] **P25-1-1** — Define the aircraft model matrix — 4 silhouette families covering
      all aircraft types in the simulation:

  | Model file                | Represents               | Types covered          | Approx. seats |
  | ------------------------- | ------------------------ | ---------------------- | ------------- |
  | `narrowbody_single.glb`   | Single-aisle narrowbody  | A320, A321, B738, B739 | 150–220       |
  | `narrowbody_regional.glb` | Regional jet / turboprop | E195, DH8D, AT75       | 50–130        |
  | `widebody_twin.glb`       | Twin-aisle long-haul     | B77W, A333, A332, A359 | 280–400       |
  | `freighter.glb`           | Cargo freighter          | B744F, B77F            | N/A           |

- [ ] **P25-1-2** — Source royalty-free base models. Recommended free sources:
  - **Sketchfab** (CC BY): search "Boeing 737" or "Airbus A320", filter by license
  - **NASA 3D Resources** (public domain): https://nasa3d.arc.nasa.gov
  - **OpenGameArt** (CC0/CC BY): https://opengameart.org
  - **Blenderkit** (free assets): https://blenderkit.com

- [ ] **P25-1-3** — Prepare models for CesiumJS (globe, high-altitude view):
  - Export as glTF 2.0 binary (`.glb`) from Blender
  - Nose pointing toward +Y, wings along X, up along +Z
  - Centre at aircraft centre of gravity (roughly at wing root)
  - Scale: 1 unit = 1 metre (a B737 fuselage is ~39 m long)
  - Baked ambient occlusion texture, no specular maps needed at globe scale
  - Target polygon count: < 5,000 triangles per model (LOD2, seen from > 10 km)

- [ ] **P25-1-4** — Prepare models for Mapbox (airport surface, top-down icons):
  - Simplified top-down SVG sprite per aircraft family
  - Single colour fill + subtle shadow, pointing north (nose = up)
  - 4 sprite sizes: 16×16, 24×24, 32×32, 48×48 px for different zoom levels
  - Export as PNG sprite atlas + JSON descriptor (Mapbox sprite format)
  - Store in `public/sprites/aircraft-sprites.png` + `aircraft-sprites.json`

- [ ] **P25-1-5** — Prepare high-detail models for ground ops close-up (zoom 15+):
  - LOD0: < 50,000 triangles, livery-ready material slots (fuselage, engines, landing gear)
  - Generic white livery by default; airline colour as a configurable material
  - Animated landing gear: retracted at altitude, deployed below 1,000 ft AGL
  - Animated engines: slow rotation at idle, fast at thrust
  - Store in `public/models/aircraft/` with one subfolder per family

- [ ] **P25-1-6** — Implement LOD switching in CesiumJS based on camera altitude:

  ```typescript
  function getModelUri(aircraftType: string, cameraAltitude: number): string {
    const family = AIRCRAFT_FAMILY[aircraftType]; // e.g. "narrowbody_single"
    if (cameraAltitude > 100_000) return `/sprites/aircraft-${family}.png`;
    if (cameraAltitude > 10_000) return `/models/aircraft/${family}_lod2.glb`;
    return `/models/aircraft/${family}_lod0.glb`;
  }
  ```

- [ ] **P25-1-7** — Add aircraft colour coding by operational status:
  - Normal airborne: white silhouette
  - Low fuel warning (holding > 30 sim-min): amber + pulse animation
  - Delayed on ground: amber
  - Incident-affected: red
  - Diverted: gray

### 2.5.2 — 3D airport model

A physically accurate 3D representation of KART rendered in CesiumJS at zoom 13+,
replacing the current GeoJSON extruded rectangles with a proper architectural model.

- [ ] **P25-2-1** — Model the airport footprint in Blender from the `layout.json`
      coordinate grid. Export individual GLB files per structural element:
  - `terminal_a.glb`, `terminal_b.glb`, `terminal_c.glb` — terminal buildings with
    glass curtain wall, roof details, and jetbridge attachment points
  - `control_tower.glb` — ATC tower with rotating radar dish (animated via CesiumJS property)
  - `hangar_a.glb`, `hangar_b.glb` — maintenance hangars on the south apron
  - `fuel_depot.glb` — fuel farm near runway 09R threshold
  - `cargo_terminal.glb` — cargo apron building south of Terminal C

- [ ] **P25-2-2** — Model runway and taxiway infrastructure:
  - Runway surface with threshold markings, touchdown zone bars, centreline,
    and distance remaining markers — baked into a UV-mapped texture atlas
  - Taxiway surface with blue centreline lighting strips (emissive material at night)
  - Apron with painted stand numbers and aircraft guidance lines
  - All runway/taxiway elements as terrain-clamped GeoJSON with custom materials

- [ ] **P25-2-3** — Model airport furniture and animated elements:
  - Jet bridges: 3 articulated sections, animated to extend/retract on flight arrival/departure
  - Ground vehicle models (small, < 2,000 triangles each): fuel truck, pushback tug,
    catering truck, baggage loader, passenger stairs
  - Vehicle pools at their home positions between dispatches (see Phase 1.3)

- [ ] **P25-2-4** — Add night-mode lighting driven by sim_time:
  - Runway edge lights: white point lights along both edges, red threshold lights
  - Taxiway centreline lights: green emissive strips
  - Apron floodlights: warm white area lights on tall masts
  - Terminal glazing: warm orange interior glow (emissive material)
  - All lights activate when `sim_time` hour is in [20:00–06:00]

  ```typescript
  const simHour = new Date(simTime).getUTCHours();
  const isNight = simHour < 6 || simHour >= 20;
  airportLights.forEach((l) => {
    l.show = isNight;
  });
  ```

- [ ] **P25-2-5** — Add weather visual effects tied to the simulation weather state:
  - CAVOK / VMC: clear sky, sharp shadows, full sun
  - IMC: fog post-process effect reducing far-scene visibility, overcast sky
  - LIFR: heavy fog (Cesium `FogStage`), rain particle system, low ceiling
  - SN phenomena: snow particle system, white overlay on apron surfaces

### 2.5.3 — 2D baggage conveyor layout

An accurate, interactive 2D schematic of the KART baggage handling system — an
engineering-style diagram showing every belt, zone, and flow direction with live
throughput data overlaid.

```
┌──────────────────────────────────────────────────────────────────────┐
│  KART — Baggage Handling System — Level B1 (below check-in)         │
│                                                                      │
│  TERMINAL A           TERMINAL B           TERMINAL C               │
│  ┌──────────┐         ┌──────────┐         ┌──────────┐             │
│  │ A1..A8   │         │ B1..B8   │         │ C1..C8   │             │
│  │ check-in │         │ check-in │         │ check-in │             │
│  └────┬─────┘         └────┬─────┘         └────┬─────┘             │
│       ▼ 2min               ▼ 2min               ▼ 2min              │
│  [INDUCT-A]           [INDUCT-B]           [INDUCT-C]               │
│    600/hr               600/hr               600/hr                 │
│       ▼ 3min               ▼ 3min               ▼ 3min              │
│  [S1][S2]             [S3][S4]             [S5][S6]                 │
│  300/hr ea.           300/hr ea.           300/hr ea.               │
│       └──────────────────┬──────────────────────┘                   │
│                    [SORT MATRIX]                                     │
│                      1800/hr                                         │
│              ┌───────────┼───────────┐                              │
│         4min │      8min │     12min │  (inter-terminal penalties)  │
│              ▼           ▼           ▼                              │
│         [MU-A 1..5]  [MU-B 1..5]  [MU-C 1..5]                     │
│         150/hr ea.   150/hr ea.   150/hr ea.                        │
│         A01..A14     B01..B14     C01..C14                          │
│                                                                      │
│  ARRIVALS:  [CAR1][CAR2]   [CAR3][CAR4]   [CAR5][CAR6]             │
│             Terminal A      Terminal B      Terminal C               │
│             200/hr ea.      200/hr ea.      200/hr ea.              │
└──────────────────────────────────────────────────────────────────────┘
```

- [ ] **P25-3-1** — Implement the conveyor diagram as a React SVG component
      (`BaggageConveyorMap.tsx`). Each zone node is an SVG element with:
  - Fill colour driven by utilisation: green (0–60%) → amber (61–85%) → red (>85%)
  - Stroke: normal (neutral), offline (red dashed), degraded (amber dashed)
  - Belt segments as animated dashed `<line>` elements: CSS `stroke-dashoffset`
    animation speed proportional to current throughput (faster belt = faster animation)
  - Item count badge floating above each zone, live from WebSocket

- [ ] **P25-3-2** — Add live bag tracking on the diagram:
  - Selecting a bag in the search drawer highlights its current zone on the conveyor
    map and traces a glowing path from its origin check-in zone to its assigned make-up
    carousel, including any inter-terminal segments
  - Show all bags for a selected flight as a heatmap overlay on the diagram zones
  - Animate the last 10 bags to change zone as small moving squares along belt segments

- [ ] **P25-3-3** — Add zone-level throughput sparklines:
      a 10-minute mini chart of bags/minute sits below each major zone node (induction,
      screening, sorting matrix, make-up). Visible without hovering.

- [ ] **P25-3-4** — Add inter-terminal routing visualisation:
  - Cross-terminal bags shown in a distinct colour (purple) with transfer time badge
  - Hovering the inter-terminal segment shows current occupancy and delay impact

- [ ] **P25-3-5** — Add incident overlays on the diagram:
  - `system_failure (conveyor-sorting)`: sorting matrix turns red, all downstream
    arrows stop animating, `⚠ OFFLINE` badge appears
  - `baggage_fire (make-up-B-3)`: affected node pulses red for 3 seconds then turns
    gray, `🔥 FIRE` badge, adjacent nodes turn amber
  - Incident resolved: green flash before returning to utilisation colour

- [ ] **P25-3-6** — Add arrival carousel assignment panel below the diagram:
      active carousels, flight allocation, bags collected vs total, progress bar per carousel.

- [ ] **P25-3-7** — Add PNG export of the diagram for incident reports and scenario
      result archives (`[Export diagram]` button captures the live SVG state).

### 2.5.4 — 2D terminal floor plan (passenger flow)

A companion 2D floor plan for the passenger flow dashboard showing each terminal as
a simplified architectural plan rather than an abstract heatmap grid.

- [ ] **P25-4-1** — Design simplified floor plan SVGs for each terminal:
      check-in desk rows, security lane corridors, passport control booths (international
      terminal), retail/F&B zone labels, gate numbers correctly positioned, jetbridge
      symbols, and arrival carousel locations.
      Three files: `terminal_a_plan.svg`, `terminal_b_plan.svg`, `terminal_c_plan.svg`.

- [ ] **P25-4-2** — Overlay passenger density as a heat layer on the floor plan:
      semi-transparent zone fills (cold blue → hot red) driven by `zone_load_pct`,
      updating every 5 sim-seconds with a smooth CSS transition.

- [ ] **P25-4-3** — Animate passenger flow as moving dots:
      small circles travel along path segments from zone to zone at a rate proportional
      to throughput. Spawn at check-in, pass through security, branch into gate corridors.
      Rendered via `requestAnimationFrame`, decoupled from the WebSocket event cadence.

- [ ] **P25-4-4** — Visualise security lanes individually:
      each lane drawn as a distinct corridor with a dot queue extending behind it.
      Open lanes: green indicator. Closed: gray with ×. Queue length proportional to
      actual `security_queue_depth` divided by the number of open lanes.

- [ ] **P25-4-5** — Add a terminal view switcher: tabs above the passenger flow
      dashboard toggle between the existing heatmap grid and the floor plan view.
      Both use the same live WebSocket data.

### 2.5.5 — Asset pipeline & tooling

- [ ] **P25-5-1** — Set up a Blender Python export script (`scripts/export_models.py`)
      that batch-exports all airport and aircraft models to GLB with correct axis
      orientation, scale, and LOD variants:

  ```bash
  blender --background --python scripts/export_models.py
  ```

- [ ] **P25-5-2** — Set up a model optimisation pipeline using `gltf-pipeline` +
      Draco compression (60–80% file size reduction with no visible quality loss):

  ```bash
  npx gltf-pipeline -i narrowbody_single.glb     -o narrowbody_single.draco.glb --draco.compressionLevel 7
  ```

- [ ] **P25-5-3** — Add `public/models/README.md` documenting every model file:
      source URL, license, polygon count per LOD, axis orientation, scale, and which
      entity types use it.

- [ ] **P25-5-4** — Add model preloading on dashboard startup: fetch all GLB files
      into the CesiumJS cache before the first aircraft appears, eliminating pop-in.

- [ ] **P25-5-5** — Add a model viewer page (`/models`) in the dashboard:
      a standalone CesiumJS scene showing all aircraft models side by side at ground level
      with controls for LOD toggle, rotation, and polygon/texture stats inspection.
      Useful for validating community-contributed models before merging.

---

## Phase 3 — Multi-airport network simulation

### _From a single airport to an interconnected hub network_

A single airport twin is valuable. A network of interconnected twins reveals the
propagation of disruptions across the entire aviation system.

- [x] **P3-1** — Define a `Network` configuration: a YAML file listing 3–5 airports (KART + 4 real airports used as hubs), each with their own `config/airport.yaml` profile and a distance matrix.
- [x] **P3-2** — Implement network-aware delay propagation: when KART delays an outbound flight to LHR, LHR's incoming flight is also delayed, affecting its turnaround and subsequent departures. Model this as a cross-airport cascade.
- [x] **P3-3** — Add a network map view: a Mapbox/Cesium overlay showing all network airports as nodes, with real-time arc colours reflecting disruption status (green/amber/red).
- [x] **P3-4** — Implement network ground delay program: when one airport declares a GDP (Phase 2), affected feeder airports receive flow control constraints limiting their departure rate to that airport.
- [x] **P3-5** — Add a `GET /network/status` endpoint returning the health of all network airports: active incidents, delay propagation in-flight, and estimated recovery time.
- [x] **P3-6** — Add a network disruption scenario: one YAML scenario triggering a cascading disruption across the full network (e.g. LIFR at LHR → inbound KART flights delayed → KART departures delayed → CDG inbounds affected).

---

## Phase 4 — Community & ecosystem

### _From a reference project to a platform others can build on_

- [ ] **P4-1** — Publish the project to npm/PyPI: a `kart-sim` Python package that allows `pip install kart-sim && kart-sim start` to launch the full stack without cloning the repo.
- [ ] **P4-2** — Implement a scenario marketplace: a `scenarios/community/` directory with a submission guide. Community scenarios are validated by the CI pipeline (gate conditions must pass) before merging.
- [ ] **P4-3** — Add a plugin architecture for custom incident types: a `plugins/incidents/` directory where users define new incident types as Python classes implementing the `IncidentPlugin` interface without modifying core services.
- [ ] **P4-4** — Add an airport template gallery: 5 pre-built `config/airport.yaml` files for real airports (LHR, CDG, JFK, DXB, SIN) with their actual terminal counts, gate numbers, and runway configurations.
- [ ] **P4-5** — Add a Jupyter notebook gallery: reproducible analysis notebooks in `notebooks/` demonstrating: cascade depth distribution, LightGBM feature importance, weather FSM transition probabilities, scenario comparison.
- [ ] **P4-6** — Write an academic citation guide: how to cite the project in papers, the BibTeX entry, and guidance on which components are novel contributions vs established techniques.

---

## Phase 5 — Advanced ML & AI

### _Move beyond LightGBM to reinforcement learning and generative AI_

### 5.1 — Reinforcement learning for operations optimisation

- [ ] **P5-1-1** — Define the RL environment: state space (queue depths, gate utilisation, weather category, active incidents), action space (open lane, reassign gate, hold flight, issue GDP), reward function (negative delay minutes + negative missed connections).
- [ ] **P5-1-2** — Implement a `GymEnvironment` wrapper around the simulation engine using `gymnasium`. Each step advances the simulation by 1 sim-minute and returns the new state vector.
- [ ] **P5-1-3** — Train a PPO (Proximal Policy Optimisation) agent using `stable-baselines3`. Training runs the simulation in BULK mode at 3600× to generate episodes quickly.
- [ ] **P5-1-4** — Compare RL agent performance against: (a) no intervention baseline, (b) rule-based recommendation engine from Phase 2, (c) human operator in user study.
- [ ] **P5-1-5** — Deploy the trained RL agent as a fourth option in the autonomous mode toggle (alongside off / rule-based / threshold).

### 5.2 — Natural language operations interface

- [ ] **P5-2-1** — Add a natural language query endpoint `POST /query`: accepts plain English questions about the current simulation state and returns structured answers. Powered by an LLM with the current airport state as context.
  - "How many flights are delayed and what is the main cause?"
  - "Which connecting passengers are most at risk right now?"
  - "What would happen if I closed runway 09L for 20 minutes?"
- [ ] **P5-2-2** — Add a natural language incident injection: "Inject a severe security breach in Terminal B affecting gate B07" → parses intent → calls `POST /incidents/inject` with the correct parameters.
- [ ] **P5-2-3** — Add a simulation narration mode: the LLM generates a real-time running commentary of significant events ("At 08:32, flight AX412 entered the holding stack due to runway capacity constraints. This is the third holding event this hour..."). Displayed as a scrolling text feed in the dashboard.
- [ ] **P5-2-4** — Add an after-action report generator: at the end of a scenario run, generate a 2-page natural language summary of what happened, what interventions were applied, and what could have been done differently.

### 5.3 — Anomaly detection

- [ ] **P5-3-1** — Train an isolation forest on normal simulation metrics (queue depths, conveyor throughput, delay rates) to define a baseline. Deploy as a `GET /analysis/anomalies` endpoint returning current deviations from baseline with z-scores.
- [ ] **P5-3-2** — Add anomaly indicators to Grafana: red/amber/green status per service based on isolation forest score. Alert when any service deviates more than 3σ from baseline.
- [ ] **P5-3-3** — Add a "root cause" trace for each anomaly: walk the Kafka event log backwards from the anomaly timestamp to identify the originating event that triggered the deviation.

---

## Phase 6 — Observability & performance

### _Production-grade reliability and deep system introspection_

- [ ] **P6-1** — Add distributed tracing with OpenTelemetry: instrument all FastAPI services and the Node.js gateway. Export traces to Jaeger. Each Kafka event carries a `trace_id` in its envelope, enabling end-to-end trace from `SimClockTick` through all downstream effects.
- [ ] **P6-2** — Add structured logging with Loki: replace `print()` and standard `logging` with structlog producing JSON log lines. Ship to Grafana Loki. Add a Grafana Explore panel for log-to-trace correlation.
- [ ] **P6-3** — Add a simulation performance profiler: measure and report the real-time processing budget consumed by each service per tick. Alert if any service consumes > 80% of the available real-time budget at the current speed.
- [ ] **P6-4** — Implement Kubernetes manifests: `k8s/` directory with Deployment, Service, ConfigMap, and HorizontalPodAutoscaler manifests for all services. Target: `kubectl apply -f k8s/` deploys the full stack.
- [ ] **P6-5** — Add a CI/CD pipeline: GitHub Actions workflow running lint, unit tests, integration tests (against real Neo4j + Kafka containers), and docker-compose build on every PR. Badge on README.
- [ ] **P6-6** — Add load testing: a `tests/load/` directory with k6 scripts simulating 100 concurrent WebSocket connections and 1,000 REST requests/minute to the API gateway. Document the performance envelope.

---

## Phase 7 — Real operations bridge

### _Connecting the twin to real airport data streams_

This phase is the most ambitious and the closest to a production digital twin.

- [ ] **P7-1** — Implement ACARS (Aircraft Communications Addressing and Reporting System) message parsing: ACARS carries real-time operational messages (off-blocks, airborne, on-blocks, fuel uplifts). Parse a historical ACARS feed and use it to drive flight state transitions instead of the synthetic clock.
- [ ] **P7-2** — Implement ATIS (Automatic Terminal Information Service) broadcast: generate a synthetic ATIS voice broadcast (TTS) from the current weather conditions and active NOTAMs. Play it in the ground ops dashboard as ambient audio.
- [ ] **P7-3** — Implement NOTAM parsing: download active NOTAMs for KART's region from the FAA/Eurocontrol API and display them in a dedicated dashboard panel. Map NOTAM types to simulation effects (runway NOTAM → closure, navaid NOTAM → ILS unavailable).
- [ ] **P7-4** — Implement slot coordination (IATA Level 3 airport): add a slot allocation layer where airlines request departure and arrival slots, and the sim-orchestrator grants or modifies them based on capacity. Model slot compression during GDP.
- [ ] **P7-5** — Add a digital ATIS display to the ground ops dashboard: D-ATIS style weather summary in monospaced aviation format, updating every 30 sim-minutes. Include active runway, wind, visibility, ceiling, METAR, and any special remarks (runway contamination, bird activity, construction).

---

## Priority summary

| Phase       | Name                                   | Effort    | Impact                       | Prerequisite           |
| ----------- | -------------------------------------- | --------- | ---------------------------- | ---------------------- |
| **0**       | Developer & operator tooling           | Low       | High — daily use             | None                   |
| **1.1**     | ADS-B integration                      | Medium    | High — real-world validation | Phase 6 Mapbox done ✅ |
| **1.2**     | Noise & variability model              | Low       | Medium — simulation realism  | None                   |
| **1.3**     | Ground vehicle simulation              | Medium    | High — turnaround realism    | Gap 2 done ✅          |
| **1.4**     | Runway sequencing model                | Medium    | Medium — ATC realism         | None                   |
| **2.1–2.2** | Bottleneck detection + recommendations | Medium    | Very high — DT value prop    | Phase 1 services ✅    |
| **2.3**     | What-if analysis                       | High      | Very high — decision support | Phase 2.1              |
| **2.4**     | Autonomous mode                        | Medium    | High — demo wow factor       | Phase 2.2              |
| **2.5.1**   | 3D aircraft models                     | Medium    | High — visual realism        | CesiumJS done ✅       |
| **2.5.2**   | 3D airport model                       | High      | Very high — wow factor       | CesiumJS done ✅       |
| **2.5.3**   | 2D baggage conveyor layout             | Medium    | High — operational clarity   | Baggage service ✅     |
| **2.5.4**   | 2D terminal floor plan                 | Low       | Medium — UX improvement      | Passenger service ✅   |
| **2.5.5**   | Asset pipeline & tooling               | Low       | Medium — contributor DX      | Phase 2.5.1            |
| **3**       | Multi-airport network                  | High      | High — systemic view         | Phase 2 done           |
| **4**       | Community & ecosystem                  | Low       | High — adoption              | Phase 0 done           |
| **5.2**     | Natural language interface             | Medium    | High — accessibility         | Phase 2 done           |
| **5.1**     | RL optimisation                        | High      | Medium — research value      | Phase 2.3              |
| **5.3**     | Anomaly detection                      | Low       | Medium — ops intelligence    | Phase 6 Prometheus ✅  |
| **6**       | Observability & performance            | Medium    | Medium — production grade    | None                   |
| **7**       | Real operations bridge                 | Very high | Very high — production DT    | All prior phases       |

**Recommended order for next 3 months:**

```
Phase 0      (2 weeks)  → Phase 1.2 (1 week)  → Phase 1.3 (2 weeks)
→ Phase 2.1  (1 week)  → Phase 2.2 (2 weeks)  → Phase 2.3 (2 weeks)
→ Phase 2.5.3 (1 week) → Phase 2.5.4 (1 week) → Phase 2.5.1 (2 weeks)
→ Phase 4    (1 week)  → Phase 5.2  (2 weeks)
```

Phase 2.5 (models & layouts) can be parallelised with Phase 2 if a team member with
Blender skills is available — the visual assets do not depend on the recommendation
engine and can be developed independently.

Phase 2 (prescriptive DT) is the highest-priority investment: it is the capability
that most clearly differentiates this project from existing airport simulation tools,
and it is the most compelling demonstration for the scientific paper's evaluation section.
