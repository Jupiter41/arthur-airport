# Phase 2 — Prescriptive Digital Twin — Implementation Plan

## Architecture Decision

Create a new **analysis-service** (Python 3.11 + FastAPI, port 8007) that acts as
a read-only aggregator of all domain events. This follows the same event-driven pattern
as all other services:

- **Consumes** Kafka events from `sim.clock`, `flights.events`, `passengers.events`,
  `baggage.events`, `weather.events`, `incidents.events`, `ground.events`
- **Does not produce** domain events (it's a read-side service, not an authority on any entity)
- **Produces** events on `analysis.events` topic for dashboard fan-out (bottleneck/recommendation notifications)
- **Reads** Neo4j for snapshot queries (gate availability, connection clusters, etc.)
- **Exposes** REST endpoints: `GET /analysis/bottlenecks`, `GET /analysis/recommendations`,
  `POST /analysis/what-if`, plus health/ready/metrics
- **WebSocket** at `/ws/analysis` for live bottleneck/recommendation push

This is the cleanest separation: the analysis-service doesn't own any entity but synthesises
actionable intelligence from cross-domain data.

---

## Implementation Sequence

### Step 1 — Service scaffold (P2-1-1 partial)
- Dockerfile, requirements.txt, main.py, db/, kafka/, routers/, services/, models/
- Docker-compose entry at port 8007
- Gateway proxy route for `/api/v1/analysis`
- Kafka topic `analysis.events` creation

### Step 2 — Bottleneck detection engine (P2-1-1 through P2-1-7)
- `models/domain.py` — Bottleneck Pydantic model
- `services/detectors.py` — Six detector functions, one per bottleneck type
- Kafka consumer builds in-memory operational state from events
- Detectors run every tick and emit bottleneck events
- REST endpoint `GET /api/v1/analysis/bottlenecks`

### Step 3 — Recommendation engine (P2-2-1 through P2-2-7)
- `models/domain.py` — Recommendation Pydantic model
- `services/recommender.py` — Rule-based recommendation generators per bottleneck type
- REST endpoint `GET /api/v1/analysis/recommendations`
- Dashboard recommendation feed on incident page

### Step 4 — What-if analysis engine (P2-3-1 through P2-3-5)
- `services/whatif.py` — Shadow simulation using in-memory event replay
- `POST /api/v1/analysis/what-if` endpoint
- Multi-action comparison support
- Dashboard what-if panel
- Analysis log persistence

### Step 5 — Autonomous operations mode (P2-4-1 through P2-4-4)
- Settings integration for autonomous_mode toggle
- Auto-apply loop with confidence threshold
- Action log with outcome tracking
- Safety guards for destructive actions

---

## Bottleneck Detectors (Detail)

| Detector | Source Events | Threshold | Severity |
|---|---|---|---|
| Security queue | PassengerStatusChanged + forecast | wait > 20 min, conf > 0.75 | warning → critical at 30 min |
| Gate utilisation | FlightStatusChanged + FlightGateAssigned | < 2 free gates + queued flights | warning → critical at 0 gates |
| Baggage throughput | BaggageStatusChanged | make-up > 90% for > 5 min | warning → critical at 95% |
| Connection cluster | FlightStatusChanged (delay) + passenger data | 5+ pax same inbound + connection | critical |
| Ground vehicle | GroundVehicleDispatched/Returned | type util > 85% + demand in 15 min | warning |
| Runway capacity | WeatherStateChanged + flight queue depth | capacity < 60% + queue > 5 | warning |

## Recommendation Matrix (Detail)

| Bottleneck | Recommendations |
|---|---|
| Security queue | Open additional lane, early gate call, redirect check-in |
| Gate conflict | Pre-assign alternate gate, delay taxi, swap departures |
| Connection risk | Hold connecting flight, fast-track cluster, rebook |
| Baggage throughput | Redirect to adjacent make-up, expedite loading, alert ground crew |
| Ground vehicle | Redistribute vehicles between depots, defer non-critical tasks |
| Low capacity (GDP) | Hold departing flights at gate, stagger departures, advise airlines |

---

## File Structure

```
services/analysis-service/
├── Dockerfile
├── requirements.txt
├── main.py
├── SKILL.md
├── db/
│   ├── __init__.py
│   └── neo4j.py
├── kafka/
│   ├── __init__.py
│   ├── consumer.py
│   └── producer.py
├── models/
│   ├── __init__.py
│   └── domain.py
├── routers/
│   ├── __init__.py
│   └── analysis.py
├── services/
│   ├── __init__.py
│   ├── detectors.py
│   ├── recommender.py
│   ├── whatif.py
│   ├── autonomous.py
│   └── state.py          # In-memory operational state aggregator
└── metrics.py
```
