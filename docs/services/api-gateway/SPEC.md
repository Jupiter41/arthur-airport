# api-gateway — specification

**Language:** Node.js 20+ / TypeScript  
**Framework:** Express 5 + ws (WebSocket)  
**Port:** 3000  
**Responsibility:** Single entry point for all dashboard and external clients. Aggregates REST responses from upstream FastAPI services, fans out real-time events from all Kafka topics to dashboard WebSocket clients, handles auth (stub JWT), and rate-limits requests.

---

## 1. Domain responsibilities

- Proxy and aggregate REST requests to upstream services
- Subscribe to all Kafka topics and maintain a WebSocket fan-out to connected clients
- Issue and validate stub JWT tokens
- Apply rate limiting per client
- Provide a unified OpenAPI spec aggregating all upstream endpoints
- Serve the `/api/v1/airport` aggregate endpoint (combines status from all services)
- Forward manual incident injection requests to `incidents.inject`

---

## 2. Architecture

```
Dashboard client (React)
    │
    ├── REST (HTTP)  ──► Express router
    │                       │
    │                       ├── /flights/**   ──► flight-service:8001
    │                       ├── /passengers/**──► passenger-service:8002
    │                       ├── /baggage/**   ──► baggage-service:8003
    │                       ├── /weather/**   ──► weather-service:8004
    │                       ├── /incidents/** ──► incident-service:8005
    │                       ├── /sim/**       ──► sim-orchestrator:8006
    │                       └── /airport      ──► aggregated (parallel fetch)
    │
    └── WebSocket    ──► WS server
                            │
                            └── Kafka consumer group (all topics)
                                    ├── flights.events
                                    ├── passengers.events
                                    ├── baggage.events
                                    ├── weather.events
                                    ├── incidents.events
                                    └── incidents.alerts
```

---

## 3. Authentication

### Token issuance

```
POST /auth/token
Body: { "client_id": "dashboard", "secret": "art-dev-secret" }
Response: { "token": "<JWT>", "expires_in": 86400 }
```

The JWT payload:
```json
{
  "sub": "dashboard",
  "role": "operator",
  "iat": 1718462400,
  "exp": 1718548800
}
```

Secret is configured via `JWT_SECRET` env var. In development mode (`NODE_ENV=development`), any client_id is accepted with any secret.

### Token validation middleware

All routes except `/health`, `/ready`, and `/auth/token` require `Authorization: Bearer <token>`. Invalid or expired tokens return `401`.

---

## 4. REST API

The gateway exposes all upstream endpoints under `/api/v1/` with the same paths as the upstream services. It adds:

#### `GET /api/v1/airport`
Aggregate snapshot of the entire airport state. Fetches data from all services in parallel.

Response `200`:
```json
{
  "sim_time": "2024-06-15T14:32:00Z",
  "airport": {
    "iata": "ART",
    "icao": "KART",
    "name": "Arthur International Airport"
  },
  "simulation": {
    "running": true,
    "speed_multiplier": 60,
    "day_number": 1
  },
  "weather": {
    "category": "IMC",
    "visibility_m": 2800,
    "wind_speed_kt": 28,
    "runway_impact": "reduced_rate",
    "metar_raw": "KART 151428Z 27028G42KT 2800 TS RA BKN009 Q1002"
  },
  "flights": {
    "total_today": 420,
    "active": 87,
    "delayed": 12,
    "cancelled": 1,
    "airborne": 34
  },
  "passengers": {
    "in_airport": 4218,
    "security_queued": 187,
    "connections_at_risk": 7
  },
  "baggage": {
    "in_system": 1842,
    "flagged": 3,
    "system_failures": 0
  },
  "incidents": {
    "active": 1,
    "highest_severity": "critical",
    "latest": {
      "type": "runway_incursion",
      "title": "Runway incursion — 09L",
      "started_at": "2024-06-15T14:30:00Z"
    }
  }
}
```

---

#### `GET /api/v1/health/services`
Health of all upstream services.

Response `200`:
```json
{
  "gateway": "ok",
  "flight_service": "ok",
  "passenger_service": "ok",
  "baggage_service": "ok",
  "weather_service": "ok",
  "incident_service": "ok",
  "sim_orchestrator": "ok",
  "neo4j": "ok",
  "kafka": "ok"
}
```

---

## 5. WebSocket fan-out

### Connection

```
WS ws://localhost:3000/ws
Headers: Authorization: Bearer <token>
```

On connect, the server sends a snapshot frame:
```json
{
  "type": "snapshot",
  "sim_time": "2024-06-15T14:32:00Z",
  "active_incidents": 1,
  "flights_active": 87,
  "weather_category": "IMC"
}
```

### Topic subscriptions

Clients declare which event types they want to receive:

```json
{
  "action": "subscribe",
  "topics": ["flights", "incidents", "weather"]
}
```

Valid topic keys: `flights`, `passengers`, `baggage`, `weather`, `incidents`, `alerts`

Subscribing to `alerts` receives only `IncidentAlert` events — a high-priority feed suitable for the notification panel.

### Event forwarding

The gateway relays Kafka events to subscribed WebSocket clients verbatim (the upstream event envelope is preserved). The `type` field maps to the `event_type` of the Kafka event.

### Heartbeat

The server sends a `ping` frame every 15 real seconds:
```json
{ "type": "ping", "sim_time": "..." }
```

Clients that do not respond with a `pong` within 5 seconds are disconnected.

### Reconnection

Clients should implement exponential backoff reconnection. On reconnect, they will receive a new `snapshot` frame to re-sync state.

---

## 6. Rate limiting

| Tier | Limit | Window |
|---|---|---|
| Default (all clients) | 200 requests | 60 seconds |
| `/api/v1/airport` aggregate | 10 requests | 60 seconds |
| `/sim/reset` | 1 request | 300 seconds |
| `/incidents/inject` | 5 requests | 60 seconds |

Rate limit headers returned on every response:
```
X-RateLimit-Limit: 200
X-RateLimit-Remaining: 187
X-RateLimit-Reset: 1718462460
```

Exceeded limits return `429 Too Many Requests`.

---

## 7. Upstream proxy configuration

| Upstream | Base URL | Timeout | Retry |
|---|---|---|---|
| flight-service | `http://flight-service:8001/api/v1` | 5s | 2× on 502/503 |
| passenger-service | `http://passenger-service:8002/api/v1` | 5s | 2× |
| baggage-service | `http://baggage-service:8003/api/v1` | 5s | 2× |
| weather-service | `http://weather-service:8004/api/v1` | 3s | 2× |
| incident-service | `http://incident-service:8005/api/v1` | 5s | 2× |
| sim-orchestrator | `http://sim-orchestrator:8006/api/v1` | 10s | 1× |

If an upstream service is unavailable, the gateway returns a partial response with the unavailable service's fields set to `null` and adds a `degraded_services` array to the response body.

---

## 8. Configuration

| Env variable | Default | Description |
|---|---|---|
| `PORT` | `3000` | Gateway listen port |
| `JWT_SECRET` | `art-digital-twin-dev` | JWT signing secret |
| `JWT_EXPIRES_IN` | `86400` | Token TTL in seconds |
| `KAFKA_BROKERS` | `kafka:9092` | |
| `KAFKA_GROUP_ID` | `api-gateway` | Consumer group |
| `FLIGHT_SERVICE_URL` | `http://flight-service:8001` | |
| `PASSENGER_SERVICE_URL` | `http://passenger-service:8002` | |
| `BAGGAGE_SERVICE_URL` | `http://baggage-service:8003` | |
| `WEATHER_SERVICE_URL` | `http://weather-service:8004` | |
| `INCIDENT_SERVICE_URL` | `http://incident-service:8005` | |
| `SIM_ORCHESTRATOR_URL` | `http://sim-orchestrator:8006` | |
| `WS_HEARTBEAT_INTERVAL_MS` | `15000` | |
| `NODE_ENV` | `development` | |
| `LOG_LEVEL` | `info` | |

---

## 9. Health & observability

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness (always `200 ok` if process is alive) |
| `GET /ready` | Readiness: Kafka connected, at least one upstream reachable |
| `GET /metrics` | Prometheus (prom-client) |

### Key Prometheus metrics

| Metric | Type | Description |
|---|---|---|
| `gateway_requests_total` | Counter | All HTTP requests by method, path, status |
| `gateway_request_duration_ms` | Histogram | Response time by upstream |
| `gateway_ws_connections_active` | Gauge | Active WebSocket connections |
| `gateway_ws_events_forwarded_total` | Counter | Events forwarded by topic |
| `gateway_upstream_errors_total` | Counter | Upstream errors by service |
| `gateway_rate_limit_hits_total` | Counter | Rate limit rejections |
