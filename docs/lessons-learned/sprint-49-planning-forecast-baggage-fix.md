# Sprint 49 — Planning Forecast, Baggage Fix & UI Polish

**Date:** 2026-05-29  
**Scope:** sim-orchestrator bugfix, planning-service forecast endpoints, dashboard UI improvements

---

## What was done

### 1. Bug fix — sim-orchestrator baggage tag collision (P0)

**Problem:** The orchestrator crashed on startup with `ConstraintError: Node already exists with label Baggage and property tag = '...'` during `_persist_arrival_baggage`. Both `_persist_baggage` and `_persist_arrival_baggage` used `CREATE` for Baggage nodes, which fails when a tag collision occurs (timestamp-based counter can repeat across day-boundary reseeds).

**Fix:** Changed both methods from `CREATE` to `MERGE` on `Baggage.tag` with `ON CREATE SET` for remaining properties. Relationships also use `MERGE` for idempotency. This follows the project's hard rule: _use MERGE not CREATE for Neo4j where idempotency matters_.

**Files:** `services/sim-orchestrator/services/baggage.py`

**Lesson:** Always use `MERGE` when a uniqueness constraint exists on the target label. `CREATE` + uniqueness constraint = crash on retry or duplicate data. The `_unique_tag_start()` function provides _probabilistic_ uniqueness but not _guaranteed_ uniqueness — the Cypher must be the safety net.

---

### 2. UI polish — scenario cards on Results & Investment tabs

**Problem:** Scenario selector buttons were minimal pills (`px-3 py-1.5`) with poor visual hierarchy — hard to distinguish selected from unselected, no metadata shown.

**Fix:** Replaced pill buttons with card-style grid (`grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`). Each card shows scenario name, horizon, MC run count, and completion date. Selected state uses `border-2` with shadow for clear visual distinction. Results tab uses cyan accent, Investment tab uses emerald accent for consistency with their themes.

**Files:** `dashboards/art-dashboard/src/pages/Planning/PlanningPage.tsx`

---

### 3. Planning page — structured capacity changes for custom scenarios

**Problem:** Users could name a custom scenario but had no way to specify _what_ infrastructure changes it models (+1 gate, -1 security lane, etc.). The `infrastructure` field existed in the backend `CreateScenarioRequest` but was never populated by the frontend custom form.

**Fix:** Added a "Infrastructure Changes" panel to the custom scenario form with +/− stepper controls for:

- Gates per terminal (A/B/C)
- Security lanes per terminal (A/B/C)
- Screening units
- Runways

Each control shows the delta from baseline with color coding (cyan = increase, amber = decrease). The built `infrastructure` dict is passed to the backend's `CreateScenarioRequest.infrastructure` field, which feeds into `InfrastructureConfig.from_dict()` and is used by the simulation engine. A summary line shows all changes.

**Files:** `dashboards/art-dashboard/src/pages/Planning/PlanningPage.tsx`

---

### 4. Traffic forecast section on Planning page

**Problem:** No way to visualize or fine-tune passenger growth projections. The demand growth data existed in the backend but was only shown as static STATFOR numbers in the Investment tab.

**Fix:** Added:

- **Backend endpoint:** `POST /demand/forecast/custom` — takes `base_year_pax`, `growth_rate_pct`, `shock_year`, `shock_pct` and returns 10-year annual projections with optional demand shock modeling.
- **Frontend component:** `TrafficForecast` — collapsible section in the Builder tab with adjustable growth rate (preset buttons for low/base/high CAGR), optional shock year + magnitude, and a horizontal bar chart showing annual pax over 10 years. Shock years are highlighted in amber.

Kept the planning page uncluttered by using a collapsible panel rather than a new tab.

**Files:** `services/planning-service/routers/planning.py`, `dashboards/art-dashboard/src/hooks/useApi.ts`, `dashboards/art-dashboard/src/pages/Planning/PlanningPage.tsx`

---

### 5. Multi-year scenario comparison on Results tab

**Problem:** Results tab showed point-in-time KPI comparison but no forward-looking view of how scenarios perform as demand grows.

**Fix:** Added:

- **Backend endpoint:** `POST /scenarios/compare/multiyear` — takes scenario IDs, years ahead, and growth rate. Projects KPIs over N years with demand scaling (linear for cost/delay KPIs, sub-linear for utilisation, degrading for rates).
- **Frontend component:** `MultiYearProjection` — grouped horizontal bar chart showing any selected KPI over years for all completed scenarios side by side. KPI selector dropdown, adjustable growth rate. Uses distinct colors per scenario with a legend.

**Files:** `services/planning-service/routers/planning.py`, `dashboards/art-dashboard/src/hooks/useApi.ts`, `dashboards/art-dashboard/src/pages/Planning/PlanningPage.tsx`

---

## Key lessons

1. **MERGE vs CREATE is a policy, not an optimization.** When uniqueness constraints exist, `CREATE` becomes a correctness bug, not a performance concern. Default to `MERGE` for all node-creation Cypher that runs in seeder/startup paths.

2. **Frontend infra config was the missing link.** The backend already supported full `InfrastructureConfig` — the gap was entirely in the UI. Always check both ends of the data flow before assuming a feature is missing.

3. **Collapsible sections > new tabs** for supplementary features on an already-tabbed page. Avoids nested navigation fatigue.

4. **Demand growth projection is simple math but high UX value.** Linear CAGR scaling with optional shocks covers 90% of planning use cases without requiring complex simulation.

## Validation

- `ruff check` — all checks passed
- `npx tsc --noEmit` — clean build, no type errors
- No IDE diagnostics on modified files
