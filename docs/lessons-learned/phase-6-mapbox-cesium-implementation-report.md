# Phase 6.1-6.8 Implementation Report (Map-Only Final)

Date: 2026-03-29
Scope: ROADMAP Phase 6 geospatial digital twin implementation in dashboard + CI-aligned validation.

## What Was Implemented

### Phase 6.1 - Real-world placement
- Added KART coordinate constants and geospatial baseline in dashboard utility code:
  - `dashboards/art-dashboard/src/utils/geospatial.ts`
- Anchored world map view around KART (`38.75, -27.0833`).

### Phase 6.2 - Mapbox GL JS integration
- Added dependencies for map rendering:
  - `mapbox-gl`, `@mapbox/mapbox-sdk`, `leaflet`, `@types/leaflet`
- Added required static airport layers:
  - `dashboards/art-dashboard/public/geojson/apron.geojson`
  - `dashboards/art-dashboard/public/geojson/runways.geojson`
  - `dashboards/art-dashboard/public/geojson/taxiways.geojson`
  - `dashboards/art-dashboard/public/geojson/terminals.geojson`
  - `dashboards/art-dashboard/public/geojson/gates.geojson`
- Added World view page with layer stack and live overlays:
  - `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`
- Added route and nav integration:
  - `dashboards/art-dashboard/src/App.tsx`
  - `dashboards/art-dashboard/src/components/HeaderBar.tsx`

### Phase 6.3 - Real destination airports
- Implemented dataset generation from OurAirports for destination coordinates:
  - Script: `scripts/helper_generate_destination_coordinates.py`
  - Generated output: `dashboards/art-dashboard/src/data/destinationCoordinates.ts`
- Documented helper usage in:
  - `scripts/README.md`

### Phase 6.4 - Live aircraft positioning
- Implemented great-circle interpolation, distance, bearing, and altitude profile:
  - `dashboards/art-dashboard/src/utils/geospatial.ts`
- World map derives per-flight positions from sim time + flight schedule/status.

### Phase 6.5 - Flight route arcs
- World map renders dashed route arcs for departures and updates them via batched source updates.

### Phase 6.6 - World map view (`/world`)
- Added new route and page:
  - `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`
- Implemented zoom-based visibility behavior for gate detail layers.
- Added KPI footer strip (airborne, >6h, approaching, longest route marker).

### Phase 6.7 - hardening notes
- Implemented token fallback behavior:
  - Mapbox when `VITE_MAPBOX_TOKEN` is present
  - Leaflet + OpenStreetMap fallback when token absent
- Batched route/aircraft data updates are done via source replacement (`setData`) in Mapbox path.

### Phase 6.8 - CesiumJS 3D globe (removed by product decision)
- Cesium was initially integrated, then removed after UX review because it duplicated the usefulness of the world map while increasing complexity and bundle size.
- Removal was completed by deleting Globe route/UI/dependencies/config:
  - `dashboards/art-dashboard/src/App.tsx` (`/globe` route removed)
  - `dashboards/art-dashboard/src/components/HeaderBar.tsx` (Globe tab removed)
  - `dashboards/art-dashboard/src/pages/GlobeView/GlobeViewPage.tsx` (deleted)
  - `dashboards/art-dashboard/package.json` (`cesium`, `vite-plugin-static-copy` removed)
  - `dashboards/art-dashboard/vite.config.ts` (Cesium static-copy config removed)
- Value was consolidated into an upgraded world map:
  - real destination airports + highlighted KART
  - moving aircraft markers driven by simulation time
  - route visualization from KART to destinations
  - click-on-aircraft details panel (flight number, status, delay, gate, terminal)

## Additional Issues Fixed Along The Way

- Resolved repository `ruff` failures that blocked CI lint pass:
  - Removed unused `SimSettings` import in `services/sim-orchestrator/routers/sim.py`
  - Removed unused `pytest` imports and unused variable in:
    - `tests/unit/test_baggage_conveyor_spatial.py`
    - `tests/unit/test_baggage_spatial.py`
    - `tests/unit/test_passenger_spatial.py`

## Validation and Test Results

### Executed
1. Dashboard dependency install:
- `npm install` in `dashboards/art-dashboard`
- Result: success

2. Dashboard unit tests:
- `npm test` in `dashboards/art-dashboard`
- Result: success, `8` test files passed, `43` tests passed

3. Dashboard production build:
- `npm run build` in `dashboards/art-dashboard`
- Result: success
- Notes: chunk-size warnings reduced after Cesium removal; Mapbox remains the main geospatial dependency

4. Python lint checks:
- `ruff check .`
- Result: initially failed on 5 lint issues, fixed, then passed

### Blocked
- Docker container rebuild validation (`docker compose build dashboard`) could not run due local Docker engine unavailable:
  - `dockerDesktopLinuxEngine` named pipe missing on machine.

## Temporary Artifacts Handling
- Command outputs were written under `tmp/phase6-*.log` during implementation.
- Temporary log files were removed at end of process.

## Notes / Follow-up Recommendations
- Keep map-only approach and avoid parallel globe UI unless a distinct non-overlapping operational use case is defined.
- Add explicit `.env.example` entry for `VITE_MAPBOX_TOKEN` in dashboard docs.
- Optionally move destination coordinate lookup to compact JSON served from `public/` if startup parse time grows.
