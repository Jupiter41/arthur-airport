# Sprint 36 — ADS-B Improvements + ML Feed — Report

**Date:** 2026-05-09
**Scope:** 5 UX fixes — click-zoom, ADS-B airborne filter, ADS-B labels, ADS-B click popup, ML page feed

Plan: [sprint-36-adsb-improvements-ml-feed-plan.md](sprint-36-adsb-improvements-ml-feed-plan.md)

---

## Changes

### 1. Fix: click on flight zooms to plane, not destination

**Root cause:** `selectPlane` recomputed the aircraft position via
`computeAircraftPosition()`. For flights at fraction ≈ 1 (near arrival at
destination), the recomputed position IS the destination airport coordinates.
The Mapbox click event's `lngLat` holds the exact icon position the user
clicked, which is always correct.

**Fix in `WorldMapPage.tsx`:**
- The `aircraft-symbols` click handler now passes `event.lngLat` coordinates
  to `selectPlane(flightId, clickCoords)`.
- `selectPlane` prefers the click coordinates over recomputed position.
- Increased flyTo zoom from 7 → 10 for tighter focus on the aircraft.
- Search-panel clicks continue to use `computeAircraftPosition` (no click event).

### 2. ADS-B: only show airborne aircraft

The Mapbox path was not filtering out `on_ground` ADS-B aircraft (the Leaflet
path already did). Now the data-update effect and the initial seed both filter
`adsbData.features.filter(f => !f.properties.on_ground)` before pushing to
the `adsb-aircraft` source.

### 3. ADS-B: hide callsign labels until zoomed in

ADS-B callsign labels cluttered the map at low zoom levels (hundreds to
thousands of label overlaps). Changed `text-field` from `["get", "callsign"]`
to a zoom step expression:
```json
["step", ["zoom"], "", 9, ["get", "callsign"]]
```
Labels only appear at zoom ≥ 9. Simulated flight labels remain visible at all
zoom levels since the count is much lower.

### 4. ADS-B: improved click popup + fly to aircraft

Clicking an ADS-B aircraft now:
- Flies the camera to the clicked position (`event.lngLat`) with
  `zoom: max(currentZoom, 8)` so the view never zooms OUT.
- Shows flight level (FL) alongside altitude in metres.
- Shows heading in degrees.

### 5. ML page: Recent Actions always visible

The `AutonomousPanel` component previously hid the "Recent Actions" section
entirely when `log.length === 0`. Now:
- The section always renders with the active agent mode label.
- When empty and mode is `off`: "Enable an autonomous mode to start collecting actions."
- When empty and an agent is active: "No autonomous actions taken yet. Actions will
  appear here when the agent detects bottlenecks and applies recommendations."
- When actions exist: same card list as before.

---

## Validation

| Check | Result |
|-------|--------|
| `ruff check services scripts` | All checks passed |
| `npx tsc --noEmit` (api-gateway) | Clean |
| `npm run build` (art-dashboard) | Built in 6.61s, zero TS errors |
| `docker compose up --build --no-deps -d dashboard` | Built and deployed OK |

---

## Lessons learned

1. **Mapbox click → use event coordinates.** When a user clicks on a symbol
   layer, `event.lngLat` gives the exact spot they clicked. Recomputing the
   position from flight data introduces drift at high fraction values.
2. **ADS-B filtering belongs at the source data level.** Filtering
   `on_ground` at the GeoJSON source (not a Mapbox filter expression) keeps
   the feature count low for better performance and simpler click handling.
3. **Zoom-dependent labels via step expressions.** Mapbox's `["step", ["zoom"], ...]`
   is cleaner than `minzoom` on the layer because it affects only the text
   while keeping icons visible at all zoom levels.
