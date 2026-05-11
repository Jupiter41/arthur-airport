# Sprint 36 — ADS-B Improvements + ML Feed — Plan

## Tasks

### 1. Fix: click on flight zooms to destination instead of plane

**Root cause:** The `selectPlane` function recomputes the aircraft position
via `computeAircraftPosition(flight, currentSimTime)`. For flights near their
destination (fraction ≈ 1), the returned position IS the destination airport
coordinates. The Mapbox click event carries the actual rendered icon
coordinates in `event.lngLat`, which is the precise screen location the user
clicked.

**Fix:** When clicking directly on the map layer (`aircraft-symbols`), use
the Mapbox click event's coordinates (`event.lngLat`) for the flyTo, instead
of recomputing. Keep recomputation as fallback for search-panel clicks. Also
increase zoom from 7 → 10 for a tighter focus.

### 2. ADS-B: airborne filter

The Leaflet fallback already filters `on_ground` ADS-B aircraft, but the
Mapbox path sends ALL features including ground aircraft. Filter the ADS-B
GeoJSON features to exclude `on_ground === true` in the data-update effect
so only airborne real aircraft appear.

### 3. ADS-B: show route + origin/destination on click

The adsb.lol API doesn't include origin/destination data. However, we can
enhance the ADS-B popup by:
- Zooming/flying to the clicked aircraft position (use `event.lngLat`)
- Showing the flight's heading as a cardinal direction
- Adding `on_ground` status

Route display for real ADS-B flights would require a separate API (e.g.,
FlightAware, FR24) which adds paid dependencies. Instead, we'll show
available metadata more prominently and note the data source limitation.

### 4. ADS-B: hide callsign labels until zoomed in

Currently `adsb-symbols` shows `text-field: ["get", "callsign"]` at all zoom
levels, cluttering the map. Fix: set `minzoom` for text visibility or
make `text-size` 0 below zoom 8 and ramp up to readable at zoom 10+.
Simulated flights already show labels at all zooms since there are fewer.

### 5. ML page: Recent Actions feed always visible

The `AutonomousPanel` component has a "Recent Actions" section gated by
`log.length > 0`. When no actions have been taken, the section disappears
entirely, confusing users who expect feedback. Fix: always render the section
with a "No autonomous actions taken yet" placeholder when empty.

## Files to modify

| File | Changes |
|------|---------|
| `WorldMapPage.tsx` | Tasks 1–4: click handler, ADS-B filter, label zoom, popup |
| `MLTrainingPage.tsx` | Task 5: always-visible recent actions |
