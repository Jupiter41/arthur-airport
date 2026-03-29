# Phase 6 Plan - Mapbox Geospatial Twin + Cesium Globe

Date: 2026-03-29
Status: In progress

## Scope
Implement roadmap Phase 6.1-6.8 in dashboard `dashboards/art-dashboard` with an elegant, maintainable architecture.

## Constraints Applied
- No service-to-service HTTP changes.
- No wall-clock business logic for simulation-driven visuals (derive from sim clock + flight schedule).
- Keep map updates batched (`source.setData` in Mapbox, entity updates in Cesium).
- Add fallback rendering path when Mapbox token is absent.

## Step-by-Step Execution

1. Baseline geospatial assets
- Add `public/geojson/apron.geojson`
- Add `public/geojson/runways.geojson`
- Add `public/geojson/taxiways.geojson`
- Add `public/geojson/terminals.geojson`
- Add `public/geojson/gates.geojson`

2. Geospatial computation layer
- Add `src/utils/geospatial.ts`:
  - Great-circle interpolation
  - Haversine distance
  - Bearing computation
  - Altitude profile by aircraft type
  - Flight position derivation from sim time

3. Destination airport coordinate support
- Add generated data file from `data/ourairports/airports.csv` under dashboard source for destination lookup
- Add helper script under `scripts/` with `helper_` prefix to regenerate lookup data and document usage in `scripts/README.md`

4. World view (Phase 6.1-6.7)
- Add `src/pages/WorldMap/WorldMapPage.tsx`
- Add map engine switch:
  - Mapbox mode when `VITE_MAPBOX_TOKEN` exists
  - Leaflet fallback mode when token missing
- Render required layer stack and dynamic overlays:
  - apron, runways, taxiways, terminals, gates, routes, aircraft
- Add `/world` route and navigation entry
- Implement zoom-dependent visibility and KPI strip

5. Cesium globe view (Phase 6.8)
- Add `src/pages/GlobeView/GlobeViewPage.tsx`
- Integrate Cesium with Vite static copy plugin
- Render:
  - airport GeoJSON
  - 3D route arcs and aircraft altitude positions
  - day/night lighting with simulation-clock sync
- Add `/globe` route and navigation entry

6. Validation
- Run dashboard tests
- Run dashboard build
- Run root `ruff check`
- Save command outputs in `tmp/phase6-*.log` during work, then clean them before finalizing 

7. Documentation/reporting
- Add completion report in `docs/lessons-learned/` with:
  - implemented items
  - issues fixed
  - tests run and results
  - limitations and next increments

## Risks and Mitigations
- Map provider tokens unavailable:
  - Mitigation: tokenless Leaflet fallback for `/world`; graceful fallback messaging for Cesium token.
- Large destination dataset overhead:
  - Mitigation: compact generated JSON map with only needed fields.
- Route update performance:
  - Mitigation: batched source updates and memoized feature generation.
