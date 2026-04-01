# Sprint 14: Flight Display, Incidents & Infra Hardening

**Status:** ✅ **COMPLETE**  
**Date:** 2025-07-25

---

## 1. Summary

Batch of UX polish, backend fixes, and infrastructure improvements across the dashboard, incident system, flight pipeline, and Docker orchestration.

### Changes Delivered

| #   | Area          | Change                                                                                                                                                |
| --- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Flight Board  | Removed strikethrough on non-delayed flights; added text-color coding for airborne flights (green = on-time, amber = slight delay, red = heavy delay) |
| 2   | Flight Board  | Added arrival tracking: `flight_duration_minutes` in schedule, `arrived` state in state machine, `arrival_estimated_time` computed on departure       |
| 3   | Incident Feed | Fixed 1-second disappearance bug — comma-separated status param was matched literally instead of as `IN` list in Neo4j                                |
| 4   | Cascade Tree  | Stored cascade tree in JSON report; added "View Cascade" button + modal for resolved incidents; fixed empty tree by fetching detail on selection      |
| 5   | Flight Config | Configurable flight type repartition (cargo / charter weights) in `airport.yaml`                                                                      |
| 6   | Infra (Kafka) | Added Zookeeper healthcheck; Kafka now waits for healthy Zookeeper before starting                                                                    |
| 7   | Dashboard Nav | Consolidated 9 tabs into 5 (Flights, Terminal ▾, Incidents, Ops ▾, Simulation ▾) using dropdown groups                                                |

---

## 2. Root Cause Analysis

### 2.1 Incident Feed Disappearing After 1 Second

**Symptom:** Active incidents appeared briefly then vanished.  
**Root cause:** `get_incidents(status="active,contained")` used `WHERE i.status = $status` in Cypher — a single string `"active,contained"` never matches any node.  
**Fix:** Split the comma-separated value into a list and use `WHERE i.status IN $statuses`. Same fix applied to `count_incidents()`.

### 2.2 Cascade Tree Always Empty

**Symptom:** Clicking "View Cascade" showed an empty tree despite `cascade_depth > 0`.  
**Root cause:** The list endpoint (`GET /incidents`) returns `IncidentSummary` with `cascade_depth` but no `cascade_tree`. The WebSocket `IncidentCreated` event also omits the tree. Only the detail endpoint (`GET /incidents/:id`) builds the tree from Neo4j `SPAWNED` relationships.  
**Fix:** Added a `useEffect` that fetches the full incident detail via `incidentsApi.get(id)` when an incident is selected or its cascade is viewed, then upserts the result (with `cascade_tree`) into the store.

### 2.3 Kafka Intermittent Startup Failure

**Symptom:** `docker compose up` occasionally failed with Kafka healthcheck timeout, but succeeded on retry.  
**Root cause:** Kafka's `depends_on: zookeeper` only waited for the container to start, not for Zookeeper to be ready. Under load, Zookeeper could still be initializing when Kafka tried to connect.  
**Fix:** Added a Zookeeper healthcheck (`echo ruok | nc localhost 2181 | grep imok`) and changed Kafka's dependency to `condition: service_healthy`. Increased Kafka healthcheck retries to 15 with `start_period: 30s`.

---

## 3. Key Design Decisions

1. **Text color over borders for airborne status** — Initial implementation used green/amber/red `border-left` on flight rows. This was visually cluttered; switched to coloring only the time text.

2. **Fetch-on-select for cascade tree** — Rather than adding `cascade_tree` to the list endpoint (expensive: recursive Cypher per incident), we fetch on demand when the user clicks. Cached in the store so repeat views are instant.

3. **Dropdown nav groups** — Grouped related pages (Terminal: Passengers + Baggage; Ops: Ground Ops + World; Simulation: History + Scenarios + Settings) behind dropdown menus. All routes preserved; no pages removed.

4. **Flight arrival as state machine transition** — `arrived` is a terminal state after `airborne`, triggered by `sim_time >= arrival_estimated_time`. Duration comes from schedule generation using real great-circle distance.

---

## 4. Files Modified

### Backend

- `services/incident-service/db/neo4j.py` — comma-separated status → `IN` list
- `services/incident-service/services/reports.py` — cascade_tree in JSON report
- `services/flight-service/services/state_machine.py` — `arrived` status
- `services/flight-service/db/neo4j.py` — new fields in flight queries
- `services/flight-service/kafka/consumer.py` — compute `arrival_estimated_time` on departure
- `services/flight-service/models/domain.py` — new domain fields
- `services/sim-orchestrator/services/schedule.py` — `flight_duration_minutes`, flight type classification
- `services/sim-orchestrator/services/airport_config.py` — `AirportFlightTypes` model

### Frontend

- `dashboards/art-dashboard/src/pages/FlightBoard/FlightBoardPage.tsx` — delay display, arrival info, airborne text colors
- `dashboards/art-dashboard/src/pages/IncidentConsole/IncidentConsolePage.tsx` — cascade modal, JSON report, detail fetch on select
- `dashboards/art-dashboard/src/components/HeaderBar.tsx` — dropdown nav groups (9 → 5 items)
- `dashboards/art-dashboard/src/types.ts` — `Flight` type with arrival fields

### Infrastructure

- `docker-compose.yml` — Zookeeper healthcheck, Kafka dependency ordering
- `config/airport.yaml` — `flight_types` section

---

## 5. Lessons Learned

- **Always test Cypher with the exact parameter shape.** The `status = "active,contained"` bug was invisible in unit tests because fixtures used single-status queries.
- **List vs. detail endpoints should be clearly documented.** The cascade tree was only available on the detail endpoint — this wasn't obvious from the frontend code that only consumed the list.
- **Docker healthchecks should cover the full dependency chain.** A `depends_on` without `condition: service_healthy` is just a container start order, not a readiness guarantee.
- **Visual polish matters.** The green border was technically correct but immediately flagged as ugly. Subtler text-color cues are more effective for status at a glance.
