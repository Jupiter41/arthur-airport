# Sprint 33 — Map Differentiation, Comparison Modal, ADS-B Fallback

**Date:** 2025-07-17
**Scope:** WorldMapPage, DataSourcesPage, flight-service ADS-B

---

## Changes

### 1. Departure/Arrival Visual Differentiation on World Map

**Problem:** All aircraft on the map used the same cyan icon regardless of direction, making it impossible to distinguish departures from arrivals at a glance.

**Solution:**

- Added `direction` property to `PositionFeature` and `RouteFeature` interfaces
- Created a green (`#34d399`) arrival plane icon alongside the existing cyan (`#22d3ee`) departure icon
- Mapbox `icon-image` expression now uses a 3-way case: selected → yellow, arrival → green, departure → cyan
- Route line colors also differentiate: arrivals green, departures cyan, selected yellow
- Leaflet fallback updated with same logic
- Stats panel now shows departure/arrival counts with color-coded dots

**Files:** `WorldMapPage.tsx`

### 2. Weather Comparison Chart Modal

**Problem:** The inline chart toggle replaced the table view, and the chart was too small (h-32) for meaningful comparison.

**Solution:**

- Table now always visible in the card (removed `showChart` toggle)
- "📈 Chart" button opens a full-screen modal via `createPortal`
- `ComparisonModal` component with: h-64 chart, field selector, source legend with active indicator, full comparison table with Δ column
- Modal closes on backdrop click or ✕ button

**Files:** `DataSourcesPage.tsx`

### 3. ADS-B Synthetic Fallback

**Problem:** OpenSky Network free API aggressively rate-limits (429 on every request). After 5 consecutive failures, the cache was permanently empty — ADS-B overlay showed 0 aircraft forever.

**Root cause:** No authentication, no fallback, exponential backoff grew but never recovered.

**Solution:**

- Added `OPENSKY_USERNAME`/`OPENSKY_PASSWORD` env var support with httpx basic auth
- After `MAX_CONSECUTIVE_ERRORS` (5) failures, switches to `_use_synthetic = True`
- Polling loop in synthetic mode calls `generate_synthetic_adsb()` which queries Neo4j for airborne flights and computes interpolated positions
- New `services/adsb_synthetic.py` module: queries flights with status `departed`/`airborne`/`approach`, estimates position along great-circle route, filters to within 400km radius
- GeoJSON metadata now includes `"source": "synthetic" | "opensky"` so the frontend can indicate data origin
- Docker-compose passes optional OpenSky credentials from host environment

**Files:** `services/adsb.py`, `services/adsb_synthetic.py`, `routers/flights.py`, `docker-compose.yml`

---

## Lessons Learned

1. **Mapbox expressions with multiple conditions** must use nested `["case", cond1, val1, cond2, val2, default]` — not multiple case blocks. The "selected" condition should always come first so it takes priority.

2. **Image loading chains in Mapbox** — when adding a third icon variant, the `onload` callback chain deepens. Each image must be loaded before `addLayer` can reference it by name. Consider refactoring to `Promise.all` for readability in the future.

3. **OpenSky Network rate limits** are very aggressive for anonymous users. Even 30s intervals trigger 429. Authenticated users get ~1 req/5s. Always design external API integrations with a fallback path.

4. **React `createPortal`** is ideal for modals in deeply nested component trees — avoids z-index wars and overflow clipping from parent containers.
