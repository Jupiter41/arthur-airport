# Phase 1 — Simulation Engine Fidelity — Implementation Plan

## Goal

Close the remaining physical and operational gaps in the simulation to make it
produce realistic, noisy outcomes instead of suspiciously clean results.

## Implementation Order

We implement in dependency order:

1. **Phase 1.2 — Noise and variability model** (foundation — all other phases benefit from noise)
2. **Phase 1.3 — Ground vehicle simulation** (requires Neo4j schema change + new Kafka topic)
3. **Phase 1.4 — Runway sequencing model** (enhances runway queue with separation/alternation)
4. **Phase 1.1 — ADS-B integration** (external data — least coupled, can be last)

## Phase 1.2 — Noise and Variability Model

### P1-2-1 — Crew readiness stochastic delay
- **Where**: `services/flight-service/services/state_machine.py` — `_eval_boarding()` transition
- **Logic**: 5% of flights get a 5–15 min crew delay at boarding→departed transition
- **Event**: `FlightStatusChanged` with `delay_reason: "crew_readiness"`
- **Settings**: Add `crew_delay_probability` (0.05) and `crew_delay_range` ([5, 15]) to SimSettings

### P1-2-2 — ATC slot allocation delays (CTOT)
- **Where**: `services/flight-service/kafka/consumer.py` — per-tick departure evaluation
- **Logic**: During peak hours, 10% of departures get a CTOT slot (5–30 min delay)
- **New event**: `FlightCTOTAssigned` on `flights.events`
- **Settings**: Add `ctot_probability_peak` (0.10), `ctot_delay_range` ([5, 30])

### P1-2-3 — Passenger no-shows
- **Where**: `services/passenger-service/kafka/consumer.py` — at boarding time
- **Logic**: 2–4% of booked pax don't board. Their bags must be offloaded.
- **Turnaround**: Add conditional "no-show bag check" task to turnaround plan
- **Settings**: Add `noshow_rate` (0.03)

### P1-2-4 — Equipment failures
- **Where**: `services/flight-service/services/turnaround_plan.py` — task execution
- **Logic**: 1% chance per flight of minor ground equipment failure adding 8–20 min
- **Settings**: Add `equipment_failure_rate` (0.01), `equipment_failure_delay_range` ([8, 20])

### P1-2-5 — Flight diversion events
- **Where**: `services/flight-service/services/state_machine.py` — `_eval_approach()` or `_eval_airborne()`
- **Logic**: 0.3% of arrivals diverted (weather < CAT III or medical). Flight never arrives.
- **Cascade**: Passengers rebooked, baggage rerouted
- **Settings**: Add `diversion_rate` (0.003)

### P1-2-6 — Holding fuel burn tracking
- **Where**: `services/flight-service/kafka/consumer.py` — holding stack management
- **Logic**: Track fuel burn (2,500 kg/hr). After 30 min → `MinimumFuelWarning`. After 45 min → PAN PAN priority.
- **New event**: `MinimumFuelWarning` on `flights.events` (or `incidents.alerts`)

## Phase 1.3 — Ground Vehicle Simulation

### P1-3-1 — GroundVehicle Neo4j node
- **DATA_MODEL.md update** + Neo4j constraint/index
- Types: fuel_truck, catering_truck, pushback_tug, baggage_loader, stairs
- Status: available, dispatched, at_gate, returning

### P1-3-2 — Vehicle dispatch model
- **Where**: New `services/flight-service/services/ground_vehicles.py`
- Nearest available vehicle dispatched on turnaround task start
- Transit time from spatial layout model

### P1-3-3 — Vehicle contention
- If no vehicle of type available → delay turnaround task until one returns
- Creates realistic ground crunch during peak

### P1-3-4 — Kafka events
- New topic: `ground.events`
- Events: `GroundVehicleDispatched`, `GroundVehicleReturned`
- Add to kafka-init in docker-compose

### P1-3-5 — Dashboard ground vehicle icons (deferred to separate sprint)
### P1-3-6 — Grafana metrics (included in backend)

## Phase 1.4 — Runway Sequencing Model

### P1-4-1 — Wake turbulence separation
- **Where**: `services/flight-service/services/runway_queue.py`
- Separation matrix by aircraft weight category (SUPER/HEAVY/MEDIUM/LIGHT)
- Enforce minimum separation in NM converted to time

### P1-4-2 — Runway alternation in IMC
- **Where**: `services/flight-service/services/runway_queue.py`
- Interleave arrivals/departures on single runway during IMC

### P1-4-3 — Runway occupancy time (ROT)
- **Where**: `services/flight-service/services/runway_queue.py`
- 40–90s occupancy after landing, varies by aircraft type

### P1-4-4 — Dashboard throughput chart (deferred)

## Phase 1.1 — ADS-B Integration

### P1-1-1 — OpenSky Network integration
- New module: `services/flight-service/services/adsb.py`
- Poll OpenSky REST API every 10 real seconds
- Store in in-memory cache (no Redis needed — scope is small)

### P1-1-2 — GET /flights/adsb-states endpoint
- GeoJSON FeatureCollection of aircraft within 1000km of KART

### P1-1-3 — Dashboard ADS-B overlay toggle
- New layer on WorldMap and globe views

### P1-1-4/5/6 — Track comparison, calibration, nearby panel (stretch goals)

---

## Testing Strategy

- Unit tests for each new stochastic model (mock RNG for determinism)
- Live Docker stack validation with curl requests
- Monitor sim for a few sim-days to verify noise produces realistic distributions
- Save test scripts in `scripts/` with `helper_` prefix
