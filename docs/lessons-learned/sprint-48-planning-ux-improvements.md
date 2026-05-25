# Sprint 48 — Planning UX & Cost Model Improvements

**Date:** 2025-07  
**Scope:** planning-service backend, PlanningPage.tsx frontend, QUICKSTART_PLANNING.md

---

## What changed

### Backend (planning-service)

1. **Automatic baseline comparison** — Every scenario now runs the baseline configuration
   with the same dates and random seeds alongside the proposed change. Results include
   `baseline_kpis`, `delta` (per-KPI comparison), and `infrastructure_changes` (human-readable diff).

2. **Template auto-execution** — All 4 template endpoints (`add_gate`, `add_runway`,
   `new_route`, `security_lanes`) now automatically trigger scenario execution via
   `background_tasks`, so the user doesn't need a separate "run" step.

3. **Richer result model** — `ScenarioResults` now carries `baseline_kpis` and
   `infrastructure_changes` fields, enabling the frontend to show what changed and
   how the baseline compares.

4. **Financial improvements** — `cumulative_cash_flows` array added to financials
   for rendering the payback chart. Annual benefit now uses actual simulation delta
   instead of heuristic estimates.

### Frontend (PlanningPage.tsx)

1. **Template forms with real parameters** — Each template now has a dedicated form
   with actual infrastructure parameters (terminal selector, gate count, runway ID/ILS/length,
   per-terminal lane adjustments). Previously templates were fire-and-forget with no
   user input beyond a name.

2. **Results tab redesign** — KPI comparison table with baseline vs scenario columns,
   change %, 90% confidence band, and verdict (✓/✗/—). Methodology banner explains
   how results are computed. Infrastructure diff shows exactly what changed.

3. **Investment tab redesign** — Headline metrics (NPV, IRR, Payback, Recommendation)
   with context sublabels. Benefit breakdown, cumulative cash flow bar chart with
   payback marker, and demand growth projections.

4. **Cost preview** — New `CostPreview` component in the builder tab shows auto-configured
   capex, opex, horizon, and discount rate before the user submits.

---

## Lessons learned

### 1. TypeScript `unknown` leaking into JSX

When `useQuery` returns `unknown` (because the API client returns `Promise<unknown>`),
any conditional rendering like `{data && <div>...</div>}` produces type `unknown | false`
which is not assignable to `ReactNode`. 

**Fix:** Use `{data != null && (...)}` or `!!(expr)` to ensure boolean narrowing.
The `!!` pattern for `hasFinancials` and `!= null` for `growth` both work.

### 2. React Query + untyped API clients

The `planningApi` methods return `unknown` because `apiFetch<T>` is generic but the
planning endpoints weren't typed. Rather than typing every endpoint (which would require
maintaining parallel type definitions), we cast at the usage site with `as` assertions.
This is pragmatic but fragile — a future improvement would be to generate types from
the OpenAPI spec.

### 3. Monte Carlo × 2 = progress tracking matters

Since every scenario now runs both baseline and scenario simulations, the total number
of Monte Carlo runs doubles. The progress tracker was updated to reflect this
(`total_runs = n_runs * 2`), but it's easy to forget this when modifying the runner.

### 4. DCF parameters need transparency

Users couldn't understand why an investment was "good" or "bad" because the cost
parameters (€102/min delay, €285/pax rebooking) were hidden in backend code. Adding
methodology banners and benefit breakdowns to the UI made the analysis interpretable
without requiring users to read the source code.
