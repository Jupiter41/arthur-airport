# Lessons Learned — Sprint 45: Autonomous Ops, Charts, Planning Phase 4

**Date:** 2025-07-22

---

## Bugs Fixed

### 1. Autonomous operations: repeated actions / recommendations not visible

**Root cause:** `generate_recommendations()` created new `Recommendation` objects with fresh UUIDs
every tick. The `rec.applied` check in `evaluate_and_apply()` never matched prior recommendations
since IDs were different each cycle.

**Fix:** Added a cooldown system in `autonomous.py` keyed by `bottleneck.id`. Once an action is
applied for a bottleneck, it enters a 30-minute cooldown. The recommender marks bottlenecks in
cooldown as `applied=True`. The `AutonomousPanel.tsx` was restructured to always show diagnostics
and recommendations (pending + applied/cooldown sections).

**Lesson:** When recommendation objects are ephemeral (regenerated each tick), identity-based
deduplication must use a stable key (bottleneck ID), not the recommendation's own UUID.

---

### 2. Data source active indicator stuck on "Simulated"

**Root cause:** `IncidentComparisonInline` had `isActive: true` hardcoded on the simulated column.

**Fix:** Accept `currentSource` prop, derive `isActive` dynamically per column.

---

### 3. Chart button not opening passenger flow modal

**Root cause:** `PassengerComparisonInline` had `graphEnabled={true}` but no `onGraphClick` handler.

**Fix:** Created `PassengerChartModal` component with SVG chart, wired `onGraphClick` to toggle modal.

---

### 4. BTS vs sim passenger count mismatch (5461 vs ~10)

**Root causes:**
1. BTS sample data had unrealistically low monthly pax (~150 instead of ~10,000).
2. Comparison mixed apples and oranges: sim = pax currently in airport (stock), BTS = hourly throughput (flow).

**Fix:** Scaled sample data to ~4,500–14,200/month. Added `AVG_DWELL_HOURS=3` multiplier to
convert BTS hourly throughput to estimated in-airport stock.

**Lesson:** When comparing simulation state (stock) with historical data (flow), always normalize
to the same unit. Document the conversion factor.

---

### 5. Chart modal missing labels, units, data points

**Fix:** Replaced `MiniChart`-based modals with proper SVG charts featuring:
- Y-axis labels with units (°C, %, km/h, hPa, pax, incidents)
- X-axis time labels
- Data point circles with hover tooltips
- Grid lines
- Removed comparison table from modal (chart-only view)

---

## Feature: ROADMAP_PLANNING Phase 4 — Investment Model

### P4.1: NPV/IRR Calculator (`finance/investment.py`)
- `compute_investment()`: DCF analysis with bisection-method IRR
- `sensitivity_analysis()`: NPV under low/base/high demand growth (1.8%/3.4%/4.8% CAGR)
- Returns `InvestmentResult` with recommendation: invest / marginal / do not invest

### P4.2: Benefit Extractor (`finance/benefit_extractor.py`)
- `extract_annual_benefit()`: Converts daily KPI deltas (baseline vs scenario) to annual EUR
- Uses Eurocontrol Standard Inputs: €102/min delay, €285 rebooking, €400 EU261

### REST Endpoints Added
- `POST /api/v1/planning/investment/analyze` — standalone NPV/IRR
- `POST /api/v1/planning/investment/sensitivity` — multi-scenario sensitivity
- `GET /api/v1/planning/scenarios/{id}/investment` — scenario-attached results

### Integration
- `scenarios/runner.py` now calls `compute_investment()` and `extract_annual_benefit()` when
  `capex_eur > 0`, populating `ScenarioResults.financials` and `annual_benefit_breakdown`.

---

## Files Modified

| File | Change |
|------|--------|
| `services/analysis-service/services/autonomous.py` | Cooldown tracking system |
| `services/analysis-service/services/recommender.py` | `applied_bottleneck_ids` parameter |
| `services/analysis-service/kafka/consumer.py` | Pass cooldown IDs to recommender |
| `dashboards/.../AutonomousPanel.tsx` | Always-visible recommendations UI |
| `dashboards/.../SourceComparisons.tsx` | Passenger chart modal, incident active fix |
| `dashboards/.../SourceCard.tsx` | Pass `currentSource` to incident comparison |
| `dashboards/.../WeatherComparison.tsx` | SVG chart modal with labels/units, removed duplicate portal |
| `services/passenger-service/routers/passengers.py` | Dwell-time normalization for compare |
| `services/passenger-service/services/bts_adapter.py` | Realistic sample data |
| `services/passenger-service/kafka/consumer.py` | CSV path fix (T100_2026) |
| `services/planning-service/finance/investment.py` | **NEW** — NPV/IRR calculator |
| `services/planning-service/finance/benefit_extractor.py` | **NEW** — Annual benefit extraction |
| `services/planning-service/scenarios/runner.py` | Wire investment analysis into results |
| `services/planning-service/routers/planning.py` | Investment REST endpoints |
