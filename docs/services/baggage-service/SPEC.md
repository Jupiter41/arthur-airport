# baggage-service — specification

**Language:** Python 3.11+  
**Framework:** FastAPI  
**Port:** 8003  
**Responsibility:** Tracks every baggage item through the full handling chain — from passenger drop-off through screening, sorting, loading, in-flight carriage, arrival, carousel assignment, and collection. Handles dangerous goods flagging and the cascading effects of flight delays on baggage state.

---

## 1. Domain responsibilities

- Maintain authoritative state for all `Baggage` nodes in Neo4j
- Advance baggage status based on `SimClockTick` and flight events
- Model the conveyor/sorting system with throughput constraints and failure modes
- Detect and flag dangerous goods, emit `BaggageFlagged` events
- React to flight delays and cancellations (hold, offload, reroute baggage)
- React to `system_failure` incidents (conveyor jam, power outage)
- Produce `BaggageStatusChanged` and `BaggageFlagged` events
- Expose REST endpoints for baggage tracking and flow analytics

---

## 2. Baggage state machine

```
dropped_off
    │
    ▼ (induction belt — T-90 min)
inducted
    │
    ▼ (screening unit — 2 min/item)
screening ──────────────────────────► flagged (DG or security)
    │                                     │
    ▼ (clear)                             ▼ (manual review, T+30 min)
sorting                               held_for_review ──► loaded (if cleared)
    │                                                  ──► offloaded (if rejected)
    ▼ (make-up area assignment)
loaded
    │
    ▼ (flight departed)
in_hold
    │
    ▼ (flight landed, at_gate)
arrived
    │
    ▼ (carousel assigned, T+20 min)
on_carousel
    │
    ▼ (passenger collects)
collected

(at any point if flight cancelled)
loaded / in_hold ──► offloaded ──► on_carousel (return)
```

---

## 3. Handling system model

### Conveyor network zones

| Zone | Description | Throughput |
|---|---|---|
| `induction-{A/B/C}` | Check-in desk to main belt | 600 items/hr per terminal |
| `screening-unit-{1–6}` | X-ray and ETD screening | 300 items/hr per unit |
| `sorting-matrix` | Automated tag-reading sorter | 1,800 items/hr total |
| `make-up-{A/B/C}-{1–5}` | Per-gate make-up carousels | 150 items/hr per carousel |
| `arrival-belt-{1–6}` | Arrival carousels (public) | 200 items/hr per belt |

### Throughput model

On each `SimClockTick`, the service calculates how many items to advance from each zone based on current throughput capacity.

```python
items_to_advance = int(zone_throughput_per_hour / 60 * sim_minutes_elapsed)
```

Queue overflow (items exceeding zone capacity) triggers a `QueueBacklog` internal alert and slows upstream zones proportionally.

### System failure impact

When a `system_failure` incident is received:

| Failure location | Effect |
|---|---|
| `conveyor-sorting` | Sorting matrix halts; items back up to screening |
| `conveyor-induction-{terminal}` | Induction belt halted; new drop-offs queued manually |
| `power-{terminal}` | All belts in terminal halt; throughput → 0 |
| `screening-unit-{n}` | One screening unit offline; capacity reduced by 1/6 |

Recovery: when `IncidentStatusChanged` (resolved) is received, the affected zone resumes at full capacity.

---

## 4. Dangerous goods detection

The screening model applies a probabilistic detection algorithm to each item passing through screening.

### Detection model

```python
# Base detection rates per DG class
DETECTION_RATES = {
    "2": 0.88,  # gases
    "3": 0.91,  # flammable liquids
    "8": 0.95,  # corrosives
    "9": 0.72,  # miscellaneous
}

def screen_item(baggage: Baggage) -> ScreeningResult:
    if baggage.is_dangerous_goods:
        detected = random.random() < DETECTION_RATES[baggage.dg_class]
        if detected:
            return ScreeningResult.FLAGGED
    # False positive rate: 0.3% of all clean items
    if random.random() < 0.003:
        return ScreeningResult.FALSE_POSITIVE
    return ScreeningResult.CLEAR
```

A flagged item transitions to `flagged` status and emits `BaggageFlagged`. If the DG class is 3 (flammable) and is already loaded, a `baggage_fire` incident is probabilistically triggered in the incident service.

---

## 5. Kafka

### Consumed topics

| Topic | Event type | Action |
|---|---|---|
| `sim.clock` | `SimClockTick` | Advance conveyor simulation, drain queues |
| `flights.events` | `FlightStatusChanged` | If delayed: hold loaded bags; if cancelled: offload |
| `flights.events` | `FlightCancelled` | Offload all loaded baggage, assign return carousel |
| `incidents.events` | `IncidentCreated` (system_failure) | Halt affected conveyor zones |
| `incidents.events` | `IncidentStatusChanged` (resolved) | Resume conveyor zones |
| `incidents.events` | `IncidentCreated` (baggage_fire) | Flag all items in affected make-up area |

### Produced topics

| Topic | Event type | Trigger |
|---|---|---|
| `baggage.events` | `BaggageStatusChanged` | Any status transition |
| `baggage.events` | `BaggageFlagged` | DG detected or false positive |

---

## 6. REST API

Base path: `/api/v1`

#### `GET /baggage`
List baggage items with filters.

Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `flight_id` | string | Filter by flight |
| `passenger_id` | string | Filter by passenger |
| `status` | string | Comma-separated status filter |
| `flagged` | boolean | Only flagged items |
| `zone` | string | Current handling zone |
| `limit` | integer | default 50, max 500 |
| `offset` | integer | |

Response `200`:
```json
{
  "total": 186,
  "items": [
    {
      "id": "uuid",
      "tag": "0074123456",
      "passenger_id": "uuid",
      "passenger_name": "Jordan Alvarez",
      "flight_number": "AX412",
      "status": "loaded",
      "weight_kg": 18.4,
      "is_dangerous_goods": false,
      "last_scan_zone": "make-up-B-3",
      "last_scan_at": "2024-06-15T13:55:00Z"
    }
  ]
}
```

---

#### `GET /baggage/{baggage_id}`
Full item detail with scan history.

Response `200`:
```json
{
  "id": "uuid",
  "tag": "0074123456",
  "status": "loaded",
  "weight_kg": 18.4,
  "is_dangerous_goods": false,
  "passenger": { "id": "uuid", "name": "Jordan Alvarez", "pnr": "ART7X2" },
  "flight": { "id": "uuid", "flight_number": "AX412", "status": "boarding" },
  "scan_history": [
    { "zone": "induction-B",     "status": "inducted",  "at": "2024-06-15T13:30:00Z" },
    { "zone": "screening-unit-3","status": "screening", "at": "2024-06-15T13:32:00Z" },
    { "zone": "sorting-matrix",  "status": "sorting",   "at": "2024-06-15T13:34:00Z" },
    { "zone": "make-up-B-3",     "status": "loaded",    "at": "2024-06-15T13:55:00Z" }
  ]
}
```

---

#### `GET /baggage/tag/{tag}`
Look up by 10-digit barcode tag.

---

#### `GET /flow/summary`
Real-time baggage flow summary across the handling system.

Response `200`:
```json
{
  "sim_time": "2024-06-15T14:32:00Z",
  "total_in_system": 1842,
  "by_status": {
    "dropped_off": 124,
    "inducted": 89,
    "screening": 203,
    "sorting": 178,
    "loaded": 891,
    "in_hold": 234,
    "arrived": 0,
    "on_carousel": 89,
    "collected": 34
  },
  "flagged_active": 3,
  "system_failures_active": 0,
  "zones": [
    {
      "zone_id": "sorting-matrix",
      "items_queued": 178,
      "throughput_per_hour": 1800,
      "utilisation_pct": 59,
      "status": "normal"
    }
  ]
}
```

---

#### `GET /flow/map`
Conveyor zone map with current item counts — used by the baggage tracking dashboard.

Response `200`:
```json
{
  "zones": [
    { "zone_id": "induction-A", "items": 34, "status": "normal" },
    { "zone_id": "screening-unit-1", "items": 42, "status": "normal" },
    { "zone_id": "screening-unit-2", "items": 38, "status": "offline" },
    { "zone_id": "sorting-matrix", "items": 178, "status": "normal" },
    { "zone_id": "make-up-B-3", "items": 21, "status": "normal" },
    { "zone_id": "arrival-belt-4", "items": 89, "status": "normal" }
  ]
}
```

---

#### `GET /flagged`
All currently flagged baggage items.

Response `200`:
```json
{
  "flagged": [
    {
      "id": "uuid",
      "tag": "0074567890",
      "passenger_name": "Lee Petrov",
      "flight_number": "BK217",
      "flag_reason": "dangerous_goods_detected",
      "dg_class": "3",
      "current_zone": "screening-unit-4",
      "flagged_at": "2024-06-15T14:28:00Z",
      "review_status": "pending"
    }
  ]
}
```

---

### WebSocket

#### `WS /ws/baggage`
Streams `BaggageStatusChanged` and `BaggageFlagged` events.

Filter frame:
```json
{ "filter": { "flight_number": "AX412" } }
```

---

## 7. Configuration

| Env variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://neo4j:7687` | |
| `NEO4J_USER` | `neo4j` | |
| `NEO4J_PASSWORD` | `art-digital-twin` | |
| `KAFKA_BROKERS` | `kafka:9092` | |
| `SORTING_THROUGHPUT_PER_HR` | `1800` | Sorting matrix capacity |
| `SCREENING_UNITS` | `6` | Number of active screening units |
| `DG_FALSE_POSITIVE_RATE` | `0.003` | Screening false positive probability |
| `LOG_LEVEL` | `INFO` | |

---

## 8. Health & observability

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness |
| `GET /ready` | Readiness: Neo4j + Kafka |
| `GET /metrics` | Prometheus |

### Key Prometheus metrics

| Metric | Type | Description |
|---|---|---|
| `baggage_in_system_total` | Gauge | Total items in handling system |
| `baggage_flagged_active` | Gauge | Currently flagged items |
| `conveyor_zone_utilisation_pct` | Gauge | Utilisation per zone |
| `conveyor_zone_status` | Gauge | 0=normal, 1=degraded, 2=offline |
| `baggage_status_transitions_total` | Counter | Transitions by status |
| `dangerous_goods_detected_total` | Counter | DG detections by class |
| `false_positives_total` | Counter | Screening false positives |
| `offloaded_due_to_cancellation_total` | Counter | Items offloaded from cancelled flights |
