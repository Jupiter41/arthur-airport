# Sprint 51 — Cost model P1 & P2

## Goal

Implement every P1 and P2 item in PLAN.md §1 ("Cost model robustness &
clarity") and mark them complete with backing tests and live validation.

## Changes shipped

### P1 — Cost engine robustness

1. **Gate-fee path wired** (`services/cost-service/services/cost_engine.py`).
   - In-memory `_gate_occupancy_starts` records the entry sim_time on
     `boarding` (departures) and `at_gate` (arrivals), with `setdefault` so
     `delayed → boarding` flips don't reset the window.
   - On `departed` (departures) and `arrived` (arrivals) the engine pops the
     window, computes the delta in whole minutes, and emits a dual-entry
     `gate_fee` cost+revenue pair scaled by
     `airport_fees.gate_rate_per_hour_eur`.
   - `cancelled` always clears the window. Mid-sim restarts silently drop
     unknown flight ids (no false fees).
2. **Optional live fuel-price feed** (`services/cost-service/services/fuel_price.py`).
   - Reads `FUEL_PRICE_URL`; when unset the loop is a no-op and the fixture is
     authoritative.
   - When set, fetches a small JSON `{ price_eur_per_kg, as_of, source }`
     once at startup and every 6 wall-clock hours, sanity-bounded (0 < p ≤ €10/kg).
   - Patches `rates["delay_costs"]["fuel_price_per_kg_eur"]` in place and
     records provenance under `rates["_meta"]["fuel_price"]`.
   - Failures (timeout, bad JSON, malformed price) are warning-logged and
     never block startup or stall the hot loop.
   - Adds `httpx>=0.27.0` to cost-service `requirements.txt`.
3. **Per-airline rate overrides** (`fixtures/cost_rates.json`,
   `services/cost_engine.py`).
   - New top-level `airline_overrides` dict keyed by IATA carrier code
     (2-3 letters). Ships with `EK` (wide-body premium) and `FR` (low-cost
     discount) presets, plus a `_comment` line for ops.
   - `_airline_code_from_flight_number` extracts the alpha prefix (handles
     mixed case, returns `None` on numeric-only or empty strings).
   - `resolve_rates_for_airline` deep-copies the base table and merges the
     per-airline patch over the top — returns the base reference unchanged
     when no override matches (no allocation in the common case).
   - Wired through `compute_landing_fee`, `compute_passenger_fee`, slot fee,
     ground-handling, and EU261 paths for both `on_flight_status_changed` and
     `on_flight_cancelled`.
4. **Recommendations 95 % confidence band** (`services/recommendations.py`,
   `services/cost_engine.py`).
   - `cost_engine.reset_for_new_day` now snapshots the closing day's
     `total_cost_eur`, `total_revenue_eur`, `eu261_exposure` and per-category
     totals into a 7-day rolling `_daily_history` before zeroing.
   - `recommendations._ci_for_signal` computes the 1.96·σ half-width on the
     historical population and applies the recommendation's projected
     `saving_factor` to give a `{low_eur, high_eur, sample_days}` payload.
   - Returns `None` when fewer than 2 historical days exist so the dashboard
     can render a "n/a" badge instead of a fake-precision range.

### P2 — Carbon + Valuation

5. **Carbon tab — verified complete.** Already shipped in Phase 1
   (cost-service `/api/v1/costs/carbon/{summary,by-source,timeline,factors,scenario}`
   - dashboard `CarbonPage`). Confirmed intact and marked done in PLAN.
6. **Airport valuation model** (`services/cost-service/services/valuation.py`,
   `routers/costs.py`).
   - `build_ebitda(daily_pnl, horizon)` produces a revenue waterfall (landing,
     passenger, gate, slot, retail), an airport-OpEx waterfall (staffing,
     incident_direct, incident_response), a pass-through block (ground
     handling, holding fuel, EU261) for context, and an EBITDA + margin
     projected at `day`/`week`/`year` horizons.
   - `run_sensitivity` runs the cartesian product over `demand_growth`,
     `fuel_price_pct` and `eu261_rate_pct`.
   - `build_thesis` synthesises a structured investment-case JSON (summary,
     EBITDA range, scenarios, risk factors, top-level recommendation).
   - Three new endpoints:
     - `GET /api/v1/costs/ebitda?day=&horizon=`
     - `POST /api/v1/costs/valuation/sensitivity`
     - `POST /api/v1/costs/valuation/thesis`
   - Dashboard Valuation tab is intentionally **deferred** to a follow-up UX
     sprint — the backend contract is final and dashboard-consumable, but
     adding the tab is a separate front-end task.

## Tests

- New unit suite `tests/unit/test_cost_p1_p2.py` (27 tests) covering:
  - Gate-fee calculator (zero / one-hour / partial-hour).
  - Airline-code extraction edge cases.
  - `resolve_rates_for_airline` identity, lookup, immutability, and downstream
    effect on `compute_passenger_fee`.
  - Recommendations CI: `None` with no history, populated after 2+ day
    transitions, ordering invariant.
  - Valuation: baseline EBITDA, horizon multiplier, pass-through exclusion,
    cartesian product size, growth monotonicity, unknown-horizon rejection,
    thesis schema and range invariants.
  - Fuel-price coercion + `apply_to_rates` patching.
- Existing `tests/unit/test_cost_recommendations.py::test_all_recommendations_have_required_fields`
  updated to require the new `saving_eur_ci` field.
- `ruff check services tests scripts` → clean.
- `pytest tests/unit -q` → **734 passed**, 15 pre-existing pandas-related
  planning-adapter failures (unrelated, missing `pandas` in test venv).
- `npm run build` (`dashboards/art-dashboard`) → built in 9.36 s.

## Live validation (docker compose, light mode)

```
$ docker compose up -d --build cost-service
$ curl -s http://localhost:8008/ready
{"status":"ready","neo4j":"ok","kafka":"ok"}

$ curl -s http://localhost:8008/api/v1/costs/rates | jq '.airline_overrides | keys'
["EK", "FR", "_comment"]

$ curl -s 'http://localhost:8008/api/v1/costs/pnl?day=1' | jq '.by_category'
{
  "gate_fee": 10562.5,        # ← P1.1 firing
  "ground_handling": 3888417.0,
  "holding_fuel": 104790.0,
  ...
}

$ curl -s 'http://localhost:8008/api/v1/costs/ebitda?day=1&horizon=year' | jq '.ebitda'
{"daily_eur": 4400183.33, "horizon_eur": 1606066915.45, "margin_pct": 91.8}

$ curl -s -X POST http://localhost:8008/api/v1/costs/valuation/sensitivity \
    -H 'Content-Type: application/json' \
    -d '{"day":1,"demand_growth":[-0.1,0,0.1],"fuel_price_pct":[0],"eu261_rate_pct":[0]}' \
    | jq '.scenarios[] | {dg: .scenario.demand_growth, ebitda: .ebitda_daily_eur}'
{"dg": -0.1, "ebitda": 3968871.74}
{"dg":  0.0, "ebitda": 4453304.71}
{"dg":  0.1, "ebitda": 4937737.68}
```

## Lessons learned

- **`import_service_module` clears `services.*` from `sys.modules`.** Pulling
  two modules from the same service in a test file resets the first one's
  global state. Either pull the dependent module first (so the parent is
  the _current_ `sys.modules` entry) or grab it from `sys.modules` after.
  This trapped the CI-band test until the import order was inverted.
- **Cost engines benefit from "pass-through" categorisation.** Putting
  airline-borne lines (EU261, ground handling, holding fuel) in their own
  bucket makes airport EBITDA honest and stops accidental double-count when
  the model is later wired into a planning DCF.
- **Optional live-data feeds belong behind an env-var with a synchronous
  startup attempt + background refresh.** Never let a flaky external HTTP
  endpoint block service startup or block the Kafka loop. The fixture is
  always the authoritative fallback.

## Follow-ups (out of scope this sprint)

- Dashboard Valuation tab consuming the three new endpoints.
- Wire `gate_fee` into incident-cost ranking (currently bucketed under
  `ground_handling` when an incident extends gate occupancy).
- Real EIA/IATA jet-fuel adapter behind `FUEL_PRICE_URL` (currently the env
  expects a plain `{price_eur_per_kg, ...}` JSON; a tiny shim service could
  proxy EIA's authenticated API).
