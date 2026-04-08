# Sprint 19: Neo4j Property Warnings, UI Polish & Performance

**Date:** 2026-04-08
**Scope:** Neo4j data quality, flight board UI, world map features, airport configurability, performance optimization

---

## Issues Fixed

### 1. Neo4j property warnings — `actual_time`, `gate_id`, `arrival_estimated_time` (Critical)

**Root cause:** Flight nodes were created without `actual_time`, `gate_id`, and `arrival_estimated_time` properties. Cypher queries that project these fields trigger `01N52` warnings ("property does not exist") on every poll cycle, flooding logs with ~8 warnings per second.

**Fix (creation):** Initialised all three properties at Flight node creation time with empty strings in `schedule.py` and `debug.py` (sim-orchestrator).

**Fix (gate sync):** In `flight-service/db/neo4j.py`, the `assign_flight_to_gate()` function now also sets `f.gate_id = $gate_id` when creating the `ASSIGNED_TO` relationship (previously only `release_gate()` updated this field).

**Fix (migration):** Added `migrate_flight_properties()` in `flight-service/db/neo4j.py` that runs on startup and backfills any existing Flight nodes missing these properties. Called from the lifespan startup after `create_constraints_and_indexes()`.

**Files:**

- `services/sim-orchestrator/services/schedule.py` — Flight CREATE Cypher
- `services/sim-orchestrator/routers/debug.py` — Debug flight inject Cypher
- `services/flight-service/db/neo4j.py` — `assign_flight_to_gate()`, `migrate_flight_properties()`
- `services/flight-service/main.py` — Startup lifespan calls migration

**Lesson:** Neo4j doesn't store null properties — they simply don't exist on the node. Cypher projections (`.property_name`) on missing properties produce driver-level warnings. Always initialise all projected properties at node creation time. Add migration backfills for running systems.

---

### 2. Flight board filter UI — toggle instead of always-visible (UX)

**Root cause:** The filter row was always visible beneath each FIDS panel header, taking up vertical space even when no filters were active. User feedback: "The filters buttons are weird, it should be an icon besides the sorting one."

**Fix:** Added a filter toggle button (funnel SVG icon) next to the existing sort controls in each panel header. The filter row is now collapsible — hidden by default, shown on click. Active filters are indicated by a colored badge on the icon. Clear button moved to the header bar for accessibility when filters are hidden.

**File:** `dashboards/art-dashboard/src/pages/FlightBoard/FlightBoardPage.tsx`

---

### 3. Hub Network styling — visibility and interaction (UX)

**Root cause:** The Hub Network overlay in WorldMapPage only showed a sidebar panel with airport cards. No actual arcs or airport markers were rendered on the Mapbox map. The panel used purple/pink colors that were hard to read against a dark map.

**Fix:**

- Added `network-arcs` and `network-airports` GeoJSON sources to the Mapbox map
- Added 3 layers: arc lines (colored by status: green/amber/red), airport circles (colored by disruption level), airport labels
- Made network airport circles clickable — clicking flies the map to that airport
- Updated `NetworkPanel` to accept an `onFlyToAirport` callback, making sidebar airport cards clickable too
- Changed colour scheme from purple to emerald/teal throughout

**File:** `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`

---

### 4. World map timeline cursor (Feature)

**Root cause:** No way to view historical flight positions on the world map. Users couldn't scrub back in time to see where flights were at a previous moment.

**Fix:**

- Added `timelineActive` and `timelineOffset` state (±360 minutes range)
- Added `effectiveSimTime` computed from `simTime + offset`
- Replaced raw `simTime` with `effectiveSimTime` for position calculations and track comparisons
- Added timeline slider UI between the map and footer with amber accent styling
- Added real-vs-simulated flight legend when ADS-B is enabled

**File:** `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`

---

### 5. Airport configurability — hourly weights (Feature)

**Root cause:** The `sample_departure_slots()` function in `schedule.py` had hardcoded hourly traffic weights (hours 5–22), making it impossible to configure flight distribution through the settings UI.

**Fix:**

- Added `hourly_weights` map to `config/airport.yaml` under `simulation:`
- Added `hourly_weights: dict[int, int]` to `AirportSimulation` Pydantic model in `airport_config.py`
- Added `hourly_weights` field to `SimSettings` in `settings.py`
- Updated `sample_departure_slots()` to read weights from `SimSettings` instead of hardcoded dict
- Added `HourlyWeightsEditor` interactive bar chart component in `SettingsPage.tsx` (click to increment, mouse wheel to adjust, +/- buttons per hour)

**Files:**

- `config/airport.yaml`
- `services/sim-orchestrator/services/airport_config.py`
- `services/sim-orchestrator/services/settings.py`
- `services/sim-orchestrator/services/schedule.py`
- `dashboards/art-dashboard/src/pages/Settings/SettingsPage.tsx`

---

### 6. Performance optimisations (Performance)

**Root cause:** General sluggishness reported — slow Neo4j queries, excessive React re-renders, aggressive polling, redundant HTTP client creation, and frequent WebSocket store updates.

**Fixes applied:**

| Optimisation                                                         | Impact                             | File                              |
| -------------------------------------------------------------------- | ---------------------------------- | --------------------------------- |
| Added Neo4j indexes on `direction`, `airline_code`, `scheduled_time` | Faster filtered queries            | `flight-service/db/neo4j.py`      |
| Wrapped `FlightRow` with `React.memo`                                | Skip re-renders for unchanged rows | `FlightBoardPage.tsx`             |
| Increased `refetchInterval` 10s→15s, `staleTime` 5s→10s              | 33% fewer API calls                | `App.tsx`                         |
| Reuse `httpx.AsyncClient` for ADS-B polling                          | Eliminate per-request TCP setup    | `flight-service/services/adsb.py` |
| Throttle `markWsMessage()` to 1 update/sec                           | Fewer Zustand store triggers       | `connectionStore.ts`              |

---

## Tests & CI

| Check                                                            | Result                                           |
| ---------------------------------------------------------------- | ------------------------------------------------ |
| `ruff check services/flight-service/ services/sim-orchestrator/` | All checks passed                                |
| `npx tsc --noEmit` (dashboard)                                   | Passed (after fixing network click handler type) |
| `npm run build` (dashboard)                                      | Success — dist/ output generated                 |
| `docker compose up --build` (all 16 services)                    | All healthy                                      |
| Neo4j property warnings post-migration                           | 0 warnings in 2-minute window                    |

---

## TypeScript type fix

The network airports click handler initially used `mapboxgl.MapMouseEvent` which caused a TS2345 error because the Mapbox event type system is complex. Fixed by simplifying the handler parameter type to `{ lngLat?: { lng: number; lat: number } }`.

---

## Files modified (summary)

| File                                                                 | Change type       |
| -------------------------------------------------------------------- | ----------------- |
| `services/sim-orchestrator/services/schedule.py`                     | Fix + Feature     |
| `services/sim-orchestrator/routers/debug.py`                         | Fix               |
| `services/sim-orchestrator/services/settings.py`                     | Feature           |
| `services/sim-orchestrator/services/airport_config.py`               | Feature           |
| `config/airport.yaml`                                                | Feature           |
| `services/flight-service/db/neo4j.py`                                | Fix + Performance |
| `services/flight-service/main.py`                                    | Fix               |
| `services/flight-service/services/adsb.py`                           | Performance       |
| `dashboards/art-dashboard/src/pages/FlightBoard/FlightBoardPage.tsx` | UX + Performance  |
| `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`       | Feature + UX      |
| `dashboards/art-dashboard/src/pages/Settings/SettingsPage.tsx`       | Feature           |
| `dashboards/art-dashboard/src/stores/connectionStore.ts`             | Performance       |
| `dashboards/art-dashboard/src/App.tsx`                               | Performance       |
