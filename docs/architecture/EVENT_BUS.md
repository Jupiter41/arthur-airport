# Event bus — Kafka topics & schemas

**Project:** Arthur International Airport Digital Twin  
**Broker:** Apache Kafka 3.x  
**Schema format:** JSON (Avro-compatible, Schema Registry optional)

---

## 1. Design principles

- **Every state change produces an event.** No service mutates another service's data directly.
- **Events are facts, not commands.** A topic named `flights.events` carries `FlightStatusChanged` facts — not `UpdateFlight` commands.
- **Topics are domain-scoped.** One topic family per domain. Sub-topics use dot notation.
- **Consumers are idempotent.** Every consumer handles duplicate delivery gracefully (events carry a UUID `event_id`).
- **The simulation clock is a first-class topic.** All services synchronise simulated time from `sim.clock`.

---

## 2. Topic catalogue

| Topic               | Producer                     | Consumers                                                         | Retention |
| ------------------- | ---------------------------- | ----------------------------------------------------------------- | --------- |
| `sim.clock`         | sim-orchestrator             | all services                                                      | 1h        |
| `flights.events`    | flight-service               | passenger-service, baggage-service, incident-service, api-gateway | 7 days    |
| `flights.schedule`  | sim-orchestrator             | flight-service                                                    | 7 days    |
| `passengers.events` | passenger-service            | `incident-svc`, `gateway`                                         | 7 days    |
| `baggage.events`    | baggage-service              | api-gateway                                                       | 7 days    |
| `weather.events`    | weather-service              | flight-service, incident-service, api-gateway                     | 7 days    |
| `incidents.events`  | incident-service             | flight-service, passenger-service, baggage-service, api-gateway   | 30 days   |
| `incidents.alerts`  | incident-service             | api-gateway                                                       | 30 days   |
| `incidents.inject`  | api-gateway (manual trigger) | incident-service                                                  | 1h        |

---

## 3. Partition and consumer group strategy

| Topic               | Partitions | Key            | Consumer groups                               |
| ------------------- | ---------- | -------------- | --------------------------------------------- |
| `sim.clock`         | 1          | —              | all services (broadcast)                      |
| `flights.events`    | 6          | `flight_id`    | `pax-svc`, `bag-svc`, `inc-svc`, `gateway`    |
| `passengers.events` | 6          | `passenger_id` | `gateway`                                     |
| `baggage.events`    | 6          | `baggage_tag`  | `gateway`                                     |
| `weather.events`    | 1          | —              | `flight-svc`, `inc-svc`, `gateway`            |
| `incidents.events`  | 3          | `incident_id`  | `flight-svc`, `pax-svc`, `bag-svc`, `gateway` |
| `incidents.alerts`  | 3          | `incident_id`  | `gateway`                                     |
| `incidents.inject`  | 1          | —              | `inc-svc`                                     |

---

## 4. Event schemas

All events share a common envelope:

```json
{
  "event_id": "uuid-v4",
  "event_type": "FlightStatusChanged",
  "schema_version": "1.0",
  "produced_at": "2024-06-15T14:32:00.000Z",
  "sim_time": "2024-06-15T14:32:00.000Z",
  "producer": "flight-service",
  "payload": { ... }
}
```

---

### 4.1 `sim.clock` — `SimClockTick`

Emitted every simulated minute. All services use this to advance their internal clocks.

```json
{
  "event_type": "SimClockTick",
  "payload": {
    "sim_time": "2024-06-15T14:32:00.000Z",
    "real_time": "2024-06-15T10:15:03.412Z",
    "speed_multiplier": 60,
    "tick_number": 87243,
    "day_of_sim": 3,
    "step_minutes": 1,
    "mode": "REALTIME"
  }
}
```

`mode` is one of `REALTIME` (≤60×), `FAST` (≤600×), or `BULK` (>600×).
`step_minutes` is the number of simulated minutes per tick (usually 1; higher in BULK mode).

---

### 4.2 `flights.events`

#### `FlightStatusChanged`

Emitted whenever a flight transitions between states.

```json
{
  "event_type": "FlightStatusChanged",
  "payload": {
    "flight_id": "uuid",
    "flight_number": "AX412",
    "previous_status": "scheduled",
    "new_status": "delayed",
    "delay_minutes": 45,
    "delay_reason": "inbound_aircraft_late",
    "gate_id": "B07",
    "estimated_time": "2024-06-15T15:17:00.000Z",
    "affected_pax_count": 178
  }
}
```

#### `FlightGateAssigned`

```json
{
  "event_type": "FlightGateAssigned",
  "payload": {
    "flight_id": "uuid",
    "flight_number": "AX412",
    "previous_gate_id": "B07",
    "new_gate_id": "C12",
    "reason": "cascade_delay_reassignment",
    "effective_at": "2024-06-15T14:35:00.000Z"
  }
}
```

#### `FlightRunwayAssigned`

```json
{
  "event_type": "FlightRunwayAssigned",
  "payload": {
    "flight_id": "uuid",
    "flight_number": "AX412",
    "runway_id": "09L",
    "operation": "landing",
    "scheduled_at": "2024-06-15T15:20:00.000Z"
  }
}
```

#### `FlightCancelled`

```json
{
  "event_type": "FlightCancelled",
  "payload": {
    "flight_id": "uuid",
    "flight_number": "AX412",
    "reason": "severe_weather",
    "affected_pax_count": 178,
    "rebooking_required": true
  }
}
```

---

### 4.3 `passengers.events`

#### `PassengerStatusChanged`

```json
{
  "event_type": "PassengerStatusChanged",
  "payload": {
    "passenger_id": "uuid",
    "pnr": "ART7X2",
    "flight_id": "uuid",
    "previous_status": "security_queue",
    "new_status": "airside",
    "location_zone": "security-exit-B",
    "at": "2024-06-15T14:10:00.000Z"
  }
}
```

#### `PassengerAlert`

```json
{
  "event_type": "PassengerAlert",
  "payload": {
    "passenger_id": "uuid",
    "pnr": "ART7X2",
    "alert_type": "gate_change",
    "message": "Your flight AX412 has moved to gate C12.",
    "urgency": "medium",
    "at": "2024-06-15T14:35:00.000Z"
  }
}
```

#### `SecurityCongestionDetected`

```json
{
  "event_type": "SecurityCongestionDetected",
  "payload": {
    "terminal": "B",
    "queue_depth": 103,
    "wait_minutes": 34,
    "consecutive_ticks_over_threshold": 6,
    "effective_throughput_pax_per_hr": 312,
    "slowdown_factor": 0.58,
    "forecast_queue_depth": 67,
    "at": "2024-06-15T14:43:00Z"
  }
}
```

---

### 4.4 `baggage.events`

#### `BaggageStatusChanged`

```json
{
  "event_type": "BaggageStatusChanged",
  "payload": {
    "baggage_id": "uuid",
    "tag": "0074123456",
    "passenger_id": "uuid",
    "flight_id": "uuid",
    "previous_status": "sorting",
    "new_status": "loaded",
    "scan_zone": "make-up-area-B",
    "at": "2024-06-15T13:55:00.000Z"
  }
}
```

#### `BaggageFlagged`

```json
{
  "event_type": "BaggageFlagged",
  "payload": {
    "baggage_id": "uuid",
    "tag": "0074123456",
    "passenger_id": "uuid",
    "flight_id": "uuid",
    "flag_reason": "dangerous_goods_detected",
    "dg_class": "9",
    "scan_zone": "screening-unit-3",
    "at": "2024-06-15T13:50:00.000Z"
  }
}
```

---

### 4.5 `weather.events`

#### `WeatherStateChanged`

```json
{
  "event_type": "WeatherStateChanged",
  "payload": {
    "weather_id": "uuid",
    "previous_category": "VMC",
    "new_category": "IMC",
    "visibility_m": 800,
    "wind_direction": 270,
    "wind_speed_kt": 28,
    "wind_gust_kt": 42,
    "ceiling_ft": 500,
    "temperature_c": 4.2,
    "phenomena": ["TS", "RA"],
    "runway_impact": "reduced_rate",
    "recommended_arrival_rate": 18,
    "recommended_departure_rate": 16,
    "at": "2024-06-15T14:28:00.000Z"
  }
}
```

#### `METARIssued`

Full METAR string for developer / dashboard display.

```json
{
  "event_type": "METARIssued",
  "payload": {
    "raw": "KART 151428Z 27028G42KT 8000 TS RA BKN015 OVC050 04/02 Q1002",
    "at": "2024-06-15T14:28:00.000Z"
  }
}
```

---

### 4.6 `incidents.events`

#### `IncidentCreated`

```json
{
  "event_type": "IncidentCreated",
  "payload": {
    "incident_id": "uuid",
    "type": "runway_incursion",
    "severity": "critical",
    "trigger": "probabilistic",
    "title": "Runway incursion — 09L",
    "description": "Vehicle detected on active runway 09L during approach sequence.",
    "location": "runway-09L",
    "affected_entity_ids": ["flight-uuid-1", "flight-uuid-2"],
    "protocol": "RUNWAY_STOP",
    "started_at": "2024-06-15T14:30:00.000Z"
  }
}
```

#### `IncidentStatusChanged`

```json
{
  "event_type": "IncidentStatusChanged",
  "payload": {
    "incident_id": "uuid",
    "previous_status": "active",
    "new_status": "contained",
    "update_note": "Vehicle removed, runway inspection underway.",
    "at": "2024-06-15T14:38:00.000Z"
  }
}
```

#### `IncidentCascaded`

Emitted when an incident spawns a child incident/effect.

```json
{
  "event_type": "IncidentCascaded",
  "payload": {
    "parent_incident_id": "uuid",
    "child_incident_id": "uuid",
    "cascade_type": "runway_closure_causes_holding_stack",
    "description": "Runway 09L closure has caused 7 aircraft to enter holding pattern.",
    "affected_entity_ids": ["flight-uuid-1", "..."],
    "at": "2024-06-15T14:31:00.000Z"
  }
}
```

---

### 4.7 `incidents.alerts`

#### `IncidentAlert`

Pushed to dashboards as real-time notifications.

```json
{
  "event_type": "IncidentAlert",
  "payload": {
    "incident_id": "uuid",
    "severity": "critical",
    "title": "CRITICAL — Runway incursion on 09L",
    "short_message": "All departures from 09L suspended. Go-around issued to AX412.",
    "affected_zones": ["runway-09L", "gate-B07", "gate-B09"],
    "dashboard_color": "red",
    "sound_alert": true,
    "at": "2024-06-15T14:30:00.000Z"
  }
}
```

---

### 4.8 `incidents.inject` — manual trigger input

Sent by the API gateway (from the dashboard) to manually fire a hazardous event.

```json
{
  "event_type": "InjectIncident",
  "payload": {
    "type": "baggage_fire",
    "severity": "high",
    "location": "make-up-area-B",
    "trigger": "manual",
    "requested_by": "operator-dashboard",
    "at": "2024-06-15T14:45:00.000Z"
  }
}
```

---

### 4.9 `BulkStateSnapshot` (emitted on originating topic)

In BULK mode (speed > 600×), individual per-entity events are suppressed. Instead,
each service emits a `BulkStateSnapshot` on its own topic every 60 sim-minutes.
The snapshot summarises aggregate state.

Emitted on: `flights.events`, `passengers.events`, `baggage.events`

```json
{
  "event_type": "BulkStateSnapshot",
  "producer": "flight-service",
  "payload": {
    "service": "flight-service",
    "summary": {
      "by_status": {
        "at_gate": 120,
        "boarding": 8,
        "scheduled": 45
      },
      "active_turnarounds": 12,
      "held_flights": 2,
      "affected_runways": ["09L"],
      "affected_gates": ["B07"]
    }
  }
}
```

The `summary` structure varies per service:

- **flight-service**: `by_status`, `active_turnarounds`, `held_flights`, `affected_runways`, `affected_gates`
- **passenger-service**: `by_status` (status → count map)
- **baggage-service**: `by_stage` (pipeline stage → count map)

---

## 5. Dead letter queue

Failed or unprocessable messages are routed to `{topic}.dlq` (e.g. `flights.events.dlq`). Each DLQ message includes:

```json
{
  "original_topic": "flights.events",
  "original_offset": 10482,
  "error": "ValidationError: missing field flight_id",
  "raw_value": "...",
  "failed_at": "2024-06-15T14:31:05.000Z"
}
```

---

## 6. Schema evolution rules

1. **Additive changes only** — new optional fields may be added to any payload without a version bump.
2. **Breaking changes** — removing or renaming fields requires a `schema_version` increment and a migration period where both versions are consumed.
3. **Consumers must ignore unknown fields** — all consumers use lenient deserialization (no strict schema enforcement in MVP).
