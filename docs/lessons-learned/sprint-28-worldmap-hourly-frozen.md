# Sprint 28 — World Map Zoom, Hourly Distribution, Frozen Security Display

**Date:** 2026-04-26

## Issues Fixed

### 1. World map: no zoom when searching for a plane

**File:** `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`

**Root cause:** The `selectPlane()` function only called `setSelectedFlightId()` to highlight the plane visually, but never flew the map camera to the plane's computed position. Users had to manually pan/zoom to find the selected aircraft.

**Fix:** After setting the selected flight ID, compute the aircraft's current position via `computeAircraftPosition()` and call `map.flyTo()` with zoom level 6. Handles both Mapbox (object-style `flyTo`) and Leaflet (positional-args `flyTo`) APIs.

---

### 2. Hourly distribution bars all at 0 height

**File:** `dashboards/art-dashboard/src/pages/Settings/SettingsPage.tsx`

**Root cause:** The `HourlyWeightsEditor` used `flex items-end` on the outer container, which made each child column use `flex-col items-center`. The bar `<label>` element had a percentage-based `height` style (`height: N%`), but CSS percentage heights only resolve when the parent has an explicit height. The `flex-col` child divs did not have a definite height (they sized to content), so the percentage resolved to 0.

**Fix:** Changed the outer container from `flex items-end gap-[2px] h-24` to `flex gap-[2px] h-24`, and changed each child column from `flex-1 flex flex-col items-center group` to `flex-1 flex flex-col justify-end items-center`. This ensures:
- The parent `h-24` provides a definite height
- Each column stretches to fill the full height (`flex-1`)
- `justify-end` pushes the bar label to the bottom (same visual as `items-end` on parent)
- The bar's percentage height now resolves correctly against the column's full height

---

### 3. ~999 min waiting time in security during breach

**Files:**
- `services/passenger-service/services/security.py`
- `services/passenger-service/routers/passengers.py`
- `dashboards/art-dashboard/src/types.ts`
- `dashboards/art-dashboard/src/pages/PassengerFlow/PassengerFlowPage.tsx`

**Root cause:** When a security breach freezes a terminal's checkpoint, `SecurityCheckpoint.wait_minutes()` returns 999.0 (sentinel value for "infinite wait"). The dashboard displayed this literally as "~999 min wait", which is confusing and misleading.

**Fix:**
1. Added `frozen` boolean to `SecuritySystem.get_summary()` output
2. Propagated `frozen` through the `/flow/summary` REST response
3. Added `frozen?: boolean` to the `PassengerFlowSummary` TypeScript type
4. Updated the KPI bar to show "🔒 FROZEN" with a pulsing animation instead of "~999 min wait"
5. Updated the security queue chart to display 0 wait (not 999) for frozen terminals
6. Shows "Security breach — lanes closed" instead of lane count when frozen

## Validation

- **Dashboard build:** `npm run build` succeeds with no TypeScript errors
- **Python lint:** `ruff check` passes on all modified files (pre-existing errors in test files only)
- **Unit tests:** 20/20 security tests pass
- **API verification:** `/flow/summary` now returns `frozen: false` for each terminal
- **Docker:** passenger-service and dashboard containers rebuilt and healthy
