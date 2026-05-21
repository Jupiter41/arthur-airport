# Sprint 42 — Architecture Stabilization & Dashboard Refactoring

**Date:** 2025-07-15  
**Focus:** Monolithic page decomposition, backend bug fixes, CI verification

---

## Changes Made

### 1. Dashboard Page Refactoring

Four monolithic pages were decomposed into sub-components with shared utilities:

| Page              | Before      | After      | Sub-files created                                                                                                                    |
| ----------------- | ----------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| CostDashboardPage | 909 lines   | ~120 lines | 7 (constants.ts, CostBreakdownChart, HourlyCurveChart, IncidentRankingTable, RecommendationsPanel, CategoryBarChart, CostRateEditor) |
| GroundOpsPage     | 1,291 lines | 262 lines  | 7 (AirfieldComponents, StatusPanels, WeatherSidePanel, TurnaroundPanel, TerminalActivityPanel, NearbyFlightsPanel, GroundVehicles)   |
| DataSourcesPage   | 1,142 lines | 189 lines  | 4 (constants.ts, WeatherComparison, SourceComparisons, SourceCard)                                                                   |
| ScenariosPage     | 1,078 lines | 659 lines  | 2 (types.ts, ScenarioComponents)                                                                                                     |

**Shared components created:**

- `formatCurrency.ts` — reusable EUR formatting (replaced 3 duplicate implementations)
- `KpiCard.tsx` — standard KPI card component
- `LoadingState.tsx` / `ErrorState` — consistent loading/error UI
- `AutonomousPanel.tsx` — extracted from MLTrainingPage, reused in CostDashboard

### 2. CSV Export Bug Fix (`exportData.ts`)

**Bug:** Nested objects (metric_snapshots, outcome_results) serialized as `[object Object]` in CSV exports.  
**Fix:** Added `typeof val === "object" ? JSON.stringify(val) : String(val)` check before CSV cell output.

### 3. cost-service: `datetime.now()` Violation Fixed (`cost_engine.py`)

**Bug:** `_record_cost()` used `datetime.now(timezone.utc)` for the `last_updated` field, violating the architecture rule that all time must come from `sim_time`.  
**Fix:** Changed `_record_cost` to accept a `sim_time` kwarg; caller `_write_and_emit` passes `sim_time=record.get("sim_time")`. Removed unused `timezone` import.

### 4. passenger-service: Source Validation Added (`consumer.py`)

**Bug:** `switch_passenger_source()` accepted any string as `new_source` without validation — invalid values silently broke passenger generation.  
**Fix:** Added guard: `if new_source not in ("simulation", "bts_historical"): raise ValueError(...)`. The HTTP endpoint already validated, but the function-level check provides defense-in-depth.

### 5. SimHistoryPage: Shared Formatting

Replaced inline `formatEur` with the shared `formatCurrency` utility — eliminated duplicate code.

---

## Known Issues (Not Fixed — Documented for Future)

| #   | Issue                                                                           | Severity | Location         |
| --- | ------------------------------------------------------------------------------- | -------- | ---------------- |
| 1   | `gate_fee` cost never triggered — `compute_gate_fee()` defined but never called | Medium   | cost_engine.py   |
| 2   | Staffing costs use hardcoded resource counts instead of Neo4j queries           | Low      | cost_engine.py   |
| 3   | Retail revenue uses hardcoded airside pax counts                                | Low      | cost_engine.py   |
| 4   | `_last_staffing_hour` not rebuilt from Neo4j on restart                         | Low      | cost_engine.py   |
| 5   | Scenario reset opens new Neo4j session per loop iteration                       | Low/Perf | sim-orchestrator |

---

## CI Verification

- **TypeScript:** `npx tsc --noEmit` — clean (0 errors)
- **Vite build:** `npm run build` — success, shared components properly code-split
- **Python lint:** `ruff check` — clean after removing unused `timezone` import

---

## Patterns & Lessons

1. **Decomposition strategy:** Extract constants/types first, then display-only components, then stateful sub-panels. Keep query/mutation logic in the main page file.
2. **Defense-in-depth validation:** Even when the HTTP layer validates, add validation in the domain function — Kafka consumers bypass HTTP entirely.
3. **`datetime.now()` grep audit:** After fixing one violation, grep the entire codebase. The unused import was a telltale sign of incomplete cleanup.
