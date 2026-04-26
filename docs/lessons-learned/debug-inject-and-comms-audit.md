# Lessons Learned — Debug Inject, Communications Audit & Dashboard Fixes

**Date:** 2026-04-25

## Issues Found & Fixed

### 1. Debug-injected flights not appearing in dashboard

**Root causes (3 layered bugs):**

1. **Wrong Neo4j property names** in `sim-orchestrator/routers/debug.py`: used `origin`/`destination` instead of `origin_iata`/`destination_iata`, so flight-service queries (which filter on `origin_iata`) never returned them.

2. **Missing Kafka event**: debug inject only emitted `FlightScheduleSeeded` to `flights.schedule`, which flight-service merely logs. No `FlightStatusChanged` event was emitted to `flights.events`, so the gateway WebSocket never received anything.

3. **WebSocket handler silently dropped new flights**: `useWebSocket.ts` `FlightStatusChanged` handler checked `store.flights[flight_id]` and returned early if the flight wasn't already in the store — new flights were ignored. Fixed by invalidating React Query's `["flights"]` cache when an unknown flight arrives, triggering a re-fetch.

**Lesson:** When adding debug/injection endpoints, ensure they produce the exact same data schema and event flow as the normal seed path. Test the full pipeline (DB → API → Kafka → WebSocket → UI), not just the DB write.

### 2. Gateway proxy POST timeout (PowerShell-specific)

**Issue:** POST requests to proxied endpoints (e.g., `/api/v1/debug/inject/flight`) timed out when using PowerShell `Invoke-RestMethod` but worked with `curl.exe` and from inside the container.

**Fix:** Replaced manual `proxyReq.write(bodyData)` in `proxy.ts` with the official `fixRequestBody` helper from `http-proxy-middleware` v3. The manual approach missed edge cases around stream piping when `express.json()` had already consumed the body.

**Lesson:** Always use `fixRequestBody` from `http-proxy-middleware` when `express.json()` or other body parsers run before the proxy middleware. The manual `write()` pattern is fragile across different HTTP clients.

### 3. Baggage conveyor-status returning 404

**Issue:** `GET /api/v1/baggage/conveyor-status` returned `{"detail":"Baggage not found"}` because FastAPI matched `conveyor-status` against the `/{baggage_id}` path parameter route defined earlier.

**Fix:** Reordered routes in `baggage-service/routers/baggage.py` to put `/baggage/conveyor-status` and `/baggage/tag/{tag}` before `/baggage/{baggage_id}`.

**Lesson:** In FastAPI, static path segments must be defined before parameterized routes at the same level. Always define `/resource/action` routes before `/resource/{id}`.

### 4. Mapbox map not rendering (3D map)

**Issue:** The WorldMap page requires `VITE_MAPBOX_TOKEN` baked in at Vite build time. Docker layer caching caused the token to be missing from the built JS.

**Fix:** Forced `docker compose build --no-cache dashboard` to ensure the `ARG VITE_MAPBOX_TOKEN` was properly injected during the Vite build.

**Lesson:** Vite `import.meta.env` variables are compile-time only. When changing build args in `docker-compose.yml`, use `--no-cache` to ensure the build stage re-runs.

### 5. Vehicle position visualization

**Enhancement:** Added a `VehiclePositionTable` component to the GroundOps page showing each vehicle's type, status, assigned gate, current task, and grid coordinates. Vehicles are sorted by activity (at_gate → dispatched → returning → available).

## Files Modified

| File | Change |
|------|--------|
| `services/sim-orchestrator/routers/debug.py` | Fixed property names, added missing fields, added Kafka event emission |
| `services/api-gateway/src/proxy.ts` | Replaced manual body rewrite with `fixRequestBody` |
| `services/baggage-service/routers/baggage.py` | Reordered routes (static before parameterized) |
| `dashboards/art-dashboard/src/queryClient.ts` | New: shared QueryClient instance |
| `dashboards/art-dashboard/src/App.tsx` | Import shared queryClient |
| `dashboards/art-dashboard/src/hooks/useWebSocket.ts` | Invalidate flights cache on unknown flight events |
| `dashboards/art-dashboard/src/pages/GroundOps/GroundOpsPage.tsx` | Added VehiclePositionTable component |
