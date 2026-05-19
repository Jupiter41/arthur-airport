# Sprint 37 — Cost Models & Capacity Planning

## Plan

### Scope

1. **LLM Recommendation Engine (Mistral Integration)**
   - Modify `services/analysis-service/services/nlp/llm.py` to support Mistral as primary LLM
   - Mistral uses OpenAI-compatible API at `https://api.mistral.ai/v1`
   - Routing: Mistral (MISTRAL_API_KEY) → fallback to generic LLM_API_KEY → template
   - Log model selection for traceability
   - Update docker-compose.yml env vars

2. **BTS Data Integration (Calibration)**
   - Create `services/sim-orchestrator/services/bts_calibration.py`
     - Load BTS T100_2026.csv
     - Extract per-route load factors, departure frequencies, capacity distributions
     - Expose calibration params to schedule + passenger generation
   - Modify `services/sim-orchestrator/services/schedule.py`
     - Use BTS route frequencies to weight destination selection
     - Use BTS seat counts to inform capacity constraints
   - Modify `services/sim-orchestrator/services/passengers.py`
     - Use BTS load factors per route instead of global beta distribution
   - Mount `data/` volume in sim-orchestrator container

3. **World Map UI Refactor**
   - Create unified `MapControlPanel` component
   - Replace scattered toolbar buttons with collapsible settings panel
   - Single entry point (gear icon button)
   - Sections: Map Style, Data Layers, Flight Filters, Display Options
   - No performance regression (memoization preserved)

4. **DATA.md Documentation**
   - Document all data sources, their purpose, and how they're used

### Architecture Compliance

- No new inter-service HTTP calls
- BTS calibration runs inside sim-orchestrator (data stays local)
- Mistral integration uses existing OpenAI-compatible adapter pattern
- No new architectural layers introduced

### Files Modified

| File                                                           | Change                                |
| -------------------------------------------------------------- | ------------------------------------- |
| `services/analysis-service/services/nlp/llm.py`                | Mistral routing + logging             |
| `docker-compose.yml`                                           | MISTRAL env vars for analysis-service |
| `services/sim-orchestrator/services/bts_calibration.py`        | NEW — BTS data loader & calibration   |
| `services/sim-orchestrator/services/schedule.py`               | BTS-weighted destinations             |
| `services/sim-orchestrator/services/passengers.py`             | BTS per-route load factors            |
| `services/sim-orchestrator/Dockerfile`                         | Mount data/ volume                    |
| `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx` | Unified control panel                 |
| `dashboards/art-dashboard/src/components/MapControlPanel.tsx`  | NEW — control panel component         |
| `dashboards/art-dashboard/src/stores/worldMapSettingsStore.ts` | Add status filter                     |
| `DATA.md`                                                      | NEW — data source documentation       |

---

## Report

### Summary of changes

**1. LLM Mistral Integration** (`services/analysis-service/services/nlp/llm.py`)

- Replaced single-provider OpenAI adapter with Mistral-first routing
- Routing: MISTRAL_API_KEY → LLM_API_KEY → template fallback
- Mistral uses `https://api.mistral.ai/v1` (OpenAI-compatible)
- Added provider logging for debugging/traceability
- If Mistral fails, automatically falls back to generic LLM provider
- Updated `get_config()` to report provider info
- Added `MISTRAL_API_KEY` env var to docker-compose analysis-service

**2. BTS Data Integration** (`services/sim-orchestrator/services/bts_calibration.py` — NEW)

- Created BTS calibration module that parses T100_2026.csv
- Extracts per-route load factors, departure frequency weights, seasonal curves, capacity profiles
- Integrated into `schedule.py`: destination selection now boosted by BTS departure frequency
- Integrated into `passengers.py`: per-route BTS load factor replaces global beta distribution (with ±2.5% noise and seasonal adjustment)
- BTS data is loaded at startup (logged), graceful fallback if CSV not present
- Mounted `data/` volume read-only in sim-orchestrator container
- BTS field mapping fully documented in code comments and DATA.md

**3. World Map UI Refactor** (`dashboards/art-dashboard/`)

- Created `MapControlPanel.tsx` — unified collapsible settings panel
- Single entry point: ⚙ Settings button in toolbar
- Sections: Map Style, Data Layers (Routes/ADS-B/Network toggles), Flight Filters (direction/status/data source)
- Removed scattered individual toggle buttons from toolbar (Routes, ADS-B, Network, direction select, map style select)
- Added `statusFilter` (all/airborne/boarding/ground) and `dataSource` (all/simulated/real) to `worldMapSettingsStore`
- Bumped store version to 2 for migration
- All settings persist via localStorage

**4. DATA.md** (project root — NEW)

- Documented all 7 data sources: OurAirports, BTS T-100, OpenFlights, ADS-B, Weather, Incidents, Airport Config
- For each: what it represents, how it's used, why it exists
- Explicit BTS→simulation calibration mapping
- Data flow summary diagram

### Bugs found and fixed

1. **`GATE_OPEN_MINUTES` test drift**: `test_passenger_state_machine.py` had two tests asserting `GATE_OPEN_MINUTES == 30` and testing gate-open timing with 30-minute assumptions, but the constant was changed to 50 at some point. Updated test to match actual value (50) and adjusted timing test scenario.

### Decisions and rationale

- **Mistral as primary, not sole provider**: Kept generic LLM fallback chain so the system works even if Mistral is down or if users prefer different providers
- **BTS calibration as separate module**: Isolated from schedule/passenger generators so it can be tested independently and disabled without code changes (just remove the CSV)
- **BTS weight boosting vs. replacement**: Used multiplicative boost (`fixture_weight * (1 + bts_weight)`) rather than full replacement so destinations not in BTS data still appear in the schedule
- **Load factor noise**: Added ±2.5% Gaussian noise to BTS load factors to prevent identical passenger counts across identical routes
- **Control panel vs. toolbar**: Consolidated all map settings into a single collapsible panel to reduce UI clutter while preserving quick access via the ⚙ button

### Tests executed and results

| Check                      | Result                         |
| -------------------------- | ------------------------------ |
| `ruff check services/`     | ✅ All checks passed           |
| `tsc --noEmit`             | ✅ 0 errors                    |
| `vite build`               | ✅ 837 modules, built in 6.25s |
| `pytest tests/unit/`       | ✅ 563 passed                  |
| `vitest run`               | ✅ 43 passed (8 test files)    |
| `lint-augmented-assign.py` | ✅ 0 issues                    |
| `lint-cypher.py`           | ✅ 0 new issues                |
| `docker compose build`     | ✅ 3 images built              |

### Trade-offs

- The `MapControlPanel` is positioned absolute top-left, same spot as the search panel. They're mutually exclusive (control panel hides when search opens) to avoid overlap.
- BTS seasonal adjustment uses a simple ratio approach rather than full time-series decomposition — adequate for simulation calibration purposes.
