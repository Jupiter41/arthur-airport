# flight-service — specification

**Language:** Python 3.11+  
**Framework:** FastAPI  
**Port:** 8001  
**Responsibility:** Owns the full lifecycle of every flight movement at KART — from schedule ingestion through gate assignment, runway allocation, airborne state, and arrival/departure completion.

---

## 1. Domain responsibilities

- Maintain authoritative state for all `Flight` nodes in Neo4j
- React to `SimClockTick` events and advance flight states based on sim time
- React to `WeatherStateChanged` events and apply capacity constraints
- React to `IncidentCreated` / `IncidentStatusChanged` events affecting runways or gates
- Produce `FlightStatusChanged`, `FlightGateAssigned`, `FlightRunwayAssigned`, `FlightCancelled` events
- Expose REST endpoints for querying flight data
- Expose WebSocket endpoint for live flight state streaming

---

## 2. Flight state machine

```
scheduled
    │
    ├──(T-60 min)──► boarding
    │                   │
    │               (T-0 min, door close)
    │                   │
    │               ◄──► delayed ──────────────► cancelled
    │                   │
    │               departed
    │                   │
    │               airborne
    │
(arrivals only)
    │
    approach
    │
    landed
    │
    taxiing
    │
    at_gate
```

### State transition rules

| Transition | Trigger | Conditions |
|---|---|---|
| `scheduled` → `boarding` | SimClockTick: T-60 min | gate assigned, no active runway/gate incident |
| `boarding` → `departed` | SimClockTick: T-0 min | pax boarded ≥ 95%, no hold |
| `boarding` → `delayed` | hold event received | weather, incident, or manual hold |
| `delayed` → `boarding` | hold lifted | incident resolved or weather improved |
| `delayed` → `cancelled` | delay ≥ 180 min OR manual | cascade: triggers all cascade effects |
| `departed` → `airborne` | SimClockTick: T+5 min | automatic after departure |
| `airborne` → `approach` | SimClockTick: ETA-20 min | automatic |
| `approach` → `landed` | SimClockTick: ETA | runway available, weather permits |
| `approach` → `delayed` | runway unavailable | weather/incident — enters holding stack |
| `landed` → `taxiing` | SimClockTick: ATA+2 min | automatic |
| `taxiing` → `at_gate` | SimClockTick: ATA+8 min | gate available |

---

## 3. Data model (owned fields)

The service writes to and reads from the `Flight` node. See `DATA_MODEL.md` for the full schema. The service additionally maintains an in-memory **runway queue** (sorted list of flights awaiting runway assignment) and a **holding stack** (arrivals delayed due to capacity).

---

## 4. Kafka

### Consumed topics

| Topic | Event type | Action |
|---|---|---|
| `flights.schedule` | `FlightScheduleSeeded` | Persist new flights to Neo4j |
| `sim.clock` | `SimClockTick` | Advance all flight state machines |
| `weather.events` | `WeatherStateChanged` | Apply runway capacity limits, delay arrivals |
| `incidents.events` | `IncidentCreated` | If runway/gate affected: hold or reroute flights |
| `incidents.events` | `IncidentStatusChanged` | If resolved: resume held flights |

### Produced topics

| Topic | Event type | Trigger |
|---|---|---|
| `flights.events` | `FlightStatusChanged` | Any status transition |
| `flights.events` | `FlightGateAssigned` | Gate change (initial or reassignment) |
| `flights.events` | `FlightRunwayAssigned` | Runway slot allocated |
| `flights.events` | `FlightCancelled` | Cancellation |

---

## 5. REST API

Base path: `/api/v1`  
All responses: `application/json`  
Authentication: `Authorization: Bearer <token>` (stub JWT)

### Flights

#### `GET /flights`
List all flights for the current simulated day.

Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `status` | string | Filter by status (comma-separated) |
| `direction` | string | `arrival` or `departure` |
| `terminal` | string | `A`, `B`, or `C` |
| `airline` | string | 2-letter airline code |
| `from` | datetime | sim time range start (ISO 8601) |
| `to` | datetime | sim time range end |
| `limit` | integer | default 50, max 200 |
| `offset` | integer | pagination offset |

Response `200`:
```json
{
  "total": 210,
  "limit": 50,
  "offset": 0,
  "flights": [
    {
      "id": "uuid",
      "flight_number": "AX412",
      "airline_code": "AX",
      "direction": "departure",
      "status": "boarding",
      "aircraft_type": "B738",
      "origin_iata": "VRN",
      "destination_iata": "MDQ",
      "gate_id": "B07",
      "runway_id": "09L",
      "scheduled_time": "2024-06-15T15:30:00Z",
      "estimated_time": "2024-06-15T15:30:00Z",
      "delay_minutes": 0,
      "pax_count": 142,
      "seat_capacity": 189
    }
  ]
}
```

---

#### `GET /flights/{flight_id}`
Full flight detail including passengers and baggage summary.

Response `200`:
```json
{
  "id": "uuid",
  "flight_number": "AX412",
  "status": "boarding",
  "gate": { "id": "B07", "terminal": "B", "jetbridge": true },
  "runway": { "id": "09L", "status": "open" },
  "passengers": {
    "total": 142,
    "boarded": 98,
    "at_gate": 31,
    "airside": 13,
    "connections_at_risk": 2
  },
  "baggage": {
    "total_items": 186,
    "loaded": 124,
    "in_sorting": 62,
    "flagged": 0
  },
  "history": [
    { "status": "scheduled", "at": "2024-06-15T14:00:00Z" },
    { "status": "boarding",  "at": "2024-06-15T14:30:00Z" }
  ]
}
```

---

#### `GET /flights/{flight_id}/cascade`
Returns the full cascade tree of effects triggered by this flight's delay or cancellation.

Response `200`:
```json
{
  "flight_id": "uuid",
  "flight_number": "AX412",
  "delay_minutes": 55,
  "cascade": {
    "gate_conflict": { "resolved": true, "new_gate": "C12" },
    "connecting_passengers": { "count": 3, "at_risk": 2, "missed": 1 },
    "baggage_held": { "count": 62 },
    "turnaround_delay": {
      "next_flight": "AX415",
      "propagated_delay_minutes": 25
    }
  }
}
```

---

#### `GET /runways`
Current runway status.

Response `200`:
```json
{
  "runways": [
    {
      "id": "09L",
      "status": "open",
      "current_use": "landing",
      "ils": true,
      "arrivals_queued": 3,
      "departures_queued": 2
    },
    {
      "id": "09R",
      "status": "open",
      "current_use": "takeoff",
      "ils": false,
      "arrivals_queued": 0,
      "departures_queued": 5
    }
  ]
}
```

---

#### `GET /gates`
All gate statuses.

Query parameters: `terminal`, `status`

Response `200`:
```json
{
  "gates": [
    {
      "id": "B07",
      "terminal": "B",
      "status": "occupied",
      "flight_number": "AX412",
      "occupied_until": "2024-06-15T15:45:00Z",
      "jetbridge": true
    }
  ]
}
```

---

#### `POST /flights/{flight_id}/hold`
Manually place a flight on hold (operator override).

Request body:
```json
{ "reason": "awaiting_crew", "expected_duration_minutes": 20 }
```

Response `200`: updated flight object.

---

#### `POST /flights/{flight_id}/release`
Release a manually held flight.

Response `200`: updated flight object.

---

### WebSocket

#### `WS /ws/flights`
Streams `FlightStatusChanged`, `FlightGateAssigned`, `FlightRunwayAssigned`, and `FlightCancelled` events in real time.

Connection message (server → client on connect):
```json
{ "type": "connected", "sim_time": "2024-06-15T14:32:00Z", "active_flights": 87 }
```

Event message:
```json
{
  "type": "FlightStatusChanged",
  "flight_id": "uuid",
  "flight_number": "AX412",
  "previous_status": "scheduled",
  "new_status": "boarding",
  "gate_id": "B07",
  "sim_time": "2024-06-15T14:30:00Z"
}
```

Client can send a filter frame:
```json
{ "filter": { "terminal": "B", "status": ["boarding", "delayed"] } }
```

---

## 6. Internal service logic

### Runway queue manager
Maintains a priority queue of flights awaiting runway assignment. Priority is: scheduled time ASC, then direction (arrivals > departures in IMC/LIFR). On each `SimClockTick`, assigns runway slots to the next N flights where N = current capacity rate ÷ 60.

### Gate conflict resolver
When a gate reassignment is needed (inbound late, outbound waiting), the resolver queries Neo4j for available gates in the same terminal and assigns the nearest free gate. Emits `FlightGateAssigned`.

### Turnaround tracker
Maintains a map of `aircraft_registration → (inbound_flight, outbound_flight)`. When the inbound flight is delayed, automatically recalculates and propagates delay to the outbound flight after applying the turnaround buffer.

---

## 7. Configuration

| Env variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j connection |
| `NEO4J_USER` | `neo4j` | |
| `NEO4J_PASSWORD` | `art-digital-twin` | |
| `KAFKA_BROKERS` | `kafka:9092` | Kafka bootstrap servers |
| `TURNAROUND_NARROW_MIN` | `30` | Narrow-body turnaround buffer (minutes) |
| `TURNAROUND_WIDE_MIN` | `45` | Wide-body turnaround buffer |
| `CASCADE_MAX_DEPTH` | `5` | Max turnaround propagation hops |
| `LOG_LEVEL` | `INFO` | |

---

## 8. Health & observability

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness: returns `{"status": "ok"}` |
| `GET /ready` | Readiness: checks Neo4j + Kafka connectivity |
| `GET /metrics` | Prometheus metrics (text format) |

### Key Prometheus metrics

| Metric | Type | Description |
|---|---|---|
| `flight_status_transitions_total` | Counter | Total state transitions, labelled by `from`, `to` |
| `flights_delayed_current` | Gauge | Currently delayed flights |
| `flights_cancelled_total` | Counter | Total cancellations |
| `runway_queue_depth` | Gauge | Flights waiting for runway slot, per runway |
| `cascade_depth_histogram` | Histogram | Depth of delay cascade chains |
| `gate_conflicts_resolved_total` | Counter | Gate reassignments performed |
