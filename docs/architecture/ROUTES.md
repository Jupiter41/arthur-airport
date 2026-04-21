# API Routes Reference

Complete endpoint inventory for all services in the Arthur International Airport digital twin.
Routes are grouped by service, listing the HTTP method, path, and a one-line description.

> **Gateway note:** All domain-service endpoints are available through the API gateway
> (`http://localhost:3000`) under the same `/api/v1/` prefix. Some paths are remapped —
> see the [API Gateway](#api-gateway-port-3000) section for details.

---

## flight-service (port 8001)

| Method | Path                                  | Description                                                           |
| ------ | ------------------------------------- | --------------------------------------------------------------------- |
| `GET`  | `/api/v1/flights`                     | List all flights for the current sim day with filters and pagination  |
| `GET`  | `/api/v1/flights/{flight_id}`         | Full flight detail including passenger/baggage summary and history    |
| `GET`  | `/api/v1/flights/{flight_id}/cascade` | Cascade tree of effects triggered by a flight's delay or cancellation |
| `GET`  | `/api/v1/runways`                     | Current runway operational status and queue depths                    |
| `GET`  | `/api/v1/gates`                       | All gate statuses, filterable by terminal and status                  |
| `POST` | `/api/v1/flights/{flight_id}/hold`    | Manually place a flight on hold (operator override)                   |
| `POST` | `/api/v1/flights/{flight_id}/release` | Release a manually held flight                                        |
| `GET`  | `/health`                             | Liveness probe                                                        |
| `GET`  | `/ready`                              | Readiness probe (Neo4j + Kafka connectivity)                          |
| `GET`  | `/metrics`                            | Prometheus metrics                                                    |
| `WS`   | `/ws/flights`                         | Real-time flight event stream (status, gate, runway, cancellation)    |

---

## passenger-service (port 8002)

| Method | Path                                | Description                                                           |
| ------ | ----------------------------------- | --------------------------------------------------------------------- |
| `GET`  | `/api/v1/passengers`                | Paginated list of passengers with filters                             |
| `GET`  | `/api/v1/passengers/search`         | Search passengers by PNR or name                                      |
| `GET`  | `/api/v1/passengers/{passenger_id}` | Full passenger detail with timeline and alerts                        |
| `GET`  | `/api/v1/flow/summary`              | Real-time passenger flow summary across all zones                     |
| `GET`  | `/api/v1/flow/heatmap`              | Zone-level passenger density for the heatmap dashboard                |
| `GET`  | `/api/v1/flow/forecast`             | LightGBM queue depth forecast per terminal (up to 90 sim-min)         |
| `GET`  | `/api/v1/connections/at-risk`       | All connecting passengers currently at risk of missing connection     |
| `GET`  | `/api/v1/alerts`                    | Recent passenger alerts (gate changes, connection risks, emergencies) |
| `GET`  | `/health`                           | Liveness probe                                                        |
| `GET`  | `/ready`                            | Readiness probe (Neo4j + Kafka connectivity)                          |
| `GET`  | `/metrics`                          | Prometheus metrics                                                    |
| `WS`   | `/ws/passengers`                    | Real-time passenger status and alert event stream                     |

---

## baggage-service (port 8003)

| Method | Path                           | Description                                                       |
| ------ | ------------------------------ | ----------------------------------------------------------------- |
| `GET`  | `/api/v1/baggage`              | List baggage items with filters (flight, passenger, status, zone) |
| `GET`  | `/api/v1/baggage/{baggage_id}` | Full item detail with scan history                                |
| `GET`  | `/api/v1/baggage/tag/{tag}`    | Look up baggage by 10-digit barcode tag                           |
| `GET`  | `/api/v1/flow/summary`         | Real-time baggage flow summary across the handling system         |
| `GET`  | `/api/v1/flow/map`             | Conveyor zone map with current item counts and zone statuses      |
| `GET`  | `/api/v1/flagged`              | All currently flagged baggage items (DG or security)              |
| `GET`  | `/health`                      | Liveness probe                                                    |
| `GET`  | `/ready`                       | Readiness probe (Neo4j + Kafka connectivity)                      |
| `GET`  | `/metrics`                     | Prometheus metrics                                                |
| `WS`   | `/ws/baggage`                  | Real-time baggage status and flagging event stream                |

---

## weather-service (port 8004)

| Method | Path                      | Description                                                          |
| ------ | ------------------------- | -------------------------------------------------------------------- |
| `GET`  | `/api/v1/weather/current` | Current weather conditions at KART (JSON with METAR + runway impact) |
| `GET`  | `/api/v1/weather/metar`   | Latest METAR string (plain text)                                     |
| `GET`  | `/api/v1/weather/taf`     | Current TAF forecast (plain text)                                    |
| `GET`  | `/api/v1/weather/history` | Rolling weather history (up to 48 sim-hours)                         |
| `GET`  | `/api/v1/weather/impact`  | Operational impact summary (capacity, delays, holding stack)         |
| `GET`  | `/health`                 | Liveness probe                                                       |
| `GET`  | `/ready`                  | Readiness probe (Neo4j + Kafka connectivity)                         |
| `GET`  | `/metrics`                | Prometheus metrics                                                   |
| `WS`   | `/ws/weather`             | Real-time weather state and METAR event stream                       |

---

## incident-service (port 8005)

| Method | Path                                      | Description                                                      |
| ------ | ----------------------------------------- | ---------------------------------------------------------------- |
| `GET`  | `/api/v1/incidents`                       | List incidents with filters (status, type, severity, time range) |
| `GET`  | `/api/v1/incidents/{incident_id}`         | Full incident detail with cascade tree and affected flights      |
| `POST` | `/api/v1/incidents/inject`                | Manually inject a hazardous event                                |
| `POST` | `/api/v1/incidents/{incident_id}/contain` | Mark incident as contained                                       |
| `POST` | `/api/v1/incidents/{incident_id}/resolve` | Resolve an incident                                              |
| `GET`  | `/api/v1/incidents/{incident_id}/report`  | Auto-generated incident report                                   |
| `GET`  | `/api/v1/alerts`                          | Active alerts for the dashboard notification panel               |
| `GET`  | `/api/v1/protocols`                       | List of emergency protocol definitions (code-only, not in spec)  |
| `GET`  | `/health`                                 | Liveness probe                                                   |
| `GET`  | `/ready`                                  | Readiness probe (Neo4j + Kafka connectivity)                     |
| `GET`  | `/metrics`                                | Prometheus metrics                                               |
| `WS`   | `/ws/incidents`                           | Real-time incident lifecycle and alert event stream              |

---

## sim-orchestrator (port 8006)

| Method  | Path                   | Description                                                        |
| ------- | ---------------------- | ------------------------------------------------------------------ |
| `GET`   | `/api/v1/sim/status`   | Full current simulation status (time, speed, day, weather, counts) |
| `PATCH` | `/api/v1/sim/speed`    | Change simulation speed multiplier (1×, 10×, 60×, 600×, 3600×)     |
| `POST`  | `/api/v1/sim/pause`    | Pause the simulation clock                                         |
| `POST`  | `/api/v1/sim/resume`   | Resume after pause                                                 |
| `POST`  | `/api/v1/sim/reset`    | Full reset: wipe all data, reseed from Day 1 (destructive)         |
| `POST`  | `/api/v1/sim/inject`   | Inject a hazardous incident (proxied to incidents.inject topic)    |
| `GET`   | `/api/v1/sim/schedule` | Current day's flight schedule                                      |
| `GET`   | `/api/v1/sim/metrics`  | Simulation performance metrics (tick latency, drift, event counts) |
| `GET`   | `/health`              | Liveness probe                                                     |
| `GET`   | `/ready`               | Readiness probe (Neo4j + Kafka + upstream services)                |
| `GET`   | `/metrics`             | Prometheus metrics                                                 |

---

## analysis-service (port 8007)

| Method  | Path                               | Description                                                |
| ------- | ---------------------------------- | ---------------------------------------------------------- |
| `GET`   | `/api/v1/analysis/bottlenecks`     | List active bottlenecks with optional severity/type filter |
| `GET`   | `/api/v1/analysis/recommendations` | Top 3 ranked recommendations by impact/cost ratio          |
| `POST`  | `/api/v1/analysis/what-if`         | Run what-if projection for 1–3 proposed actions            |
| `GET`   | `/api/v1/analysis/what-if/log`     | What-if analysis log, most recent first                    |
| `GET`   | `/api/v1/analysis/autonomous`      | Get autonomous mode settings                               |
| `PATCH` | `/api/v1/analysis/autonomous`      | Update autonomous mode settings                            |
| `GET`   | `/api/v1/analysis/autonomous/log`  | Autonomous action log, most recent first                   |
| `GET`   | `/api/v1/analysis/anomalies`       | Anomaly detection status and deviations from baseline      |
| `POST`  | `/api/v1/analysis/query`           | Natural language question about current airport state      |
| `POST`  | `/api/v1/analysis/nl-inject`       | Parse natural language incident injection command          |
| `GET`   | `/api/v1/analysis/narration`       | Get narration settings and recent history                  |
| `PATCH` | `/api/v1/analysis/narration`       | Toggle narration mode on/off and update settings           |
| `POST`  | `/api/v1/analysis/report`          | Generate after-action report for current simulation        |
| `GET`   | `/api/v1/analysis/llm-config`      | Current LLM configuration and availability                 |
| `GET`   | `/api/v1/analysis/training/status` | Training status, history, and available models             |
| `GET`   | `/api/v1/analysis/training/config` | Training environment config, model paths, loaded status    |
| `POST`  | `/api/v1/analysis/training/start`  | Start a new training run (rl/anomaly/forecast)             |
| `POST`  | `/api/v1/analysis/training/stop`   | Stop the active training run                               |
| `GET`   | `/health`                          | Liveness probe with Kafka consumer status                  |
| `GET`   | `/ready`                           | Readiness probe (Neo4j + Kafka + consumer)                 |
| `GET`   | `/perf`                            | Tick processing performance stats                          |

---

## API Gateway (port 3000)

### Gateway-native endpoints

| Method | Path                      | Description                                                   |
| ------ | ------------------------- | ------------------------------------------------------------- |
| `POST` | `/auth/token`             | Issue a stub JWT token                                        |
| `GET`  | `/api/v1/airport`         | Aggregate airport snapshot (parallel fetch from all services) |
| `GET`  | `/api/v1/health/services` | Health matrix of all upstream services and infra              |
| `GET`  | `/health`                 | Gateway liveness probe                                        |
| `GET`  | `/ready`                  | Gateway readiness probe                                       |
| `GET`  | `/metrics`                | Prometheus metrics (prom-client)                              |
| `WS`   | `/ws`                     | Authenticated fan-out WebSocket for all Kafka-backed events   |

### Proxied upstream routes

The gateway remaps some upstream paths to avoid collisions between services that
share similar path segments (e.g. `/flow/summary` exists on both passenger and baggage services).

| Gateway path prefix                | Upstream service       | Upstream path prefix    |
| ---------------------------------- | ---------------------- | ----------------------- |
| `/api/v1/flights/*`                | flight-service:8001    | `/api/v1/flights/*`     |
| `/api/v1/runways/*`                | flight-service:8001    | `/api/v1/runways/*`     |
| `/api/v1/gates/*`                  | flight-service:8001    | `/api/v1/gates/*`       |
| `/api/v1/weather/*`                | weather-service:8004   | `/api/v1/weather/*`     |
| `/api/v1/incidents/alerts/*`       | incident-service:8005  | `/api/v1/alerts/*`      |
| `/api/v1/incidents/*`              | incident-service:8005  | `/api/v1/incidents/*`   |
| `/api/v1/sim/*`                    | sim-orchestrator:8006  | `/api/v1/sim/*`         |
| `/api/v1/passengers/flow/*`        | passenger-service:8002 | `/api/v1/flow/*`        |
| `/api/v1/passengers/connections/*` | passenger-service:8002 | `/api/v1/connections/*` |
| `/api/v1/passengers/alerts/*`      | passenger-service:8002 | `/api/v1/alerts/*`      |
| `/api/v1/passengers/*`             | passenger-service:8002 | `/api/v1/passengers/*`  |
| `/api/v1/baggage/flow/*`           | baggage-service:8003   | `/api/v1/flow/*`        |
| `/api/v1/baggage/flagged/*`        | baggage-service:8003   | `/api/v1/flagged/*`     |
| `/api/v1/baggage/*`                | baggage-service:8003   | `/api/v1/baggage/*`     |
| `/api/v1/analysis/*`               | analysis-service:8007  | `/api/v1/analysis/*`    |

### WebSocket topics

Clients subscribe to event topics via the gateway WebSocket:

| Topic key    | Source            | Events forwarded                                                                 |
| ------------ | ----------------- | -------------------------------------------------------------------------------- |
| `flights`    | flights.events    | FlightStatusChanged, FlightGateAssigned, FlightRunwayAssigned, FlightCancelled   |
| `passengers` | passengers.events | PassengerStatusChanged, PassengerAlert, SecurityCongestionDetected               |
| `baggage`    | baggage.events    | BaggageStatusChanged, BaggageFlagged                                             |
| `weather`    | weather.events    | WeatherStateChanged, METARIssued                                                 |
| `incidents`  | incidents.events  | IncidentCreated, IncidentStatusChanged, IncidentCascaded                         |
| `alerts`     | incidents.alerts  | IncidentAlert (high-priority feed)                                               |
| `analysis`   | analysis.events   | BottleneckDetected, RecommendationIssued, AutonomousActionTaken, AnomalyDetected |
