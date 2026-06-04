# Sprint 51 — Cost model P1 & P2 plan

Source: `PLAN.md §1` — "Cost model robustness & clarity" → Proposed (P1) and Proposed (P2).

## Scope

### P1 — Cost engine robustness

1. **Wire gate-fee path.** `compute_gate_fee` exists but is never called.
   - Track gate occupancy windows in-memory from `FlightStatusChanged` events.
   - For **departures**: gate held from `boarding` until `departed`.
   - For **arrivals**: gate held from `at_gate` until `arrived`.
   - On exit, compute `delta_minutes`, emit dual-entry `gate_fee` cost+revenue.
   - Restart-safe: drop unknown flight ids silently.
2. **Real fuel price feed.**
   - Add an optional async fetcher in `services/cost-service/services/fuel_price.py`.
   - Env var `FUEL_PRICE_URL` (defaults unset → fixture). When set, fetch returns
     JSON `{ "price_eur_per_kg": float, "as_of": str }`.
   - Refreshed on startup and once every 6 sim-hours (or weekly real-time — pick
     real-time since this is wall-clock). Cache result onto
     `rates["delay_costs"]["fuel_price_per_kg_eur"]`.
   - Fallback to fixture on error. Never blocks startup.
3. **Per-airline rate overrides.**
   - Add `airline_overrides` top-level dict to `cost_rates.json`:
     `{ "AF": { "airport_fees": {"passenger_departure_fee_eur": 10.5}, ... } }`
   - Add helper `resolve_rates_for_airline(rates, airline_code)` that deep-merges
     overrides over the base rate table.
   - Wire into `compute_landing_fee`, `compute_passenger_fee`, slot fee emit.
   - Airline code derived from `flight_number` prefix (first 2 letters,
     uppercased). Fallback to base rates when unknown.
4. **Recommendations 95% CI.**
   - Track rolling 7-day history of completed daily totals
     (`by_category`, `eu261_exposure`, `total_cost_eur`).
   - Snapshot on `reset_for_new_day` (capture previous day before clearing).
   - In `recommendations.py`, derive `saving_eur_ci_low/high` = mean ± 1.96·σ
     when ≥2 historical days exist. Otherwise emit `saving_eur_ci = None`.

### P2 — Carbon + Valuation

5. **Carbon tab.** Already shipped in Phase 1 (`/api/v1/costs/carbon/*` +
   `dashboards/.../CarbonDashboard`). Verify and mark the PLAN entry complete.
6. **Airport valuation (3B).**
   - Add `GET /api/v1/costs/ebitda?horizon=day|week|year` returning:
     - Revenue waterfall by stream (landing, passenger, retail, slot, parking
       placeholder, cargo placeholder)
     - OpEx by stream (staffing, ground_handling, holding_fuel, eu261, incidents)
     - EBITDA = total_revenue − total_opex
     - Margin %, daily/annualised projection
   - Add `POST /api/v1/costs/valuation/sensitivity` body:
     `{ demand_growth: [-0.1, 0, 0.05], fuel_price_pct: [-0.3, 0, 0.3], eu261_rate_pct: [-0.5, 0, 0.5] }`
     and return EBITDA per scenario tuple.
   - Add `POST /api/v1/costs/valuation/thesis` body `{ scenario: {...} }` returning
     a JSON investment case (text sections, sensitivity table, risk factors).
     PDF rendering is **out of scope** — the JSON is consumable by the dashboard
     and could be rendered by a separate tool later.
   - Dashboard: **defer** to a follow-up sprint. The backend exposes everything
     needed; adding the tab is a separate UX task. Documented as such in PLAN.

## Non-goals

- Real EIA API integration with auth keys.
- Slot-allocation per-airline conflict logic.
- PDF rendering for valuation thesis.
- A Valuation dashboard tab.

## Validation

- Unit tests for all new pure functions (gate fee, airline override resolution,
  CI math, EBITDA waterfall).
- `ruff check services tests scripts` clean.
- `pytest tests/unit -q` green.
- `docker compose up --build cost-service` (light mode), then `curl` against new
  endpoints; logs scanned for warnings.

## Status update

Sprint 51 — Lessons-learned report to be written at the end.
