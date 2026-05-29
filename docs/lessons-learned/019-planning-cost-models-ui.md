# Lessons Learned — Planning Cost Models & UI Decomposition

**Date:** 2026-05-29
**Task:** Add cost models and capacity planning scenarios
**Duration:** ~4 hours

---

## Summary of Changes

### Backend (planning-service)

1. **Fixed 500 on scenario results** — `float('inf')` in `payback_years` caused JSON serialization
   failure. `json.dumps(float('inf'))` raises `ValueError` because Infinity is not valid JSON.
   Fix: use `years_horizon + 1` as sentinel for "never pays back", and added `_safe()` helper
   in `InvestmentResult.to_dict()` that replaces `inf`/`NaN` with 0.

2. **Fixed payback calculation bug** — dead code was computing payback via linear interpolation
   then overwriting it with a simpler formula. Cleaned up to single clean linear interpolation.

3. **Added terminal template** — `create_terminal_scenario()` in `templates.py` and
   `POST /templates/add_terminal` endpoint. Auto-configures gates, security lanes, and screening
   units per terminal, with cost estimation.

4. **Added cost estimation endpoint** — `POST /cost-estimate` accepts proposed infrastructure
   changes and returns auto-calculated CAPEX/OPEX breakdown using Eurocontrol Standard Inputs.

5. **Added baseline endpoint** — `GET /baseline` returns current KART infrastructure config
   plus annual passenger estimate from `airport.yaml`.

### Frontend (dashboard)

6. **Decomposed PlanningPage.tsx** — Split 2582-line monolith into 7 files:
   - `types.ts` (~100 lines) — shared types + KPI metadata
   - `components/shared.tsx` (~200 lines) — 8 reusable UI components
   - `components/ScenarioBuilder.tsx` (~650 lines) — builder tab with templates + auto-cost
   - `components/ResultsTab.tsx` (~260 lines) — KPI comparison + multi-year projection
   - `components/InvestmentTab.tsx` (~270 lines) — DCF analysis + demand growth
   - `components/AuditTab.tsx` (~170 lines) — decision audit trail
   - `PlanningPage.tsx` (~57 lines) — thin shell with tab bar

7. **Fixed import paths** — `shared.tsx` used `../../hooks/useApi` instead of `../../../hooks/useApi`
   because it was in the `components/` subfolder. Caught by Docker build.

### Documentation

8. **Created PLANNING.md** — explains cost models, scenario methodology, DCF analysis,
   multi-year projections, and architecture. Same style as COST.md and DATA.md.

9. **Created ROADMAP_USECASE.md** — 13 feasible use cases from FUTURE_USE_CASES.md, organized
   into 4 phases with precise implementation tasks. All use free/public data sources.

---

## Root Cause of 500 Error

The 500 error on `GET /planning/scenarios/{id}/results` was caused by `float('inf')` in the
`payback_years` field of `InvestmentResult`. This happens when:

- A scenario has CAPEX > 0 but the net annual benefit is zero or negative
- The payback period is infinite (investment never pays back)
- `round(float('inf'), 2)` in Python returns `inf`
- FastAPI serializes the response with `json.dumps()`, which raises `ValueError: Out of range float values are not JSON compliant`
- FastAPI catches this and returns a 500 Internal Server Error

**Why it only appeared from the UI:** The default templates (add_gate, add_runway) always produce
positive benefits, so `payback_years` was finite. But custom scenarios or scenarios with high OPEX
could trigger the infinity case. The UI created such scenarios more often than CLI testing did.

**Fix:** Replace `float('inf')` with `years_horizon + 1` (a finite sentinel meaning "does not
pay back within the investment horizon"), and add a `_safe()` guard in `to_dict()` that replaces
any remaining `inf`/`NaN` with 0.

---

## Key Technical Decisions

1. **In-memory storage is intentional** — scenarios and results live in Python dicts, not Neo4j.
   This is a simulation tool, not a production database. Results are ephemeral by design.

2. **Eurocontrol Standard Inputs for costs** — €8M/gate, €800M/runway, €102/min delay,
   €285/pax rebooking. These are the European reference values; users can override via API.

3. **Component decomposition pattern** — each tab is a standalone component with its own
   React Query hooks. The parent shell only manages the active tab. This allows each tab
   to refetch independently and doesn't force re-renders across tabs.

---

## Validation

- All Python services pass `ruff check` with no errors
- Dashboard passes `tsc --noEmit` with no TypeScript errors
- Docker build succeeds for both `planning-service` and `dashboard`
- Edge case tested: scenario with €999M capex and €10M opex → returns 200 with
  `payback_years: 26.0` and `recommendation: "do not invest"`
- Normal scenario tested: add 2 gates to Terminal B → returns 200 with full KPI data
