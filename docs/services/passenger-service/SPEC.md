# passenger-service — specification

### Raspberry runtime profile (2026-10-15)

`FORECAST_TRAINING_ENABLED=false` disables collection, parquet writes, and all
automatic/manual retraining entrypoints. Read-only pretrained model inference
and the documented schedule-based fallback remain available. `ML_THREADS`
limits LightGBM workers (default 1); numerical libraries also receive one-thread
environment settings. Training is performed off-device and only trusted model
files may be installed by the host administrator.

**Language:** Python 3.11+  
**Framework:** FastAPI  
**Port:** 8002  
**Responsibility:** Tracks every passenger through the airport from check-in to boarding (departures) or from landing to airport exit (arrivals). Generates alerts for gate changes, connection risks, and emergency protocols.

---

## 1. Domain responsibilities

`GET /api/v1/flow/configuration` reports `sim_time` and `values` containing
`lanes_a/b/c` (durable checkpoint overrides, otherwise this owner's configured
defaults) and `mct_minutes` from the connection model. A failed checkpoint read
fails the request rather than reporting defaults as effective state.

### Explicit lane control (operator cockpit, 2026-11-14)

`POST /api/v1/flow/security/{terminal}/lanes` accepts `lanes_open` (strict integer
1–20) and an optional stable `command_id`. Terminal must be A, B or C. It uses
the same `security_lane_command_atomic` boundary as Kafka `OpenSecurityLane`:
lane state, measured checkpoint, domain facts and receipt commit together.
The response carries the stored receipt; retries with the same ID do not apply
the command again. No available owner simulation clock means 503. Gateway
operator authorization applies; this route is deliberately unavailable on
public deployments. The local teaching runner uses this explicit owner API,
not the orchestrator's presently non-executing lane-settings fields.

Legacy `RebookPassengers` commands are advisory-only until replacement itinerary
execution exists. The rejection receipt and its outbox fact commit atomically;
replay delivers the stored receipt without changing passenger status or flight.

If a passenger tick's managed transaction fails or loses the checkpoint race,
restore its tentative queues, membership sets, zone density and local tick time.
Keep any independently committed lane-setting command. Failures after a
successful commit must not undo the committed runtime projection.

Status summaries count non-null persisted statuses through the existing status
index, avoiding full node/property scans as synthetic history accumulates.

Boarding candidate reads start from the flight-status index and include only
`boarding`, `scheduled`, `delayed`, `airborne`, `departed`, and `taxiing` flights
within the existing schedule cutoff. These are exactly the states accepted by
the boarding/catch-up rules; arrived/diverted/cancelled history cannot board and
must not repeatedly materialize its passenger manifests. Other status queries
keep their existing behavior. Historical passenger records are not rewritten.

- Maintain authoritative state for all `Passenger` nodes in Neo4j
- Advance passenger location/status based on `SimClockTick` events
- React to `FlightStatusChanged` and `FlightGateAssigned` events to issue passenger alerts
- React to `IncidentCreated` events to trigger zone evacuations or access lockdowns
- Produce `PassengerStatusChanged`, `PassengerAlert`, and `SecurityCongestionDetected` events
- Expose REST endpoints for individual and aggregate passenger queries
- Provide queue depth metrics for security, check-in, and gate zones
- Run a LightGBM forecasting model to predict per-terminal queue depth up to 90 sim-minutes ahead
- Detect peak slowdown congestion and emit alerts when security wait exceeds 20 simulated minutes

---

## 2. Passenger state machine

### Departure flow

```
booked
    │
    ▼ (per passenger: sim ≥ show_up_at, drawn at seed time — §3)
    ├──► departed_airport  (zone "no-show": deterministic no-show draw, never enters the airport)
checked_in
    │
    ▼ (per passenger: show_up_at + 10 min check-in processing, at the latest at check-in close T-45)
security_queue
    │
    ▼ (sim: throughput rate, queue drain model)
airside
    │
    ▼ (sim: gate open T-50 + dwell + walk)
at_gate
    │
    ▼ (sim: boarding call T-35, only while the flight is scheduled/boarding/delayed)
boarded
    │
    ▼ (FlightStatusChanged: departed)
departed_airport

(FlightStatusChanged: departed, passenger not yet boarded)
booked / checked_in / security_queue / airside / at_gate ──► missed_flight (terminal)
```

A passenger only progresses toward a flight that is still on the ground and
open: `scheduled`, `boarding` or `delayed`. Nobody checks in, clears to the gate
or boards once the flight is `departed` / `airborne` / `taxiing` (RC5).

### Arrival flow

```
airborne  (inherited from flight state)
    │
    ▼ (flight landed + taxiing)
deplaning
    │
    ▼ (sim: T+15 min after at_gate)
baggage_claim
    │
    ▼ (sim: baggage collected OR T+45 min)
departed_airport
```

### Transfer flow (connecting passengers)

```
airborne → deplaning (on the inbound arrival)
    │
    ▼ (sim: T+15 min after at_gate; onward flight still scheduled/boarding/delayed)
airside  (re-linked ON_FLIGHT to the onward departure, inbound_flight_id kept)
    │       transfer dwell = TRANSFER_DWELL_MIN (10): sterile transfer corridor,
    │       no customs, no landside security, no baggage claim
    ▼
at_gate → boarded → departed_airport   (the departure flow of §2, unchanged)
```

A connecting passenger whose onward flight is no longer open when deplaning ends
(departed, airborne, cancelled, diverted …) becomes `missed_connection` with a
`PassengerAlert` (`connection_missed`). One whose onward flight is unknown to the
FlightView (evicted, another day) follows the normal arrival flow. A transfer that
reaches the gate after its flight left becomes `missed_flight` like any other
departure passenger. Their checked bags are transfer bags: baggage-service moves them
from the inbound hold through the BHS onto the onward flight (baggage-service SPEC §2).

### State transition rules

| Transition                           | Trigger                                     | Notes                                          |
| ------------------------------------ | ------------------------------------------- | ---------------------------------------------- |
| `booked` → `checked_in`              | SimClockTick: `sim_time ≥ show_up_at`       | Per passenger; `show_up_at ~ T-180 + 135·Beta(3,2)` (§3) |
| `booked` → `departed_airport` (`no-show`) | SimClockTick: `sim_time ≥ show_up_at`  | Per passenger, deterministic draw `hash(id) < noshow_rate` (3%) over the whole booked cohort |
| `checked_in` → `security_queue`      | SimClockTick: `show_up_at + 10 min`, or check-in close T-45 | Per passenger (no flight-wide batch)  |
| `security_queue` → `airside`         | SimClockTick: per queue drain rate          | Rate = `security_lanes_open × 180 pax/hr/lane` |
| `airside` → `at_gate`                | SimClockTick: gate open + dwell + walk      | Flight still `scheduled`/`boarding`/`delayed`  |
| `at_gate` → `boarded`                | SimClockTick: boarding call                 | Progressive: 10 pax/min; flight still `scheduled`/`boarding`/`delayed` — never after departure |
| `boarded` → `departed_airport`       | FlightStatusChanged: `departed`             | All boarded passengers of the flight           |
| any pre-boarding status → `missed_flight` | FlightStatusChanged: `departed`        | Terminal; one `PassengerStatusChanged` each; removed from queues and zones (RC5) |
| `deplaning` → `baggage_claim`        | SimClockTick: T+15 after at_gate            | Arrival pax that are not transferring          |
| `deplaning` → `airside` (transfer)   | SimClockTick: T+15 after at_gate            | `connection=true`, onward flight open: `ON_FLIGHT` moves to the onward flight, `inbound_flight_id` / `transfer_at` set, dwell 10 min |
| `deplaning` → `missed_connection`    | SimClockTick: T+15 after at_gate            | `connection=true`, onward flight no longer open; `PassengerAlert` (`connection_missed`) |
| `baggage_claim` → `departed_airport` | BaggageStatusChanged (collected) OR timeout | Timeout = T+45 min                             |

---

## 3. Queue and flow model

### Durable security projection (G9)

Every tick persists each terminal's measured main/assistance queue depths, open
lanes, frozen status, observed wait and simulation timestamp on its
`SecurityCheckpoint`, within the passenger tick transaction. The matching
`SecurityQueueUpdated` aggregate is unsampled in REALTIME and BULK modes.
Lane commands update the checkpoint's lanes and observed wait under the same
owner lock and emit a full queue snapshot alongside the existing lane fact and
receipt. Analysis reads these public owner projections, never private runtime
serialization. Legacy checkpoints without queue fields fall back to graph
passenger counts until the next owner tick.

### Security throughput

KART has 3 security checkpoints (one per terminal), each with a configurable number of open lanes.

```
base_throughput_per_lane = 180 pax/hr

total_base_throughput = open_lanes × base_throughput_per_lane
```

#### Peak slowdown (congestion penalty)

When actual queue depth exceeds the forecast by 30% or more, throughput degrades due to crowding:

```
slowdown_factor = min(1.0, forecast_queue_depth / actual_queue_depth)
effective_throughput = total_base_throughput × slowdown_factor

queue_drain_minutes = actual_queue_depth / effective_throughput × 60
```

When `security_wait_minutes > 20` for 5 consecutive simulated minutes in any terminal, the service
emits `SecurityCongestionDetected` on `passengers.events`. The incident-service consumes this and
creates a `system_failure / security_congestion` incident with the full cascade treatment.

#### Special assistance lane

Passengers with `special_assistance: true` are routed to a dedicated lane per terminal with a fixed
capacity of 20 pax/hr, independent of the main queue. They do not contribute to main queue depth and
do not benefit from additional open lanes. This lane is never affected by the congestion penalty.

During incidents of type `security_breach`, all main lanes in the affected terminal are closed and the
queue is frozen. The special assistance lane remains open at reduced capacity (10 pax/hr).

### Check-in queue

Each airline has a designated check-in zone (zones 1–12). Passengers arrive at check-in following a
time distribution that peaks at T-90 minutes before departure.

```
arrival_distribution: Beta(α=3, β=2) over window [T-180, T-45]
show_up_at = scheduled_time − 180 min + 135 min × Beta(3, 2)      (mean ≈ T-99)
```

`show_up_at` is drawn per passenger at seed time and stored on the `Passenger`
node (RC5). This distribution — not a flight-wide batch — is what releases
passengers into check-in and then security, so a flight's cohort reaches security
spread over about two hours instead of in one minute. Records seeded before
RC5 (no `show_up_at`) derive the same distribution deterministically from their
ID. After check-in, a passenger joins security `CHECKIN_PROCESS_MINUTES` (10)
later, or at check-in close (T-45) if that comes first.

#### No-shows (RC5)

Each booked passenger gets exactly one no-show draw, when their `show_up_at`
is reached: `hash(passenger_id) < noshow_rate` (default 0.03). It covers the
full booked cohort, is deterministic (a replayed tick re-derives the same
outcome, no per-flight "drawn" set is checkpointed), and a no-show never enters
the airport (`departed_airport`, zone `no-show`). `BoardingProgress.total`
excludes no-shows, so the 95% departure threshold is measured against the
passengers who actually showed up.

#### Lanes per terminal

Default open lanes come from `config/airport.yaml` `operations.security_lanes_open`
(A 8, B 12, C 8 — B hosts the hub carrier and ~55–60% of peak departures).
`SECURITY_LANES_OPEN`, when set, overrides every terminal. Lane commands and the
persisted `SecurityCheckpoint` lanes still take precedence at runtime.

### Gate dwell time

After clearing security, passengers enter a simulated dwell phase (retail/F&B) before proceeding to
gate. Dwell duration:

```
dwell_minutes ~ Normal(μ=25, σ=12), clamped to [5, 90]
```

Special assistance passengers skip the dwell phase and proceed directly to gate via dedicated routing.

---

## 3a. Forecasting model

### Purpose

A LightGBM regressor predicts per-terminal security queue depth up to 90 simulated minutes ahead.
The forecast is used to:

- Detect imminent congestion before it becomes an incident
- Drive the slowdown factor in the throughput model (§3)
- Power the demand curve widget in the passenger flow dashboard

### Features

| Feature                        | Type  | Description                                                 |
| ------------------------------ | ----- | ----------------------------------------------------------- |
| `hour_of_day`                  | int   | Simulated hour (0–23)                                       |
| `day_of_week`                  | int   | Simulated day of week (0=Mon)                               |
| `month`                        | int   | Simulated month (1–12)                                      |
| `weather_category`             | int   | Encoded: 0=CAVOK, 1=VMC, 2=IMC, 3=LIFR                      |
| `flights_departing_next_90min` | int   | Count of departures from this terminal in next 90 sim-min   |
| `expected_pax_next_90min`      | float | Sum of `pax_count` for those flights                        |
| `active_incident_in_terminal`  | bool  | Any active incident in this terminal                        |
| `adjacent_terminal_congested`  | bool  | Either of the other two terminals is congested              |
| `is_special_event`             | bool  | A special event is active (from `fixtures/events.json`)     |
| `event_pax_multiplier`         | float | Event demand multiplier (1.0 if no event)                   |
| `load_factor_avg_today`        | float | Running average load factor for current sim day             |
| `season`                       | int   | 0=winter, 1=spring, 2=summer, 3=autumn (derived from month) |

### Target variable

`actual_queue_depth` at terminal `{A, B, C}`, sampled every simulated minute.

### Training cadence

- **Day 1:** no model — fallback to schedule-based formula:
  `forecast = expected_pax_next_90min × 0.35` (empirically calibrated)
- **After day 3:** first training run using accumulated history
- **Every 3 simulated days thereafter:** retrain on full history

Training runs in a background thread to avoid blocking the event loop. The model is serialized to
`$MODELS_PATH/forecast_{terminal}.lgbm` and hot-reloaded after each training run.

**Interruption recovery (G7, A58).** Model and parquet writes use a temporary file plus
`os.replace`, so a crash never leaves a truncated model or training file. The retrain schedule is
derived state: after a restart the next due tick (simulated day ≥ 3) retrains from the persisted
parquet history, which also re-runs any retrain interrupted by the crash. Rows still in the
in-memory buffer (at most one 60-sim-minute flush interval) are lost on an abrupt exit; they are
forecast training samples, not operational state. Compose mounts the `passenger-ml` volume at
`/app/ml-artifacts` (`MODELS_PATH=/app/ml-artifacts/models`,
`TRAINING_DATA_PATH=/app/ml-artifacts/training_data`) so models and history survive container
recreation.

### Model spec

```python
import lightgbm as lgb

model = lgb.LGBMRegressor(
    n_estimators=200,
    learning_rate=0.05,
    max_depth=6,
    num_leaves=31,
    min_child_samples=20,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
)
```

### Forecast endpoint

```
GET /api/v1/flow/forecast?terminal=B&window=90
```

Response `200`:

```json
{
  "terminal": "B",
  "sim_time": "2024-06-15T14:32:00Z",
  "window_minutes": 90,
  "model_trained": true,
  "forecast": [
    {
      "sim_time": "2024-06-15T14:35:00Z",
      "predicted_queue_depth": 42,
      "predicted_wait_minutes": 14
    },
    {
      "sim_time": "2024-06-15T14:40:00Z",
      "predicted_queue_depth": 67,
      "predicted_wait_minutes": 22
    },
    {
      "sim_time": "2024-06-15T14:45:00Z",
      "predicted_queue_depth": 103,
      "predicted_wait_minutes": 34
    }
  ],
  "congestion_risk": {
    "detected": true,
    "estimated_onset_sim_time": "2024-06-15T14:43:00Z",
    "confidence": 0.81
  },
  "feature_importance": {
    "expected_pax_next_90min": 0.38,
    "hour_of_day": 0.21,
    "weather_category": 0.14,
    "load_factor_avg_today": 0.11,
    "is_special_event": 0.08,
    "adjacent_terminal_congested": 0.05,
    "other": 0.03
  }
}
```

---

## 4. Connection management

A passenger with `connection=true` has a minimum connection time (MCT) of 45 simulated minutes. The service monitors all connecting passengers and triggers alerts when risk is detected.

Connections live on the inbound leg: the passenger is `ON_FLIGHT` an arrival and
`connection_flight_id` names the onward departure (assigned at seed time, see SIMULATION.md).
The check runs every 10 ticks over the connecting passengers of arrival flights whose
estimated time is within `CONNECTION_LOOKBACK_MIN` (default 180) before to
`CONNECTION_LOOKAHEAD_MIN` (default 240) after the sim time, taken from the FlightView and
read by `Flight.id`, not over every live-status passenger.

### Connection risk levels

| Condition                                                     | Risk level | Alert                                                              |
| ------------------------------------------------------------- | ---------- | ------------------------------------------------------------------ |
| Inbound delay: 15–30 min                                      | `watch`    | No alert yet, internal flag                                        |
| Inbound delay: 30–45 min OR time to connection < MCT + 15 min | `at_risk`  | `PassengerAlert` (connection_at_risk)                              |
| Time to connection < MCT                                      | `missed`   | `PassengerAlert` (connection_missed), status → `missed_connection` |

---

## 5. Kafka

### Consumed topics

| Topic              | Event type                         | Action                                                |
| ------------------ | ---------------------------------- | ----------------------------------------------------- |
| `sim.clock`        | `SimClockTick`                     | Advance passenger state machines, drain queues        |
| `flights.events`   | `FlightStatusChanged`              | Detect delays, update connection risk                 |
| `flights.events`   | `FlightGateAssigned`               | Issue gate change alerts to affected pax              |
| `flights.events`   | `FlightCancelled`                  | Mark all on-flight passengers as disrupted            |
| `incidents.events` | `IncidentCreated`                  | Security breach → lock zone; severe weather → monitor |
| `baggage.events`   | `BaggageStatusChanged` (collected) | Advance arrival pax to `departed_airport`             |

### Produced topics

| Topic               | Event type                   | Trigger                                   |
| ------------------- | ---------------------------- | ----------------------------------------- |
| `passengers.events` | `PassengerStatusChanged`     | Event/command-driven transitions (arrival, departure, cancellation, disruption) |
| `passengers.events` | `PassengerStatusBatchChanged` | Every committed tick: all tick transitions (never sampled) |
| `passengers.events` | `PassengerAlert`             | Gate change, connection risk, emergency   |
| `passengers.events` | `SecurityCongestionDetected` | Wait > 20 sim-min for 5 consecutive ticks |

---

## 6. REST API

Base path: `/api/v1`

#### `GET /passengers`

Paginated list of passengers.

Paginate distinct passenger entities before expanding flight metadata. An
existential flight match applies flight-ID/number filters and excludes orphan
passengers without multiplying rows. Order by name and ID for stable pages;
counts and page selection use the same predicates.

The unfiltered path uses the transactional `ON_FLIGHT` relationship count
store under the domain invariant of one outbound assignment per passenger.
Orphans contribute no relationship. Named/identified passengers are read in
name/ID index order before flight metadata expansion. Multiple assignments or
missing required names/IDs are invalid graph data and must be repaired rather
than treated as supported pagination input. Filtered totals count matching
passenger entities using the predicates above.

Query parameters:

| Parameter            | Type    | Description                                  |
| -------------------- | ------- | -------------------------------------------- |
| `flight_id`          | string  | Filter by flight UUID                        |
| `flight_number`      | string  | Filter by flight number                      |
| `status`             | string  | Filter by passenger status (comma-separated) |
| `zone`               | string  | Filter by current location zone              |
| `connection`         | boolean | Only connecting passengers                   |
| `special_assistance` | boolean |                                              |
| `limit`              | integer | default 50, max 500                          |
| `offset`             | integer |                                              |

Response `200`:

```json
{
  "total": 142,
  "limit": 50,
  "offset": 0,
  "passengers": [
    {
      "id": "uuid",
      "name": "Jordan Alvarez",
      "pnr": "ART7X2",
      "flight_number": "AX412",
      "status": "at_gate",
      "location_zone": "gate-B07",
      "seat": "23A",
      "connection": false,
      "special_assistance": false
    }
  ]
}
```

---

#### `GET /passengers/{passenger_id}`

Full passenger detail.

Response `200`:

```json
{
  "id": "uuid",
  "name": "Jordan Alvarez",
  "pnr": "ART7X2",
  "nationality": "US",
  "flight": {
    "id": "uuid",
    "flight_number": "AX412",
    "status": "boarding",
    "gate_id": "B07",
    "estimated_time": "2024-06-15T15:30:00Z"
  },
  "status": "at_gate",
  "location_zone": "gate-B07",
  "seat": "23A",
  "connection": false,
  "baggage": [{ "tag": "0074123456", "status": "loaded" }],
  "alerts": [
    {
      "type": "gate_change",
      "message": "Your flight has moved to gate B07.",
      "issued_at": "2024-06-15T14:35:00Z"
    }
  ],
  "timeline": [
    { "status": "checked_in", "at": "2024-06-15T13:00:00Z" },
    { "status": "security_queue", "at": "2024-06-15T14:00:00Z" },
    { "status": "airside", "at": "2024-06-15T14:12:00Z" },
    { "status": "at_gate", "at": "2024-06-15T14:50:00Z" }
  ]
}
```

---

#### `GET /passengers/search`

Search by PNR or name.

Query parameters: `pnr`, `name` (partial match)

---

#### `GET /flow/summary`

`by_status` and `total_in_airport` use a read snapshot rebuilt from Neo4j before
startup readiness, then refreshed in the background every 15 real seconds after
the preceding read completes. This is a presentation cache, not operational
state or a decision input. Security queues remain the committed owner projection.
Responses expose `counts_observed_sim_time`, `counts_age_seconds` and
`counts_stale`; source failure retains the last successful snapshot and marks it
stale. The observation clock is the owner clock when the read began, not a claim
of a globally historical snapshot. Monotonic elapsed time measures read freshness
only; business time remains driven by `SimClockTick`.

Real-time passenger flow summary across all zones.

Response `200`:

```json
{
  "sim_time": "2024-06-15T14:32:00Z",
  "total_in_airport": 4218,
  "by_status": {
    "checked_in": 312,
    "security_queue": 187,
    "airside": 1402,
    "at_gate": 891,
    "boarded": 743,
    "deplaning": 214,
    "baggage_claim": 469
  },
  "security": {
    "terminal_a": { "queue_depth": 34, "wait_minutes": 11, "lanes_open": 4 },
    "terminal_b": { "queue_depth": 78, "wait_minutes": 22, "lanes_open": 3 },
    "terminal_c": { "queue_depth": 12, "wait_minutes": 4, "lanes_open": 4 }
  },
  "connections_at_risk": 7,
  "connections_missed": 1
}
```

---

#### `GET /flow/heatmap`

Zone-level passenger density for the heatmap dashboard.

Response `200`:

```json
{
  "sim_time": "2024-06-15T14:32:00Z",
  "zones": [
    { "zone_id": "check-in-A", "density": 42, "capacity": 200, "load_pct": 21 },
    { "zone_id": "security-B", "density": 78, "capacity": 120, "load_pct": 65 },
    { "zone_id": "gate-B07", "density": 134, "capacity": 180, "load_pct": 74 },
    { "zone_id": "carousel-3", "density": 89, "capacity": 150, "load_pct": 59 }
  ]
}
```

---

#### `GET /connections/at-risk`

All connecting passengers currently at risk.

Response `200`:

```json
{
  "at_risk": [
    {
      "passenger_id": "uuid",
      "name": "Sam Okonkwo",
      "pnr": "ART9K1",
      "inbound_flight": "AX201",
      "inbound_delay_minutes": 38,
      "connection_flight": "AX508",
      "connection_departs_in_minutes": 52,
      "mct_minutes": 45,
      "risk_level": "at_risk",
      "baggage_count": 1
    }
  ]
}
```

---

#### `GET /alerts`

Recent passenger alerts (last 100 by default).

Query parameters: `type`, `urgency`, `flight_id`, `limit`

---

### WebSocket

#### `WS /ws/passengers`

Streams `PassengerStatusChanged` and `PassengerAlert` events.

Supports filter frame:

```json
{ "filter": { "flight_number": "AX412" } }
```

---

## 7. Zone definitions

| Zone ID                      | Description                        | Capacity |
| ---------------------------- | ---------------------------------- | -------- |
| `check-in-A/B/C`             | Check-in halls per terminal        | 200      |
| `security-A/B/C`             | Security screening checkpoints     | 120      |
| `airside-A/B/C`              | Post-security retail/F&B concourse | 800      |
| `gate-{id}`                  | Individual gate waiting areas      | 120–200  |
| `carousel-1` to `carousel-6` | Baggage claim carousels            | 150      |
| `arrivals-hall`              | Arrivals public hall               | 500      |

---

## 8. Configuration

| Env variable                             | Default             | Description                                  |
| ---------------------------------------- | ------------------- | -------------------------------------------- |
| `NEO4J_URI`                              | `bolt://neo4j:7687` |                                              |
| `NEO4J_USER`                             | `neo4j`             |                                              |
| `NEO4J_PASSWORD`                         | `art-digital-twin`  |                                              |
| `KAFKA_BROKERS`                          | `kafka:9092`        |                                              |
| `SECURITY_LANES_OPEN`                    | `4`                 | Default open lanes per checkpoint            |
| `BOARDING_RATE_PAX_PER_MIN`              | `10`                | Boarding throughput                          |
| `MIN_CONNECTION_TIME_MIN`                | `45`                | MCT in simulated minutes                     |
| `SECURITY_CONGESTION_WAIT_THRESHOLD_MIN` | `20`                | Wait minutes before congestion incident      |
| `SECURITY_CONGESTION_CONSECUTIVE_TICKS`  | `5`                 | Ticks above threshold before firing          |
| `FORECAST_RETRAIN_EVERY_N_DAYS`          | `3`                 | Simulated days between model retrains        |
| `FORECAST_FALLBACK_QUEUE_RATIO`          | `0.35`              | Day-1 fallback: queue = expected_pax × ratio |
| `MODELS_PATH`                            | `/app/models`       | Directory for serialized LightGBM models     |
| `LOG_LEVEL`                              | `INFO`              |                                              |

---

## 9. Health & observability

### Endpoints

| Endpoint       | Description              |
| -------------- | ------------------------ |
| `GET /health`  | Liveness                 |
| `GET /ready`   | Readiness: Neo4j + Kafka |
| `GET /metrics` | Prometheus               |

### Key Prometheus metrics

| Metric                          | Type    | Description                                          |
| ------------------------------- | ------- | ---------------------------------------------------- |
| `passengers_in_airport_total`   | Gauge   | Total pax currently in airport                       |
| `security_queue_depth`          | Gauge   | Queue depth per terminal                             |
| `security_wait_minutes`         | Gauge   | Estimated wait time per terminal                     |
| `connections_at_risk_total`     | Gauge   | Pax with at-risk connections                         |
| `connections_missed_total`      | Counter | Missed connections (cumulative)                      |
| `passengers_missed_flight_total` | Counter | Passengers not boarded when their flight departed (RC5) |
| `passenger_alerts_issued_total` | Counter | Alerts by type                                       |
| `zone_load_pct`                 | Gauge   | Load percentage per zone                             |
| `security_congestion_active`    | Gauge   | 1 if congestion incident active, per terminal        |
| `forecast_queue_depth`          | Gauge   | Predicted queue depth per terminal (next 30 sim-min) |
| `forecast_model_trained`        | Gauge   | 1 if LightGBM model is loaded, per terminal          |
| `forecast_mae`                  | Gauge   | Mean absolute error of last model evaluation         |


### Command execution receipts (Real LDT correction)

`rebook_passengers` remains advisory: passenger IDs and an inbound flight do not
define a replacement itinerary. Until destination/capacity validation and an
atomic `ON_FLIGHT` reassignment are implemented, analysis must not dispatch it.
Previously queued `RebookPassengers` commands receive `CommandRejected` without
mutations. A nonexistent `rebooking` status must not imply successful rebooking.

Accepted commands emit the existing domain fact plus `CommandExecuted`; rejected
commands emit `CommandRejected` with a reason. Both receipts carry `command_id`
and `command_type`, use the current simulation clock, and are stored in Neo4j
for restart-safe redelivery. See `EVENT_BUS.md`, “Real LDT execution and planning
corrections”, for the lifecycle and transaction-boundary limitation.

`OpenSecurityLane` also persists `SecurityCheckpoint.lanes_open`, restores these
overrides on restart, and emits `SecurityLanesChanged` with the previous count.


`SecurityQueueUpdated` is an unsampled aggregate on `passengers.events` with
`terminal`, `queue_depth`, `lanes_open`, `wait_minutes`, `sa_queue_depth`,
`frozen` and `at`. Passenger-service publishes it on every tick in REALTIME and BULK. Analysis uses
these measured snapshots to detect and resolve observed congestion. It does
not invent forecast confidence from an observed wait. This also avoids trying
to reconstruct exact queue counts from sampled per-passenger events.

Before publishing each aggregate, passenger-service saves the validated payload
on `SecurityCheckpoint {terminal}` in Neo4j. The snapshot preserves its own
simulation timestamp `at`, queue depth, lane count and observed wait. It is
unsampled in normal and BULK modes. Analysis
reads these owner snapshots at startup and reconciliation, without advancing its
clock. Observation, tick checkpoint and outbox delivery entries share the owner
transaction. Legacy `SecurityProjection` documents are retained but not updated.


### Forecast correctness verification (2026-10-17)

The forecast API reads the known simulated departure schedule for each future
window, using current weather/incident/adjacent-queue context. It no longer
substitutes five flights and 500 passengers. All future conditions other than
the known schedule are held constant and identified as assumptions. Frozen or
closed checkpoints return the documented 999-minute unavailable-service wait.
Each point labels its actual source (`lightgbm` or `schedule_ratio`), including
fallback after model failure. Congestion `confidence` is nullable and remains
null with `confidence_calibrated=false`; no calibrated probability is available.

Training sorts/deduplicates simulation timestamps before fitting the earliest
80% and evaluates only the later 20%. This corrects the original example's
training/validation leakage. Model promotion and parquet replacement are atomic;
failed writes retain the buffer and previous file. Retraining reports success
only after an artifact is actually written. Synthetic artifact training/reload
tests demonstrate mechanics, not forecast calibration in operational history.

### Security breach ownership and recovery

Security freezes retain each breach's incident identity. Resolving an unrelated
cascade child cannot unfreeze the terminal, and overlapping breaches must all
resolve before security resumes. Active/contained breaches are rebuilt from
Neo4j alongside queues and lane counts on startup.

### Command scheduling under event load

`passengers.commands` has a dedicated consumer (`pax-commands-svc`) in the same
service process. It executes serially on the service's asyncio loop while the
fact/tick consumer awaits database I/O, so a fact backlog cannot starve operator
commands. Commands wait for a validated simulation clock, retain partition order,
and retry transient failures. Offsets are committed after durable receipt handling;
receipts remain replayable from Neo4j. This does not close the domain-write/receipt
transaction gap or provide a transactional Kafka outbox.

### G1 transaction boundary

A clock tick locks `PassengerRuntime` before planning. Its domain writes, durable
runtime checkpoint and pending facts commit in one Neo4j transaction. A failed
attempt discards private queue/cache state; replay at or before the checkpoint
is a no-op. Lane overrides and rebooking commit their receipt and receipt fact
with the domain mutation. Inputs are acknowledged only after successful processing.

Individual tick status notifications remain sampled for display throughput.
`PassengerStatusBatchChanged` is the unsampled audit fact: `status_groups`
(`ids`, `status`, `zone`), `dwell_items`, `location_updates` and `risk_updates`
carry all FSM writes for that tick. Warm-start status cohorts use the same event.

### UI observation timestamps (2026-11-16)

`GET /flow/summary` security rows include nullable `observed_at`: the owner published
simulation clock at the read, not a last-change time or real fetch time.
No owner clock means null. This is read-only response metadata; no domain
mutation or additional Kafka event occurs. See the dashboard observation
contract in `docs/dashboards/UI_IMPLEMENTATION.md`.

### Owner-state reconciliation after missed flight facts (2026-11-16)

**Updated by RC4:** reconciliation runs only for the first `RECONCILE_BOOT_TICKS`
(10) ticks after a start and then every `RECONCILE_INTERVAL_MIN` (60) sim-minutes,
and judges flights on the event-fed FlightView (flights as consumed from
`flights.events`), never on the live Flight nodes, so it cannot run ahead of the
`FlightStatusChanged` handlers it backs up.

A reconciling tick reconciles a bounded cohort of passenger records against the
consumed flight state, in the existing owner tick transaction with outbox facts. A
departed, airborne or finished departure cannot retain booked/checked-in/security/
airside/at-gate passengers: reconcile them to `missed_flight` (RC5), without
claiming a missing boarding event happened; boarded passengers go to
`departed_airport`. Already boarded passengers on departed or
airborne departures also leave airport occupancy. Landed arrivals whose at-gate
fact was missed enter deplaning; diverted arrivals leave airport occupancy.
Only flights already observed by the current simulation clock are eligible.
Original flight/passenger history is retained; reconciliation facts use the
current simulated observation time and identify their recovery reason. A replay
or failed tick cannot publish partial recovery. Normal departure progression
excludes terminal flights, so it cannot overwrite a recovery transition in the
same tick. Physical occupancy includes checked-in, security, airside, gate,
deplaning, customs, baggage-claim and disrupted passengers; booked, airborne,
boarded and departed records are excluded from terminal density.


### Event-fed flight state and BoardingProgress (RC4, 2026-11-16)

Every FSM read that depends on a flight (status, schedule/estimate, gate, terminal,
flight type) takes it from the FlightView fed by `flights.events` (OVERVIEW.md
ADR-007); the graph is traversed only by flight identity (`ON_FLIGHT`). Each tick
also stages `BoardingProgress` (`boarded`/`total` per departure in `boarding`),
which flight-service uses to decide departure. `total` excludes no-shows (RC5).

### Warm start on a fresh simulation (RC5 follow-up, 2026-11-16)

A fresh simulation starts mid-morning-wave: every booked passenger whose
`show_up_at` is already past would otherwise be released on the first tick
(≈4,100 at a 06:00 start), flooding security for about three sim-hours. On the
owner's first tick, each such departing passenger is instead placed where their
own free-flow timeline puts them at the start time, computed from `show_up_at`:

| Start time falls…                                   | Placed as         |
| --------------------------------------------------- | ----------------- |
| before `show_up_at`                                 | stays `booked`    |
| no-show draw (`hash(id) < noshow_rate`)             | `departed_airport` (zone `no-show`) |
| before security entry (`show_up_at + 10`, ≤ T-45)   | `checked_in`      |
| within `WARM_SECURITY_MINUTES` (5) of security entry | `security_queue` (joins the in-memory queue) |
| before gate arrival (`max(T-50, airside + dwell)`)  | `airside`, with the remaining dwell |
| before the passenger's boarding slot (T-35 + rank / 10 pax/min, rank by gate arrival) | `at_gate` |
| at or after that slot                               | `boarded`         |

Only flights still `scheduled` / `boarding` / `delayed` are considered. The
placement is one more contribution to the first tick's atomic transaction (status
writes, dwell, `PassengerStatusBatchChanged`), not a direct write, and the same
tick's check-in rule skips the placed passengers. It runs once per fresh owner
state (`tick_counter == 1`); a restored checkpoint never re-runs it.

### Departure outcome (RC5, 2026-11-16)

On `FlightStatusChanged(departed)` for a departure, in one atomic owner write:
boarded passengers → `departed_airport` (zone `departed`); every passenger still
`booked` / `checked_in` / `security_queue` / `airside` / `at_gate` →
`missed_flight` (zone `missed-flight`, stamps `missed_flight_at`), each with its
own `PassengerStatusChanged`. After commit they leave the in-memory security
queues and zone density, and assisted passengers release their wheelchair.
`missed_flight` is terminal and archived by retention 24 sim-h after
`missed_flight_at`, like `departed_airport`. Metric:
`passengers_missed_flight_total`.

### Source health (RC10, 2026-11-16)

`GET /passengers/source` includes the RC10 `health` block (api-gateway SPEC §5a): `last_observation_at` is the owner's last committed tick (sim).


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

### Terminal retention completion (RC1, 2026-11-19)

`missed_connection` is terminal in this model (no automatic rebooking). It is
archived 24 sim-hours after its owner-written `missed_connection_at`, using an
indexed age seek. Relationships remain; archives purge 168 sim-hours after
archival. Each batch and its `EntitiesArchived`/`EntitiesPurged` fact commit
together. Flight schedule and wall time do not substitute for transition time.

### Durable baggage observations (RC8 / RC12, 2026-11-19)

The passenger owner persists one `PassengerBaggageObservation` per passenger ID,
independently of whether seeding has created that passenger yet. Named
`on_carousel`/`collected` facts commit observation timestamps, durable inbox and
`PassengerBaggageObserved` outbox facts together under the passenger runtime
lock, before acknowledgement. Duplicates and stale carousel inputs cannot erase
collection. No mutable baggage-owner state is read in tick decisions.

Carousel positioning is allowed only while the passenger is `baggage_claim`.
Early observations remain durable until that lifecycle prerequisite is reached.
Arrival tick queries join these owner observations and use only timestamps at
or before the tick. Collected observations include claimants before their
timeout; cached sets are optional accelerators, never the recovery source.
`PassengerBaggageObservation` survives passenger archival and is deleted with
the passenger's archive at purge. Identity links and flight assignments remain.

At startup only, a read-only snapshot of linked live/archived arrival bags in
`on_carousel`/`collected` rebuilds missing observations for active passengers.
This bootstrap handles missing/expired offsets beyond Kafka retention. Persist
the source scan timestamp, and fence its use by owner tick sim time; never
pretend an ahead-of-checkpoint scan happened earlier. Bootstrap uses the same
atomic observation path and durable facts. Anonymous legacy bags cannot prove
collection for an individual passenger and retain the documented timeout.

Observation records with no live or archived passenger expire after
`RETENTION_PURGE_AFTER_H` sim-hours since their latest source observation.
An indexed, bounded background sweep commits deletion with
`PassengerBaggageObservationsPurged`; linked active/archive observations remain
under passenger retention. This bounds obsolete replay records without retaining
whole-history checkpoint sets. `baggage_collected` is retired from snapshots;
legacy checkpoints remain readable and the durable projection supplies progress.
