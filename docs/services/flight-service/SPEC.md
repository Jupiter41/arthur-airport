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

The current-day flight list requires a `SimClockTick` before serving data. Until
that clock is available after startup/restart, `/flights` and `/ready` return 503;
the service must not silently expand the list to every seeded day. A paused clock
must emit a tick or resume before this clock-dependent readiness condition clears.

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

Runway/gate restrictions retain every active/contained incident's identity.
Resolving one incident cannot release another's restriction; containment alone
does not reopen the resource. Weather restrictions remain separate, so weather
improvement cannot clear an active incident. Incident identities and locations
are rebuilt from Neo4j on startup.

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
      "length_m": 3500,
      "threshold_x": 100, "threshold_y": 800,
      "end_x": 900, "end_y": 800,
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

#### `GET /runways/queue`
Read-only snapshot of the owner's runway sequencing state (`services/runway_queue.py`).
The queue is airport-wide: one arrival heap and one departure heap, ordered by
`(emergency first, estimated_time, flight_id)`. A runway is assigned only when a
slot is granted. Nothing in this response is a clearance; the flight owner does
not model ATC clearances.

Response `200`:
```json
{
  "sim_time": "2024-06-15T14:02:00",
  "weather_category": "VMC",
  "ils_required": false,
  "arrival_rate": 30, "departure_rate": 30,
  "capacity_per_hour": 60, "current_rate": 22,
  "runway_free_at": "2024-06-15T14:02:50",
  "runway_occupied": true,
  "last_arrival_type": "A320", "last_departure_type": "B77W",
  "arrivals": [
    { "position": 1, "flight_id": "uuid", "aircraft_type": "A333",
      "weight_category": "HEAVY", "estimated_time": "2024-06-15T14:05:00",
      "emergency": false, "wake_separation_seconds": 138 }
  ],
  "departures": []
}
```
`wake_separation_seconds` is the owner's minimum time behind the preceding
movement in the same queue (the last assigned type for position 1), from the
ICAO Doc 4444 matrix converted at the follower's approach speed.

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
      "jetbridge": true,
      "position_x": 160, "position_y": 400
    }
  ]
}
```

#### Spatial and timing projection (read-only, 3D twin)

Positions use the seeded 0–1000 layout grid (`fixtures/layout.json`, 1 unit ≈ 1 m).
These fields only expose state the owner already holds; no client may write them.

- `GET /flights` rows include `actual_time` (stamped at `landed`/`departed`),
  `aircraft_registration`, and `taxi_initial_minutes` / `taxi_total_minutes`:
  the exact durations the FSM uses for `landed → taxiing → at_gate`
  (`taxi_time_from_positions`, defaults 2/8 without positions).
- `GET /runways` rows include `length_m` and threshold/end coordinates.
- `GET /gates` rows include `position_x` / `position_y`.
- `GET /ground-vehicles` rows (and `GroundVehicleSnapshot` payloads) include the
  current trip: `origin_x`, `origin_y`, `target_x`, `target_y`, `dispatched_at`,
  `arrives_at`. A trip is a straight apron segment travelled over the owner's
  transit time; all six are `null` when the vehicle is stationary. Checkpoints
  written before these fields restore with `null` trips.

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
| `CASCADE_MAX_DEPTH` | `5` | Max turnaround propagation hops — now from `operations.cascade_max_depth` in `config/airport.yaml` (D6), env var removed |
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


### Command execution receipts (Real LDT correction)

Flight mutations, command receipts and their initial outbox facts commit in one
transaction. A receipt's event document is retained with its durable receipt.
Redelivery requeues only that stored receipt, with its original event ID and
simulation timestamp; a pending receipt is not duplicated, and no flight
mutation or domain fact is repeated.

`GroundDelayProgram` accepts a non-empty list of concrete flight IDs and a
positive `stagger_minutes`. Duplicate IDs are applied once. Only departures in
`scheduled` or `boarding` can be ground-held; arrivals and other states are
skipped. The current command applies the same hold duration to each eligible
flight; it does not allocate staggered runway slots. An entirely ineligible batch
is rejected. These command writes and their receipt/outbox records are atomic.

Accepted commands emit the existing domain fact plus `CommandExecuted`; rejected
commands emit `CommandRejected` with a reason. Both receipts carry `command_id`
and `command_type`, use the current simulation clock, and are stored in Neo4j
for restart-safe redelivery. See `EVENT_BUS.md`, “Real LDT execution and planning
corrections”, for the lifecycle and transaction-boundary limitation.


Manual holds persist their reason, duration and simulation timestamp on Flight.
A restart reloads them before ticks resume; only a successful release/status
transition clears the hold. Gate reassignment must resolve the destination gate
before deleting the old assignment and must reject unknown/occupied targets.

### G1 transaction boundary

G9 adds startup restoration of the committed runtime before serving fleet and
turnaround reads. Seeding creates missing vehicles without overwriting existing
ones. Every tick mirrors the full fleet (including transit timestamps and busy
statuses) to public `GroundVehicle` nodes and stages an unsampled
`GroundVehicleSnapshot` on `ground.events`, inside the same owner transaction
in both REALTIME and BULK modes. Analysis counts all non-available vehicles by
identity; it never reconstructs exact utilisation by adding dispatch events.

Each clock tick locks `FlightRuntime` before reading/planning and commits all
flight/gate/runway writes, turnaround and vehicle progress, fuel tracking,
facts and its simulation-time checkpoint together. Runtime state is stored as
versioned JSON with an explicit local type whitelist. Competing workers restore
the winning checkpoint; replay at or before it performs no domain work. REST
and outbox tasks cannot borrow a tick's transaction. WebSocket fan-out follows
commit. All domain facts, including fuel, turnaround and vehicle changes, use
the outbox in every speed mode; BULK snapshots are additional summaries.

### Overdue owner recovery (2026-11-16)

The FSM reads indexed nonterminal flights up to the next 24 hours, including
older overdue flights. A rolling lower date bound must not strand an active
movement forever after downtime or clock migration. Terminal history remains
excluded by status; remote future timetables remain excluded by the upper bound.
Normal owning-service FSM transitions and facts handle these overdue movements.

### Source health (RC10, 2026-11-16)

`GET /flights/adsb/source` (RC10) reports the ADS-B adapter's `health` block (api-gateway SPEC §5a): `enabled` = `ADSB_ENABLED`, `items` = aircraft in the cache, `source` = `adsb.lol` / `opensky` / `synthetic`, poll failures as `last_error`.


### Owner-applied seeding and recovery (RC7 / RC8, 2026-11-17)

This supersedes the legacy direct-write seeding instructions above. The
orchestrator generates complete manifests without writing Flight, Passenger or
Baggage nodes. It atomically stores a SeedDay and bounded SeedBatch requests
(owner, immutable JSON rows, simulation timestamp), then publishes a
FlightScheduleSeeded notification on flights.schedule. Each owner alone applies
its batches: domain creation, identity relationships, durable acceptance and
batch creation facts commit with its transactional outbox. Seed batches wait
until referenced identities exist, so independently starting owners cannot
silently drop links. Startup and each clock tick retry pending owner requests;
a lost notification or publication crash does not lose a manifest. A SeedDay
marker, rather than a partially created timetable, fences repeat generation.
Existing legacy days are preserved, without inventing historical passengers.

Arrival bags are generated per named passenger, including local arrivals, and
always carry passenger_id and optional transfer_flight_id. Arrival passengers
start booked; consumed inbound airborne/approach/landed/taxiing facts advance
them to airborne, and at_gate/arrived/completed facts to deplaning. The arrival
flight enters airborne at ETA minus its synthetic flight duration.

Owner consumer groups start at earliest when no valid offset exists; committed
offsets remain authoritative. Reconciliation uses consumed FlightView state,
never another owner's mutable graph state. Arrival baggage recovery runs on
startup ticks and hourly, includes old in_hold bags even outside the normal
flight-view history window, and calls the same atomic offload path as the fact
handler. New bags created after a flight fact are picked up by recovery. Facts
for recovery transitions remain durable in BULK mode.
