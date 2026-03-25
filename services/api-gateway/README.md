# api-gateway

> 📄 **Specification:** [docs/services/api-gateway/SPEC.md](../../docs/services/api-gateway/SPEC.md)
> 🧠 **Skill file:** [SKILL.md](./SKILL.md)

**Language:** Node.js 20 · **Framework:** Express 5 + ws · **Port:** 3000

Single entry point for all dashboard and external clients. Proxies REST requests to upstream FastAPI services, fans out real-time Kafka events to WebSocket clients, and handles auth (stub JWT).

---

## Architecture

```
api-gateway/src/
├── index.ts        # Express bootstrap, middleware wiring, graceful shutdown
├── auth.ts         # JWT token issuance and auth middleware
├── proxy.ts        # Upstream URL map and proxy route setup
├── aggregate.ts    # /api/v1/airport parallel fetch from all services
├── health.ts       # Service health fan-out and readiness checks
├── kafka.ts        # Kafka consumer lifecycle, topic subscriptions
├── websocket.ts    # WS server, topic subscriptions, latest-event cache
└── rateLimit.ts    # Per-route rate limiter presets
```

## How it works

1. **REST proxy:** every `/api/v1/{service}/**` request is transparently proxied to the corresponding upstream FastAPI service. The gateway adds no business logic.
2. **WebSocket fan-out:** a Kafka consumer subscribes to all event topics. Incoming events are cached (latest per type) and pushed to all connected WS clients based on their topic subscription.
3. **Auth:** a stub JWT system — clients request a token via `POST /auth/token` with a shared secret. The token is verified on protected routes.
4. **Rate limiting:** per-route rate limits (default, heavy, sim-reset, inject) to prevent abuse.
5. **Aggregate endpoint:** `GET /api/v1/airport` fetches data from all services in parallel and returns a full airport state snapshot.

## Running

```bash
# Full stack
docker compose up --build

# Local development
cd services/api-gateway
npm install
npm run dev
```

## Key endpoints

| Method | Path                      | Description                                   |
| ------ | ------------------------- | --------------------------------------------- |
| POST   | `/auth/token`             | Get a JWT token (body: `{client_id, secret}`) |
| GET    | `/api/v1/airport`         | Full airport state snapshot (parallel fetch)  |
| GET    | `/api/v1/health/services` | Health of all upstream services               |
| WS     | `/ws`                     | Real-time event stream (all topics)           |
| \*     | `/api/v1/flights/**`      | Proxied to flight-service :8001               |
| \*     | `/api/v1/passengers/**`   | Proxied to passenger-service :8002            |
| \*     | `/api/v1/baggage/**`      | Proxied to baggage-service :8003              |
| \*     | `/api/v1/weather/**`      | Proxied to weather-service :8004              |
| \*     | `/api/v1/incidents/**`    | Proxied to incident-service :8005             |
| \*     | `/api/v1/sim/**`          | Proxied to sim-orchestrator :8006             |

## WebSocket protocol

Connect to `ws://localhost:3000/ws` and subscribe to topics:

```json
{ "action": "subscribe", "topics": ["flights", "weather", "incidents"] }
```

Available topics: `flights` · `passengers` · `baggage` · `weather` · `incidents` · `alerts`

On connect, the server sends the latest cached event for each subscribed topic.

## Environment variables

| Variable        | Default                | Description                       |
| --------------- | ---------------------- | --------------------------------- |
| `KAFKA_BROKERS` | `kafka:9092`           | Kafka bootstrap servers           |
| `JWT_SECRET`    | `art-digital-twin-dev` | Secret for signing/verifying JWTs |
| `GATEWAY_PORT`  | `3000`                 | Listening port                    |
