# Sprint 34 – Freemium Datasets: BTS Passengers & ADS-B Map Fix

**Date:** 2025-01-09  
**Scope:** 3 features — ADS-B map display fix, QUICKSTART_WHATIF.md, BTS passenger data support

---

## 1. ADS-B Aircraft Not Rendering on WorldMap

**Symptom:** Toggle ADS-B on, API returns ~2000 features, but no orange aircraft appear on the map.

**Root causes:**

1. **Race condition** — The data-update `useEffect` runs before the Mapbox `adsb-aircraft` source/layer exist (created inside a nested `image.onload` callback). `map.getSource("adsb-aircraft")` returns `undefined` silently.
2. **Non-standard GeoJSON metadata** — The flight-service wraps the FeatureCollection with a top-level `metadata` field. Mapbox `setData()` silently ignores data that doesn't strictly conform.

**Fix:**

- Added a `mapLoaded` state flag set to `true` inside the image-onload callback, added to the data-update effect's dependency array so it re-runs once layers exist.
- Added a `useRef` for `adsbData` so the onload closure can read the latest data immediately when creating the source.
- Strip `metadata` when calling `setData()`: pass `{ type: "FeatureCollection", features: adsbData.features }`.

**Lesson:** When Mapbox sources are created inside async callbacks (image loading), effects that update those sources must gate on a flag that proves the source exists. Silent `undefined?.setData?.()` calls are invisible bugs.

---

## 2. BTS Historical Passenger Data — Route Ordering Bug

**Symptom:** `GET /api/v1/passengers/source` returns `{"detail": "Passenger not found"}`.

**Root cause:** FastAPI matches routes in declaration order. The new `/passengers/source` endpoint was declared **after** `/passengers/{passenger_id}`, so `"source"` was captured as a `passenger_id` path parameter.

**Fix:** Moved all `/passengers/source` and `/passengers/bts/*` endpoints before the `/{passenger_id}` catch-all route.

**Lesson:** In FastAPI, always declare static path segments before parameterized ones on the same prefix. This is a classic pitfall.

---

## 3. BTS Adapter Design

The `BTSPassengerSource` class in `services/passenger-service/services/bts_adapter.py`:

- Loads BTS T-100 CSV data (or generates sample data for demo mode)
- Disaggregates monthly totals into hourly estimates using a diurnal weight curve
- Provides `get_flow_at(sim_time)` returning zone-distributed passenger counts
- Runtime-switchable via `POST /api/v1/passengers/source`

Gateway `dataSources.ts` now queries the passenger-service `/source` endpoint to report the real active source instead of hardcoding `"simulation"`.

Dashboard `DataSourcesPage` enables the switch button for both weather and passengers.

---

## 4. QUICKSTART_WHATIF.md

New root-level guide documenting:
- Part 1: ML Training page — RL model training, autonomous mode, LLM configuration
- Part 2: Incidents page — Analysis & AI Tools tabs, anomaly detection, NLP query, what-if scenarios

---

## Tests Run

| Check | Result |
|-------|--------|
| `ruff check` on all modified Python files | ✅ All passed |
| `npm run build` dashboard | ✅ Built successfully |
| `npx tsc --noEmit` api-gateway | ✅ Clean |
| `GET /api/v1/passengers/source` | ✅ `{"source":"simulation","available":["simulation","bts_historical"]}` |
| `POST /api/v1/passengers/source` switch to BTS | ✅ 276 route-months loaded |
| `GET /api/v1/passengers/bts/flow` | ✅ Returns flow with route breakdown |
| `GET /api/v1/data-sources` aggregate | ✅ Passengers show correct source & available list |
| ADS-B count in data-sources | ✅ 1949 aircraft |
