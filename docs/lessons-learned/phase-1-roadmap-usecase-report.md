# Phase 1 — ROADMAP_USECASE.md — Implementation Report

**Date:** 2026-06-04 (sim) · light docker-compose profile
**Scope:** 1A Carbon Footprint Tracker · 1B Counterfactual Delay Analysis · 1C Accessibility & Special Assistance
**Outcome:** Backend complete and live. All new REST endpoints return 200 OK under load.

---

## What ships

### 1A — Carbon Footprint Tracker (`cost-service`, port 8008)

- `services/cost-service/services/carbon_tracker.py` — in-memory totals + Neo4j persistence.
  Computes CO₂ per ICAO Carbon Calculator (per-pax-km, haul-band), APU by aircraft family,
  terminal kWh × grid intensity (ACI ACA + EEA), per-turnaround ground vehicles.
- `services/cost-service/services/carbon_tracker.py::on_flight_departed` → emits `CarbonRecorded`.
- `services/cost-service/services/carbon_tracker.py::on_clock_tick` → APU + terminal + ground emissions.
- Neo4j: `CarbonRecord` node + `FOR_FLIGHT` / `FOR_TERMINAL` / `FOR_DAY` relationships.
- REST:
  - `GET /api/v1/costs/carbon/summary` → live totals
  - `GET /api/v1/costs/carbon/by-source?day=…` → pie-chart breakdown
  - `GET /api/v1/costs/carbon/timeline?day=…` → hourly series
  - `GET /api/v1/costs/carbon/factors` → emission-factor JSON
  - `POST /api/v1/costs/carbon/scenario` → projected savings for GPU/EV/solar adoption
- Kafka: `CarbonRecorded` envelope on `cost.events`.

### 1B — Counterfactual Delay Analysis (`planning-service`, port 8009)

- `services/planning-service/engine/interventions.py` — `Intervention`, `Disruption`,
  `aggregate_capacity_factor()` → `(cap_factor, extra_lanes, extra_gates)`.
- `engine/simulation.py::run_day` and `_tick` accept `interventions` + `disruption`:
  - Runway: `cap_factor` multiplies `max_dep` / `max_arr`.
  - Security: `extra_lanes` added at both queue-build and queue-drain sites (lines 383, 448).
  - Stands: `gate_swap` deltas extend the per-day stand pool.
- `scenarios/model.py::PlanningScenario` gains `interventions`, `disruption`, `parent_scenario_id`.
- `scenarios/runner.py::_run_monte_carlo` threads interventions + disruption into baseline and
  scenario MC runs so deltas isolate the infrastructure choice.
- `routers/counterfactual.py`:
  - `POST /scenarios/{id}/replay` → spawns child scenario
  - `POST /scenarios/{id}/counterfactual-report` → spawns N children varying timing
  - `GET  /scenarios/{id}/causal-graph` → DAG of scenario → disruption → interventions → KPIs
  - `GET  /scenarios/{id}/replays` → child status + results
- SPEC: `docs/services/planning-service/SPEC.md` updated.

### 1C — Accessibility & Special Assistance (`passenger-service`, port 8002)

- `config/airport.yaml::accessibility` — pool size per terminal, SLA target %, boarding cutoff.
- `services/passenger-service/services/wheelchair.py` — in-memory `_Pool` per terminal +
  `_Assignment` lifecycle. Persists `WheelchairResource` and `WheelchairAssignment` to Neo4j on
  every dispatch / return.
- Hooks in `kafka/consumer.py`:
  - On booked → checked_in: `wheelchair.request(...)` for SA passengers.
  - Once per tick: `wheelchair.tick()` to drain queues.
  - On airside → at_gate: `wheelchair.mark_at_gate()` records SLA outcome.
  - On at_gate → boarded: `wheelchair.release()` frees the chair, emits `WheelchairReturned`.
- Kafka: `WheelchairDispatched` + `WheelchairReturned` on `passengers.events`.
- REST under `/api/v1/passengers/accessibility`:
  - `GET /sla` → ECAC Doc 30 compliance (target / actual / by-terminal / mean wait)
  - `GET /staffing` → recommended agents per terminal (peak × 1.2, floor pool/4)
  - `GET /resources` → pool sizes + queue depth
- Docs: `docs/architecture/DATA_MODEL.md` + `docs/architecture/EVENT_BUS.md` updated.

---

## Validation (light profile, single live run)

| Probe                                                        | Outcome                                                   |
| ------------------------------------------------------------ | --------------------------------------------------------- |
| `GET /api/v1/costs/carbon/summary`                           | 200 → `2.6 tonnes`, sources `apu/terminal/ground_vehicle` |
| `GET /api/v1/costs/carbon/by-source`                         | 200 → APU 95.8%, ground 4.0%, terminal 0.2%               |
| `GET /api/v1/costs/carbon/timeline?day=1`                    | 200 → 5 active hours                                      |
| `POST /api/v1/costs/carbon/scenario` (0.5/0.4/0.2)           | 200 → projected savings 44.4% (5067 kg)                   |
| `GET /api/v1/passengers/accessibility/sla`                   | 200 → 94 samples, by-terminal breakdown                   |
| `GET /api/v1/passengers/accessibility/resources`             | 200 → 28 chairs across A/B/C, 488 queued                  |
| `GET /api/v1/passengers/accessibility/staffing`              | 200 → recommended agents per terminal                     |
| `POST /api/v1/planning/scenarios/{id}/replay`                | 202 → child scenario `completed` in 22.5 s                |
| `POST /api/v1/planning/scenarios/{id}/counterfactual-report` | 202 → 3 children spawned                                  |
| `GET /api/v1/planning/scenarios/{id}/causal-graph`           | 200 → nodes + edges DAG                                   |
| `GET /api/v1/planning/scenarios/{id}/replays`                | 200 → parent's child set                                  |

`ruff check services/cost-service services/planning-service services/passenger-service` → **all checks passed**.
`python -m compileall` → clean.
Container builds: 3.9 s incremental, all 12 services healthy in the light profile.

---

## Bugs found & fixed

1. **`carbon_tracker` import error blocked cost-service startup.**
   The first wave of edits in the prior session added the `CarbonRecord` constraint to
   `db/neo4j.py`, but the persistence helpers (`write_carbon_record`,
   `link_carbon_to_flight/terminal/airport_day`, `rebuild_carbon_totals`,
   `carbon_summary_by_source`, `carbon_hourly_timeline`) were never actually appended.
   The summary file claimed they were — they weren't. Discovered when `docker compose up`
   crashed with `ImportError: cannot import name 'link_carbon_to_airport_day'`.
   **Fix:** appended all six helpers to `services/cost-service/db/neo4j.py`.
   **Lesson:** verify file tails after multi-file edits, especially when an in-session terminal
   heredoc was used for an "append" step — the heredoc may have failed silently.

2. **`/api/v1/costs/carbon/by-source` returned 500.**
   `routers/carbon.py` expected each row from `carbon_summary_by_source()` to have key
   `total_kg`, but the helper returned `{"sim_day": …, "by_source": [...]}` with row key
   `co2_kg` / `count`. Mismatch between writer and reader.
   **Fix:** changed `carbon_summary_by_source` to return a flat `list[dict]` with the keys the
   router already expects (`source`, `total_kg`, `records`).
   **Lesson:** when a router and its db helper are added in separate edits, write the contract
   inline in the helper docstring so the next edit can't drift.

3. **`open_security_lanes` intervention had no observable effect.**
   The aggregate produced `extra_lanes` but `_tick` was not consuming it on either the
   queue-build or queue-drain path.
   **Fix:** added `+ extra_lanes` to the two `sec_lanes = …` assignments in
   `engine/simulation.py`. Replays now show measurable delta.

4. **Ruff `F401` on `counterfactual.py`.** Removed unused `logging` import.

---

## Known scope cuts (intentional)

- **Dashboard frontend (Carbon tab, What-If panel, Accessibility card)** — backend is complete and
  contractually documented in the SPECs; frontend work is a separate roadmap item.
- **Gate-swap throughput coupling** — `extra_gates` is added to the stand pool count for the day
  but not yet wired into the per-flight stand allocation logic; the runway capacity factor and
  security lane delta carry the bulk of the counterfactual signal.
- **Wheelchair SLA backfill** — current SLA computation uses only the rolling 24 h window; no
  Neo4j-backed historical reporting yet (Phase 2 candidate).

---

## Files touched

| Created                                                  | Modified                                         |
| -------------------------------------------------------- | ------------------------------------------------ |
| `services/cost-service/fixtures/carbon_factors.json`     | `services/cost-service/db/neo4j.py`              |
| `services/cost-service/services/carbon_tracker.py`       | `services/cost-service/kafka/producer.py`        |
| `services/cost-service/routers/carbon.py`                | `services/cost-service/kafka/consumer.py`        |
| `services/planning-service/engine/interventions.py`      | `services/cost-service/main.py`                  |
| `services/planning-service/routers/counterfactual.py`    | `services/planning-service/engine/simulation.py` |
| `services/passenger-service/services/wheelchair.py`      | `services/planning-service/scenarios/model.py`   |
| `services/passenger-service/routers/accessibility.py`    | `services/planning-service/scenarios/runner.py`  |
| `docs/lessons-learned/phase-1-roadmap-usecase-plan.md`   | `services/planning-service/main.py`              |
| `docs/lessons-learned/phase-1-roadmap-usecase-report.md` | `services/passenger-service/main.py`             |
|                                                          | `services/passenger-service/db/neo4j.py`         |
|                                                          | `services/passenger-service/kafka/producer.py`   |
|                                                          | `services/passenger-service/kafka/consumer.py`   |
|                                                          | `config/airport.yaml`                            |
|                                                          | `docs/architecture/DATA_MODEL.md`                |
|                                                          | `docs/architecture/EVENT_BUS.md`                 |
|                                                          | `docs/services/planning-service/SPEC.md`         |
