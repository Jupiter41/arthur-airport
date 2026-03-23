# Monitoring — Prometheus & Grafana

**Project:** Arthur International Airport Digital Twin  
**Stack:** Prometheus 2.x · Grafana 10.x  
**Ports:** Prometheus `9090` · Grafana `3001`

---

## 1. Overview

Every service in the KART digital twin exposes a `/metrics` endpoint in Prometheus text format. Prometheus scrapes all endpoints on a 5-second interval. Grafana reads from Prometheus and provides five pre-built dashboards — one per operational domain — plus a system health overview.

This document defines the full metrics catalogue, scrape configuration, alerting rules, and Grafana dashboard layout for each panel.

---

## 2. Prometheus scrape configuration

```yaml
# prometheus.yml
global:
  scrape_interval:     5s
  evaluation_interval: 5s

rule_files:
  - "alerts.yml"

scrape_configs:
  - job_name: flight-service
    static_configs:
      - targets: ['flight-service:8001']

  - job_name: passenger-service
    static_configs:
      - targets: ['passenger-service:8002']

  - job_name: baggage-service
    static_configs:
      - targets: ['baggage-service:8003']

  - job_name: weather-service
    static_configs:
      - targets: ['weather-service:8004']

  - job_name: incident-service
    static_configs:
      - targets: ['incident-service:8005']

  - job_name: sim-orchestrator
    static_configs:
      - targets: ['sim-orchestrator:8006']

  - job_name: api-gateway
    static_configs:
      - targets: ['api-gateway:3000']

  - job_name: kafka
    static_configs:
      - targets: ['kafka-exporter:9308']

  - job_name: neo4j
    static_configs:
      - targets: ['neo4j:2004']
```

---

## 3. Full metrics catalogue

### 3.1 Simulation

| Metric | Type | Labels | Description |
|---|---|---|---|
| `sim_tick_total` | Counter | — | Total clock ticks emitted |
| `sim_tick_latency_ms` | Histogram | — | Real time per tick (buckets: 10, 50, 100, 500ms) |
| `sim_speed_multiplier` | Gauge | — | Current speed setting |
| `sim_day_number` | Gauge | — | Current simulated day |
| `sim_paused` | Gauge | — | 1 if paused, 0 if running |
| `sim_events_injected_total` | Counter | `type` | Probabilistic events fired |

### 3.2 Flights

| Metric | Type | Labels | Description |
|---|---|---|---|
| `flight_status_transitions_total` | Counter | `from`, `to` | All state transitions |
| `flights_active` | Gauge | `status` | Active flights per status |
| `flights_delayed_current` | Gauge | — | Currently delayed |
| `flights_cancelled_total` | Counter | `reason` | Cancellations by reason |
| `runway_queue_depth` | Gauge | `runway_id`, `direction` | Queue depth per runway |
| `runway_capacity_per_hour` | Gauge | `runway_id`, `direction` | Current capacity |
| `cascade_depth` | Histogram | — | Delay cascade chain depth |
| `gate_conflicts_resolved_total` | Counter | — | Gate reassignments |
| `turnaround_delay_minutes` | Histogram | `aircraft_type` | Turnaround delay distribution |

### 3.3 Passengers

| Metric | Type | Labels | Description |
|---|---|---|---|
| `passengers_in_airport` | Gauge | `status` | Pax count per status |
| `security_queue_depth` | Gauge | `terminal` | Queue depth per checkpoint |
| `security_wait_minutes` | Gauge | `terminal` | Estimated wait per terminal |
| `security_lanes_open` | Gauge | `terminal` | Open lanes |
| `connections_at_risk` | Gauge | `risk_level` | watch / at_risk / missed |
| `connections_missed_total` | Counter | — | Cumulative missed connections |
| `passenger_alerts_total` | Counter | `type` | Alerts by type |
| `zone_load_pct` | Gauge | `zone_id` | Load % per zone |

### 3.4 Baggage

| Metric | Type | Labels | Description |
|---|---|---|---|
| `baggage_in_system` | Gauge | `status` | Items per status |
| `baggage_flagged_active` | Gauge | — | Currently flagged items |
| `conveyor_zone_utilisation_pct` | Gauge | `zone_id` | Utilisation per zone |
| `conveyor_zone_status` | Gauge | `zone_id` | 0=normal 1=degraded 2=offline |
| `baggage_transitions_total` | Counter | `from`, `to` | Status transitions |
| `dangerous_goods_detected_total` | Counter | `dg_class` | DG detections by class |
| `screening_false_positives_total` | Counter | — | False positive detections |
| `baggage_offloaded_total` | Counter | `reason` | Offloads (cancellation, incident) |

### 3.5 Weather

| Metric | Type | Labels | Description |
|---|---|---|---|
| `weather_category` | Gauge | — | 0=CAVOK 1=VMC 2=IMC 3=LIFR |
| `weather_transitions_total` | Counter | `from`, `to` | FSM transitions |
| `visibility_m` | Gauge | — | Current visibility |
| `wind_speed_kt` | Gauge | — | Current wind speed |
| `wind_gust_kt` | Gauge | — | Current gust speed |
| `runway_arrival_rate` | Gauge | — | Max arrivals/hr |
| `runway_departure_rate` | Gauge | — | Max departures/hr |
| `holding_stack_depth` | Gauge | — | Arrivals in holding |
| `flights_delayed_by_weather_total` | Counter | `category` | Weather-caused delays |

### 3.6 Incidents

| Metric | Type | Labels | Description |
|---|---|---|---|
| `incidents_active` | Gauge | `type`, `severity` | Active incidents |
| `incidents_created_total` | Counter | `type`, `severity`, `trigger` | All incidents created |
| `incident_ttr_minutes` | Histogram | `type` | Time-to-resolve (buckets: 5, 15, 30, 60, 120min) |
| `cascade_events_total` | Counter | `parent_type` | Child incidents spawned |
| `cascade_depth_max` | Gauge | — | Deepest active cascade |
| `protocols_activated_total` | Counter | `protocol` | Emergency protocols fired |
| `flights_impacted_by_incidents_total` | Counter | `incident_type` | Flights affected |

### 3.7 API gateway

| Metric | Type | Labels | Description |
|---|---|---|---|
| `gateway_requests_total` | Counter | `method`, `path`, `status` | All HTTP requests |
| `gateway_request_duration_ms` | Histogram | `upstream` | Response latency |
| `gateway_ws_connections_active` | Gauge | — | Connected WebSocket clients |
| `gateway_ws_events_forwarded_total` | Counter | `topic` | Events forwarded per topic |
| `gateway_upstream_errors_total` | Counter | `service`, `status` | Upstream failures |
| `gateway_rate_limit_hits_total` | Counter | `endpoint` | Rate limit rejections |

---

## 4. Alerting rules

```yaml
# alerts.yml
groups:
  - name: simulation
    rules:
      - alert: SimulationPaused
        expr: sim_paused == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Simulation has been paused for > 2 minutes"

      - alert: SimTickLatencyHigh
        expr: histogram_quantile(0.99, sim_tick_latency_ms_bucket) > 500
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Simulation tick p99 latency > 500ms — sim may be lagging"

  - name: incidents
    rules:
      - alert: CriticalIncidentActive
        expr: incidents_active{severity="critical"} > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Critical incident active at KART"

      - alert: DeepCascadeActive
        expr: cascade_depth_max >= 4
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Cascade depth >= 4 — monitor all systems"

  - name: operations
    rules:
      - alert: RunwayCapacityDegraded
        expr: runway_arrival_rate < 20
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Runway arrival rate below 20/hr — weather impact"

      - alert: HoldingStackDeep
        expr: holding_stack_depth > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Holding stack > 5 aircraft for > 2 minutes"

      - alert: SecurityQueueLong
        expr: security_wait_minutes > 25
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Security wait > 25 min in terminal {{ $labels.terminal }}"

      - alert: ConveyorZoneOffline
        expr: conveyor_zone_status == 2
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Conveyor zone {{ $labels.zone_id }} offline"

  - name: gateway
    rules:
      - alert: UpstreamServiceDown
        expr: gateway_upstream_errors_total > 10
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Upstream service {{ $labels.service }} returning errors"
```

---

## 5. Grafana dashboards

### Dashboard 1 — Simulation overview

**UID:** `art-sim-overview`  
**Refresh:** 5s  
**Purpose:** Top-level health of the entire digital twin.

| Panel | Type | Query |
|---|---|---|
| Sim clock | Stat | `sim_day_number`, `sim_speed_multiplier` |
| Sim running | Stat | `sim_paused` → green/red |
| Tick latency p99 | Gauge | `histogram_quantile(0.99, sim_tick_latency_ms_bucket)` |
| Events produced (rate) | Time series | `rate(sim_tick_total[1m])` |
| Active incidents | Stat | `sum(incidents_active)` |
| Weather category | Stat | `weather_category` (value map: 0=CAVOK etc.) |
| All services health | Table | Status of each scrape target |

---

### Dashboard 2 — Flight operations

**UID:** `art-flights`  
**Refresh:** 5s

| Panel | Type | Query |
|---|---|---|
| Flights by status | Bar gauge | `flights_active` by `status` label |
| Delayed flights | Stat | `flights_delayed_current` |
| Cancellations today | Stat | `flights_cancelled_total` |
| Runway queue depth | Time series | `runway_queue_depth` by `runway_id` + `direction` |
| Runway capacity | Gauge | `runway_arrival_rate`, `runway_departure_rate` |
| Holding stack | Stat | `holding_stack_depth` |
| Status transitions (rate) | Time series | `rate(flight_status_transitions_total[5m])` by `to` |
| Cascade depth histogram | Heatmap | `cascade_depth_bucket` |
| Gate conflicts resolved | Stat | `gate_conflicts_resolved_total` |

---

### Dashboard 3 — Passenger & baggage

**UID:** `art-pax-bag`  
**Refresh:** 5s

| Panel | Type | Query |
|---|---|---|
| Passengers in airport | Stat | `sum(passengers_in_airport)` |
| Pax by status | Bar gauge | `passengers_in_airport` by `status` |
| Security wait times | Bar gauge | `security_wait_minutes` by `terminal` |
| Connections at risk | Stat | `sum(connections_at_risk)` — coloured amber/red |
| Connections missed (cumulative) | Stat | `connections_missed_total` |
| Zone load % | Heatmap | `zone_load_pct` by `zone_id` |
| Baggage in system | Stat | `sum(baggage_in_system)` |
| Baggage by status | Bar gauge | `baggage_in_system` by `status` |
| Conveyor zone utilisation | Heatmap | `conveyor_zone_utilisation_pct` by `zone_id` |
| Flagged items | Stat | `baggage_flagged_active` — amber when > 0 |
| DG detections (rate) | Time series | `rate(dangerous_goods_detected_total[5m])` |

---

### Dashboard 4 — Weather & incidents

**UID:** `art-weather-incidents`  
**Refresh:** 5s

| Panel | Type | Query |
|---|---|---|
| Weather category | Stat | `weather_category` with value map |
| Visibility | Gauge | `visibility_m` (thresholds: 1500=red, 5000=amber) |
| Wind speed | Gauge | `wind_speed_kt` |
| Weather category (history) | State timeline | `weather_category` over time |
| Flights delayed by weather | Time series | `rate(flights_delayed_by_weather_total[5m])` |
| Active incidents | Table | `incidents_active` by type + severity |
| Incidents created today | Time series | `rate(incidents_created_total[5m])` by type |
| Time-to-resolve | Histogram | `incident_ttr_minutes_bucket` |
| Cascade depth max | Stat | `cascade_depth_max` — red when ≥ 4 |
| Protocols activated | Bar chart | `protocols_activated_total` by protocol |

---

### Dashboard 5 — API gateway & system health

**UID:** `art-gateway`  
**Refresh:** 10s

| Panel | Type | Query |
|---|---|---|
| Request rate | Time series | `rate(gateway_requests_total[1m])` |
| Error rate | Time series | `rate(gateway_requests_total{status=~"5.."}[1m])` |
| p95 latency by upstream | Time series | `histogram_quantile(0.95, gateway_request_duration_ms_bucket)` by `upstream` |
| Active WebSocket connections | Stat | `gateway_ws_connections_active` |
| WS events forwarded (rate) | Time series | `rate(gateway_ws_events_forwarded_total[1m])` by `topic` |
| Rate limit hits | Time series | `rate(gateway_rate_limit_hits_total[1m])` |
| Upstream errors | Table | `gateway_upstream_errors_total` by service |
| Kafka consumer lag | Time series | Kafka exporter metric `kafka_consumer_group_lag` |
| Neo4j query latency | Time series | Neo4j exporter `neo4j_query_execution_time_seconds` |

---

## 6. Grafana provisioning

Grafana is configured via provisioning files mounted at startup — no manual UI setup needed.

```yaml
# grafana/provisioning/datasources/prometheus.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

```yaml
# grafana/provisioning/dashboards/dashboards.yml
apiVersion: 1
providers:
  - name: ART Dashboards
    folder: Arthur Airport
    type: file
    options:
      path: /etc/grafana/dashboards
```

All five dashboard JSON files live in `grafana/dashboards/` and are auto-loaded on container start.

---

## 7. Default Grafana credentials

| Field | Value |
|---|---|
| URL | http://localhost:3001 |
| Username | `admin` |
| Password | `art-grafana` |

Change via `GF_SECURITY_ADMIN_PASSWORD` env var in `docker-compose.yml`.
