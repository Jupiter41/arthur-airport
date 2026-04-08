# Phase 3 — Traffic Realism, Flight Board Filters, Neo4j Fix & Network Simulation

## Scope

This plan covers four distinct work items requested together:

1. **Fix `arrival_estimated_time` Neo4j warning** — Property not initialized on flight creation
2. **Improve flight traffic realism** — Replace pure bimodal distribution with realistic airport traffic curve
3. **Add column filters to flight board** — Per-column filters (airline, destination, status, gate) with new-flights-first ordering
4. **Implement Phase 3 (multi-airport network simulation)** — Items P3-1 through P3-6 from ROADMAP.md

---

## 1. Fix `arrival_estimated_time` Neo4j Warning

**Root cause:** The `_persist_flights` Cypher in `services/sim-orchestrator/services/schedule.py` creates Flight nodes without the `arrival_estimated_time` property. When `services/flight-service/db/neo4j.py` queries `f.arrival_estimated_time`, Neo4j emits a property-not-found warning.

**Fix:** Add `arrival_estimated_time: null` to the CREATE Cypher in `_persist_flights`.

**Files:**

- `services/sim-orchestrator/services/schedule.py` — add property to CREATE

---

## 2. Improve Flight Traffic Realism

**Problem:** Current `sample_departure_slots()` uses a simple bimodal Normal(7.5, 1.5) + Normal(17.5, 1.5), clipped to [5, 23]. This produces:

- No flights before 5am (real airports have first departures at ~6am)
- Two sharp peaks with dead valleys mid-day
- No steady base flow throughout the day

**Solution:** Replace with a realistic airport traffic curve based on actual airport hourly distributions. Real mid-size hub airports have:

- **Early morning ramp** (05:00–07:00): gradual build-up, ~5-8% of daily traffic
- **Morning peak** (07:00–09:00): ~18-22% of daily traffic
- **Mid-day plateau** (09:00–12:00): steady ~12-15% of daily traffic
- **Afternoon steady** (12:00–16:00): ~15-18% of daily traffic
- **Evening peak** (17:00–19:00): ~18-22% of daily traffic
- **Evening wind-down** (19:00–23:00): gradual decline, ~10-15% of daily traffic

**Implementation:** Use a piecewise hourly weight distribution instead of two Gaussians. This gives more control and produces a realistic "camel hump" shape with a sustained mid-day base.

**Hourly weight table (for departures):**

| Hour | Weight | Description        |
| ---- | ------ | ------------------ |
| 05   | 2      | First wave         |
| 06   | 8      | Early ramp         |
| 07   | 14     | Morning peak start |
| 08   | 16     | Morning peak       |
| 09   | 12     | Post-peak          |
| 10   | 10     | Mid-morning        |
| 11   | 9      | Steady             |
| 12   | 8      | Lunch              |
| 13   | 9      | Afternoon start    |
| 14   | 10     | Afternoon          |
| 15   | 10     | Afternoon          |
| 16   | 12     | Pre-evening        |
| 17   | 15     | Evening peak start |
| 18   | 14     | Evening peak       |
| 19   | 10     | Wind-down          |
| 20   | 7      | Late evening       |
| 21   | 5      | End of ops         |
| 22   | 3      | Last flights       |

Total weight: 198. Each slot = weight/total \* target_departures.

Within each hour, departure times are uniformly jittered (not all at :00 or :30).

Arrivals are paired 90min before departure (unchanged logic), but clipped to 04:00 minimum.

**Files:**

- `services/sim-orchestrator/services/schedule.py` — rewrite `sample_departure_slots()`

---

## 3. Flight Board Column Filters

**Current state:** The FIDSPanel has a single "type" filter dropdown. Need per-column filters for: airline, destination/origin, status, gate.

**Design:**

- Add a filter row below the header with small dropdown/text inputs for each filterable column
- Filters are AND-combined
- New flights (detected via WebSocket `FlightStatusChanged` events) appear at the top of the list before being sorted into position after a brief highlight period
- Maintain existing sort functionality alongside filters

**Filterable columns:**

- **Flight** — text search (flight number contains)
- **Type** — dropdown (existing)
- **To/From** — text search (IATA code contains)
- **Gate** — text search (gate ID contains)
- **Status** — multi-select dropdown
- **Airline** — dropdown (built from unique airline codes in current flights)

**Files:**

- `dashboards/art-dashboard/src/pages/FlightBoard/FlightBoardPage.tsx` — add filter UI and logic to FIDSPanel

---

## 4. Phase 3 — Multi-Airport Network Simulation

### P3-1: Network Configuration YAML

Create `config/network.yaml` with KART + 4 hub airports, distance matrix, and per-airport profiles.

### P3-2: Network-Aware Delay Propagation

When KART delays an outbound flight, the destination airport's inbound schedule is affected. Model this as cross-airport cascade events via Kafka.

### P3-3: Network Map View

Mapbox overlay showing network airports as nodes with arc colours reflecting disruption status.

### P3-4: Network GDP

When one airport declares a GDP, feeder airports receive flow constraints.

### P3-5: `GET /network/status` Endpoint

Returns health of all network airports.

### P3-6: Network Disruption Scenario

YAML scenario triggering cascading disruption across the full network.

**Implementation approach:** Create a lightweight `network` module inside `sim-orchestrator` that:

- Loads network config at startup
- Maintains virtual state for remote airports (not full simulation — just delay state)
- Propagates delays via a simple model: when a departure from KART is delayed, the arrival delay at the remote airport is `max(0, delay - turnaround_buffer)`, and this can cascade back if the remote airport has a return flight to KART
- Exposes REST endpoints for network status
- Dashboard overlay connects via existing world map

---

## Implementation Order

1. Fix `arrival_estimated_time` (5 min)
2. Flight traffic realism (schedule.py rewrite)
3. Flight board filters (React component update)
4. Phase 3 network simulation (new module + config + API + dashboard)
5. Validate all changes (docker-compose rebuild, curl tests, lint, build)
6. Write summary report
