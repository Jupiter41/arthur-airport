# Sprint 47 — Cost Models & Capacity Planning (Phases 6–8)

## Bugs Fixed

### 1. Live cost values changing on page refresh
- **Root cause**: `rebuild_running_totals()` summed ALL `CostRecord` nodes across ALL sim days. On restart, in-memory totals included every historical day.
- **Fix**: Query `max(c.sim_day)` first, then filter `MATCH (c:CostRecord {sim_day: $day})`.
- **Lesson**: Any "rebuild from Neo4j" function must scope to the correct time window — never aggregate the full history into "current" state.

### 2. BTS data wildly different from simulation
- **Root cause**: T100 reference CSV has float-formatted values (`"3.00"`). `int("3.00")` raises `ValueError`, silently skipping all rows, falling back to `_generate_sample_data()`. Load factor formula also had `* 1.1` making values exceed 1.0.
- **Fix**: `int(float(...))` for CSV parsing. Removed `* 1.1` from load factor.
- **Lesson**: Always use `int(float(x))` when parsing CSV numeric fields — many export tools write integers as floats.

### 3. Chart timestamps showing only 2 hours
- **Root cause**: Hourly endpoint only returned hours with actual cost records. Early in simulation, only 1–2 hours have data.
- **Fix**: Pad response to 24 data points (hours 0–23), filling missing hours with zeros.
- **Lesson**: Time-series chart endpoints should always return the full expected time range.

### 4. Incidents stacking up, recommendations ineffective
- **Root cause**: `security_congestion` and cascade child types had `TTR=None` (never auto-resolve). `apply_recommendation_ttr_reduction()` skipped None-TTR incidents. Only 1 action per autonomous cycle.
- **Fix**: Added TTR ranges for all incident types. Recommendation handler now assigns TTR when applied to None-TTR incidents. Rule-based mode applies multiple actions per cycle.
- **Lesson**: Every incident type must have a finite TTR. None-TTR means "infinite duration" which breaks the simulation lifecycle.

## Phases Implemented

### Phase 6: ML Demand Forecasting
- LightGBM demand model with heuristic fallback (`planning-service/ml/demand_model.py`)
- LightGBM delay prediction model (`planning-service/ml/delay_model.py`)
- Training pipeline from BTS CSV data (`planning-service/ml/training_pipeline.py`)
- REST endpoints: `/demand/forecast`, `/demand/growth`, `/delay/predict`, `/ml/train`, `/ml/status`

### Phase 7: Decision Audit Trail
- In-memory audit store with 500-entry cap (`planning-service/audit/audit_trail.py`)
- Tracks: recommendation → applied → outcome with predicted vs actual savings
- REST endpoints: `/audit/recommendations`, `/audit/summary`, `/audit/log`, `/audit/apply/{id}`, `/audit/outcome/{id}`

### Phase 8: Planning Dashboard
- New React page at `/planning` with 4 tabs:
  - **Scenario Builder**: form + template presets + scenario list with status
  - **Results Comparison**: KPI distribution table (mean, std, P5/P50/P95)
  - **Investment Dashboard**: NPV/IRR/payback cards + demand growth projections
  - **Decision Audit Trail**: summary cards + accuracy bar + recommendation history table
- API client (`planningApi`) added to `useApi.ts`
- Nav item added under Simulation menu
