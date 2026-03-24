# NOTE — Future development roadmap

## Arthur International Airport Digital Twin

This document captures design gaps, future capabilities, and the long-term vision for the
project. It is organised by priority and serves as both a technical backlog and a product
roadmap. Each section includes diagrams, examples, and concrete implementation directions.

---

## Current limitations

The current simulation is **operationally correct but spatially blind**. It models what happens
(flights delay, bags get screened, passengers queue) but not _where_ or _how long it physically
takes to get there_. The four gaps below define what "Phase 1 completeness" currently lacks.

---

### Gap 0 - Better documentation

As this project grew in complexity, the files are reparted in a lot of place and responsabilities are not super clear. A better documentation of the codebase and architecture is needed to make it easier to onboard new contributors and maintain a shared understanding of the system.
Improve the documentation by:

- Adding docstrings to all functions and classes, explaining their purpose, inputs, outputs, and side effects.
- Creating a high-level architecture diagram that shows how the different services, databases, and message queues interact with each other.
- Writing a README for each service that explains its role, how to run it, and how to test it.
- Improve the repo README to include an overview of the project, its goals, and how to get started. The interest of each service (with link to doc) should be explained so that users only interested in a specific part of the system can easily find the relevant information.

### Gap 1 — No physical layout

The airport has no spatial model. Gates, runways, taxiways, terminals, and carousels are abstract
labels (`"gate-B07"`, `"runway-09L"`) with no position, distance, or adjacency relationship.

**What this means in practice:**

A bag dropped at check-in desk `C12` and destined for gate `A03` travels the same simulated
distance as a bag going to gate `C02` next door. A plane landing on runway `09L` and taxiing to
gate `B07` takes the same time as one going to `C14` on the opposite side of the airport.

**What the real layout looks like:**

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
                                 │
         ════════════════════════╪═════════════════════════ RWY 09R/27L
                                 │
                            SOUTH


Gate distances from runway 09L threshold (approximate, metres):
  Terminal A:  A01=800m   A07=1,100m  A14=1,400m
  Terminal B:  B01=1,600m B07=1,900m  B14=2,200m
  Terminal C:  C01=2,400m C07=2,700m  C14=3,000m

Taxiing speed: ~15 km/h on taxiway, ~5 km/h on apron
→ Terminal A gate: ~4–7 min taxi time
→ Terminal B gate: ~7–10 min taxi time
→ Terminal C gate: ~11–15 min taxi time
```

**Proposed fix:** add a `position` property to `Gate`, `Runway`, and `Terminal` nodes in Neo4j
(x/y coordinates on a normalised 0–1000 grid), and compute taxi time dynamically:

```python
def taxi_time_minutes(runway_id: str, gate_id: str,
                       positions: dict) -> int:
    rwy_pos  = positions[runway_id]   # (x, y)
    gate_pos = positions[gate_id]     # (x, y)
    distance_m = euclidean(rwy_pos, gate_pos) * SCALE_FACTOR
    # Taxiway: 15 km/h → 250 m/min. Apron: 5 km/h → 83 m/min
    taxiway_dist = distance_m * 0.7
    apron_dist   = distance_m * 0.3
    return int(taxiway_dist / 250 + apron_dist / 83)
```

---

### Gap 2 — Turnaround time is a flat buffer, not a sequence

The current model applies a flat buffer (30 min narrow-body, 45 min wide-body) to absorb inbound
delays. Real turnaround is a sequenced set of parallel tasks with hard dependencies.

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

**The critical path** is: baggage offload → baggage loading → boarding → door close.
Any delay in the baggage chain directly delays departure — this is the link between
`baggage-service` and `flight-service` that the current model approximates with the buffer.

**Proposed fix:** model turnaround as a task graph with dependencies and per-task durations.
Replace the flat buffer with a `TurnaroundPlan` object:

```python
@dataclass
class TurnaroundTask:
    name: str
    starts_after: list[str]   # task names this depends on
    duration_min: int
    status: str               # pending | active | complete

NARROW_BODY_TURNAROUND = [
    TurnaroundTask("deplaning",        starts_after=[],           duration_min=14),
    TurnaroundTask("baggage_offload",  starts_after=[],           duration_min=12),
    TurnaroundTask("cleaning",         starts_after=["deplaning"], duration_min=8),
    TurnaroundTask("catering",         starts_after=[],           duration_min=15),
    TurnaroundTask("fueling",          starts_after=[],           duration_min=20),
    TurnaroundTask("baggage_loading",  starts_after=["baggage_offload"], duration_min=12),
    TurnaroundTask("boarding",         starts_after=["cleaning", "baggage_loading"], duration_min=22),
    TurnaroundTask("door_close",       starts_after=["boarding", "catering", "fueling"], duration_min=2),
]
```

---

### Gap 3 — No flight type distinction

All flights are treated identically. In reality:

| Flight type              | Turnaround | Baggage       | Passengers                 | Gate requirements             |
| ------------------------ | ---------- | ------------- | -------------------------- | ----------------------------- |
| Domestic short-haul      | 25–35 min  | 1 bag avg     | No customs                 | Any gate                      |
| International short-haul | 35–50 min  | 1.2 bags avg  | Customs + passport control | International gate            |
| Long-haul (>6h)          | 60–90 min  | 1.5 bags avg  | Customs + immigration      | Wide-body gate with jetbridge |
| Cargo                    | 90–180 min | N/A (freight) | None                       | Cargo apron                   |
| Charter                  | 45–60 min  | 1.3 bags avg  | Group check-in             | Any gate                      |

**Proposed fix:** add `flight_type` and `route_category` to the `Flight` node:

```python
class FlightType(str, Enum):
    DOMESTIC       = "domestic"
    INTL_SHORT     = "international_short"
    INTL_LONG      = "international_long"
    CARGO          = "cargo"
    CHARTER        = "charter"

class RouteCategory(str, Enum):
    SHORT_HAUL = "short_haul"   # < 3h
    MEDIUM_HAUL = "medium_haul" # 3–6h
    LONG_HAUL  = "long_haul"    # > 6h
```

This also unlocks realistic passenger processing differences — international arrivals go through
passport control and customs, domestic arrivals go directly to baggage claim.

---

### Gap 4 — Baggage conveyor has no spatial model

Bags travel from check-in to gate on a conveyor system with a fixed throughput rate, but the
actual layout of the conveyor — which check-in zones feed which screening units, which make-up
carousels serve which gates — is not modelled. A bag checked in at zone C12 for a flight at gate
A03 crosses two terminal boundaries. The current model treats this as instantaneous.

**Real KART baggage conveyor layout:**

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

---

## Roadmap — five development phases

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
```

---

## Phase 2 — Scenario engine

### What a scenario is

A scenario is a **named, reproducible sequence of events** injected into the simulation at
defined sim-time offsets, producing a documented expected outcome.

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
  - at_sim_offset_minutes: 45 # 08:15 sim time
    type: runway_incursion
    severity: critical
    location: runway-09L
    trigger: manual

  - at_sim_offset_minutes: 80 # 08:50 sim time — second stressor
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
├── runner.py                  ← CLI: python runner.py run morning-peak-storm
├── definitions/
│   ├── morning-peak-storm.yaml
│   ├── runway-incursion-peak.yaml
│   └── ...
├── results/
│   └── {scenario-name}/{timestamp}/
│       ├── metrics.json       ← captured Prometheus snapshots
│       ├── events.jsonl       ← all Kafka events during the run
│       ├── report.md          ← auto-generated narrative report
│       └── screenshots/       ← dashboard screenshots (Playwright)
└── comparisons/
    └── compare.py             ← diff two scenario results
```

**CLI usage:**

```bash
# Run a scenario
python scenarios/runner.py run runway-incursion-peak --speed 600

# Run and capture dashboard screenshots
python scenarios/runner.py run morning-peak-storm --capture

# Compare two runs
python scenarios/runner.py compare \
  results/morning-peak-storm/2024-06-15/ \
  results/morning-peak-storm/2024-06-16/

# List available scenarios
python scenarios/runner.py list
```

---

## Phase 3 — Physical environment

### Airport layout model

Add a `layout.json` to the sim-orchestrator fixtures defining all physical positions
on a normalised 1000×1000 grid (1 unit ≈ 1 metre):

```json
{
  "grid_scale": 1.0,
  "runways": {
    "09L": {
      "threshold_x": 0,
      "threshold_y": 300,
      "length": 3200,
      "heading": 90
    },
    "27R": {
      "threshold_x": 3200,
      "threshold_y": 300,
      "length": 3200,
      "heading": 270
    },
    "09R": {
      "threshold_x": 0,
      "threshold_y": 700,
      "length": 2800,
      "heading": 90
    },
    "27L": {
      "threshold_x": 2800,
      "threshold_y": 700,
      "length": 2800,
      "heading": 270
    }
  },
  "taxiways": {
    "alpha": { "from": "09L_exit", "to": "terminal_A_apron", "length_m": 400 },
    "bravo": { "from": "alpha", "to": "terminal_B_apron", "length_m": 350 },
    "charlie": { "from": "bravo", "to": "terminal_C_apron", "length_m": 320 }
  },
  "gates": {
    "A01": { "x": 850, "y": 120, "terminal": "A", "wide_body": false },
    "A07": { "x": 1050, "y": 120, "terminal": "A", "wide_body": true },
    "B01": { "x": 850, "y": 500, "terminal": "B", "wide_body": false },
    "B07": { "x": 1050, "y": 500, "terminal": "B", "wide_body": true },
    "C01": { "x": 850, "y": 880, "terminal": "C", "wide_body": false }
  }
}
```

### Taxi time computation

```python
from math import sqrt

def compute_taxi_time(runway_id: str, gate_id: str,
                       layout: dict) -> int:
    rwy   = layout["runways"][runway_id]
    gate  = layout["gates"][gate_id]

    # Distance from runway exit to gate (via taxiway segments)
    exit_x = rwy["threshold_x"] + 600  # typical exit point
    exit_y = rwy["threshold_y"]

    taxiway_dist_m = sqrt((gate["x"] - exit_x)**2 +
                           (gate["y"] - exit_y)**2)

    # Speed: taxiway 15 km/h = 250 m/min, apron 5 km/h = 83 m/min
    taxiway_min = taxiway_dist_m * 0.7 / 250
    apron_min   = taxiway_dist_m * 0.3 / 83

    return max(3, int(taxiway_min + apron_min))  # minimum 3 minutes
```

### Passenger flow spatial model

Add walking time between zones based on their physical distance:

```
Zone distances at KART (approximate, metres):

  Check-in A → Security A:    120m  (~1.5 min walk)
  Security A → Airside A:      80m  (~1.0 min)
  Airside A  → Gate A01:       50m  (~0.7 min)
  Airside A  → Gate A14:      300m  (~3.5 min)
  Airside A  → Gate B01:      400m  (cross-terminal, ~5.0 min via connector)
  Airside A  → Gate C01:      700m  (cross-terminal, ~8.5 min via connector)

Special assistance: multiply all walking times × 2.5
```

This directly feeds the connection risk model — a passenger connecting from a C-pier arrival
to an A-pier departure in 45 minutes faces a much tighter constraint than the same connection
within Terminal B.

---

## Phase 4 — Simulation settings UI

A dedicated settings panel in the React dashboard that exposes all simulation parameters
as interactive controls, with real-time effect on the running simulation.

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
└─────────────────────────┴───────────────────────────────────┘
```

Each change sends a `PATCH` to the sim-orchestrator or the relevant service via the API gateway,
taking effect on the next simulated minute tick.

---

## Phase 5 — Real-world data integration

### Weather (live)

Replace the FSM with real METAR data from a public aviation weather API:

```python
import httpx

AVWX_API = "https://avwx.rest/api/metar/{station}"

async def fetch_real_metar(icao: str = "EHAM") -> WeatherParams:
    """
    Fetch real METAR from a real airport (e.g. EHAM = Amsterdam Schiphol)
    and map it to our WeatherParams model.
    Use a real airport as a weather proxy for our fictional KART.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            AVWX_API.format(station=icao),
            headers={"Authorization": f"Bearer {AVWX_TOKEN}"}
        )
    data = resp.json()
    return WeatherParams(
        category=classify_category(data["visibility"], data["ceiling"]),
        visibility_m=data["visibility"]["value"],
        wind_direction=data["wind_direction"]["value"],
        wind_speed_kt=data["wind_speed"]["value"],
        wind_gust_kt=data.get("wind_gust", {}).get("value", 0),
        ceiling_ft=data.get("ceiling", {}).get("value"),
        temperature_c=data["temperature"]["value"],
        dew_point_c=data["dewpoint"]["value"],
        qnh_hpa=data["altimeter"]["value"],
        phenomena=[c["modifier"] for c in data.get("wx_codes", [])],
    )
```

### Flight schedules (historical CSV)

Map real historical schedule data (e.g. from OpenSky Network or Eurocontrol NEST exports)
to our `Flight` model, replacing the synthetic bimodal generator:

```python
import pandas as pd

def load_schedule_from_csv(path: str, sim_date: str) -> list[dict]:
    """
    Expected CSV columns:
    callsign, origin, destination, scheduled_departure, scheduled_arrival,
    aircraft_type, airline_iata
    """
    df = pd.read_csv(path)
    df = df[df["scheduled_departure"].str.startswith(sim_date)]
    flights = []
    for _, row in df.iterrows():
        flights.append({
            "flight_number": row["callsign"],
            "airline_code":  row["airline_iata"],
            "origin_iata":   row["origin"],
            "destination_iata": row["destination"],
            "aircraft_type": row["aircraft_type"],
            "scheduled_time": row["scheduled_departure"],
            "direction": "departure",
        })
    return flights
```

**Data sources for real schedules:**

| Source              | Format    | Coverage           | License       |
| ------------------- | --------- | ------------------ | ------------- |
| OpenSky Network     | CSV       | Global, historical | CC BY 4.0     |
| Eurocontrol NEST    | CSV       | European, detailed | Research only |
| FlightAware AeroAPI | JSON REST | Global, live       | Commercial    |
| OurAirports         | CSV       | Airports + routes  | Public domain |

---

## HOW-TO — Create your own airport

This section will become a standalone `HOW_TO_CREATE_AIRPORT.md` once Phase 2 is complete.
The goal: a developer should be able to fork this repo, change a single config file, and have
a fully functioning different airport simulation running in under an hour.

### Minimum configuration to customise

```yaml
# config/airport.yaml

identity:
  name: "Heathrow International Airport"
  iata: "LHR"
  icao: "EGLL"
  city: "London"
  timezone: "Europe/London"

infrastructure:
  terminals: 5 # T2, T3, T4, T5 + T1 (closed)
  gates_per_terminal: [28, 32, 26, 60, 0]
  runways:
    - id: "09L/27R"
      length_m: 3902
      ils: true
    - id: "09R/27L"
      length_m: 3660
      ils: true

simulation:
  daily_flight_target: 1300 # LHR does ~650 movements/day
  load_factor_mean: 0.88
  peak_hours: [6, 7, 8, 17, 18, 19, 20]

airlines: # define the fictional carriers for this airport
  - code: "BA"
    name: "British Artex Airways"
    market_share: 0.45
    hub_terminal: "T5"
  - code: "VS"
    name: "Violet Star"
    market_share: 0.12
    hub_terminal: "T3"
```

The sim-orchestrator reads this file at startup and generates all fixtures dynamically.
No other code changes are needed to simulate a different airport.

---

## Priority order summary

| Priority | Phase                                   | Effort | Impact                            |
| -------- | --------------------------------------- | ------ | --------------------------------- |
| 1        | Fix Gap 2 — turnaround task graph       | Medium | High — makes delays realistic     |
| 2        | Fix Gap 3 — flight type distinction     | Low    | Medium — domestic vs intl realism |
| 3        | Phase 2 — scenario engine + YAML runner | High   | High — makes project demonstrable |
| 4        | Fix Gap 1 — spatial layout (taxi times) | Medium | Medium — physical realism         |
| 5        | Fix Gap 4 — conveyor spatial model      | Medium | Medium — baggage realism          |
| 6        | Phase 4 — settings UI                   | Medium | High — interactive demonstrations |
| 7        | Phase 3 — full physical environment     | High   | High — wow factor                 |
| 8        | Phase 5 — real weather API              | Low    | Medium — easy win                 |
| 9        | Phase 5 — real schedule CSV loader      | Medium | High — real-world credibility     |
| 10       | HOW-TO + airport config system          | Medium | High — community adoption         |

The scenario engine (Phase 2) should be built in parallel with or immediately after fixing
the four gaps — without reproducible scenarios, it is hard to demonstrate that the gap fixes
actually improved anything.

---

## Phase 6 — Geospatial digital twin (Mapbox)

This phase transforms the project from an abstract operational simulation into a **true
geospatial digital twin** anchored in the real world. Three capabilities build on each other:
airport placement → real destinations → live aircraft positioning.

---

### 6.1 — Placing KART in the real world

Arthur International Airport is a fictional airport but it needs a real-world coordinate
so it can be rendered on a map and so that distances to real destination airports are
meaningful.

**Proposed location:** mid-Atlantic fictional island territory, chosen to avoid overlapping
any real airport while being geographically plausible for an international hub.

```
KART — Arthur International Airport
Coordinates: 38.7500° N, 27.0833° W
             (fictional Azores-adjacent location, open ocean)
Elevation:   48 m AMSL
Magnetic variation: 8.5° W

Runway orientations (true):
  09L/27R: heading 090° / 270° (east–west)
  09R/27L: heading 090° / 270° (parallel, 400m south)

Real-world bounding box:
  SW corner: 38.7420° N, 27.1100° W
  NE corner: 38.7600° N, 27.0400° W
  Airport footprint: ~3.2 km × 1.8 km
```

**Why this location:**

- No real airport within 300 km — no conflicts with real-world flight data
- Realistic North Atlantic position — plausible routes to Europe, Americas, Africa
- Time zone: UTC−1 (fictional) — easy offset for sim time display

---

### 6.2 — Mapbox GL JS integration

The ground ops dashboard (`/ground-ops`) and a new world map view (`/world`) both use
Mapbox GL JS as the base renderer.

**Layer stack (bottom to top):**

```
┌─────────────────────────────────────────────────────┐  ← layer 7: aircraft icons (live)
├─────────────────────────────────────────────────────┤  ← layer 6: flight route arcs
├─────────────────────────────────────────────────────┤  ← layer 5: gate labels + status
├─────────────────────────────────────────────────────┤  ← layer 4: terminal buildings (fill)
├─────────────────────────────────────────────────────┤  ← layer 3: taxiways (line)
├─────────────────────────────────────────────────────┤  ← layer 2: runways (fill-extrusion)
├─────────────────────────────────────────────────────┤  ← layer 1: apron surface (fill)
├─────────────────────────────────────────────────────┤  ← layer 0: Mapbox satellite base
└─────────────────────────────────────────────────────┘
             real world hidden below custom layers
```

**Implementation approach — GeoJSON sources updated from WebSocket:**

```typescript
// src/map/AirportMap.tsx

import mapboxgl from "mapbox-gl";

const KART_CENTER: [number, number] = [-27.0833, 38.75];

const map = new mapboxgl.Map({
  container: "map",
  style: "mapbox://styles/mapbox/satellite-v9",
  center: KART_CENTER,
  zoom: 14,
  bearing: 0,
  pitch: 45, // 3D tilt for building extrusion
});

map.on("load", () => {
  // Hide real-world POIs and labels in the airport area
  map.setLayoutProperty("poi-label", "visibility", "none");
  map.setLayoutProperty("road-label", "visibility", "none");
  map.setLayoutProperty("airport-label", "visibility", "none");

  // Add airport surface layers from static GeoJSON
  map.addSource("kart-runways", {
    type: "geojson",
    data: "/geojson/runways.geojson",
  });
  map.addSource("kart-taxiways", {
    type: "geojson",
    data: "/geojson/taxiways.geojson",
  });
  map.addSource("kart-terminals", {
    type: "geojson",
    data: "/geojson/terminals.geojson",
  });
  map.addSource("kart-apron", {
    type: "geojson",
    data: "/geojson/apron.geojson",
  });

  // Live data sources — updated from WebSocket
  map.addSource("aircraft-live", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addSource("flight-routes", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addSource("gate-status", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });

  addAirportLayers(map);
  addAircraftLayer(map);
  addRouteLayer(map);
});
```

**Airport GeoJSON files (static, checked into repo):**

```
public/geojson/
├── runways.geojson      ← two runway polygons with headings
├── taxiways.geojson     ← taxiway centreline LineStrings
├── terminals.geojson    ← terminal building footprint Polygons
├── gates.geojson        ← gate positions as Points with gate_id property
└── apron.geojson        ← apron surface Polygon
```

**Runway layer (3D extrusion for realism):**

```typescript
map.addLayer({
  id: "runways-surface",
  type: "fill-extrusion",
  source: "kart-runways",
  paint: {
    "fill-extrusion-color": "#2a2a2a",
    "fill-extrusion-height": 0.3, // 30 cm above ground
    "fill-extrusion-base": 0,
    "fill-extrusion-opacity": 0.95,
  },
});

// Runway threshold markings
map.addLayer({
  id: "runway-markings",
  type: "line",
  source: "kart-runways",
  paint: {
    "line-color": "#ffffff",
    "line-width": 1.5,
    "line-dasharray": [10, 5],
  },
});
```

**Terminal buildings (3D extrusion):**

```typescript
map.addLayer({
  id: "terminals-3d",
  type: "fill-extrusion",
  source: "kart-terminals",
  paint: {
    "fill-extrusion-color": [
      "match",
      ["get", "terminal"],
      "A",
      "#4a90d9",
      "B",
      "#7b68ee",
      "C",
      "#50c878",
      "#888888",
    ],
    "fill-extrusion-height": ["get", "height_m"], // A=18m, B=22m, C=16m
    "fill-extrusion-base": 0,
    "fill-extrusion-opacity": 0.85,
  },
});
```

---

### 6.3 — Real destination airports

Replace the 40 fictional destination airports with real ones drawn from the
**OurAirports public domain database** (updated monthly, CC0 license).

**Data source:**

```
https://ourairports.com/data/airports.csv
Columns: id, ident, type, name, latitude_deg, longitude_deg,
         elevation_ft, continent, iso_country, municipality,
         iata_code, ...
```

**Selection criteria for the KART destination pool:**

```python
import pandas as pd
from math import radians, sin, cos, sqrt, atan2

KART_LAT = 38.7500
KART_LON = -27.0833

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def build_destination_pool() -> pd.DataFrame:
    df = pd.read_csv("ourairports_airports.csv")

    # Keep only large and medium airports with IATA codes
    df = df[df["type"].isin(["large_airport", "medium_airport"])]
    df = df[df["iata_code"].notna() & (df["iata_code"] != "")]

    # Compute distance from KART
    df["distance_km"] = df.apply(
        lambda r: haversine_km(KART_LAT, KART_LON,
                                r["latitude_deg"], r["longitude_deg"]),
        axis=1
    )

    # Filter: 200km minimum (no local hops), 12,000km maximum (ultra-long-haul)
    df = df[(df["distance_km"] >= 200) & (df["distance_km"] <= 12000)]

    # Sample a realistic pool: bias toward major hubs
    # Weight large airports 5× higher than medium
    df["weight"] = df["type"].map({"large_airport": 5, "medium_airport": 1})

    return df.sample(n=200, weights="weight", random_state=42)
```

**Flight duration from real distance:**

```python
# Cruise speed by aircraft type (km/h)
CRUISE_SPEED = {
    "B738": 840, "A320": 833, "A321": 833,
    "B77W": 905, "A333": 871, "A332": 871,
    "E195": 829, "DH8D": 556,
}

# Climb + descent overhead (minutes)
ALTITUDE_OVERHEAD = {
    "short_haul":  25,  # < 1500 km
    "medium_haul": 35,  # 1500–4000 km
    "long_haul":   50,  # > 4000 km
}

def compute_flight_duration(distance_km: float,
                             aircraft_type: str) -> int:
    speed = CRUISE_SPEED.get(aircraft_type, 840)
    cruise_time_min = (distance_km / speed) * 60

    if distance_km < 1500:
        overhead = ALTITUDE_OVERHEAD["short_haul"]
    elif distance_km < 4000:
        overhead = ALTITUDE_OVERHEAD["medium_haul"]
    else:
        overhead = ALTITUDE_OVERHEAD["long_haul"]

    return int(cruise_time_min + overhead)
```

**What this unlocks:**

```
KART → LHR (London Heathrow):   2,142 km  →  3h 10min  (A320)
KART → JFK (New York JFK):      4,956 km  →  6h 45min  (B77W)
KART → GRU (São Paulo):         5,218 km  →  7h 05min  (B77W)
KART → CDG (Paris CDG):         2,070 km  →  3h 05min  (A321)
KART → NBO (Nairobi):           7,431 km  →  9h 20min  (B77W)
KART → SYD (Sydney):           18,640 km  → beyond range
```

The 12,000 km cap reflects realistic range limits. Ultra-long-haul beyond this range
is excluded from the destination pool unless a specific wide-body with aux tanks is modelled.

This also drives the flight type classification automatically:

- distance < 1,500 km → short-haul
- 1,500–4,000 km → medium-haul (most European routes)
- > 4,000 km → long-haul (North America, Africa, Middle East)

---

### 6.4 — Live aircraft positioning on the world map

Every airborne flight has a known departure point (KART), a known destination (real lat/lon
from OurAirports), and a known elapsed fraction of its flight time. Position is interpolated
along the **great-circle arc** between the two points.

**Great-circle interpolation:**

```python
from math import radians, degrees, sin, cos, atan2, asin, sqrt

def great_circle_point(lat1_deg: float, lon1_deg: float,
                        lat2_deg: float, lon2_deg: float,
                        fraction: float) -> tuple[float, float]:
    """
    Returns (lat, lon) at `fraction` (0.0–1.0) along the great circle
    from (lat1, lon1) to (lat2, lon2).
    """
    lat1, lon1 = radians(lat1_deg), radians(lon1_deg)
    lat2, lon2 = radians(lat2_deg), radians(lon2_deg)

    d = 2 * asin(sqrt(
        sin((lat2 - lat1) / 2)**2 +
        cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2)**2
    ))

    if d < 1e-10:
        return lat1_deg, lon1_deg

    A = sin((1 - fraction) * d) / sin(d)
    B = sin(fraction * d) / sin(d)

    x = A * cos(lat1) * cos(lon1) + B * cos(lat2) * cos(lon2)
    y = A * cos(lat1) * sin(lon1) + B * cos(lat2) * sin(lon2)
    z = A * sin(lat1) + B * sin(lat2)

    lat = atan2(z, sqrt(x**2 + y**2))
    lon = atan2(y, x)

    return degrees(lat), degrees(lon)


def compute_aircraft_position(flight: dict, sim_time: datetime) -> dict:
    departed_at = datetime.fromisoformat(flight["actual_departure"])
    total_min   = flight["flight_duration_minutes"]
    elapsed_min = (sim_time - departed_at).total_seconds() / 60

    fraction = max(0.0, min(1.0, elapsed_min / total_min))

    lat, lon = great_circle_point(
        KART_LAT, KART_LON,
        flight["destination_lat"], flight["destination_lon"],
        fraction
    )

    # Altitude model: climb to FL350, cruise, descend last 20%
    altitude_ft = compute_altitude(fraction, flight["aircraft_type"])

    # Heading: bearing toward next great-circle point
    heading = compute_bearing(lat, lon,
                               flight["destination_lat"],
                               flight["destination_lon"])

    return {
        "flight_id":     flight["id"],
        "flight_number": flight["flight_number"],
        "lat": lat, "lon": lon,
        "altitude_ft":   altitude_ft,
        "heading_deg":   heading,
        "fraction":      fraction,
        "aircraft_type": flight["aircraft_type"],
        "origin_iata":   "ART",
        "destination_iata": flight["destination_iata"],
    }


def compute_altitude(fraction: float, aircraft_type: str) -> int:
    """Simplified altitude profile: climb 0–15%, cruise 15–85%, descend 85–100%"""
    cruise_fl = 350 if aircraft_type in {"B77W","A333","A332"} else 380
    cruise_ft = cruise_fl * 100

    if fraction < 0.15:
        return int((fraction / 0.15) * cruise_ft)
    elif fraction > 0.85:
        return int(((1 - fraction) / 0.15) * cruise_ft)
    else:
        return cruise_ft
```

**Serving live positions via the flight-service:**

```python
# GET /api/v1/flights/live-positions
# Returns GeoJSON FeatureCollection for Mapbox

async def get_live_positions(sim_time: datetime) -> dict:
    airborne = await get_flights_by_status(["airborne", "approach"])
    features = []
    for flight in airborne:
        pos = compute_aircraft_position(flight, sim_time)
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [pos["lon"], pos["lat"]]
            },
            "properties": {
                "flight_id":      pos["flight_id"],
                "flight_number":  pos["flight_number"],
                "altitude_ft":    pos["altitude_ft"],
                "heading_deg":    pos["heading_deg"],
                "aircraft_type":  pos["aircraft_type"],
                "origin":         pos["origin_iata"],
                "destination":    pos["destination_iata"],
                "fraction":       pos["fraction"],
            }
        })
    return {"type": "FeatureCollection", "features": features}
```

**Mapbox aircraft layer:**

```typescript
// Rotate icon by heading — Mapbox supports icon-rotate from a feature property
map.addLayer({
  id: "aircraft-live",
  type: "symbol",
  source: "aircraft-live",
  layout: {
    "icon-image": "aircraft-icon", // custom SVG sprite
    "icon-size": 0.6,
    "icon-rotate": ["get", "heading_deg"],
    "icon-allow-overlap": true,
    "icon-rotation-alignment": "map",
    "text-field": ["get", "flight_number"],
    "text-size": 10,
    "text-offset": [0, 1.5],
    "text-optional": true,
  },
  paint: {
    "icon-color": [
      "match",
      ["get", "aircraft_type"],
      "B77W",
      "#e74c3c", // wide-body: red
      "A333",
      "#e74c3c",
      "#3498db", // narrow-body: blue
    ],
    "text-color": "#ffffff",
    "text-halo-color": "#000000",
    "text-halo-width": 1,
  },
});

// Update positions every simulated minute from WebSocket
ws.onmessage = (event) => {
  const envelope = JSON.parse(event.data);
  if (envelope.event_type === "SimClockTick") {
    fetch("/api/v1/flights/live-positions")
      .then((r) => r.json())
      .then((geojson) => {
        (map.getSource("aircraft-live") as mapboxgl.GeoJSONSource).setData(
          geojson,
        );
      });
  }
};
```

---

### 6.5 — Flight route arcs

Each airborne flight's great-circle route is rendered as a curved arc on the world map,
fading from full opacity at the aircraft's current position to transparent at the destination.

**Route GeoJSON generation:**

```python
def generate_route_arc(flight: dict, n_points: int = 60) -> dict:
    """Generate a LineString of n_points along the great-circle route."""
    coords = []
    for i in range(n_points + 1):
        frac = i / n_points
        lat, lon = great_circle_point(
            KART_LAT, KART_LON,
            flight["destination_lat"], flight["destination_lon"],
            frac
        )
        coords.append([lon, lat])

    return {
        "type": "Feature",
        "geometry": { "type": "LineString", "coordinates": coords },
        "properties": {
            "flight_id":     flight["id"],
            "flight_number": flight["flight_number"],
            "fraction":      flight["fraction"],  # how far along the route
        }
    }
```

**Route layer (dashed line, fades ahead of aircraft):**

```typescript
map.addLayer({
  id: "flight-routes",
  type: "line",
  source: "flight-routes",
  paint: {
    "line-color": "#ffffff",
    "line-width": 0.8,
    "line-opacity": 0.35,
    "line-dasharray": [4, 3],
  },
});
```

---

### 6.6 — New dashboard: world map view (`/world`)

A dedicated full-screen dashboard showing the global view of the KART operation.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Arthur Airport — World View         SIM: Day 1 · 14:32  ART  IMC  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   [Mapbox satellite globe]                                          │
│                                                                     │
│   ✈ AX412 ──────────────────────────────────────> LHR              │
│       ↖ KART                       ✈ BK217 ──────────────> JFK      │
│                                                                     │
│   ✈ KV388 ──────> CDG                                              │
│                                                                     │
│   ● KART (airport footprint — zoom in for gate detail)             │
│                                                                     │
└────────────────────────┬────────────────────────────────────────────┘
│ AIRBORNE: 34  │ ENROUTE > 6H: 8  │ APPROACHING: 4  │ LONGEST: AX801 BKK 9h12m │
└─────────────────────────────────────────────────────────────────────┘
```

**Zoom behaviour:**

- Zoom 2–8: world view — aircraft icons + route arcs, KART as a dot
- Zoom 9–12: regional view — airport outline appears, surrounding terrain visible
- Zoom 13+: airport detail view — runways, taxiways, terminals, gate status rendered

This seamless transition from world → airport → gate is the "wow" moment of the geospatial phase.

---

### 6.7 — Implementation notes and gotchas

**Mapbox token:** requires a free Mapbox account. Set `VITE_MAPBOX_TOKEN` in the dashboard
`.env` file. The satellite style (`mapbox://styles/mapbox/satellite-v9`) is free tier eligible
for a demo project at this traffic level.

**GeoJSON accuracy:** the airport GeoJSON files should be drawn in QGIS or geojson.io at
the chosen KART coordinates. Runway headings must match the magnetic variation (8.5° W)
so that the overlay aligns with the satellite base map.

**Antimeridian:** great-circle routes from KART westward to Asia cross the antimeridian
(180° longitude). Mapbox handles this if coordinates are not clipped — allow longitudes
outside −180/+180 range (e.g. 190° instead of −170°) and Mapbox wraps correctly.

**Performance:** updating 34 aircraft positions every simulated minute is trivial.
Use `source.setData()` (full GeoJSON replace) rather than per-feature updates — it is
faster in Mapbox GL JS for small feature counts.

**Aircraft icon sprite:** add a custom SVG aircraft silhouette as a Mapbox sprite.
The icon must be top-down (plan view) and point upward (north = 0°) so that
`icon-rotate: heading_deg` aligns correctly.

**Offline fallback:** if Mapbox token is missing or quota exceeded, fall back to a
Leaflet.js map with OpenStreetMap tiles. The GeoJSON layers and live aircraft positions
work identically — only the base style changes.
