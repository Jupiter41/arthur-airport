# incident-service — specification

**Language:** Python 3.11+  
**Framework:** FastAPI  
**Port:** 8005  
**Responsibility:** Owns the full lifecycle of hazardous events at KART. Receives both manual injection requests and probabilistic triggers from the sim-orchestrator. Manages cascade propagation, emergency protocol activation, alert generation, and automated incident report creation.

---

## 1. Domain responsibilities

- Own all `Incident` nodes in Neo4j
- Receive manual injection via `incidents.inject` topic
- Evaluate probabilistic event firing on each `SimClockTick`
- Propagate cascades: spawn child incidents and emit `IncidentCascaded` events
- Activate emergency protocols (runway stop, terminal lockdown, evacuation)
- Auto-resolve incidents after TTR (time-to-resolve) elapses
- Generate structured incident reports on resolution
- Produce `IncidentCreated`, `IncidentStatusChanged`, `IncidentCascaded`, and `IncidentAlert` events

---

## 2. Incident types

### 2.1 Runway incursion

A vehicle, aircraft, or person enters an active runway without clearance.

**Severity range:** high → critical  
**Trigger:** probabilistic (0.005/hr, ×2.0 during IMC/LIFR) or manual  
**Immediate effects:**

- Affected runway status → `incident`
- All flights using that runway: `FlightStatusChanged` → `delayed` (go-around / hold)
- If aircraft on approach: go-around instruction emitted
- Protocol: `RUNWAY_STOP` → ATC broadcasts stop command to all ground traffic

**Cascade chain:**

```
runway_incursion
    └── runway_closure_holding_stack    (depth 1: arrivals enter holding)
            └── departure_ground_stop  (depth 2: departures paused)
                    └── gate_congestion (depth 3: gates cannot be vacated)
```

**TTR:** 15–45 simulated minutes  
**Resolution:** Runway inspected, cleared, reopened. Holding stack drained over 20 sim-min.

---

### 2.2 Baggage fire / dangerous goods alert

A fire or DG hazard is detected in the baggage handling area.

**Severity range:** medium → high  
**Trigger:** probabilistic (0.008/hr, ×1.5 during high throughput) or manual  
**Immediate effects:**

- Affected make-up zone offline: throughput → 0
- All baggage in zone: status → `flagged`
- Nearby flights potentially delayed (baggage not loaded)
- Protocol: `BAGGAGE_HOLD` → affected zone evacuated, ARFF notified

**Cascade chain:**

```
baggage_fire
    └── make_up_zone_offline             (depth 1: zone throughput = 0)
            └── flight_baggage_not_loaded (depth 2: affected departures delayed)
```

**TTR:** 20–60 simulated minutes

---

### 2.3 Security breach

An unauthorized individual or object enters a restricted zone.

**Severity range:** medium → critical  
**Trigger:** probabilistic (0.010/hr) or manual  
**Immediate effects:**

- Affected zone status → locked
- All passengers in zone: `PassengerAlert` (zone_lockdown)
- Security lanes in terminal: closed
- Protocol: depends on severity:
  - medium: `ZONE_LOCKDOWN` (one pier)
  - high: `TERMINAL_LOCKDOWN` (full terminal)
  - critical: `FULL_EVACUATION` (all terminals)

**Cascade chain:**

```
security_breach
    └── zone_lockdown                    (depth 1: zone closed)
            └── security_queue_frozen    (depth 2: pax cannot proceed airside)
                    └── boarding_delayed (depth 3: gate boarding delayed)
                            └── flight_delayed (depth 4: departure delayed)
```

**TTR:** 30–90 simulated minutes

---

### 2.4 Severe weather

Driven by the weather FSM rather than independent probability. An `IncidentCreated` of type `severe_weather` is automatically created when weather transitions to `IMC` or `LIFR`.

**Severity:**

- IMC → `medium`
- LIFR → `critical`

**Immediate effects:**

- Runway capacity reduced (handled by flight-service on `WeatherStateChanged`)
- This incident provides the unified alert/cascade view in the dashboard

**Cascade chain:**

```
severe_weather
    └── runway_capacity_reduction        (depth 1: arrival/departure rate drops)
            └── holding_stack            (depth 2: arrivals queued in holding)
                    └── departure_ground_delay (depth 3: departures sequenced)
                            └── flight_delays_cascade (depth 4: all affected flights)
```

**TTR:** Tied to weather FSM — auto-resolved when weather improves to VMC or better.

---

### 2.5 System failure

Infrastructure failure: conveyor jam, power outage, IT system down.

**Severity range:** low → high  
**Trigger:** probabilistic (0.015/hr, ×1.5 during high throughput) or manual  
**Subtypes:**

- `conveyor_jam` — baggage sorting halted
- `power_outage` — terminal power lost (gates, conveyors, displays)
- `it_failure` — check-in systems or FIDS offline

**Cascade chain (conveyor_jam example):**

```
system_failure (conveyor_jam)
    └── baggage_throughput_reduction     (depth 1: sorting offline)
            └── make_up_delay            (depth 2: bags not reaching gates)
                    └── flight_baggage_not_loaded (depth 3: departures delayed)
```

**TTR:** 10–120 simulated minutes (wide range — minor jam vs full power outage)

#### security_congestion subtype

Triggered automatically when `passenger-service` emits `SecurityCongestionDetected` (wait > 20
sim-min for 5 consecutive ticks in a terminal). Not triggered probabilistically — only by the
passenger flow model.

**Severity:** `medium` (wait 20–30 min) → `high` (wait > 30 min)

**Immediate effects:**

- Throughput penalty deepens (slowdown_factor further reduced by 0.15)
- `PassengerAlert` issued to all pax in that terminal's security queue
- Affected terminal flagged on the passenger flow heatmap (orange zone)

**Cascade chain:**

```
system_failure (security_congestion, terminal-B)
    └── boarding_delayed                 (depth 1: gate boarding delayed for terminal-B flights)
            └── flight_departure_delay   (depth 2: departures from terminal-B delayed)
```

**TTR:** Auto-resolved when `security_wait_minutes` drops below 15 for 3 consecutive sim-minutes.
No manual resolution required — the congestion clears itself as flights depart and queue drains.

---

## 3. Cascade engine

### Cascade rules table

Each incident type defines a list of cascade rules. Rules are evaluated in sequence after the parent incident is created.

```python
CASCADE_RULES: dict[IncidentType, list[CascadeRule]] = {
    IncidentType.RUNWAY_INCURSION: [
        CascadeRule(
            child_type="runway_closure_holding_stack",
            delay_sim_minutes=0,
            condition=lambda parent: parent.severity in ["high", "critical"],
            affected_entities=lambda parent: parent.affected_entity_ids,
        ),
        ...
    ]
}
```

### Cascade depth limit

Maximum cascade depth is 5 (configurable). At depth 5, no further child incidents are created — only alerts are emitted.

### Cascade visualization data

The incident service maintains a full cascade tree in Neo4j via `SPAWNED` relationships. This is consumed by the incident dashboard for the cascade effect visualization.

---

## 4. Emergency protocols

| Protocol code        | Trigger                         | Actions                                              |
| -------------------- | ------------------------------- | ---------------------------------------------------- |
| `RUNWAY_STOP`        | Runway incursion (any severity) | All ground traffic stop; approach aircraft go-around |
| `BAGGAGE_HOLD`       | Baggage fire                    | ARFF dispatch; make-up zone evacuated                |
| `ZONE_LOCKDOWN`      | Security breach (medium)        | Pier sealed; security re-screening                   |
| `TERMINAL_LOCKDOWN`  | Security breach (high)          | Terminal closed; all boarding suspended              |
| `FULL_EVACUATION`    | Security breach (critical)      | All terminals; emergency services                    |
| `LOW_VIS_PROCEDURES` | Severe weather (IMC/LIFR)       | CAT II/III ILS; reduced taxi speed                   |

Protocol activation emits a `IncidentAlert` with `sound_alert: true` and `severity: critical` regardless of the incident's own severity field.

---

## 5. Kafka

### Consumed topics

| Topic               | Event type                    | Action                                                  |
| ------------------- | ----------------------------- | ------------------------------------------------------- |
| `sim.clock`         | `SimClockTick`                | Evaluate probabilistic event firing; advance TTR timers |
| `incidents.inject`  | `InjectIncident`              | Create manual incident                                  |
| `weather.events`    | `WeatherStateChanged`         | Auto-create severe_weather incident on IMC/LIFR         |
| `baggage.events`    | `BaggageFlagged` (DG class 3) | Probabilistically trigger baggage_fire                  |
| `passengers.events` | `SecurityCongestionDetected`  | Create security_congestion system_failure incident      |

### Produced topics

| Topic              | Event type              | Trigger                                  |
| ------------------ | ----------------------- | ---------------------------------------- |
| `incidents.events` | `IncidentCreated`       | New incident                             |
| `incidents.events` | `IncidentStatusChanged` | Status change                            |
| `incidents.events` | `IncidentCascaded`      | Cascade child created                    |
| `incidents.alerts` | `IncidentAlert`         | Every new incident + every status change |

---

## 6. REST API

Base path: `/api/v1`

#### `GET /incidents`

All incidents (active, contained, resolved).

Query parameters:

| Parameter  | Type     | Description                                    |
| ---------- | -------- | ---------------------------------------------- |
| `status`   | string   | `active`, `contained`, `resolved`, `escalated` |
| `type`     | string   | Incident type filter                           |
| `severity` | string   | `low`, `medium`, `high`, `critical`            |
| `from`     | datetime | sim time range start                           |
| `to`       | datetime |                                                |
| `limit`    | integer  | default 20, max 100                            |

Response `200`:

```json
{
  "total": 3,
  "incidents": [
    {
      "id": "uuid",
      "type": "runway_incursion",
      "severity": "critical",
      "status": "active",
      "trigger": "probabilistic",
      "title": "Runway incursion — 09L",
      "location": "runway-09L",
      "started_at": "2024-06-15T14:30:00Z",
      "resolved_at": null,
      "affected_entity_ids": ["uuid-flight-1", "uuid-flight-2"],
      "protocol": "RUNWAY_STOP",
      "cascade_depth": 2
    }
  ]
}
```

---

#### `GET /incidents/{incident_id}`

Full incident detail with cascade tree.

Response `200`:

```json
{
  "id": "uuid",
  "type": "runway_incursion",
  "severity": "critical",
  "status": "active",
  "title": "Runway incursion — 09L",
  "description": "Vehicle detected on active runway 09L during approach sequence.",
  "location": "runway-09L",
  "protocol": "RUNWAY_STOP",
  "started_at": "2024-06-15T14:30:00Z",
  "estimated_resolution_at": "2024-06-15T14:55:00Z",
  "cascade_tree": {
    "id": "uuid",
    "type": "runway_incursion",
    "children": [
      {
        "id": "uuid",
        "type": "runway_closure_holding_stack",
        "description": "7 aircraft entered holding pattern.",
        "affected_count": 7,
        "children": [
          {
            "id": "uuid",
            "type": "departure_ground_stop",
            "description": "All 09L departures paused.",
            "affected_count": 4,
            "children": []
          }
        ]
      }
    ]
  },
  "affected_flights": [
    { "flight_number": "AX412", "impact": "go_around", "delay_minutes": 22 },
    { "flight_number": "BK201", "impact": "holding", "delay_minutes": 18 }
  ],
  "timeline": [
    {
      "status": "active",
      "note": "Incident created",
      "at": "2024-06-15T14:30:00Z"
    },
    {
      "status": "active",
      "note": "RUNWAY_STOP protocol sent",
      "at": "2024-06-15T14:30:05Z"
    },
    {
      "status": "active",
      "note": "Holding stack: 7 aircraft",
      "at": "2024-06-15T14:31:00Z"
    }
  ]
}
```

---

#### `POST /incidents/inject`

Manually inject a hazardous event (also available via the dashboard UI).

Request body:

```json
{
  "type": "security_breach",
  "severity": "high",
  "location": "gate-B07",
  "description": "Unattended bag reported at gate B07."
}
```

Response `201`: created incident object.

---

#### `POST /incidents/{incident_id}/contain`

Manually mark incident as contained (investigation ongoing, immediate hazard neutralised).

Request body:

```json
{ "note": "Vehicle removed from runway. Inspection underway." }
```

---

#### `POST /incidents/{incident_id}/resolve`

Manually resolve an incident.

Request body:

```json
{ "note": "Runway cleared and inspected. Normal operations resumed." }
```

---

#### `GET /incidents/{incident_id}/report`

Returns the auto-generated incident report.

Response `200`:

```json
{
  "incident_id": "uuid",
  "report_generated_at": "2024-06-15T14:58:00Z",
  "title": "Runway Incursion — Runway 09L — 2024-06-15 14:30Z",
  "type": "runway_incursion",
  "severity": "critical",
  "trigger": "probabilistic",
  "timeline_summary": "Incursion detected at 14:30Z. RUNWAY_STOP protocol activated. Holding stack of 7 aircraft formed. Runway cleared at 14:52Z. 22 minutes of disruption.",
  "total_flights_affected": 9,
  "total_delay_minutes_caused": 198,
  "cascade_events": 3,
  "protocols_activated": ["RUNWAY_STOP"],
  "recommendations": [
    "Review ground vehicle tracking procedures.",
    "Consider additional runway guard installations."
  ]
}
```

---

#### `GET /alerts`

Current active alerts for the dashboard notification panel.

Response `200`:

```json
{
  "alerts": [
    {
      "incident_id": "uuid",
      "severity": "critical",
      "title": "CRITICAL — Runway incursion on 09L",
      "short_message": "RUNWAY_STOP active. All 09L operations suspended.",
      "affected_zones": ["runway-09L"],
      "dashboard_color": "red",
      "sound_alert": true,
      "age_minutes": 3,
      "at": "2024-06-15T14:30:00Z"
    }
  ]
}
```

---

### WebSocket

#### `WS /ws/incidents`

Streams all incident events in real time. Always receives `IncidentAlert` payloads without requiring a filter.

---

## 7. Configuration

| Env variable                      | Default             | Description                      |
| --------------------------------- | ------------------- | -------------------------------- |
| `NEO4J_URI`                       | `bolt://neo4j:7687` |                                  |
| `NEO4J_USER`                      | `neo4j`             |                                  |
| `NEO4J_PASSWORD`                  | `art-digital-twin`  |                                  |
| `KAFKA_BROKERS`                   | `kafka:9092`        |                                  |
| `CASCADE_MAX_DEPTH`               | `5`                 | Maximum cascade tree depth       |
| `PROB_RUNWAY_INCURSION_PER_HR`    | `0.005`             | Base probability                 |
| `PROB_BAGGAGE_FIRE_PER_HR`        | `0.008`             | Base probability                 |
| `PROB_SECURITY_BREACH_PER_HR`     | `0.010`             | Base probability                 |
| `PROB_SYSTEM_FAILURE_PER_HR`      | `0.015`             | Base probability                 |
| `INCIDENT_SUPPRESSION_WINDOW_HRS` | `2`                 | Post-incident suppression window |
| `LOG_LEVEL`                       | `INFO`              |                                  |

---

## 8. Health & observability

### Endpoints

| Endpoint       | Description |
| -------------- | ----------- |
| `GET /health`  | Liveness    |
| `GET /ready`   | Readiness   |
| `GET /metrics` | Prometheus  |

### Key Prometheus metrics

| Metric                                | Type      | Description                                                |
| ------------------------------------- | --------- | ---------------------------------------------------------- |
| `incidents_active_total`              | Gauge     | Active incidents by type                                   |
| `incidents_created_total`             | Counter   | All incidents created, labelled by type, severity, trigger |
| `incident_ttr_minutes`                | Histogram | Time-to-resolve distribution                               |
| `cascade_events_total`                | Counter   | Child incidents spawned                                    |
| `cascade_depth_max`                   | Gauge     | Deepest cascade in last 24 sim-hours                       |
| `protocols_activated_total`           | Counter   | Emergency protocols by code                                |
| `flights_impacted_by_incidents_total` | Counter   | Flights affected by incidents                              |
