# Sprint 31 — Solidify the Architecture: Fixes & Stability

**Date:** 2025-01-XX  
**Scope:** 9 bug fixes + 1 UX improvement across weather-service, flight-service, sim-orchestrator, analysis-service, and the React dashboard.

---

## Issues Fixed

### 1. Weather source loading state after switch (DataSources page)
**Problem:** After switching weather source on the DataSources page, the WeatherStrip in the header stayed empty until the user visited the GroundOps page.  
**Root cause:** WeatherStrip only received data from WebSocket events or GroundOps page polling — no bootstrap fetch on mount.  
**Fix:** Added `useEffect` bootstrap in `WeatherStrip.tsx` that fetches `weatherApi.current()` on mount if the store is null. Also updated `DataSourcesPage` switch mutation to proactively push fetched weather data into the Zustand store.

### 2. Live = Historical = Simulated weather values often equal
**Problem:** The comparison panel showed identical values across all three weather sources.  
**Root cause:** The old comparison used a destructive approach — temporarily switching the backend source, waiting 2 seconds, reading the cached value, then switching back. Since weather only re-evaluates on sim-hour boundaries, the cached value was still from the previous source.  
**Fix:** Created a new `GET /weather/compare` endpoint that independently reads from all three sources (simulated state, historical CSV, live ADDS API) without changing the active source. The frontend now calls this endpoint directly.

### 3. Improved data source comparison visuals
**Problem:** The comparison was a basic table with a destructive switch-and-read mechanism.  
**Fix:** Rewrote `WeatherComparisonPanel` to use the new non-destructive `/weather/compare` endpoint. Added:
- Auto-refreshing comparison table (every 15s)
- Toggle between table and chart views
- SVG mini-chart showing field value history across sources over time (last 60 data points)
- Color-coded source indicators and delta highlighting for differing values

### 4. Topology fixtures don't appear on world map
**Problem:** GeoJSON files (runways, taxiways, terminals, gates, apron) rendered at wrong coordinates (~38°N, -27°W instead of KART at 49.6°N, 6.2°E).  
**Root cause:** The original GeoJSON files were committed with incorrect coordinates. Even the git history contained wrong values (originally ~60°N, 39°E).  
**Fix:** Created `scripts/helper_transform_geojson.py` to regenerate all 5 GeoJSON files from scratch using proper meter-to-degree conversion at KART latitude. Airport layout: 2 parallel runways (3500m, heading 090°), 3 terminals (A/B/C), 42 gates, 3 taxiways, 1 apron.

### 5. OpenSky API 429 rate limiting errors
**Problem:** `flight-service` ADS-B poller hit 429 Too Many Requests from OpenSky Network.  
**Root cause:** Default poll interval was 10 seconds — too aggressive for the free tier.  
**Fix:** Changed default to 30s (configurable via `ADSB_POLL_INTERVAL_SEC` env var). Added exponential backoff on 429 responses: `min(60 × 2^(errors-1), 600s)` with automatic reset on success.

### 6. VITE_API_BASE_URL missing from .env
**Problem:** No documentation or template for the required Vite environment variables.  
**Fix:** Added commented-out `VITE_API_BASE_URL` and `VITE_WS_URL` entries to `dashboards/art-dashboard/.env` with explanatory comments. The defaults in code already work for local development.

### 7. Autonomous operations mode buttons do nothing visible
**Problem:** Clicking "RL Agent", "Rule-Based", or "Threshold" autonomous mode buttons appeared to have no effect.  
**Root cause:** The PATCH request succeeded silently. Autonomous evaluation requires active bottlenecks AND sufficient sim-time to have elapsed — users saw no feedback explaining this.  
**Fix:** Added contextual feedback banner to `MLTrainingPage.tsx` AutonomousPanel. Each mode now shows a specific message explaining what it does and when effects will be visible. Feedback auto-clears after 8 seconds.

### 8. RL training fails due to missing tqdm/rich dependencies
**Problem:** `progress_bar=True` in `train_rl.py` requires `tqdm` and `rich`, which weren't in requirements.  
**Fix:** Added `tqdm>=4.66.0` and `rich>=13.7.0` to `services/analysis-service/requirements.txt`.

### 9. Some flights leave with 0 baggages
**Problem:** Cargo flights were getting passengers but 0 bags, creating unrealistic data.  
**Root cause:** `seeder.py` generated passengers for ALL departure/arrival flights, but `baggage.py` had `BAGS_LAMBDA_BY_TYPE["cargo"] = 0.0`, correctly assigning zero bags to cargo flights. The mismatch was that cargo flights shouldn't have passengers at all.  
**Fix:** Filtered cargo flights out of passenger generation in `seeder.py`.

---

## Patterns & Takeaways

1. **Non-destructive comparison endpoints** — Never implement a "switch, read, switch back" pattern for comparing data sources. Create a dedicated read-only endpoint that samples all sources independently.

2. **Bootstrap data on mount** — Components that depend on WebSocket events or page-specific polling should always have a REST fetch fallback on mount to avoid empty-state scenarios.

3. **Exponential backoff is essential for external APIs** — Even with reasonable poll intervals, 429s will happen. Backoff with configurable base/max and automatic recovery is the minimum.

4. **User feedback for async/deferred effects** — When a UI action triggers a background process that won't have visible results immediately, always show contextual feedback explaining what will happen and when.

5. **GeoJSON coordinate validation** — Always verify GeoJSON renders at the expected location before committing. A visual sanity check on a map would have caught the coordinate bug immediately.
