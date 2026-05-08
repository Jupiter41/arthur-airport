# Sprint 30 — Solidify Architecture: Issues, Stability & UX Fixes

## Date: 2026-05-08

## Objective

Fix multiple UI/backend bugs and improve clarity of decision systems in the dashboard.

## Issues Fixed

### 1. Flight Search Zoom — Non-Airborne Flights Appear in Results

**Problem:** When searching for planes on the World Map, all departure flights appeared in results regardless of status. Clicking a flight in `scheduled`, `boarding`, or `taxi` status would show its description panel but not zoom, because `computeAircraftPosition()` returns null for non-airborne flights.

**Fix:** Filter `filteredPlanes` to only show flights with status `departed`, `airborne`, or `approach` — these are the only flights with a computable position on the map. Also decreased zoom from 9 to 7 for a wider view on plane selection.

**Files:** `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`

### 2. Data Source Switching Does Nothing

**Problem:** The `GET /weather/source` endpoint read the `WEATHER_SOURCE` env var instead of the runtime-switched value in `_state.weather_source`. After switching via `POST /weather/source`, the GET still returned the old value, making the UI appear unchanged.

**Fix:** Added `get_weather_source()` function to the consumer module and updated the GET endpoint to use it instead of `os.getenv()`.

**Files:** `services/weather-service/kafka/consumer.py`, `services/weather-service/routers/weather.py`

### 3. ADS-B Always Shows 0 Flights

**Problem:** Airport was positioned in the mid-Atlantic (38.75°N, -27.08°W) where there is no air traffic. The 1000km ADS-B radius captured 0 real aircraft.

**Fix:** Moved airport to Luxembourg Findel Airport position (49.6233°N, 6.2044°E) where European air traffic is dense. Reduced radius from 1000km to 400km (sufficient for busy European airspace). Updated all coordinate references:

- `services/flight-service/services/adsb.py` — polling coordinates
- `dashboards/art-dashboard/src/utils/geospatial.ts` — KART_COORDINATES
- `config/network.yaml` — home airport entry
- `dashboards/art-dashboard/public/geojson/*.geojson` — airport layout overlays
- `scripts/helper_generate_destinations.py` — destination generation reference

**Files:** 8 files updated

### 4. Airborne Flights with 0 Baggages

**Problem:** Poisson(λ=1.0) distribution can output 0 for individual passengers. With small flights or cargo flights, this led to departure flights having 0 total bags.

**Fix:** Ensure at least 1 bag per non-cargo passenger during baggage generation: `if lam > 0 and bag_count == 0: bag_count = 1`.

**Files:** `services/sim-orchestrator/services/baggage.py`

### 5. Autonomous Operations Mode Buttons Do Nothing

**Root causes (3 bugs):**

1. Button values used `"rule"` but API expects `"rule_based"` (enum mismatch)
2. `GET /autonomous` returns `{ autonomous: { mode: ... } }` but the panel stored the full response then read `settings?.mode` from top level (undefined)
3. `PATCH /autonomous` required a full `AutonomousSettings` model. Sending just `{ mode: "rule_based" }` caused Pydantic to fill defaults (including `enabled: false`), so mode changed but autonomous stayed disabled

**Fixes:**

- Fixed button values to use correct enum strings
- Unwrap `response.autonomous` when storing settings in the panel
- Changed PATCH endpoint to accept `dict[str, Any]` and merge partial body with existing settings
- Auto-derive `enabled` from `mode != "off"` in `update_settings()`

**Files:** `dashboards/art-dashboard/src/pages/MLTraining/MLTrainingPage.tsx`, `services/analysis-service/routers/analysis.py`, `services/analysis-service/services/autonomous.py`

### 6. Decision Systems Clarity

**Improvements:**

- Added mode descriptions to the Autonomous Operations panel (explains what each mode does)
- Replaced technical phase IDs with algorithm names in Anomaly Detection panel ("Isolation Forest" instead of "P5-3-1")
- Added brief explanation text under the Anomaly Detection header

**Files:** `dashboards/art-dashboard/src/pages/MLTraining/MLTrainingPage.tsx`, `dashboards/art-dashboard/src/pages/IncidentConsole/Phase5Panels.tsx`

### 7. RL Training Fails: TensorBoard Not Installed

**Problem:** `stable-baselines3` PPO uses `tensorboard_log` parameter, which requires the `tensorboard` package. It was not in `requirements.txt`.

**Fix:** Added `tensorboard>=2.16.0` to analysis-service requirements.

**Files:** `services/analysis-service/requirements.txt`

## Tests & Validation

- `npx tsc --noEmit` (dashboard) — 0 errors
- `npm run build` (dashboard) — success
- `npx tsc --noEmit` (api-gateway) — 0 errors
- `ruff check services/` — all checks passed
- No regressions in build or type-checking

## Design Decisions

1. **Zoom level 7 vs 9**: Level 7 provides enough context to see the aircraft in relation to surrounding geography without being so close that a slight position error makes it appear off-screen.
2. **400km ADS-B radius**: European airspace around Luxembourg is dense enough that 400km captures 50-200+ aircraft at any time, plenty for visualization without overwhelming the OpenSky API rate limits.
3. **Partial PATCH merge**: The autonomous settings endpoint now merges partial updates, so the frontend can send just the field(s) being changed without resetting other settings to defaults.
4. **Minimum 1 bag per passenger**: More realistic than pure Poisson (real passengers almost always have at least a carry-on/checked bag) and eliminates the 0-baggage edge case.
