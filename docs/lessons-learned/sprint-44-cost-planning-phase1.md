# Sprint 44 — Cost Dashboard Day Reset + Planning Service Phase 1

**Date:** 2025-01-18

## What was done

### 1. CI/CD test fix (`test_last_updated_set`)
- **Root cause:** Sprint-42 removed `datetime.now()` from `_record_cost`, making `sim_time` required. The test didn't pass it, so `last_updated` stayed `None`.
- **Fix:** Pass `sim_time="2024-06-15T14:32:00Z"` in the test call.

### 2. Cost dashboard midnight reset
- **Backend:** Added `sim_day` tracking to `_running_totals`. When `sim_day` changes, all accumulators reset via `reset_for_new_day()`. The `/summary` endpoint now includes `sim_day`.
- **Frontend:** Day navigation with ◀/▶ buttons. Live day shows running totals; historical days fetch from PNL endpoint. Green "Live" badge vs amber "Historical" indicator.
- **Lesson:** Separating live vs historical data sources in the frontend (summary for live, PNL for history) avoids complex state management.

### 3. Planning service Phase 1 — Adapter architecture
- Created `services/planning-service/` with 5 adapters:
  - **SimulationAdapter** — bimodal schedule, Markov weather, synthetic demand with seasonal curves
  - **BTSAdapter** — reads BTS T-100 CSV, calibrates schedules from real departure data
  - **MesonetAdapter** — reads Iowa State ASOS CSV, classifies weather categories, builds transition matrices
  - **EurocontrolDemandAdapter** — CAGR projections (base 3.4%, low 1.8%, high 4.8%)
  - **OpenSkyAdapter** — stub for future OpenSky Network integration
- Registry pattern with `get_schedule_adapter()`, `get_weather_adapter()`, `get_demand_adapter()`
- REST preview endpoints for all adapter outputs
- Docker + gateway proxy wired up on port 8009

### 4. Gotchas
- **`isinstance` across conftest module isolation:** `import_service_module()` creates separate module objects, so `isinstance(adapter, AbstractAdapter)` fails when they're imported separately. Fix: test interface presence (duck-typing) instead of `isinstance`.
- **Unused imports:** `ruff` catches these quickly — always run `ruff check` before committing.

## Test results
- 701 unit tests passing (0 failures)
- Ruff: all checks passed
- TypeScript (gateway): clean compile
- Dashboard: clean build

## Files changed
- `services/cost-service/services/cost_engine.py` — day reset logic
- `services/cost-service/routers/costs.py` — sim_day in summary
- `dashboards/art-dashboard/src/pages/CostDashboard/CostDashboardPage.tsx` — day navigation
- `dashboards/art-dashboard/src/types.ts` — CostSummary.sim_day
- `services/planning-service/**` — entire new service
- `services/api-gateway/src/proxy.ts` — planning proxy route
- `docker-compose.yml` — planning-service container
- `tests/unit/test_cost_engine.py` — fixed + new tests
- `tests/unit/test_planning_adapters.py` — 32 new tests
