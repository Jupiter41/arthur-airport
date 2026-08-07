# Simulation engine

**Project:** Arthur International Airport Digital Twin  
**Service:** `sim-orchestrator`  
**Language:** Python 3.11+

---

## 1. Overview

The simulation engine is the heart of the digital twin. It has three jobs:

1. **Drive time** — advance a virtual clock at configurable speed and broadcast ticks to all services.
2. **Seed reality** — generate a realistic daily flight schedule, passenger manifests, and baggage records at startup.
3. **Inject disorder** — fire probabilistic hazardous events and weather transitions that force cascading reactions across the system.

The engine does not own any domain state. It is a conductor, not a store. All state lives in Neo4j and flows through Kafka.

---

## 2. Time model

### Virtual clock

The simulation runs on a virtual `sim_time` (a DateTime). All services operate exclusively on `sim_time` — no service reads the wall clock for business logic.

```
real elapsed time × speed_multiplier = sim elapsed time
```

| Speed preset | Multiplier | 1 real second = |
| ------------ | ---------- | --------------- |
| Real time    | 1×         | 1 sim second    |
| Fast         | 10×        | 10 sim seconds  |
| Default      | 60×        | 1 sim minute    |
| Compressed   | 600×       | 10 sim minutes  |
| Fast-forward | 3600×      | 1 sim hour      |

Speed is configurable at runtime via the orchestrator API (`PATCH /sim/speed`).

### Clock tick

Every simulated minute the orchestrator emits a `SimClockTick` to `sim.clock`. Services wake on each tick and process any time-triggered events (e.g. "flight AX412 is due to depart in 30 sim-minutes — transition to boarding").

### Day boundary

The simulation runs continuous 24-hour cycles. On each day boundary, the orchestrator seeds a new flight schedule for the next simulated day and generates new passenger/baggage records for those flights.

---

## 3. Schedule seeding

On startup (and each day boundary), the orchestrator generates a full day's flight schedule for KART.

### Daily volume targets

| Metric              | Target                                        |
| ------------------- | --------------------------------------------- |
| Total movements     | 420 (210 arrivals + 210 departures)           |
| Peak hour movements | ~30–33 (07:00–09:00 and 17:00–19:00 sim time) |
| Off-peak movements  | ~16–22/hour (sustained base traffic)          |
| Airlines            | 12 fictional carriers                         |
| Aircraft types      | B738, A320, A321, B77W, A333, E195, DH8D      |

### Schedule generation algorithm

```
1. Sample 210 departure slots from a realistic hourly traffic distribution:
   - 05:00–07:00  early ramp (~5% of daily flights)
   - 07:00–09:00  morning peak (~14–16 flights/hour)
   - 09:00–16:00  sustained mid-day base (~8–12 flights/hour)
   - 17:00–19:00  evening peak (~14–15 flights/hour)
   - 19:00–23:00  wind-down (~3–10 flights/hour)
   Within each hour, departure times are uniformly jittered to nearest 5 minutes.
2. For each departure slot, assign:
   a. A fictional airline code (weighted by market share)
   b. A fictional destination (pool of 40 airports)
   c. An aircraft type (weighted by route distance)
   d. A seat capacity (from aircraft type)
3. Generate paired arrivals (same aircraft, previous leg) with 90-minute turnaround
4. Assign each flight to a gate (bin-packing by terminal preference per airline)
5. Assign runway (balanced load between 09L/27R and 09R/27L)
6. Persist all flights to Neo4j
7. Emit all flights to flights.schedule topic
```

### Passenger generation

For each flight, generate `round(seat_capacity × load_factor)` passengers where `load_factor ~ Beta(8, 2)` (mean ~80%).

Each passenger record includes:

- Generated name (from a pool of 2,000 first names × 2,000 surnames)
- PNR (6-character alphanumeric, unique)
- Nationality (weighted by destination)
- Connection flag (20% probability)
- Special assistance flag (5% probability)
- Baggage count (0–3 bags, Poisson λ=1.2)

### Baggage generation

For each passenger with bags, generate baggage records with:

- Weight sampled from `Normal(18kg, 4kg)`, clamped to [2, 32]
- Dangerous goods flag: 0.002 probability (realistic DG rate)
- If DG: assign a random IATA DG class (2, 3, 8, or 9)

---

## 4. Weather state machine

The weather service manages a finite state machine with four states representing instrument flight rule categories.

### States

| State   | Visibility | Ceiling     | Description                             |
| ------- | ---------- | ----------- | --------------------------------------- |
| `CAVOK` | > 10 km    | none        | Clear skies, no significant cloud       |
| `VMC`   | 5–10 km    | > 1500 ft   | Visual meteorological conditions        |
| `IMC`   | 1.5–5 km   | 500–1500 ft | Instrument conditions, reduced capacity |
| `LIFR`  | < 1.5 km   | < 500 ft    | Low IFR, severe restrictions            |

### Transition matrix

Transition probabilities per simulated hour:

| From \ To | CAVOK | VMC  | IMC  | LIFR |
| --------- | ----- | ---- | ---- | ---- |
| `CAVOK`   | 0.85  | 0.13 | 0.02 | 0.00 |
| `VMC`     | 0.20  | 0.65 | 0.14 | 0.01 |
| `IMC`     | 0.05  | 0.30 | 0.55 | 0.10 |
| `LIFR`    | 0.00  | 0.05 | 0.35 | 0.60 |

Transitions are sampled on each simulated hour tick. Transitions from `LIFR` back to `VMC` or `CAVOK` in a single step are not permitted — weather improves gradually.

### Parameter generation on transition

On each weather state change, the engine samples new meteorological parameters consistent with the new state:

```python
def sample_weather(state: WeatherCategory) -> WeatherParams:
    match state:
        case CAVOK:
            visibility = random.randint(10000, 20000)
            ceiling    = None
            wind_speed = random.randint(0, 15)
            phenomena  = []
        case VMC:
            visibility = random.randint(5000, 10000)
            ceiling    = random.randint(2000, 5000)
            wind_speed = random.randint(5, 25)
            phenomena  = random.choices([[], ["FEW"], ["SCT"]], weights=[0.6, 0.3, 0.1])
        case IMC:
            visibility = random.randint(1500, 5000)
            ceiling    = random.randint(500, 1500)
            wind_speed = random.randint(15, 35)
            phenomena  = random.choices([["RA"], ["TS","RA"], ["FG"], ["SN"]], weights=[0.4, 0.3, 0.2, 0.1])
        case LIFR:
            visibility = random.randint(100, 1500)
            ceiling    = random.randint(50, 500)
            wind_speed = random.randint(25, 55)
            phenomena  = random.choices([["TS","HVY RA"], ["FG"], ["SN","BLSN"]], weights=[0.5, 0.3, 0.2])
    ...
```

### Runway capacity impact

| Weather state | Max arrival rate (movements/hour) | Max departure rate | Runway config                   |
| ------------- | --------------------------------- | ------------------ | ------------------------------- |
| `CAVOK`       | 32                                | 32                 | both runways                    |
| `VMC`         | 28                                | 28                 | both runways                    |
| `IMC`         | 18                                | 16                 | single ILS runway               |
| `LIFR`        | 8                                 | 6                  | single ILS runway, CAT III only |

When capacity drops, the flight service receives the `WeatherStateChanged` event and begins delaying departures to respect the new rate limit. Arrivals are held in a simulated holding stack.

---

## 5. Cascade delay propagation

This is the core fidelity feature. When a flight is delayed, the engine propagates the impact across all connected entities in a defined sequence.

### Cascade trigger chain

```
Flight delayed / cancelled
    │
    ├── Gate: current gate flagged as potentially needed longer
    │       → if gate conflict detected: FlightGateAssigned (reassign)
    │           → PassengerAlert (gate change notification)
    │
    ├── Connecting passengers identified
    │       → if delay > connection_minimum_time (45 min):
    │           → PassengerAlert (connection at risk)
    │           → if delay > MCT (minimum connection time):
    │               → PassengerStatus → missed_connection
    │
    ├── Baggage
    │       → if already loaded and flight cancelled:
    │           → BaggageStatus → offloaded → carousel
    │       → if not yet loaded and significant delay:
    │           → BaggageStatus → hold (make-up area)
    │
    └── Downstream (turnaround aircraft)
            → next departure on same aircraft also delayed
                → repeat cascade for that flight
```

### Delay propagation rules

- A delay propagates to the turnaround departure only if the delay is ≥ 15 minutes.
- The turnaround delay = max(0, inbound_delay - turnaround_buffer) where `turnaround_buffer` = 30 minutes for narrow-body, 45 minutes for wide-body.
- Maximum cascade depth: 5 hops (to prevent runaway propagation in simulation). Configurable via `operations.cascade_max_depth` in `config/airport.yaml` (default 5).

---

## 6. Hazardous event injection

### Event types and base probabilities

Probabilities are expressed per simulated hour of operation.

| Event type         | Base probability/hour | Severity range  | Runway impact          |
| ------------------ | --------------------- | --------------- | ---------------------- |
| `runway_incursion` | 0.005                 | high–critical   | immediate closure      |
| `baggage_fire`     | 0.008                 | medium–high     | none                   |
| `security_breach`  | 0.010                 | medium–critical | terminal zone lockdown |
| `severe_weather`   | driven by weather FSM | —               | per weather state      |
| `system_failure`   | 0.015                 | low–high        | depends on system      |

### Probability modifiers

Base probabilities are multiplied by situational modifiers:

| Condition                                | Modifier                                |
| ---------------------------------------- | --------------------------------------- |
| Peak hour (07:00–09:00, 17:00–19:00)     | × 1.8                                   |
| IMC or LIFR weather                      | × 2.0 (runway incursion)                |
| High baggage throughput (> 80% capacity) | × 1.5 (baggage fire, system failure)    |
| Recent incident within 2 sim-hours       | × 0.3 (suppression — avoid event flood) |

### Manual injection

The orchestrator exposes a REST endpoint to manually fire any event:

```
POST /sim/inject
{
  "type": "runway_incursion",
  "severity": "critical",
  "location": "runway-09L"
}
```

This produces an `InjectIncident` message on `incidents.inject`, consumed by the incident service.

### Incident lifecycle

```
Created (active)
    │
    ├── (auto) contained after TTR (time-to-resolve):
    │       runway_incursion: 15–45 sim-min
    │       baggage_fire:     20–60 sim-min
    │       security_breach:  30–90 sim-min
    │       system_failure:   10–120 sim-min
    │
    ├── (manual) operator marks as contained/resolved via API
    │
    └── resolved
            → IncidentStatusChanged emitted
            → affected entities resume normal state
            → automated incident report generated
```

---

## 7. Orchestrator API

| Method | Endpoint        | Description                                           |
| ------ | --------------- | ----------------------------------------------------- |
| GET    | `/sim/status`   | Current sim time, speed, day number, active incidents |
| PATCH  | `/sim/speed`    | Change simulation speed multiplier                    |
| POST   | `/sim/reset`    | Reset to day 1, reseed all data                       |
| POST   | `/sim/pause`    | Pause the simulation clock                            |
| POST   | `/sim/resume`   | Resume after pause                                    |
| POST   | `/sim/inject`   | Manually inject a hazardous event                     |
| GET    | `/sim/schedule` | Current day's flight schedule                         |
| GET    | `/sim/metrics`  | Simulation health metrics                             |

---

## 8. Seed fixtures

The `fixtures/` directory contains static JSON files used at seed time:

```
fixtures/
├── airlines.json          # 12 fictional airlines with codes, names, hubs
├── aircraft_types.json    # aircraft types with seat configs and performance
├── destinations.json      # 40 fictional destination airports
├── first_names.json       # 2,000 first names (multinational)
├── surnames.json          # 2,000 surnames (multinational)
├── nationalities.json     # nationality distribution weights
├── dg_classes.json        # dangerous goods class definitions
└── events.json            # special events calendar (see below)
```

### Special events calendar (`fixtures/events.json`)

Special events modify passenger demand for specific simulated days. They are consumed by the
forecasting model in `passenger-service` as the `is_special_event` and `event_pax_multiplier` features.

```json
{
  "events": [
    {
      "name": "ART City Marathon",
      "sim_days": [4, 5],
      "pax_multiplier": 1.18,
      "terminals_affected": ["A", "B"],
      "description": "Major sporting event draws 18% more leisure passengers"
    },
    {
      "name": "Summer peak week",
      "sim_days": [14, 15, 16, 17, 18, 19, 20],
      "pax_multiplier": 1.32,
      "terminals_affected": ["A", "B", "C"],
      "description": "Peak summer holiday week — all terminals at high load"
    },
    {
      "name": "Business conference",
      "sim_days": [8, 9],
      "pax_multiplier": 1.12,
      "terminals_affected": ["C"],
      "description": "Regional business summit increases Terminal C traffic"
    }
  ]
}
```

The `pax_multiplier` scales the `expected_pax_next_90min` feature in the forecast model and also
inflates the number of passengers generated by the sim-orchestrator on affected sim days
(`daily_pax = base_pax × event_pax_multiplier`).

---

## 9. Hypotheses and modelling assumptions

This section makes explicit the simplifications and assumptions underlying the simulation. These are documented so that contributors can understand trade-offs and extend the models.

### Flight schedule

| Assumption                                                                       | Rationale                                                      |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| 210 departures + 210 arrivals per day                                            | Mid-size hub approximation (~18M pax/year)                     |
| Bimodal departure distribution (peaks 07–09, 17–19) with sustained mid-day base  | Realistic hourly traffic curve matching real mid-size hub data |
| Each departure has exactly one paired arrival (same aircraft, 90 min turnaround) | Simplified rotation; real airports have multi-leg rotations    |
| 12 fictional airlines with weighted market share                                 | Avoids real airline data while producing realistic diversity   |
| Deterministic seed per sim-day (`seed = 42 + sim_day`)                           | Ensures reproducible schedules for testing                     |

### Passenger flow

| Assumption                                                  | Rationale                                                               |
| ----------------------------------------------------------- | ----------------------------------------------------------------------- |
| Load factor ~ Beta(8,2), mean ~80%                          | Realistic for mid-size hub; Beta distribution avoids impossible values  |
| Security throughput = 180 pax/hr/lane, 8 lanes per terminal | Based on IATA Level of Service standards (scaled for 420 movements/day) |
| Passengers move to security queue at T−45 min               | Captures typical check-in cutoff                                        |
| Dwell time in airside ~ Normal(25min, 12min), clamp [5, 90] | Captures shopping/waiting behaviour                                     |
| 20% of passengers have connecting flights                   | Realistic for a hub airport                                             |
| Connection minimum time (MCT) = 45 min                      | Standard minimum connection time                                        |
| Boarding rate = 10 pax/min                                  | Consistent with single-aisle + dual-aisle average                       |
| Special assistance = 5%, fixed 20 pax/hr lane               | Low-throughput dedicated lane                                           |

### Baggage handling

| Assumption                                         | Rationale                                           |
| -------------------------------------------------- | --------------------------------------------------- |
| Bags/passenger ~ Poisson(λ=1.2)                    | Mean 1.2 bags, some passengers have 0 or 3+         |
| Weight ~ Normal(18kg, 4kg), clamp [2, 32]          | Approximation with max weight cap                   |
| DG rate = 0.2%                                     | Realistic dangerous goods occurrence                |
| Detection rates per DG class: 72–95%               | Based on typical X-ray detection performance        |
| False positive rate = 0.3%                         | Realistic for automated screening                   |
| Conveyor throughput from IATA BHS design standards | Induction 600, screening 300, sorting 1800 items/hr |

### Weather

| Assumption                                                              | Rationale                                                            |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Markov chain with 4 states                                              | Captures IFR category progression                                    |
| LIFR → CAVOK transition forbidden (no 2-step jumps)                     | Weather improves gradually                                           |
| Transition probabilities calibrated for ~70% CAVOK time                 | Typical temperate airport                                            |
| Crosswind/tailwind reductions are simplified (no component calculation) | Full component trigonometry adds complexity without simulation value |

### Incidents

| Assumption                                         | Rationale                                       |
| -------------------------------------------------- | ----------------------------------------------- |
| Base probabilities are per simulated hour          | ~2–3 incidents per 8-hour shift on average      |
| Peak-hour multiplier × 1.8                         | Higher traffic = higher risk                    |
| Suppression window × 0.3 for 2 hours               | Prevents unrealistic incident clustering        |
| Maximum cascade depth = 5 (`operations.cascade_max_depth` in `config/airport.yaml`) | Prevents runaway computation |
| TTR is sampled uniformly from type-specific ranges | Simplification; real TTR has heavier right tail |

---

## 10. Implementation patterns

### Clock → service → event → response cycle

All simulation logic follows the same pattern:

```python
# 1. Consumer receives SimClockTick
async def _on_clock_tick(payload, sim_time):
    state.sim_time = sim_time

    # 2. Query Neo4j for entities in active states
    entities = await db.get_active_entities(sim_time)

    # 3. Evaluate each entity through its state machine
    for entity in entities:
        new_status = state_machine.evaluate_transition(entity, sim_time)
        if new_status:
            # 4. Update Neo4j
            updated = await db.update_status(entity["id"], new_status, sim_time)
            # 5. Emit Kafka event
            producer.emit_status_changed(entity, new_status, sim_time)
            # 6. Push to WebSocket clients
            if ws_broadcast:
                await ws_broadcast({"type": "status_changed", "data": updated})
```

### State machine pattern (pure function)

State machines are implemented as pure functions with no I/O:

```python
# services/flight-service/services/state_machine.py
def evaluate_transition(flight, sim_time, runway_available=True, ...) -> str | None:
    """Returns the target state or None. No side effects."""
    match flight["status"]:
        case "scheduled":
            # Departures: T-60 → boarding
            if direction == "departure" and sim_time >= estimated - 60min:
                return "boarding"
            # Arrivals: T-20 → approach
            if direction == "arrival" and sim_time >= estimated - 20min:
                return "approach"
        case "boarding":
            if has_hold:
                return "delayed"
            if sim_time >= estimated and boarded_pct >= 0.95:
                return "departed"
        ...
```

### Forecast model lifecycle (per terminal)

```
Day 1–3: fallback formula (no model trained yet)
  forecast = expected_pax_next_90min × 0.35

Day 3+: LightGBM retrained every 3 sim-days
  1. Feature rows accumulated in deque (max 10K per terminal)
  2. Flushed to Parquet every sim-hour
  3. Model trained on temporal split (80/20)
  4. Saved to /app/models/forecast_{terminal}.lgbm
  5. Hot-reloaded into inference pipeline
  6. 12 features: hour, day-of-week, departures_next_90min,
     expected_pax, current_queue, weather_category, ...
```
