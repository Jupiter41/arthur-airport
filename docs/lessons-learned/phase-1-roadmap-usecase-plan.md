# Phase 1 (Use Case Roadmap) — Implementation Plan

Tracks `ROADMAP_USECASE.md` Phase 1 (1A Carbon, 1B Counterfactual, 1C Accessibility).

---

## 1A — Carbon Footprint Tracker (cost-service)

**Goal:** observe events, compute CO₂ per source, expose summary/by-source/timeline endpoints,
add `Carbon` tab in the Cost Dashboard with net-zero scenario builder.

**Design:** add a new in-process module `services/carbon_tracker.py`. Persistence via a new
`CarbonRecord` Neo4j node (separate from `CostRecord` to keep cost API stable). Events ride
the same Kafka consumer dispatch already in `cost-service`.

**Sources & factors (loaded from `fixtures/carbon_factors.json`):**

| Source     | Trigger                                                          | Formula                                                                  |
| ---------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `flight`   | `FlightStatusChanged → departed` (departure)                     | `distance_km × pax_count × 0.115 kg/pax-km` (ICAO short-haul default)    |
| `apu`      | `FlightStatusChanged → departed` — uses gate-stand minutes       | `stand_minutes × 3.0 kg/min` (ICAO APU reference, ~B737/A320 family)     |
| `terminal` | `SimClockTick` every 10 sim-min — uses peak/off-peak airside pax | `pax × hours × 0.012 kWh/pax/h × 0.233 kg/kWh` (ACI benchmark + EU grid) |

For 1A, stand-time we already track via `boarded_at` → `departed_at` style logic in cost
ground-handling. The simplest hook is at `departed` we know `delay_minutes` and the flight has
been at the gate for at least `turnaround_minutes` (default 45). Use a fixed default of 45 min
when stand time is not separately tracked, multiplied by aircraft family factor.

**REST endpoints (under `/api/v1/costs/carbon`):**

- `GET /summary` — running totals: total_kg, by source, day, sim_time
- `GET /by-source` — pie-chart-friendly array
- `GET /timeline?day=N` — hourly emissions for sim-day N
- `POST /scenario` — net-zero scenario builder; body `{gpu_adoption_pct, ev_fleet_pct, solar_offset_pct}` returns adjusted projection.

**Cost Dashboard:** new `Carbon` tab — pie + daily total + hourly chart + scenario sliders.

**Docs:** update `docs/architecture/DATA_MODEL.md` (CarbonRecord) and `docs/architecture/EVENT_BUS.md`
(no new topics; `cost.events` gains `CarbonRecorded` event).

---

## 1B — Counterfactual Delay Analysis (planning-service)

**Goal:** replay a completed scenario with overridden decision timing, return delta + structured
report, and expose a causal-graph DAG.

**Engine extensions:**

The current `PlanningSimEngine` is purely capacity-driven. To make counterfactual deltas
meaningful, we add a first-class `Intervention` model and an optional list passed to `run_day()`:

```python
@dataclass
class Intervention:
    action: str              # gdp_start | gdp_end | open_security_lanes | gate_swap
    sim_minute: int          # absolute minute-of-day (0..1439)
    duration_minutes: int = 60
    params: dict = field(default_factory=dict)
```

Effects (kept simple, deterministic):

- `gdp_start`: caps hourly departure capacity at `params.cap_pct` (default 70%) for `duration_minutes`
- `gdp_end`: explicit early exit
- `open_security_lanes`: additional `params.lanes` per terminal during window
- `gate_swap`: effectively raises `gates_per_terminal` by `params.delta` during window

To make replay deltas meaningful even on baseline weather, also accept a synthetic
`disruption_minute` & `disruption_capacity_pct` on the scenario, applied in baseline AND
counterfactual replays so deltas isolate the intervention timing.

**REST endpoints (planning router):**

- `POST /api/v1/planning/scenarios/{id}/replay` — body `{interventions: [...], disruption: {...}}`
  → spawns a new "counterfactual" scenario referencing the parent, runs it, returns delta.
- `POST /api/v1/planning/scenarios/{id}/counterfactual-report` — body `{base_intervention, shift_minutes_list: [-30, -15, 0, +15, +30]}`
  → runs N replays varying the intervention start, returns comparison table & best-pick.
- `GET /api/v1/planning/scenarios/{id}/causal-graph` — returns a JSON DAG: `{nodes:[…], edges:[…]}`
  built from the scenario's interventions, configured disruption, and KPI outcomes.

**No SSE, no separate Neo4j node** — counterfactual results are stored as regular
`PlanningScenario`/results in-memory store with `parent_scenario_id`. Comparison is computed
on the fly.

**Dashboard:** new `What If` panel inside the Planning Results tab — slider to shift base
intervention, calls `/counterfactual-report`, renders a small comparison chart and a cause→
effect graph from `/causal-graph`.

---

## 1C — Accessibility & Special Assistance Optimisation (passenger-service)

**Goal:** model wheelchair pool per terminal, track SA passenger SLA, recommend hourly
staffing, expose data via REST + dashboard card.

**Config:** add to `config/airport.yaml`:

```yaml
accessibility:
  wheelchairs_per_terminal: { A: 8, B: 8, C: 8 }
  agents_per_wheelchair: 1.0
  ecac_target_minutes: 30 # ECAC Doc 30 — 90% within 30 min of request
```

**Neo4j:**

- `WheelchairResource { terminal, total_count, available_count, in_use, queued }` — one per terminal
- `WheelchairAssignment { id, passenger_id, terminal, requested_at, dispatched_at, returned_at, wait_seconds, gate_reached_before_cutoff: bool }`

Constraints + indexes added to `passenger-service/db/neo4j.py`.

**Dispatch logic (in-memory per terminal, persisted via Neo4j on dispatch + return):**

- On SA passenger check-in (transition `booked → checked_in`): create `WheelchairAssignment`
  with `requested_at`, then attempt to dispatch (if `available_count > 0` → decrement, set
  `dispatched_at = sim_time`, emit `WheelchairDispatched`). Otherwise enqueue in pending queue.
- On every tick, drain pending queue against newly-available wheelchairs.
- On SA passenger transition to `at_gate` or `boarded`: complete assignment — set
  `returned_at = sim_time`, increment `available_count`, emit `WheelchairReturned`.

**Kafka events (added to `passengers.events`):**

```json
{ "event_type": "WheelchairDispatched",
  "payload": { "passenger_id", "terminal", "wait_seconds", "sim_time" } }
{ "event_type": "WheelchairReturned",
  "payload": { "passenger_id", "terminal", "duration_seconds", "sim_time" } }
```

**REST endpoints (under `/api/v1/passengers/accessibility`):**

- `GET /sla` — % SA pax reaching gate before boarding cutoff, mean check-in→gate time
  SA vs non-SA, ECAC compliance pct
- `GET /staffing` — per-terminal-per-hour recommended wheelchair-agents based on SA pax demand
  derived from upcoming flight schedule and SA probability
- `GET /resources` — current pool state per terminal

**Dashboard:** Accessibility card in Passenger Dashboard.

**Docs:** update `DATA_MODEL.md` (WheelchairResource, WheelchairAssignment) and `EVENT_BUS.md`
(two new event types).

---

## Validation plan

1. `docker compose up --build` (light mode), wait for services, check logs.
2. cURL probes:
   - `GET /api/v1/costs/carbon/summary`
   - `POST /api/v1/planning/scenarios/{id}/replay` with empty interventions → delta near-zero
   - `GET /api/v1/passengers/accessibility/sla`
3. Run `ruff check services/cost-service services/planning-service services/passenger-service`
4. Run dashboard `npm run build` to ensure TS compiles.
5. Document outcome in `docs/lessons-learned/phase-1-roadmap-usecase-report.md`.
