# api-gateway

> 📄 **Specification:** [docs/services/api-gateway/SPEC.md](../../docs/services/api-gateway/SPEC.md)

**Language:** Node.js 20 · **Framework:** Express 5 + ws · **Port:** 3000

Single entry point for all dashboard and external clients. Proxies REST requests to upstream FastAPI services, fans out real-time Kafka events to WebSocket clients, and handles auth (stub JWT).

## Responsibilities

- REST proxy to all 6 upstream services
- WebSocket fan-out: subscribes to all Kafka topics, pushes events to connected dashboards
- `/api/v1/airport` aggregate endpoint (parallel fetch from all services)
- Stub JWT auth + per-route rate limiting

## Quick start

```bash
docker compose up api-gateway
```

## Key endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/auth/token` | Get a JWT token |
| GET | `/api/v1/airport` | Full airport state snapshot |
| GET | `/api/v1/health/services` | Health of all upstream services |
| WS | `/ws` | Real-time event stream (all topics) |
| * | `/api/v1/flights/**` | Proxied to flight-service |
| * | `/api/v1/passengers/**` | Proxied to passenger-service |
| * | `/api/v1/baggage/**` | Proxied to baggage-service |
| * | `/api/v1/weather/**` | Proxied to weather-service |
| * | `/api/v1/incidents/**` | Proxied to incident-service |
| * | `/api/v1/sim/**` | Proxied to sim-orchestrator |

## WebSocket topics

Subscribe by sending: `{ "action": "subscribe", "topics": ["flights", "weather"] }`

Available: `flights` · `passengers` · `baggage` · `weather` · `incidents` · `alerts`

## Status

- [ ] Scaffolding
- [ ] JWT auth middleware
- [ ] REST proxy routes
- [ ] Kafka consumer + WS fan-out
- [ ] `/airport` aggregate endpoint
- [ ] Rate limiting
- [ ] Tests
