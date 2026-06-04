# Sprint 52 — Planning P1 + Cross-cutting hygiene P1

**Scope:** PLAN.md §2 "Planning model robustness & clarity" Proposed (P1) and §3
"Cross-cutting hygiene" Proposed (P1). P2 items deferred.

## Changes shipped

### Cross-cutting hygiene (§3 P1)

1. **Canonical Eurocontrol constants** — `services/_common/finance_constants.py`
   centralizes `DELAY_COST_PER_MINUTE_EUR = 102.0`,
   `REBOOKING_COST_PER_PAX_EUR = 285.0`, `EU261_AVERAGE_CLAIM_EUR = 400.0`,
   `EU261_TIERS`, `OPERATING_DAYS_PER_YEAR`, plus airport-fee defaults
   (`LANDING_FEE_PER_TONNE_EUR`, `GATE_FEE_PER_HOUR_EUR`,
   `PAX_DEPARTURE_FEE_EUR`).
   - `planning-service/finance/benefit_extractor.py` re-exports them via
     `__all__` for backwards compatibility.
   - `planning-service/engine/simulation.py` imports the EU261 tiers and the
     landing/gate/pax fees directly.
   - `cost-service` did **not** have duplicate Python constants (rates are
     loaded from `rates.yaml` at startup), so no change there was required.
     PLAN.md's wording about cost-service constants was slightly inaccurate but
     the spirit (single source of truth for these numbers) is satisfied.

2. **Common `/ready` helper** — `services/_common/ready.py` exposes
   `evaluate_readiness(checks)` and `readiness_response(checks)`. Eight
   services (cost, flight, weather, incident, passenger, analysis, baggage,
   sim-orchestrator) now return a uniform `{ready, checks: {...}}` payload and
   raise `HTTPException(503)` on failure. Exceptions inside check functions are
   swallowed as `False` so a broken Neo4j driver can't crash readiness itself.

3. **OpenSky adapter removed from registry surface** — `adapters/registry.py`
   no longer matches `"opensky"` in `get_schedule_adapter` and drops it from
   `list_available_adapters()["schedule"]`. The file `adapters/opensky.py` is
   kept (marked "stub — not registered" in the planning SPEC) for future
   implementation.

### Planning P1 (§2)

4. **Scenario persistence decision documented** — chose to formalise the
   in-memory store (lesson 019). `docs/services/planning-service/SPEC.md` §2
   and §16 reframe Neo4j persistence as reserved-for-future and call out the
   in-memory trade-off (scenarios lost on restart) explicitly so the spec no
   longer contradicts the implementation.

5. **`new_routes` consumed by engine** — `engine/simulation.py` now contains
   `_expand_new_routes(new_routes, sim_date, rng)` which synthesises flights
   per route (`daily_flights` evenly spread 06:00–22:00, `pax = SEAT_MAP[ac] ×
load_factor`, default distance 1500 km when missing). `run_day` accepts a
   `new_routes` argument and appends synthetic flights **after** the
   `demand_multiplier` is applied so additive demand isn't double-counted.
   `_run_monte_carlo` passes `scenario.new_routes or None` to the scenario
   leg only — baseline runs always use `None`. `CreateScenarioRequest` in
   `routers/planning.py` now exposes both `demand_multiplier` and `new_routes`.

6. **Weighted seasonal sampling** — `scenarios/runner.py` introduces
   `_MONTH_WEIGHTS` (Northern-hemisphere mid-Atlantic hub seasonality:
   `0.78, 0.74, 0.92, 0.97, 1.06, 1.10, 1.18, 1.18, 1.08, 1.02, 0.85, 0.92`)
   and `_weighted_seasonal_sample(start, n_days, sample_size, seed)`.
   Sampling is deterministic per-month stratified, replacing the previous
   even-spaced truncation that biased NPV math.

7. **Frontend typing for planning API** —
   `dashboards/art-dashboard/src/types/planning.ts` defines
   `PlanningScenario`, `PlanningScenarioSummary`, `ScenarioListResponse`,
   `ScenarioResults`, `ScenarioStatus`, `TemplateCatalogue`, `ServiceStatus`,
   `AuditLogEntry`, `AuditLogResponse`, `AuditSummary`, `DemandForecast`,
   `DemandGrowth`, `MLStatus`, `InvestmentResult`, `AnnualBenefitBreakdown`,
   `NewRoute`, `InterventionPayload`, `DisruptionPayload`,
   `InfrastructureConfig`. `useApi.ts` `planningApi` no longer returns
   `unknown` for those endpoints. **Bug found**: `WhatIfPage.tsx` was casting
   the summary list to a local `Scenario` shape with `scenario_id`, but
   `to_summary()` actually emits `id`. The cast was silently producing
   `undefined` everywhere it was used. Fixed.

## Validation

- `python3 -m ruff check services/` → clean.
- `python3 -m pytest tests/unit -q --ignore=tests/unit/test_cost_engine.py
--ignore=tests/unit/test_cost_p1_p2.py
--ignore=tests/unit/test_cost_recommendations.py` → 651 passed. The three
  excluded cost tests fail with a pre-existing `ModuleNotFoundError: neo4j`
  in this environment (PEP 668 prevents `pip install`); confirmed via
  `git stash` that they fail identically without these changes.
- `cd dashboards/art-dashboard && npm run build` → builds clean. `tsc -b`
  catches the previously-silent `scenario_id` bug.

## Pitfalls observed

- **`unknown` return types are silent accomplices.** Casting `unknown` to a
  fictional shape in consumers will compile forever and never surface backend
  drift. Tightening the API typing immediately surfaced a real bug in
  `WhatIfPage.tsx` that had been there since `sprint-48`.
- **Test sys.path for `_common`.** Tests that import planning-service code now
  also need `services/` on `sys.path` (in addition to the per-service path)
  so `from _common.finance_constants import …` resolves outside Docker.
  `tests/unit/test_planning_engine.py` was updated to do this.
- **Readiness helper must swallow exceptions.** Earlier `/ready` handlers
  threw raw exceptions when (e.g.) the Neo4j driver was misconfigured, which
  surfaced as 500 instead of the intended 503. `evaluate_readiness()` wraps
  each check in `try/except → False` so the response stays honest.

## Out of scope (deferred to P2)

- Counterfactual replay (`ROADMAP_USECASE.md` 1B)
- Slot allocation simulator (2B)
- Network resilience tab (2D)
- End-to-end smoke test in CI
- Promote `helper_test_cost_endpoints.sh` to pytest
