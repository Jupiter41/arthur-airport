# Phase 1 Completion — Dashboard Visualization + Codebase Quality Audit

**Date:** 2026-04-05  
**Phase:** 1 — Simulation Fidelity (final items)  
**Status:** 22/22 items complete (Phase 1 fully done)

---

## Summary

Completed all 6 remaining Phase 1 dashboard visualization items and performed a
codebase quality audit, fixing 4 bugs (1 critical, 3 moderate).

---

## What was implemented

### P1-1-3 — ADS-B Overlay Toggle on World Map
- Added `adsb-aircraft` GeoJSON source and `adsb-symbols` Mapbox layer with orange plane icons
- Toggle button in the world map header ("📡 ADS-B") activates/deactivates the layer
- Shows aircraft count in the button when active
- ADS-B aircraft are rendered with callsign labels, rotated by heading
- Clicking an ADS-B icon shows an info popup with ICAO24, country, altitude, speed, distance
- Footer stat pill shows ADS-B count when enabled
- Data fetched from `GET /api/v1/flights/adsb-states` every 15 seconds (only when toggled on)
- Files: `WorldMapPage.tsx`, `useQueries.ts`, `useApi.ts`, `types.ts`

### P1-1-4 — Track Comparison (Simulated vs Real)
- When ADS-B is enabled and a simulated flight is selected, the system finds the nearest
  ADS-B aircraft on a similar heading (within 20°) and within 500 km
- Displays the matched ADS-B callsign and deviation in km inside the flight detail panel
- Deviation colour-coded: green (<50 km), amber (50–150 km), red (>150 km)
- Files: `WorldMapPage.tsx` (added `findMatchingAdsb()` utility and `trackComparison` memo)

### P1-1-5 — Historical Track Calibration (Plan)
- Wrote detailed plan in `docs/lessons-learned/phase-1-adsb-calibration-plan.md`
- Covers: data acquisition from OpenSky Zenodo, route extraction, correction model fitting,
  integration into `geospatial.ts`, and validation methodology
- Decision: deferred to a dedicated data science sprint; current great-circle model is
  acceptable for demo purposes

### P1-1-6 — Real Flights Nearby Panel
- Added `NearbyFlightsPanel` component to the Ground Ops dashboard
- Lists up to 12 ADS-B aircraft sorted by distance, showing callsign, flight level, speed, distance
- Last update timestamp displayed
- Data from `GET /api/v1/flights/adsb-states` via `useADSBQuery` hook

### P1-3-5 — Ground Vehicle Icons on Airport Schematic
- Added `GroundVehicleOverlay` SVG component overlaid on the Ground Ops airfield schematic
- Active vehicles (dispatched/at_gate/returning) shown as coloured circles with type label,
  positioned according to their grid coordinates
- Vehicle depot area shows counts of available vehicles by type
- Dispatched vehicles pulse to indicate movement
- At-gate vehicles show gate assignment label
- Added `GroundVehicleStatusPanel` with utilisation bars per vehicle type (colour-coded
  by utilisation: green/amber/red)
- Files: `GroundOpsPage.tsx`, `useQueries.ts`, `useApi.ts`

### P1-4-4 — Runway Throughput Chart
- Added `RunwayThroughputChart` component to the Flight Board bottom bar
- Side-by-side bar chart showing actual movements vs capacity for each runway
- Utilisation percentage colour-coded (green <70%, amber 70–90%, red >90%)
- Shows spare capacity and queue breakdown (arrivals/departures)
- Sits alongside the existing `RunwayStatusBar` in a 2-column grid
- Files: `FlightBoardPage.tsx`

---

## Bugs Found and Fixed

### 1. Critical: Diversion event emits wrong status
**File:** `services/flight-service/kafka/consumer.py` line 928  
**Symptom:** When a flight is diverted, Neo4j status is set to `diverted` but the
`FlightStatusChanged` Kafka event emits `new_status="cancelled"`. This caused
downstream consumers (passenger, baggage, dashboard) to see a cancelled flight
while Neo4j source of truth shows diverted.  
**Fix:** Changed `new_status="cancelled"` to `new_status="diverted"` in the
diversion event emission path.

### 2. Critical: Dashboard WS handlers use wrong event field names
**File:** `dashboards/art-dashboard/src/hooks/useWebSocket.ts` lines 81–106  
**Symptom:** `BaggageStatusChanged` handler expected `zone_id` and `items` fields,
but actual events have `scan_zone` and `new_status`. `PassengerStatusChanged`
handler expected `zone_id`, `density`, `load_pct` but actual events have
`location_zone` and `new_status`.  
**Fix:** Rewrote handlers to use correct field names. Since per-entity events
don't carry zone aggregate data, handlers now just signal zone changes. Zone
aggregates continue to come from REST polling.

### 3. Moderate: datetime.utcnow() used as fallback in business logic
**Files:** `services/incident-service/routers/incidents.py`,
`services/passenger-service/routers/passengers.py`  
**Symptom:** 4 incident-service endpoints and 1 passenger-service endpoint fell back
to `datetime.utcnow()` when sim_time was unavailable. This violates the "no wall
clock in business logic" rule.  
**Fix:** Changed all fallbacks to return `HTTP 503` ("Simulation clock not available
yet") instead of using real time. Removed unused `datetime` import from passenger router.

### 4. Minor: Unused `useState` import in GroundOpsPage
**File:** `dashboards/art-dashboard/src/pages/GroundOps/GroundOpsPage.tsx`  
**Fix:** Removed unused import.

---

## New Types and API Client Functions

### types.ts additions
- `ADSBFeature` — individual ADS-B aircraft GeoJSON feature
- `ADSBFeatureCollection` — full response from `/flights/adsb-states`
- `GroundVehicleSummary` — response from `/ground-vehicles`

### useApi.ts additions
- `flightsApi.adsbStates()` — fetch ADS-B states
- `flightsApi.groundVehicles()` — fetch ground vehicle summary

### useQueries.ts additions
- `useADSBQuery(enabled)` — React Query hook, polls every 15s when enabled
- `useGroundVehiclesQuery()` — React Query hook, polls every 5s

---

## CI Results

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `pytest tests/unit/ -q` | 507 passed in 0.91s |
| Dashboard `npm run build` | ✅ (chunk size warnings only) |
| API gateway `npx tsc --noEmit` | ✅ clean |

---

## Phase 1 Status

All 22 items are now complete:
- 1.1 ADS-B: 6/6 ✅
- 1.2 Noise: 6/6 ✅
- 1.3 Ground Vehicles: 6/6 ✅
- 1.4 Runway Sequencing: 4/4 ✅
