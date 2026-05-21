# Sprint 41 — UI Bug Fixes, Data Source Comparisons & UX Polish

**Date:** 2025-01-20
**Focus:** Cost page fixes, data source comparison panels, simulation history improvements, autonomous operations wiring, UI/UX audit

---

## Changes Made

### 1. Cost Page — Zero Values & Missing Data (Fixed)

**Root cause:** Three-layer problem:
- **Layer A:** Response shape mismatch — backend returned raw field names (`cost`, `revenue`, `id`, `total_impact`), frontend expected wrapped objects with specific names (`cost_eur`, `revenue_eur`, `incident_id`, `total_eur`). Fixed in `services/cost-service/routers/costs.py`.
- **Layer B:** Running totals start at 0 — normal. Added informative empty state with amber banner.
- **Layer C:** Neo4j returns empty if no CostRecords — normal. Returns empty arrays instead of error when Neo4j driver is null.

**Endpoints fixed:**
- `/pnl` — transforms `sim_day` → `day`, builds `by_category` dict, adds `cost_records` count
- `/hourly` — wraps in `{hours: [...]}`, renames fields, adds `net_eur`
- `/incidents/ranking` — wraps in `{incidents: [...]}`, renames fields

**Dashboard additions:**
- Loading spinner with animation
- Error state with retry button
- `noData` detection with amber info banner

### 2. Data Source Comparisons (New)

**Passenger comparison:**
- New endpoint: `GET /api/v1/passengers/compare` — returns simulated vs BTS historical data side-by-side with deltas
- BTS adapter lazily initialized — always available for comparison even when simulation source is active
- Frontend: `PassengerComparisonPanel` on DataSourcesPage — expandable, auto-refreshing, shows by-status breakdown, total delta bar

**Incident comparison:**
- New endpoint: `GET /api/v1/sim/incident-compare` — returns all calibration preset probabilities with deltas and ratios
- Compares simulated vs ASRS-calibrated probabilities per event type
- Frontend: `IncidentComparisonPanel` on DataSourcesPage — expandable table showing per-event-type probabilities and ratio comparison

**API hooks added:**
- `dataSourcesApi.passengerCompare()` → `/passengers/compare`
- `dataSourcesApi.incidentCompare()` → `/sim/incident-compare`

### 3. Simulation History — Day Detail Modal & Pagination (New)

- `DayDetailModal`: KPIs (flights, on-time rate, passengers, avg delay, incidents, max severity), financials from `costsApi.pnl()`, flight breakdown, per-day export
- Keyboard-accessible (Escape to close), click-outside-to-close
- Pagination: 20 days per page, prev/next buttons
- ARIA: `role="dialog"`, `aria-modal="true"`, `aria-label`

### 4. Autonomous Operations (Fixed)

- Field name fix: `action.applied_at || action.sim_time` for timestamp display
- Description fallback: `action.description || action.action_type || "Action"`
- Diagnostic display: shows active bottleneck and recommendation counts when no actions logged
- Hint about injecting incidents to trigger the autonomous pipeline

### 5. Scenario Page — Export (New)

- Added `ExportMenu` + `exportData` to scenario result detail view
- Export available in JSON/CSV format

### 6. UI/UX Audit & Fixes

**Error/loading states added to 4 pages:**
- `FlightBoardPage` — loading spinner + error with retry + empty table message
- `PassengerFlowPage` — loading spinner + error with retry
- `GroundOpsPage` — loading spinner + error with retry
- (Cost page already had these from earlier fix)

**Accessibility fixes:**
- `FlightDetailDrawer` — added `role="dialog"`, `aria-modal="true"`, `aria-label`, close button `aria-label="Close"`
- `InjectModal` (IncidentConsole) — added `role="dialog"`, `aria-modal`, `aria-label`, close button label
- `CascadeModal` (IncidentConsole) — same ARIA additions
- `DayDetailModal` (SimHistory) — `role="dialog"`, `aria-modal`
- `ComparisonModal` (DataSources) — `role="dialog"`, `aria-modal`

**Empty state:**
- FIDSPanel — shows "No flights scheduled" or "No flights match current filters" when table is empty

---

## Verification

- **Ruff:** All services pass (`python -m ruff check services/`)
- **npm build:** Clean (839 modules, ~7s)
- **Unit tests:** 667 passed in 4.57s
- **Docker rebuild:** All containers healthy
- **Gateway integration:** All endpoints verified via curl through gateway (auth + proxy)
- **Cost endpoints:** `/summary`, `/pnl`, `/hourly`, `/incidents/ranking` all return correct shapes
- **Comparison endpoints:** `/passengers/compare` and `/sim/incident-compare` return rich comparison data

---

## Key Lessons

1. **Response shape mismatches are the #1 cause of "zero value" displays.** Always cross-reference frontend TypeScript interfaces with backend response shapes. The router layer is the right place to transform — keep DB queries clean.

2. **"No data" is not an error.** Don't return error objects when a query returns empty results. Return empty arrays/objects and let the frontend show helpful empty states.

3. **Comparison endpoints should always work regardless of active source.** The BTS adapter is lazily initialized so comparison data is available even when the simulation source is primary. This is better than requiring a source switch first.

4. **ARIA accessibility is cheap to add.** Adding `role="dialog"`, `aria-modal="true"`, and `aria-label` to modals takes seconds but makes the app usable with screen readers.

5. **Loading/error states follow a consistent pattern.** The CostDashboardPage pattern (check `isLoading` → spinner, check `isError` → error with retry, then render data) should be replicated across all data-fetching pages.
