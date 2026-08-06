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

| Topic               | Producer                     | Consumers                                                                       | Retention |
| ------------------- | ---------------------------- | ------------------------------------------------------------------------------- | --------- |
| `sim.clock`         | sim-orchestrator             | all services                                                                    | 1h        |
| `flights.events`    | flight-service               | passenger-service, baggage-service, incident-service, cost-service, api-gateway | 7 days    |
| `flights.schedule`  | sim-orchestrator             | flight-service                                                                  | 7 days    |
| `passengers.events` | passenger-service            | incident-service, cost-service, api-gateway                                     | 7 days    |
| `baggage.events`    | baggage-service              | cost-service, api-gateway                                                       | 7 days    |
| `weather.events`    | weather-service              | flight-service, incident-service, api-gateway                                   | 7 days    |
| `incidents.events`  | incident-service             | flight-service, passenger-service, baggage-service, cost-service, api-gateway   | 30 days   |
| `incidents.alerts`  | incident-service             | api-gateway                                                                     | 30 days   |
| `incidents.inject`  | api-gateway (manual trigger) | incident-service                                                                | 1h        |
| `flights.commands`     | api-gateway, analysis-service | flight-service                                                              | 1h        |
| `passengers.commands`  | api-gateway, analysis-service | passenger-service                                                           | 1h        |
| `baggage.commands`     | api-gateway, analysis-service | baggage-service                                                             | 1h        |
| `cost.events`          | cost-service                 | api-gateway                                                                  | 7 days    |
| `analysis.events`      | analysis-service             | api-gateway                                                                  | 7 days    |

---

## 3. Partition and consumer group strategy

| Topic               | Partitions | Key              | Consumer groups                                           |
| ------------------- | ---------- | ---------------- | --------------------------------------------------------- |
| `sim.clock`         | 1          | —                | all services (broadcast)                                  |
| `flights.events`    | 6          | `flight_id`      | `pax-svc`, `bag-svc`, `inc-svc`, `cost-svc`, `gateway`    |
| `passengers.events` | 6          | `passenger_id`   | `cost-svc`, `gateway`                                     |
| `baggage.events`    | 6          | `baggage_tag`    | `cost-svc`, `gateway`                                     |
| `weather.events`    | 1          | —                | `flight-svc`, `inc-svc`, `gateway`                        |
| `incidents.events`  | 3          | `incident_id`    | `flight-svc`, `pax-svc`, `bag-svc`, `cost-svc`, `gateway` |
| `incidents.alerts`  | 3          | `incident_id`    | `gateway`                                                 |
| `incidents.inject`  | 1          | —                | `inc-svc`                                                 |
| `flights.commands`    | 6          | `flight_id`      | `flight-svc`                                            |
| `passengers.commands` | 3          | `terminal`       | `pax-svc`                                               |
| `baggage.commands`    | 6          | `bag_id`         | `bag-svc`                                               |
| `cost.events`         | 3          | `cost_record_id` | `gateway`                                               |
| `analysis.events`     | 1          | entity id / —    | `gateway`                                               |

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

#### `WheelchairDispatched` (1C)

Emitted when a wheelchair is assigned to a SA passenger. `wait_minutes` is the
queue wait between request and dispatch (0 if served immediately).

```json
{
  "event_type": "WheelchairDispatched",
  "payload": {
    "assignment_id": "uuid",
    "passenger_id": "uuid",
    "terminal": "B",
    "flight_id": "uuid",
    "wait_minutes": 0.0,
    "at": "2024-06-15T13:18:00Z"
  }
}
```

#### `WheelchairReturned` (1C)

Emitted when the SA passenger boards (chair freed). `sla_met` is true when
the passenger reached the gate before the configured boarding cutoff (T-15 by
default; ECAC Doc 30 reference).

```json
{
  "event_type": "WheelchairReturned",
  "payload": {
    "assignment_id": "uuid",
    "passenger_id": "uuid",
    "terminal": "B",
    "sla_met": true,
    "at": "2024-06-15T14:55:00Z"
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

### 4.8b `flights.commands` — operator/agent command input

**Commands, not facts.** Unlike every other topic in this catalogue, `flights.commands` carries
*imperatives* ("do this"), not facts ("this happened"). It is the intent channel: the API gateway
(operator actions from the dashboard) and the analysis-service (autonomous/approved recommendations)
publish commands here; **flight-service is the sole consumer and the sole authority** that decides
whether to execute them. Executing a command still produces the normal facts on `flights.events`
(`FlightStatusChanged` for a hold, `FlightGateAssigned` for a gate reassignment) — so downstream
services never consume commands, only the resulting facts. This preserves the "services react to
facts" rule while giving a single, auditable place for human/agent intent.

Command envelope (distinct from the fact envelope — keyed on `command_type`, not `event_type`):

```json
{
  "command_type": "HoldFlight",
  "command_id": "b1c2d3e4-...",
  "issued_by": "operator-dashboard",
  "issued_at": "2024-06-15T14:45:00.000Z",
  "payload": { "flight_id": "AR1234-...", "reason": "gate_conflict", "duration_min": 20 }
}
```

- `command_id` (UUID) is required and used for **idempotency** — flight-service dedupes on it exactly
  like `event_id`, so an at-least-once redelivery executes once.
- `issued_by` / `issued_at` are audit metadata. `issued_at` is wall-clock; the executor stamps the
  resulting fact with the current `sim_time` from `sim.clock` (commands do not carry sim time).
- Commands are validated by flight-service and may be **rejected** (bad payload, unknown flight, or a
  precondition failure — e.g. a hold is only accepted from `boarding` / `scheduled` / `approach`).
  A rejected command produces no fact.

Supported commands:

| `command_type` | payload fields                                  | Effect on accept                                         |
| -------------- | ----------------------------------------------- | -------------------------------------------------------- |
| `HoldFlight`   | `flight_id`, `reason`, `duration_min`           | Flight → `delayed`; emits `FlightStatusChanged`          |
| `ReassignGate` | `flight_id`, `gate_id`                          | Re-links `ASSIGNED_TO`; emits `FlightGateAssigned`       |

`HoldFlight.duration_min` also accepts the legacy key `expected_duration_minutes` (the REST
`HoldRequest` field name).

---

### 4.8c `analysis.events` — analysis-service facts

Facts emitted by the analysis-service as it detects bottlenecks, generates recommendations, and
runs autonomous mode. All are facts ("this happened / this was proposed"), consumed only by the API
gateway for dashboard fan-out. Event types on this topic:

| `event_type`              | Emitted when                                                        | Key           |
| ------------------------- | ------------------------------------------------------------------- | ------------- |
| `BottleneckDetected`      | A new bottleneck crosses a detection threshold                      | bottleneck id |
| `BottleneckResolved`      | A previously-detected bottleneck clears                             | bottleneck id |
| `RecommendationGenerated` | A recommendation is produced for an active bottleneck               | rec id        |
| `ActionProposed`          | A proposal is enqueued for human approval or auto-approved (A9)     | proposal id   |
| `AutonomousActionApplied` | An action was applied (auto, operator "Apply", or approved proposal)| action id     |
| `AnomalyDetected`         | The anomaly detector flags a deviation from baseline                | `anomaly`     |
| `NarrationGenerated`      | A narration line is produced                                        | `narration`   |

**`ActionProposed` (A9).** The autonomous engine no longer silently applies or silently drops
candidate actions — every candidate becomes a **Proposal** routed through the approval queue.
Safety-guarded actions (`ground_delay_program`, `rebook_passengers`) and any that need a human are
enqueued `pending`; confident, unguarded, non-blocked actions are auto-approved and executed. Both
paths emit `ActionProposed` so the dashboard can show the queue and the audit trail.

```json
{
  "event_type": "ActionProposed",
  "producer": "analysis-service",
  "payload": {
    "id": "prop-a1b2c3d4e5f6",
    "action_type": "ground_delay_program",
    "description": "Impose a 15-min ground delay program on arrivals",
    "parameters": { "delay_minutes": 15 },
    "confidence_score": 0.91,
    "proposed_by": "autonomous",
    "proposed_at": "2024-06-15T14:45:00.000Z",
    "recommendation_id": "rec-...",
    "bottleneck_id": "bn-...",
    "status": "pending",
    "requires_human": true
  }
}
```

When an operator approves a proposal that targets a **concrete flight**, the analysis-service maps it
to a `flights.commands` command (`HoldFlight` / `ReassignGate`, see §4.8b) and publishes it there —
aggregate/terminal-level proposals carry no concrete `flight_id` and are recorded as facts only.

---

### 4.8d `passengers.commands` — passenger-service command input

Same envelope contract as `flights.commands` (§4.8b): keyed on `command_type`; `command_id` for
idempotency; `issued_by`/`issued_at` audit metadata; no `sim_time` — passenger-service uses the
current clock when executing.

**Supported commands**

| `command_type`     | Required payload fields          | Effect |
|--------------------|----------------------------------|--------|
| `OpenSecurityLane` | `terminal` (A/B/C), `lanes_open` (1–20) | Sets the number of open lanes at the named terminal checkpoint immediately; next drain tick reflects the new capacity. |

**Rejection semantics:** unknown `command_type`, missing/invalid `terminal`, non-positive or out-of-range `lanes_open`, or no clock tick yet received → rejected, no side effect, counter incremented.

**Example:**
```json
{
  "command_type": "OpenSecurityLane",
  "command_id": "cmd-...",
  "issued_by": "operator",
  "issued_at": "2024-06-15T14:50:00.000Z",
  "payload": {
    "terminal": "B",
    "lanes_open": 6
  }
}
```

---

### 4.8e `baggage.commands` — baggage-service command input

Same envelope contract as `flights.commands` (§4.8b).

**Supported commands**

| `command_type`   | Required payload fields                      | Effect |
|------------------|----------------------------------------------|--------|
| `RedirectBaggage` | `bag_id`, `target_flight_id` (must differ) | Re-assigns the `LOADED_ON` relationship in Neo4j to the target flight, removes the bag from its current conveyor zone, updates `last_scan_zone` to `"redirected"`, and emits `BaggageStatusChanged`. |

**Rejection semantics:** unknown `command_type`, missing/empty `bag_id` or `target_flight_id`, `bag_id == target_flight_id`, bag not found in Neo4j, target flight not found in Neo4j → rejected, no side effect.

**Example:**
```json
{
  "command_type": "RedirectBaggage",
  "command_id": "cmd-...",
  "issued_by": "operator",
  "issued_at": "2024-06-15T14:52:00.000Z",
  "payload": {
    "bag_id": "bag-uuid-...",
    "target_flight_id": "flight-uuid-..."
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

### CostRecorded

Topic: `cost.events`  
Producer: cost-service  
Triggered: whenever a CostRecord is written to Neo4j

```json
{
  "event_id": "uuid",
  "event_type": "CostRecorded",
  "schema_version": "1.0",
  "produced_at": "2024-06-15T14:32:00Z",
  "sim_time": "2024-06-15T14:32:00Z",
  "producer": "cost-service",
  "payload": {
    "cost_record_id": "uuid",
    "category": "eu261_compensation",
    "amount_eur": 18600.0,
    "is_revenue": false,
    "flight_id": "uuid | null",
    "incident_id": "uuid | null",
    "description": "EU261 — 31 pax × €600 (long-haul, delay 240min)",
    "sim_time": "2024-06-15T14:32:00Z",
    "sim_day": 1
  }
}
```

### CarbonRecorded

Topic: `cost.events`  
Producer: cost-service (1A — Carbon Footprint Tracker)  
Triggered: whenever a CarbonRecord is written to Neo4j (flight departure, terminal energy tick, ground vehicle turnaround)

```json
{
  "event_id": "uuid",
  "event_type": "CarbonRecorded",
  "schema_version": "1.0",
  "produced_at": "2024-06-15T14:32:00Z",
  "sim_time": "2024-06-15T14:32:00Z",
  "producer": "cost-service",
  "payload": {
    "carbon_record_id": "uuid",
    "source": "flight",
    "co2_kg": 18421.5,
    "flight_id": "uuid | null",
    "description": "Flight emissions — AX204 (180 pax × 1450 km)",
    "sim_time": "2024-06-15T14:32:00Z",
    "sim_day": 1
  }
}
```

`source` is one of: `flight` (Scope 3, ICAO methodology), `apu` (Scope 1, ICAO Doc 9889 reference burn rates), `terminal` (Scope 2, ACI energy benchmarks × EU grid intensity), `ground_vehicle` (Scope 1, GSE per turnaround).

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
