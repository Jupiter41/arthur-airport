# Phase 3 — Traffic Realism, Flight Board Filters & Multi-Airport Network

Sprint report documenting the implementation of four concurrent tasks.

---

## 1. Bug fix: `arrival_estimated_time` Neo4j warning

**Problem:** flight-service logs flooded with `WARNING: arrival_estimated_time does not exist` because the property was never set during flight creation.

**Fix:** Added `arrival_estimated_time: null` to the `CREATE` Cypher in `services/sim-orchestrator/services/schedule.py` → `_persist_flights()`. Neo4j no longer warns about reading a non-existent property.

**Files changed:**

- `services/sim-orchestrator/services/schedule.py` (1 line in Cypher)

---

## 2. Traffic realism: schedule distribution rewrite

**Problem:** The bimodal Normal(7.5, 1.5) + Normal(17.5, 1.5) distribution produced unrealistic departure clustering with a dead mid-day gap.

**Solution:** Replaced with a piecewise hourly weight distribution modelled on real mid-size hub traffic patterns:

| Hour | Weight | Expected flights |
| ---- | ------ | ---------------- |
| 05   | 2      | ~2               |
| 06   | 8      | ~10              |
| 07   | 14     | ~17              |
| 08   | 16     | ~20              |
| 09   | 12     | ~15              |
| 10   | 10     | ~12              |
| 11   | 9      | ~11              |
| 12   | 8      | ~10              |
| 13   | 9      | ~11              |
| 14   | 10     | ~12              |
| 15   | 10     | ~12              |
| 16   | 12     | ~15              |
| 17   | 15     | ~18              |
| 18   | 14     | ~17              |
| 19   | 10     | ~12              |
| 20   | 7      | ~8               |
| 21   | 5      | ~6               |
| 22   | 3      | ~4               |

Within each hour, times are uniformly jittered and rounded to 5-minute intervals — no two flights share the exact same slot. Validated with `scripts/helper_validate_schedule_distribution.py`.

**Files changed:**

- `services/sim-orchestrator/services/schedule.py` — rewrote `sample_departure_slots()`
- `docs/architecture/SIMULATION.md` — updated algorithm description and hypothesis table
- `scripts/helper_validate_schedule_distribution.py` — new validation script

---

## 3. Flight board column filters

**Problem:** The FIDS panel only had a departures/arrivals toggle. No way to search or filter by airline, destination, gate, status, or flight number.

**Solution:** Added a `FilterRow` rendered as a second `<tr>` in the table header with:

- **Flight number:** text input with debounce-free search
- **Airline:** `<select>` dropdown dynamically populated from current flight data
- **Type:** `<select>` for Domestic / Short-haul / Long-haul
- **Destination/Origin:** text input search
- **Gate:** text input search
- **Status:** `<select>` for all flight statuses (Scheduled, Boarding, Departed, etc.)
- **Clear all** button resets all filters at once

Sorting updated so new (flashing) flights always appear at the top.

**Files changed:**

- `dashboards/art-dashboard/src/pages/FlightBoard/FlightBoardPage.tsx`

---

## 4. Phase 3: Multi-airport network simulation (P3-1 through P3-6)

### P3-1 — Network configuration

Created `config/network.yaml` with 5 airports:

- KART (Arthur International — home hub)
- EGLL (London Heathrow)
- LFPG (Paris Charles de Gaulle)
- EDDF (Frankfurt)
- OMDB (Dubai International)

Each airport has coordinates, IATA/ICAO codes, and home flag. Propagation and GDP parameters are configurable at the network level.

### P3-2 — Network-aware delay propagation

`services/sim-orchestrator/services/network.py` implements `NetworkEngine`:

- Consumes `FlightStatusChanged` events via a Kafka consumer (`services/sim-orchestrator/kafka/consumer.py`)
- When an outbound KART flight departs with delay ≥ 15 min, propagates to the destination airport
- Absorption factor (0.6) reduces cascade severity at each hop
- Maximum cascade depth of 3 hops
- Automatic recovery: airports recover 5 min of delay per sim-hour

### P3-3 — Network map view

Added to `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx`:

- Network toggle button (🌐) in the controls bar
- `NetworkPanel` sidebar showing airport status cards with delay badges
- Active GDP display with rate reduction percentage
- Recent delay propagation log

### P3-4 — Network ground delay program

`NetworkEngine` supports GDP lifecycle:

- `declare_gdp()`: sets a departure rate reduction (up to 50%) at a target airport
- `lift_gdp()`: removes the GDP
- Auto-declare when airport delay exceeds 60% of capacity threshold
- Auto-lift after minimum duration + cooldown
- REST endpoints: `POST /network/gdp/declare`, `POST /network/gdp/lift`, `GET /network/gdps`

### P3-5 — GET /network/status endpoint

`services/sim-orchestrator/routers/network.py` exposes:

- `GET /api/v1/network/status` — full network health: per-airport delay/status, active GDPs, recent propagations
- `GET /api/v1/network/airports` — list all network airports
- `GET /api/v1/network/airports/{icao}` — single airport detail
- `GET /api/v1/network/arcs` — all airport-to-airport connections
- Gateway route added in `services/api-gateway/src/proxy.ts`

### P3-6 — Network disruption scenario

Created `services/sim-orchestrator/scenarios/definitions/network-cascade-disruption.yaml`:

- 6-hour scenario with weather cascade
- T+30: severe weather at LHR (LIFR conditions)
- T+60: GDP declared at LHR, KART inbounds delayed
- T+120: baggage system cascade at KART due to turnaround pressure

---

## New files created

| File                                                                              | Purpose                                           |
| --------------------------------------------------------------------------------- | ------------------------------------------------- |
| `config/network.yaml`                                                             | Multi-airport network configuration               |
| `services/sim-orchestrator/services/network.py`                                   | NetworkEngine — delay propagation, GDP management |
| `services/sim-orchestrator/routers/network.py`                                    | REST API for network simulation                   |
| `services/sim-orchestrator/kafka/consumer.py`                                     | Kafka consumer for flight events → network engine |
| `services/sim-orchestrator/scenarios/definitions/network-cascade-disruption.yaml` | Cascade disruption scenario                       |
| `scripts/helper_validate_schedule_distribution.py`                                | Schedule distribution validation script           |
| `docs/lessons-learned/phase-3-traffic-filters-network-plan.md`                    | Implementation plan                               |

## Validation results

- **Ruff:** 0 errors across all 7 Python services
- **TypeScript:** 0 errors in dashboard and api-gateway
- **Vite build:** 829 modules transformed, build succeeds
- **Unit tests:** 507 passing
- **Docker build:** sim-orchestrator, api-gateway, dashboard — all built successfully
- **Schedule validation:** all 6 checks passing (210 total, peaks > 30, mid-day 60–120, 5-min aligned)
