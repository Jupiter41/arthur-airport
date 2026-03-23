# passenger-service — specification

**Language:** Python 3.11+  
**Framework:** FastAPI  
**Port:** 8002  
**Responsibility:** Tracks every passenger through the airport from check-in to boarding (departures) or from landing to airport exit (arrivals). Generates alerts for gate changes, connection risks, and emergency protocols.

---

## 1. Domain responsibilities

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
checked_in
    │
    ▼ (sim: check-in closes T-45 min)
security_queue
    │
    ▼ (sim: throughput rate, queue drain model)
airside
    │
    ▼ (sim: T-30 min gate open)
at_gate
    │
    ▼ (sim: boarding call T-20 min)
boarded
```

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

### State transition rules

| Transition                           | Trigger                                     | Notes                                          |
| ------------------------------------ | ------------------------------------------- | ---------------------------------------------- |
| `checked_in` → `security_queue`      | SimClockTick: check-in cutoff T-45          | Batched — all pax on flight move together      |
| `security_queue` → `airside`         | SimClockTick: per queue drain rate          | Rate = `security_lanes_open × 180 pax/hr/lane` |
| `airside` → `at_gate`                | SimClockTick: T-30 min OR gate open         | Stochastic: ~80% arrive before T-15 min        |
| `at_gate` → `boarded`                | SimClockTick: boarding call                 | Progressive: 10 pax/min boarding rate          |
| `deplaning` → `baggage_claim`        | SimClockTick: T+15 after at_gate            | All arrival pax                                |
| `baggage_claim` → `departed_airport` | BaggageStatusChanged (collected) OR timeout | Timeout = T+45 min                             |

---

## 3. Queue and flow model

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
```

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
`/app/models/forecast_{terminal}.lgbm` and hot-reloaded after each training run.

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
| `passengers.events` | `PassengerStatusChanged`     | Any status/location transition            |
| `passengers.events` | `PassengerAlert`             | Gate change, connection risk, emergency   |
| `passengers.events` | `SecurityCongestionDetected` | Wait > 20 sim-min for 5 consecutive ticks |

---

## 6. REST API

Base path: `/api/v1`

#### `GET /passengers`

Paginated list of passengers.

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
| `passenger_alerts_issued_total` | Counter | Alerts by type                                       |
| `zone_load_pct`                 | Gauge   | Load percentage per zone                             |
| `security_congestion_active`    | Gauge   | 1 if congestion incident active, per terminal        |
| `forecast_queue_depth`          | Gauge   | Predicted queue depth per terminal (next 30 sim-min) |
| `forecast_model_trained`        | Gauge   | 1 if LightGBM model is loaded, per terminal          |
| `forecast_mae`                  | Gauge   | Mean absolute error of last model evaluation         |
