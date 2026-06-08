# PLAN — Stabilize architecture & improve business value

Status: living document. Last updated 2026-06-03.

This plan groups work into themes. Each task is independent and can be picked up
in isolation. Items marked **[P0]** are landed in this sprint; **[P1]** are
proposed follow-ups; **[P2]** are nice-to-have improvements.

> Source audit: see `docs/lessons-learned/sprint-50-stabilize-arch-improve-business.md`
> for the rationale behind P0 picks.

---

## 1. Cost model robustness & clarity

### Landed (P0)

- [x] **Externalize staffing & retail magic numbers** — `cost_engine.on_clock_tick`
      hardcoded peak/off-peak security-lane, check-in-desk, boarding-flight and
      airside-pax counts. Moved into `cost_rates.json` under a new `operations`
      section so finance teams can tune without touching code, and the `/rates`
      endpoint exposes them.
- [x] **Validate `PATCH /api/v1/costs/rates`** — previously accepted arbitrary
      nested dicts via deep merge. Now rejects unknown top-level keys with HTTP 400
      and rejects values that change the type of an existing field.
- [x] **Proper HTTP error codes** — `cost-service` `/ready` and the cost router
      endpoints returned `200 OK` with `{"error": "neo4j not connected"}`. They now
      return `503 Service Unavailable` so health probes and clients can react.
- [x] **Incident ranking labels** — added `eu261_eur` alongside the legacy
      `response_eur` field on `/api/v1/costs/incidents/ranking` (the value was
      already EU261, but the field name was misleading). Frontend can migrate.

### Proposed (P1)

- [x] **Wire gate-fee path** — `compute_gate_fee` now fires on
      `boarding → departed` (departures) and `at_gate → arrived` (arrivals).
      Occupancy tracked in-memory; cancellations clear the window. Dual-entry
      cost+revenue records produced. (sprint-51)
- [x] **Real fuel price feed** — `services/fuel_price.py` adds an optional
      startup + 6-hour refresh against `FUEL_PRICE_URL`. Falls back to fixture on
      any failure; surfaces provenance under `rates._meta.fuel_price`. (sprint-51)
- [x] **Per-airline rate overrides** — `cost_rates.json` now carries an
      `airline_overrides` block (IATA code → partial rate dict). `compute_landing_fee`,
      `compute_passenger_fee`, slot fee, ground-handling and EU261 paths resolve
      the airline from the flight-number prefix and deep-merge overrides on top
      of the base table. Ships with `EK` (wide-body premium) and `FR` (low-cost
      discount) presets. (sprint-51)
- [x] **Cost recommendations: include confidence band** — `cost_engine`
      snapshots per-category daily totals into a rolling 7-day history on day
      transitions. `recommendations.py` emits a `saving_eur_ci` field
      (`low/high/sample_days`) using 1.96·σ around the projected saving. (sprint-51)

### Proposed (P2)

- [x] **Carbon tab** — shipped in Phase 1
      (`/api/v1/costs/carbon/*` + dashboard `CarbonPage`). Verified intact in
      sprint-51.
- [x] **Airport valuation model** — `services/valuation.py` + three endpoints:
      `GET /costs/ebitda?horizon=day|week|year`,
      `POST /costs/valuation/sensitivity` (cartesian product over demand/fuel/EU261),
      `POST /costs/valuation/thesis` (structured investment-case JSON). Dashboard
      Valuation tab is intentionally deferred to a follow-up UX sprint — backend
      contract is final and dashboard-consumable. (sprint-51)

---

## 2. Planning model robustness & clarity

### Landed (P0)

- [x] **`total_flights` propagated through Monte Carlo aggregation** — was
      missing from `_collect_kpis`, causing `benefit_extractor` to silently fall
      back to a hardcoded 420 flights/day when scaling delay-cost benefits. Now
      the real per-scenario flight count drives the annual benefit math.
- [x] **IRR semantics** — `_compute_irr` returned `100.0` when there was no
      sign change but NPV was positive at the upper bound, overstating certainty.
      Now returns `None` when an IRR is not well-defined and `compute_investment`
      exposes an explicit `irr_meaningful` flag.
- [x] **Sensitivity preserves year-by-year DCF** — previous code averaged the
      projected annual benefit then recomputed an annuity, which destroys the
      growth shape of the cashflow series. Sensitivity now runs an actual
      per-year discounted cashflow.
- [x] **`demand_multiplier` actually applied** — the API/model accepted it but
      the engine ignored it. The schedule is now scaled (flight count and pax)
      before the simulation runs.
- [x] **`weather_source` actually applied** — `PlanningSimEngine` now accepts
      an optional weather adapter; the runner picks one via `get_weather_adapter`
      based on the scenario field. Falls back to the schedule adapter for
      backwards compatibility.

### Proposed (P1)

- [x] **Persist scenarios to Neo4j** — chose to formalise in-memory storage
      (lesson 019). `docs/services/planning-service/SPEC.md` §2/§16 updated to
      mark Neo4j persistence as reserved-for-future and call out the in-memory
      decision.
- [x] **`new_routes` consumed by engine** — `engine/simulation.py` now
      synthesises flights from each `new_routes[]` entry (daily_flights spread
      06:00–22:00, pax = seats × load_factor) and appends them to the daily
      schedule. Wired through `_run_monte_carlo` and surfaced on
      `CreateScenarioRequest` alongside `demand_multiplier`.
- [x] **Year/10-year horizon: weighted seasonal sample** — added `_MONTH_WEIGHTS`
      and `_weighted_seasonal_sample()` in `scenarios/runner.py`; deterministic
      stratified sampling per month replaces the evenly-spaced truncation.
- [x] **Frontend typing for planning API** — introduced
      `dashboards/art-dashboard/src/types/planning.ts` and re-typed every
      `planningApi` method that previously returned `unknown`. Fixed a latent
      bug in `WhatIfPage.tsx` that read a non-existent `scenario_id` from
      scenario summaries.

### Proposed (P2)

- [x] **Counterfactual replay** (`ROADMAP_USECASE.md` 1B).
- [x] **Slot allocation simulator** (2B).
- [x] **Network resilience tab** (2D) — feeds off existing BTS adapter.

---

## 3. Cross-cutting hygiene

### Landed (P0)

- [x] **Doc/port drift** — `ROADMAP3.md` referenced cost-service on `8007`,
      `ROADMAP4.md` referenced planning-service on `8008`; reality is `8008` and
      `8009`. Roadmaps updated.

### Proposed (P1)

- [x] **Eliminate duplicate Eurocontrol cost constants** — canonical values
      now live in `services/_common/finance_constants.py` (DELAY, REBOOKING,
      EU261 tiers, landing/gate/pax fees). `planning-service` imports from it
      and `benefit_extractor.py` re-exports for backwards compatibility.
- [x] **Common `/ready` helper in `_common/`** — added
      `services/_common/ready.py` (`evaluate_readiness` / `readiness_response`).
      All eight Python services (cost, flight, weather, incident, passenger,
      analysis, baggage, sim-orchestrator) now use it and return a uniform
      `{ready, checks}` payload with 503 on failure.
- [x] **OpenSky adapter** — removed from the adapter registry surface
      (`get_schedule_adapter`, `list_available_adapters`) and SPEC marked it
      as a stub. The file is kept for future implementation.

### Proposed (P2)

- [x] **End-to-end smoke test in CI** — current CI runs unit tests only.
      Bring up `docker compose up neo4j kafka` + cost-service + planning-service
      and run a 60-second sim, assert `cost_records > 0` and a planning scenario
      completes.
- [x] **Promote `helper_test_cost_endpoints.sh` to a `pytest` integration**.

---

## 4. Out of scope (explicitly deferred)

- Real-data fuel/incident calibration (ROADMAP3 phase 9). Requires data feeds
  beyond what we have on disk.
- MARL benchmark (ROADMAP_USECASE 3A). Research-grade, multi-week effort.
- Risk Modelling tab (3C). Depends on completed valuation model first.
