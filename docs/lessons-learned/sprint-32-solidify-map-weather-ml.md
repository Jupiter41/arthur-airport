# Sprint 32 — Solidify: Map, Weather Compare, ML Page

**Date:** 2026-05-08

## Issues fixed

### 1. Selected flight route not highlighted on map

**Problem:** When selecting a flight on the WorldMap, the aircraft icon changed to yellow but the route arc remained the same color as all other routes, making it hard to visually track the selected flight's path.

**Fix:** Added data-driven paint properties to the Mapbox `routes-line` layer that highlight the selected flight's route in yellow (#facc15) with full opacity. For the Leaflet fallback, the route line color/opacity/weight now also varies based on selection.

**Files:** `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`

### 2. Weather source comparison always empty

**Problem:** The "Source Comparison" panel on the Data Sources page always showed empty/error state. Clicking refresh and auto-refresh both failed silently.

**Root cause:** The `/weather/compare` endpoint imported `sample_params` from `services.fsm`, but the function is actually exported from `services.parameters`. The `ImportError` was raised on every call, caught silently by the frontend's `catch { /* ignore */ }`.

**Fix:** Changed the import in the compare endpoint from `from services.fsm import evaluate_transition, sample_params` to `from services.parameters import sample_params`. Removed the unused `evaluate_transition` import.

**Verified:** After fix, the endpoint returns data from all three sources (simulated, historical, live) with distinct values.

**Files:** `services/weather-service/routers/weather.py`

### 3. WorldMap showing 0 flights (ADS-B/position features empty)

**Problem:** The flights API returned flights (many with direction "arrival"), but the WorldMap showed 0 aircraft because `computeAircraftPosition` only handled departure flights. Arrival flights were silently excluded.

**Root cause:** Two filters were in play:

1. `computeAircraftPosition()` returned `null` for any flight with `direction !== "departure"`
2. `activeFlights` in WorldMap was filtered to departures only

Since many flights at any given moment are arrivals (approaching/airborne inbound to KART), the map appeared empty during arrival-heavy periods.

**Fix:**

- Extended `computeAircraftPosition` to handle both directions: departures interpolate from KART → destination, arrivals interpolate from origin → KART
- For arrivals, departure time from origin is estimated as `estimated_arrival_time - flight_duration_minutes`
- Updated `activeFlights` to include both arrivals and departures
- Updated `toRouteFeature` to render routes from origin → KART for arrivals
- Updated airport feature generation to show origin airports for arrivals
- Added `origin_iata` to the search filter for the WorldMap plane search

**Verified:** After fix, 51 flights visible on map (47 departures + 4 arrival approaches) vs 47 before.

**Files:**

- `dashboards/art-dashboard/src/utils/geospatial.ts`
- `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`

### 4. ML page missing RL model training indicator

**Problem:** The ML Training page didn't explain when the RL model is considered trained.

**Fix:** Added a note in the Environment & Models panel (RL Agent section) explaining that the RL model is considered trained when `best_model.zip` and `rl_policy.zip` files are created in the models directory.

**Files:** `dashboards/art-dashboard/src/pages/MLTraining/MLTrainingPage.tsx`

## Key lessons

- **Silent `catch { /* ignore */ }` blocks** in frontend code hide real backend errors. The weather compare issue would have been immediately apparent if the frontend logged or displayed the error.
- **Direction-agnostic position computation** is essential. Airport simulations naturally have roughly equal arrivals and departures; filtering to only one direction halves the visible traffic.
- **Import errors in lazy (function-level) imports** in Python endpoints are particularly sneaky — the endpoint registers fine at startup, but every request fails at runtime.

## Tests performed

- TypeScript compilation: `npx tsc --noEmit` — clean
- Vite production build: `npx vite build` — clean
- Python syntax/lint: `ruff check` — clean
- Docker compose full stack: all services healthy
- Weather compare endpoint: returns valid data from all 3 sources
- Flight data: 51 airborne flights visible (departures + arrivals)
