# Phase 0 — Developer & Operator Tooling — Implementation Plan

## Status: IN PROGRESS

## Analysis of existing state

### Already implemented (backend):

- **Weather source modes**: `simulated`, `historical`, `live` all implemented in weather-service
  (`kafka/consumer.py` L66). Currently driven by `WEATHER_SOURCE` env var — NOT runtime switchable.
- **Weather lock**: Settings already have `weather_lock` field (lock to CAVOK/VMC/IMC/LIFR).
- **Settings page**: Full settings UI with demand, weather, incidents, security, baggage sections.
- **Incident injection**: `POST /sim/inject` and `POST /incidents/inject` endpoints exist.

### Needs to be built:

- Runtime weather source switching via API (not just env var)
- Individual weather parameter overrides (lock visibility, wind, ceiling independently)
- Weather history chart (12h sparkline)
- Simulation state snapshot/restore
- Debug panel with entity injection forms, entity inspector, Cypher console, Kafka inspector
- All corresponding UI in the dashboard

---

## Implementation order (dependency-driven)

### Phase A — Backend APIs

#### A1. Weather source runtime switching (P0-2-1, P0-2-2, P0-2-3)

- Add `weather_source` field to `SimSettings` (values: "simulated", "historical", "live")
- Add `weather_history_file` and `weather_live_icao` fields to `SimSettings`
- When settings change, emit `sim.settings` event (or new `weather.control` topic)
- Weather-service subscribes to settings changes, switches source at runtime
- Add `POST /api/v1/weather/source` endpoint to weather-service for direct source switch
- Expose in settings UI

#### A2. Weather parameter overrides (P0-2-4)

- Add `weather_overrides` dict to `SimSettings` with nullable fields:
  `visibility_m`, `wind_speed_kt`, `ceiling_ft`, `wind_gust_kt`, `temperature_c`
- Weather-service applies overrides on top of whatever source is active
- Any override that is non-null "locks" that parameter
- Expose as a weather override panel in the dashboard

#### A3. Snapshot/restore (P0-3-1, P0-3-2)

- `POST /api/v1/sim/snapshot`:
  - Pause simulation
  - Dump full Neo4j graph to JSON (all nodes + relationships)
  - Record sim_time, day_number, tick_count, settings
  - Save to `snapshots/{name}_{timestamp}.json`
  - Resume if was running
- `POST /api/v1/sim/restore`:
  - Pause simulation
  - Wipe Neo4j
  - Restore all nodes/relationships from snapshot
  - Reset sim clock to snapshot state
  - Notify all services to rebuild in-memory caches (emit SnapshotRestored event)
  - Resume
- `GET /api/v1/sim/snapshots`: List available snapshots

#### A4. Entity injection endpoints (P0-1-1, P0-1-2, P0-1-3)

- `POST /api/v1/debug/inject/passengers` on sim-orchestrator:
  - Body: flight_id, count, status, generate names/PNRs
  - Write to Neo4j + emit PassengerStatusChanged events
- `POST /api/v1/debug/inject/flight` on sim-orchestrator:
  - Body: direction, origin/dest, aircraft_type, gate, departure_time
  - Full downstream seeding (passengers, baggage, turnaround)
- `POST /api/v1/debug/inject/baggage` on sim-orchestrator:
  - Body: flight_id, count, zone_status
  - Write to Neo4j + emit BaggageStatusChanged events

#### A5. Cypher console (P0-1-5)

- `POST /api/v1/debug/cypher` on sim-orchestrator:
  - Body: { query: "MATCH ..." } — read-only Cypher only
  - Validate query starts with MATCH/RETURN/CALL (no CREATE/DELETE/SET/MERGE/REMOVE)
  - Execute against Neo4j, return results as JSON table

#### A6. Scenario snapshot integration (P0-3-4)

- Add `start_from_snapshot` field to ScenarioDefinition model
- When present, restore from snapshot before running scenario events

### Phase B — API Gateway

- Add proxy routes for new debug endpoints
- Add proxy route for weather source control

### Phase C — Dashboard UI

#### C1. Debug panel toggle (P0-1-1 through P0-1-6)

- New `/debug` route or Ctrl+D toggle overlay
- Contains: passenger/flight/baggage injection forms, entity inspector,
  Cypher console, Kafka event inspector tabs

#### C2. Weather source switcher in settings (P0-2-1)

- Add weather source selector to Settings Weather section
- File picker for historical CSV
- ICAO input for live mode

#### C3. Weather history chart (P0-2-5)

- 12h sparkline on Ground Ops dashboard
- Category transitions color-coded (green=CAVOK, blue=VMC, amber=IMC, red=LIFR)

#### C4. Snapshot UI (P0-3-3)

- Snapshot browser in Settings page
- Create/restore/delete snapshots
- Display sim_time, day, active incidents per snapshot

#### C5. Kafka event inspector (P0-1-6)

- Live feed using existing WebSocket
- Per-topic filter, JSON syntax highlighting
- Display raw Kafka envelope

---

## Risks & mitigations

1. **Snapshot file size**: Full Neo4j dump can be large (10K+ nodes). Mitigate: compress with gzip.
2. **Restore consistency**: Must emit SnapshotRestored so all services rebuild caches.
3. **Read-only Cypher validation**: Must be strict — no mutation queries allowed.
4. **Weather source hot-switch**: Must handle mid-FSM transition gracefully.
