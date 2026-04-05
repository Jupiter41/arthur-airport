# Phase 1 — Simulation Fidelity: Lessons Learned

**Date:** 2025-07-01
**Phase:** 1 — Simulation Fidelity
**Status:** 16/22 items complete; 6 dashboard-only items deferred

---

## Summary

Phase 1 added four major simulation subsystems: ADS-B integration (1.1), operational
noise modelling (1.2), ground vehicle dispatch (1.3), and advanced runway sequencing (1.4).
The backend for all four is fully implemented, live-tested, and verified in Neo4j + Prometheus.
Dashboard visualization items (overlay map, vehicle icons, throughput chart) are deferred to
a dedicated dashboard sprint.

---

## What was implemented

### 1.1 — ADS-B Live Data (2/6 items)
- `ADSBCache` class in `services/flight-service/services/adsb.py` — polls OpenSky Network
  REST API every 10 real seconds, filters aircraft within 1000 km of KART via haversine.
- `GET /flights/adsb-states` endpoint returning GeoJSON FeatureCollection.
- Gated by `ADSB_ENABLED` env var (default `false`) to avoid rate-limiting in CI.
- Deferred: dashboard map overlay, track comparison, calibration, nearby panel.

### 1.2 — Noise Model (6/6 items — all done)
- **Crew readiness delay**: 5% Bernoulli draw → 5–15 min delay at boarding transition.
- **CTOT slot allocation**: 10% during peak hours (07–09, 17–19) → 5–30 min pushback delay.
  Emits `FlightCTOTAssigned` Kafka event on `flight.events`.
- **Passenger no-shows**: 2–4% per passenger at boarding start. No-show passengers marked
  `departed_airport` with location `no-show` in Neo4j.
- **Equipment failures**: 1% per flight → 8–20 min added to a random turnaround task.
  Emits extended Kafka event.
- **Flight diversions**: 0.3% of arrivals diverted. New `diverted` terminal state in FSM
  (reachable from `airborne` and `approach`). Emits `FlightDiverted` event.
- **Holding fuel burn**: 2500 kg/hr consumption tracked for holding flights. `MinimumFuelWarning`
  after 30 sim-minutes; PAN PAN priority after 45 min.
- All 13 noise parameters tuneable via SimSettings REST API.

### 1.3 — Ground Vehicles (5/6 items)
- `GroundVehicle` Neo4j node with constraint + indexes. Fleet: 8 fuel trucks, 6 catering,
  10 pushback tugs, 8 baggage loaders, 4 stairs (36 total).
- `GroundVehiclePool` dispatch model with nearest-available selection and spatial transit
  time (depot at grid position 500,300; vehicle speed 83.3 m/min).
- Vehicle contention: when all vehicles of a type are busy, task is queued until one returns.
  Creates realistic ground crunch during peak hours.
- `GroundVehicleDispatched` / `GroundVehicleReturned` Kafka events on `ground.events` topic.
- Prometheus metrics: `ground_vehicle_utilisation_pct` gauge (by type),
  `ground_vehicle_contention_total` counter (by vehicle type).
- Deferred: dashboard vehicle icons on apron map.

### 1.4 — Runway Sequencing (3/4 items)
- Wake turbulence separation matrix (SUPER/HEAVY/MEDIUM/LIGHT) with NM-based minima
  converted to time via approach speed lookup.
- IMC alternation: interleaves arrivals and departures on single runway when visibility < 550m.
- Runway occupancy time (ROT): 40–90 seconds post-landing, varies by weight category.
- Deferred: dashboard throughput chart.

### Dashboard + Gateway Integration
- TypeScript types for `GroundVehicle` added to `types.ts`.
- Zustand `groundVehicleStore` created.
- WebSocket handlers for 5 new event types in `useWebSocket.ts`.
- API gateway proxy routes for `/api/v1/turnarounds` and `/api/v1/ground-vehicles`.
- Gateway Kafka topic mapping for `ground.events`.

---

## Bugs found and fixed

### 1. Noise delay_reason overwrite
**Symptom:** Neo4j showed 0 noise-related delay reasons despite CTOT and crew delays firing.
**Cause:** The boarding-incomplete check in `_process_flight` unconditionally set
`delay_reason = "boarding_incomplete"`, overwriting noise-model reasons like `crew_readiness`,
`ctot_slot`, and `equipment_failure`.
**Fix:** Added a guard: if the current `delay_reason` is in the noise-model set, preserve it
instead of replacing with `boarding_incomplete`.

### 2. Metric contract test gap
**Symptom:** `test_metric_contract.py` would fail if new metrics weren't declared.
**Fix:** Added `ground_vehicle_utilisation_pct` and `ground_vehicle_contention_total` to the
expected metric list for flight-service.

---

## Patterns that worked well

1. **Incremental Docker rebuild**: `docker compose up --build --no-deps -d flight-service`
   is fast (~15s) and avoids restarting the entire stack.
2. **Neo4j as verification**: Querying Neo4j directly (`MATCH (f:Flight) WHERE f.delay_reason
   = "ctot_slot" RETURN count(f)`) provided definitive proof that noise events were firing.
3. **Prometheus for ground vehicles**: Real-time utilisation % by vehicle type immediately
   revealed peak-hour contention without needing logs.
4. **SimSettings as tuneable knobs**: All 13 noise parameters exposed via REST made it
   trivial to verify configuration was loaded correctly.

---

## Decisions and trade-offs

| Decision | Rationale |
|---|---|
| In-memory ADS-B cache (not Redis) | Only ~50–200 aircraft in range; no persistence needed |
| `ADSB_ENABLED=false` by default | Avoids OpenSky rate limits in CI and Docker dev |
| Depot at fixed grid position (500,300) | Placeholder until spatial layout model (Phase 2) provides real coordinates |
| 36 vehicles hard-coded in pool | Matches airport.yaml scale; can be made configurable later |
| Dashboard items deferred | Phase 1 focus was simulation fidelity, not visualization |

---

## CI results

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `pytest tests/unit/ -q` | 507 passed in 0.54s |
| Dashboard `npm run build` | ✅ (chunk size warnings only) |
| API gateway `npm run build` (tsc) | ✅ clean |
| Docker stack health | All containers healthy |
| Gateway proxy: `/api/v1/ground-vehicles` | 36 vehicles returned |
| Neo4j: noise events | 12 CTOT + 6 crew delays confirmed |
| Prometheus: vehicle utilisation | 100% peak, contention events tracked |

---

## What's left for Phase 1

These items are dashboard visualization work and will be picked up in a dedicated sprint:

- **P1-1-3** — Dashboard map overlay showing live ADS-B aircraft
- **P1-1-4** — Track comparison (simulated vs. real)
- **P1-1-5** — Historical track calibration tuning
- **P1-1-6** — "Real flights nearby" panel
- **P1-3-5** — Dashboard ground vehicle icons on apron map
- **P1-4-4** — Runway throughput time-series chart
