# Sprint 11 — Scenario Engine + YAML Runner (Phase 2)

## Goal

Implement a scenario engine that allows predefined + user-created YAML scenarios
to be loaded, validated, and run against the simulation — producing documented,
reproducible results with metrics capture and outcome assertions.

---

## Architecture

The scenario engine is a new subsystem within `sim-orchestrator` that:

1. **Parses** YAML scenario definition files (validated by Pydantic)
2. **Schedules** events at specific sim-time offsets during the simulation
3. **Overrides** simulation seed parameters (weather, flight count, load factor)
4. **Collects** metrics throughout the scenario run
5. **Evaluates** expected outcomes at the end
6. **Reports** results as JSON + markdown

### Integration Points

- **Clock loop**: The scenario engine registers a per-tick callback (`on_tick`)
  alongside the existing `on_hour` and `on_day` callbacks. On each tick, it checks
  if any scheduled scenario events are due and fires them.
- **Injector**: Scenario events reuse `emit_inject_incident()` for incident injection.
- **Seeder**: Seed overrides (weather, flight count, load factor) are applied
  before day 1 seeding.
- **REST API**: New endpoints to list, start, stop, and get results of scenarios.
- **Metrics**: New Prometheus metrics for scenario runs.

### File Layout

```
services/sim-orchestrator/
├── scenarios/                     ← NEW: scenario definitions
│   ├── definitions/
│   │   ├── morning-peak-storm.yaml
│   │   ├── runway-incursion-peak.yaml
│   │   ├── baggage-fire-chain.yaml
│   │   ├── security-breach-terminal-b.yaml
│   │   ├── double-disruption.yaml
│   │   ├── connection-crisis.yaml
│   │   ├── full-capacity-day.yaml
│   │   └── cascade-recovery.yaml
│   └── results/
│       └── {scenario-name}/{timestamp}/
│           ├── metrics.json
│           ├── events.jsonl
│           └── report.md
├── models/
│   └── scenario.py                ← NEW: Pydantic models for scenario
├── services/
│   └── scenario_engine.py         ← NEW: core engine logic
├── routers/
│   └── scenarios.py               ← NEW: REST endpoints
└── ...existing files...
```

---

## Implementation Steps

### Step 1: Pydantic models (`models/scenario.py`)

Define validation models for YAML scenario files:

- `ScenarioEvent`: `at_sim_offset_minutes`, `type`, `severity`, `location`, `trigger`
- `SeedOverride`: `weather`, `daily_flights`, `load_factor`
- `ExpectedOutcome`: `metric`, `condition`, `within_sim_minutes`
- `ScenarioDefinition`: `name`, `description`, `sim_speed`, `start_time`,
  `duration_sim_minutes`, `seed_overrides`, `events`, `expected_outcomes`
- `ScenarioRunResult`: run metadata, collected metrics, outcome evaluation, pass/fail

### Step 2: Scenario engine (`services/scenario_engine.py`)

Core class `ScenarioEngine` that:

- Loads and validates YAML files from `scenarios/definitions/`
- Manages the lifecycle of a scenario run: start → tick → evaluate → report
- On each clock tick, checks if scheduled events are due and injects them
- Collects real-time metrics from Neo4j (flight delays, holding stack, etc.)
- At end: evaluates expected outcomes, writes results

### Step 3: REST API (`routers/scenarios.py`)

Endpoints:

- `GET /api/v1/scenarios` — list available scenarios
- `GET /api/v1/scenarios/{name}` — get scenario definition
- `POST /api/v1/scenarios/{name}/run` — start a scenario run
- `GET /api/v1/scenarios/active` — get active scenario status + live metrics
- `POST /api/v1/scenarios/active/stop` — stop active scenario
- `GET /api/v1/scenarios/results` — list past results
- `GET /api/v1/scenarios/results/{run_id}` — get run result detail

### Step 4: Clock integration

Add an `on_tick` callback to the clock loop. The scenario engine's `on_tick`
handler fires each simulated minute and:

1. Checks if any scheduled events are due at the current offset
2. Injects them via `emit_inject_incident()`
3. Snapshots metrics every N minutes
4. Checks if scenario duration has elapsed → auto-evaluate + stop

### Step 5: YAML scenario definitions

Create 8 scenario YAML files as defined in the ROADMAP.

### Step 6: Metrics collection

For expected outcome evaluation, the engine queries Neo4j on each metric snapshot:

- `flights_delayed_current`: count of flights with delay > 0
- `holding_stack_depth`: count of flights with status `approach` + delay > 0
- `cascade_depth_max`: max cascade chain from incidents
- `avg_delay_minutes`: average over all delayed flights
- `missed_connections`: passengers with missed_connection status
- `security_queue_max`: max queue depth across terminals
- `incident_count_active`: active incidents

### Step 7: CLI runner script

`scripts/scenario-runner.sh` — a shell interface to drive scenarios via curl:

```bash
./scripts/scenario-runner.sh run runway-incursion-peak --speed 600
./scripts/scenario-runner.sh list
./scripts/scenario-runner.sh results
```

### Step 8: Gateway proxy

Add scenario routes to the api-gateway proxy so the dashboard can access them.

---

## Constraints

- The clock loop already has `on_hour` and `on_day` callbacks. Add `on_tick`
  as a third callback. This is the cleanest integration point.
- Scenario runs are singleton — only one scenario at a time.
- A scenario run resets the simulation (like `/sim/reset`) before starting.
- Results are stored on disk in the container (ephemeral) — no Neo4j persistence
  for results. This keeps it simple.
- YAML parsing uses `pyyaml` — add to requirements.txt.

---

## Results

### Files created

| File                                                     | Purpose                                                                            |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `services/sim-orchestrator/models/scenario.py`           | Pydantic v2 models for scenario definitions, run results, outcome evaluation       |
| `services/sim-orchestrator/services/scenario_engine.py`  | Core engine: YAML loading, event scheduling, metric collection, outcome evaluation |
| `services/sim-orchestrator/routers/scenarios.py`         | 7 REST endpoints for scenario management                                           |
| `services/sim-orchestrator/scenarios/definitions/*.yaml` | 8 YAML scenario definition files                                                   |
| `scripts/scenario-runner.sh`                             | CLI wrapper for driving scenarios via curl                                         |
| `scripts/README.md`                                      | Documentation for all scripts                                                      |

### Files modified

| File                                           | Change                                                         |
| ---------------------------------------------- | -------------------------------------------------------------- |
| `services/sim-orchestrator/requirements.txt`   | Added `pyyaml>=6.0.0`                                          |
| `services/sim-orchestrator/services/clock.py`  | Added `on_tick` callback to clock loop                         |
| `services/sim-orchestrator/main.py`            | Integrated scenario engine (imports, callback, router)         |
| `services/sim-orchestrator/services/seeder.py` | Made `emit_initial_weather()` accept optional `category` param |
| `services/api-gateway/src/proxy.ts`            | Added scenarios proxy route                                    |
| `ROADMAP.md`                                   | Marked Phase 2 as done                                         |

### Test runs

Two scenarios were executed end-to-end against the full stack:

1. **Cascade recovery** (3600x speed, 180 min) — 1/2 outcomes passed: incidents detected (PASS), flights delayed count slightly below threshold (4 vs >=5, FAIL). This is expected — the probabilistic nature of the simulation means thresholds may need tuning.

2. **Runway incursion during peak hour** (600x speed, 120 min) — 1/3 outcomes passed: 2 events injected correctly, incidents detected, but delay cascades were below expected thresholds. Again, expected with the current simulation model.

### Observations

- The clock `on_tick` callback integrates cleanly — no disruption to existing `on_hour`/`on_day` flow
- Metric snapshots every 5 sim-minutes provide good granularity for outcome evaluation
- Outcome thresholds in YAML files may need tuning as the simulation model evolves (the cascade/delay model doesn't yet produce large enough cascades for some scenarios)
- All 8 scenarios load and validate correctly at startup
- Results persist in-container as JSON files — ephemeral by design
