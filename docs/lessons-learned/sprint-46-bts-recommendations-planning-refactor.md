# Sprint 46 — BTS Data Fix, Recommendation Impact, Planning Phase 5, Dashboard Refactor

**Date:** 2025-07-16
**Status:** Complete

---

## Plan

### Problem 1: BTS Data Not Robust

**Root cause:** T100_2026.csv is a raw BTS download with ~43 columns. Most rows are charter/cargo
with 0 passengers. No routes match the fictitious KART/ART airport, so `bts_adapter.py` always falls
back to `_generate_sample_data()`. The `bts_calibration.py` in sim-orchestrator uses the CSV for
route weights but the data quality is poor (mostly zero-value rows).

**Fix:**
1. Download a properly filtered BTS T-100 dataset for a real medium-sized US airport (RDU — Raleigh-Durham,
   ~13M pax/year) to use as the reference airport for KART calibration
2. Create a script `scripts/helper_filter_bts_data.py` that:
   - Reads the raw T100_2026.csv
   - Filters to a specific reference airport (e.g. RDU)
   - Filters out rows with 0 passengers
   - Outputs a clean CSV with only relevant columns
   - Remaps the reference airport IATA to ART for KART compatibility
3. Update `bts_adapter.py` to use the filtered data and document the mapping
4. Update `bts_calibration.py` to handle the filtered data format
5. Fix the data source comparison UI to show meaningful, comparable numbers
6. Update documentation (DATA.md, BTS.md, DATA_SOURCES.md) to explain the mapping clearly

### Problem 2: Recommendation Impact Not Clear

**Root cause:** Incidents auto-resolve via TTR countdown (`tick_ttr()` in lifecycle.py). When a
recommendation is applied (e.g. open security lane), it has no effect on TTR or incident resolution.
The user cannot tell if the recommendation helped or if the incident just timed out.

**Fix:**
1. Add TTR reduction when recommendations are applied — applied recommendations should reduce
   TTR by a configurable percentage based on action type
2. Add a `resolution_reason` field to incidents: `"ttr_elapsed"` vs `"recommendation_applied"` vs
   `"manual"`
3. Track recommendation outcomes in the incident timeline — show "Recommendation X applied at T,
   reduced TTR from Y to Z minutes"
4. Surface this in the IncidentConsole UI: show recommendation impact in the incident detail

### Problem 3: Dashboard Refactoring

Large monolithic pages to decompose:
- WorldMapPage (2094 lines) → map components, panels, controls
- FlightBoardPage (1189 lines) → table, filters, detail drawer
- DebugPage (1092 lines) → debug panels
- IncidentConsolePage (945 lines) → incident list, detail, inject modal
- SettingsPage (783 lines) → settings sections
- ScenariosPage (696 lines) → scenario builder, results
- PassengerFlowPage (665 lines) → flow panels
- SimHistoryPage (633 lines) → history table, detail modal
- BaggageTrackerPage (547 lines) → tracker components
- MLTrainingPage (454 lines) → training panels

### Problem 4: ROADMAP_PLANNING Phase 5 — Scenario Templates

Implement pre-built scenario template functions:
- P5.1: `create_gate_scenario()` — add N gates to a terminal
- P5.2: `create_runway_scenario()` — add a runway
- P5.3: `create_route_scenario()` — add a new route
- P5.4: `create_security_scenario()` — add security lanes

Plus REST endpoints for template-based scenario creation.

---

## Execution Order

1. BTS data fix (most impactful)
2. Recommendation impact tracking
3. Phase 5 scenario templates
4. Dashboard refactoring (progressive, largest files first)
5. Tests and CI

---

## Results

### BTS Data (Problem 1) ✅
- Created `scripts/helper_filter_bts_data.py` to filter raw BTS T-100 for a reference airport and remap to ART
- Chose BOS (Boston Logan) as reference: ~488 daily flights, 65 destinations, 78% load factor — close to KART's 420 daily flights
- Generated `data/bts/T100_reference.csv` (555 rows) from the raw 18K+ row T100_2026.csv
- Updated all service paths, documentation, and frontend labels

### Recommendation Impact (Problem 2) ✅
- incident-service now subscribes to `analysis.events` topic
- New `_on_recommendation_applied()` handler reduces TTR of related active incidents by 10-40% depending on action type
- `resolution_reason` field added to incidents in Neo4j: `ttr_elapsed`, `recommendation_applied`, or `manual`
- IncidentConsole UI shows resolution reason badges and TTR countdown on active incidents

### Phase 5 Scenario Templates (Problem 4) ✅
- Created `services/planning-service/scenarios/templates.py` with 4 factory functions + TEMPLATE_CATALOGUE
- Added 5 REST endpoints: GET /templates, POST /templates/{add_gate,add_runway,new_route,security_lanes}
- All endpoints auto-proxied through API gateway via existing /api/v1/planning route

### Dashboard Refactoring (Problem 3) ✅
- Decomposed 9 monolithic pages into 40+ component files
- Largest reductions: WorldMap (2094→1719), FlightBoard (1189→120), Debug (1092→61), IncidentConsole (945→212)
- All pages build successfully with zero TypeScript errors

### Lessons Learned
- **BTS data quality**: Raw BTS T-100 downloads contain mostly zero-passenger cargo/charter rows. Always filter to a reference airport with similar traffic profile.
- **Feedback loops**: If a system generates recommendations but nothing consumes them, the recommendations are purely cosmetic. Always close the feedback loop — recommendations must affect the system state they're trying to improve.
- **Dashboard decomposition**: Extract constants/types first, then pure display components, then stateful sub-panels. Keep query logic in the main page file.
