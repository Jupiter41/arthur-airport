# baggage-service — specification

**Language:** Python 3.11+  
**Framework:** FastAPI  
**Port:** 8003  
**Responsibility:** Tracks every baggage item through the full handling chain — from passenger drop-off through screening, sorting, loading, in-flight carriage, arrival, carousel assignment, and collection. Handles dangerous goods flagging and the cascading effects of flight delays on baggage state.

---

## 1. Domain responsibilities

Status summaries count non-null persisted statuses through the existing status
index, avoiding full node/property scans as synthetic history accumulates.

- Maintain authoritative state for all `Baggage` nodes in Neo4j
- Advance baggage status based on `SimClockTick` and flight events
- Model the conveyor/sorting system with throughput constraints and failure modes
- Detect and flag dangerous goods, emit `BaggageFlagged` events
- React to flight delays and cancellations (hold, offload, reroute baggage)
- React to `system_failure` incidents (conveyor jam, power outage)
- Produce `BaggageStatusChanged` and `BaggageFlagged` events
- Expose REST endpoints for baggage tracking and flow analytics

### Aggregate projection contract

`BaggageZoneSnapshot` on `baggage.events` contains `zones` (the complete zone
summary: `zone_id`, `items`, `throughput_per_hour`, `utilisation_pct`, `status`)
and `at` in simulation time. It is published every REALTIME and BULK tick,
independent of per-bag event suppression. The latest payload is
persisted by baggage-service in `BaggageProjection {id: 'latest', document}` so
analysis can recover occupancy without replaying sampled events. Projection,
runtime checkpoint and outbox fact commit in the same owner transaction.

Flight-wide and induction status changes may use one Neo4j batch transaction.
Each changed bag still receives its own scan-history record and Kafka fact;
the batch is persisted before its facts or in-memory queue additions are made.

Restart recovery reads `last_scan_zone` (with a legacy `current_zone` fallback),
restores queued departure and arrived bags, and retains their tags, dangerous
goods attributes, passenger link and terminal routing metadata. Cross-terminal
transit progress remains tracked in roadmap G9.

Recovery materializes only conveyor queue states (`inducted`, `screening`,
`sorting`, `arrived`). Loaded, in-flight and flagged bags remain authoritative
in Neo4j and are handled by status-filtered flight/incident operations. They are
not copied into an unbounded startup deduplication set: induction reads only
`dropped_off` bags, so persisted status is its restart guard. No history is
deleted or sampled to bound recovery memory.

Conveyor failures are tracked by `system_failure` incident identity. A resolved
cascade child at the same location cannot release its parent's failed zones.
Overlapping failures keep a zone offline until every affecting failure resolves.
Active/contained system failures are rebuilt from Neo4j before consuming events.

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

(flight departed while the bag is dropped_off / inducted / screening / sorting)
──► short_shipped   (terminal; BaggageMissedFlight, never enters in_hold, RC6)
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

### Transfer bags (connecting passengers)

A connecting passenger's checked bags are seeded `in_hold` on the inbound arrival
(`LOADED_ON`), linked to the passenger (`CARRIES`) and tagged with
`transfer_flight_id` (the passenger's onward departure). When the inbound reaches
`at_gate`, in the same transaction as the other bags going to `arrived`:

```
in_hold (inbound) ──► dropped_off (zone transfer-{T}, LOADED_ON → onward flight)
    │                  onward flight still scheduled / boarding / delayed
    ▼
inducted → screening → sorting → loaded → in_hold (onward)   (departure chain above)
    └─► short_shipped if the onward flight leaves first (RC6 rule, unchanged)
```

`inbound_flight_id` keeps the bag's inbound flight. When the onward flight is no
longer open (departed, airborne, cancelled …; the passenger is then
`missed_connection`) or unknown to the FlightView, the bag stays on the inbound and
goes to the arrival belt like any arrival bag. Each transfer emits a
`BaggageStatusChanged` (`in_hold` → `dropped_off`, `scan_zone` `transfer-{T}`,
`flight_id` = onward flight, `inbound_flight_id`).

---

## 3. Handling system model

### Conveyor network zones

Throughputs come from `config/airport.yaml` `operations.baggage` (RC6), not from
code constants. Shipped values:

| Zone | Description | Throughput |
|---|---|---|
| `induction-{A/B/C}` | Check-in desk to main belt | A 1,800 · B 3,000 · C 1,800 items/hr (`induction_per_terminal_hr`) |
| `screening-unit-{1–6}` | Hold-baggage CT/EDS, 2 units per terminal | terminal's `screening_per_terminal_hr` split evenly: A/C 900, B 1,500 items/hr per unit |
| `sorting-matrix` | Automated tag-reading sorter | 5,400 items/hr total (`sorting_matrix_hr`) |
| `make-up-{A/B/C}-{1–5}` | Per-gate make-up carousels | 150 items/hr per carousel |
| `arrival-belt-{1–6}` | Arrival carousels (public) | 2,400 items/hr per belt |

Terminal B carries the hub carrier (~55–60% of peak-hour bags), so it gets the
larger induction and screening lines. Demand is sized against this capacity at
seed time (`SIMULATION.md` "BHS sizing check"): peak hourly bags per terminal
and airport-wide stay ≤ 85% of the slowest stage.

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
| `baggage.events` | `BaggageStatusChanged` | Event/command-driven transitions; on the tick only `in_hold`, `on_carousel`, `collected` |
| `baggage.events` | `BaggageStatusBatchChanged` | Every committed tick: all tick transitions (incl. `inducted`/`screening`/`sorting`/`loaded`) |
| `baggage.events` | `BaggageFlagged` | DG detected or false positive |
| `baggage.events` | `BaggageMissedFlight` | Flight departed with bags not yet `loaded` (one fact per flight, RC6) |

#### Departure outcome (RC6)

On `FlightStatusChanged(departed)` only `loaded` bags go to `in_hold`. Bags still
`dropped_off` / `inducted` / `screening` / `sorting` become `short_shipped`, are
removed from the conveyor, get their own `BaggageStatusChanged`, and are listed
in one `BaggageMissedFlight` fact — all in the departure's single transaction.
A `dropped_off` bag the induction tick finds on an already departed/airborne
flight is short-shipped the same way. There is no fast-track: no bag reaches
`in_hold` without a `loaded` scan. `short_shipped` is terminal and is archived by
retention 24 sim-h later, like `collected`.

---

## 6. REST API

Base path: `/api/v1`

#### `GET /baggage`
List baggage items with filters.

Count matching bag entities without expanding optional passenger/flight metadata.
Apply ordering and pagination to bags before loading that metadata. Flight and
passenger filters remain mandatory relationship matches, and totals count distinct
bags. Page ordering uses last scan descending with bag ID as a deterministic tie
break. A small page must not materialize the airport's full relationship history.

Unfiltered pages use indexed ordering: unscanned bags first, then scan timestamp
descending, with ID descending within each group. Null scan timestamps remain
visible. The owner uses transactional bag and unscanned-label count-store totals
to split offsets across these groups; metadata expands only after page selection.
Filtered pages retain their documented scan-descending/ID-ascending ordering.

`UnscannedBaggage` is derived index metadata for bags with no `last_scan_at`.
Seeding adds it for null scans; every owner scan/redirect removes it in the same
transaction as the timestamp update. Startup backfills legacy null scans once,
recording completion in `BaggageIndexMigration`. Timestamp remains authoritative;
the label can be rebuilt from it. This enables exact null counts from Neo4j's
count store and direct indexed null pages, avoiding scans of all historical bags.

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
    "collected": 34,
    "short_shipped": 2
  },
  "short_shipped": 2,
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
Paginated flagged/review queue. `limit` defaults to 50 (1–500); `offset` defaults
to zero. The response retains `flagged` and adds `total`, `limit`, and `offset`.
Items are ordered by ID ascending and selected before metadata expansion. Each
bag appears once even with duplicate metadata edges; inconsistent multiple
owners use the smallest passenger/flight ID for display. No records are deleted
or automatically cleared by this read endpoint.

Includes bags with status `flagged` or review status `pending`, once per bag even
when both match. Startup uses property indexes for both source candidate sets;
page reads expand passenger/flight metadata only after selecting review IDs.

`ReviewBaggage` is derived membership for that predicate. Status/flag writes
maintain it transactionally. A bounded, idempotent `review-v1` startup migration
backfills both indexed candidate sets and removes stale membership. Counts use
the label count store and pages use its ID index, without sorting the whole
historical review queue. Source status/review properties remain authoritative.

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
| `baggage_short_shipped_total` | Counter | Bags left behind at departure, by `previous_status` (RC6 KPI) |


### Command execution receipts (Real LDT correction)

Accepted commands emit the existing domain fact plus `CommandExecuted`; rejected
commands emit `CommandRejected` with a reason. Both receipts carry `command_id`
and `command_type`, use the current simulation clock, and are stored in Neo4j
for restart-safe redelivery. See `EVENT_BUS.md`, “Real LDT execution and planning
corrections”, for the lifecycle and transaction-boundary limitation.

### G1 transaction boundary

Every committed tick persists `BaggageProjection` and stages the full unsampled
`BaggageZoneSnapshot`, including the first tick in BULK mode. Aggregate recovery
does not wait for the slower metrics/display cadence. Cross-terminal transit
destinations and remaining travel time are part of the versioned owner runtime.

A clock tick locks `BaggageOutboxSeq` before planning. Conveyor/transit progress,
domain writes, scan history, aggregate projection, checkpoint and facts commit
in one transaction. Failed attempts discard private state; competing workers
restore the winning checkpoint before planning. Redirect commands commit their
receipt fact with the redirect. Kafka inputs are acknowledged after successful
processing; pending facts are deleted only after broker acknowledgement.

`BaggageStatusBatchChanged` is an unsampled tick fact and the only publication
of pipeline-internal hops (RC3; see EVENT_BUS.md "Event granularity contract").
Its payload contains `status_changes` (`id`, `status`, `zone`,
`previous_status`, `flight_id`), `flags` and `loaded_rows`, including BULK mode;
per-bag `BaggageStatusChanged` facts are suppressed in BULK mode.

### UI observation timestamps (2026-11-16)

`GET /flow/map` zones include nullable `observed_at`: the owner published
simulation clock at the read, not a last-change time or real fetch time.
No owner clock means null. This is read-only response metadata; no domain
mutation or additional Kafka event occurs. See the dashboard observation
contract in `docs/dashboards/UI_IMPLEMENTATION.md`.


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

### Diverted-arrival disposition and retention (RC1 / RC8, 2026-11-19)

An arrival diverted away from KART never unloads here. On consumed
`FlightDiverted` or `FlightStatusChanged(new_status=diverted)`, baggage-service
changes only that arrival's live `in_hold` bags to terminal `diverted`, zone
`diverted-aircraft`. Decisions use the consumed FlightView. Status, sim-time
scan, inbox marker and unsuppressed per-bag `BaggageStatusChanged` facts commit
atomically, including BULK. Identity relationships and transfer metadata remain;
no local carousel or onward transfer is invented. Other statuses/directions stay.

Startup/hourly recovery uses the same path for missed events, old arrival holds
loaded by the startup FlightView beyond its time window, and late seeded bags.
Recovery stamps observation time, never an invented historical diversion time.
Duplicates and later sweeps do not re-stamp terminal bags. `diverted` joins
`collected`/`short_shipped` in indexed 24-sim-hour archival. Scan trails archive
with the bag and purge 168 sim-hours after archival, with atomic
`EntitiesArchived`/`EntitiesPurged` facts. Active arrival holds remain live.

### Collection delivery in every speed mode (RC8 / RC12, 2026-11-19)

`on_carousel` and `collected` per-bag facts carry passenger ID and flight ID
and are never suppressed in BULK. Other pipeline transitions retain the
batch contract. This makes the passenger observation contract identical in
REALTIME, FAST and BULK. Batch transitions retain passenger ID for compatible
consumers and replay; passenger-service accepts both forms idempotently.

### Owner-allocated manifest tags (RC7 cold-start follow-up, 2026-11-19)

The baggage owner replaces generated provisional barcode tags with globally
unique 10-digit synthetic tags when accepting a seed batch. A durable
`BaggageTagSequence` high watermark is locked under the owner runtime. Its
initial value exceeds live/archive legacy tag identities; allocation, bag
creation, links, accepted manifest and creation facts commit together. Retries
consume no extra range. Exhausting the 10-digit namespace rejects the batch
explicitly. Generator timing/randomness cannot define global uniqueness.
