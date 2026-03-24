# Sprint 7 — Lessons learned

## api-gateway: unified API + WebSocket + auth + rate limiting

---

### 1. Proxy edge cases (timeouts, headers)

- **http-proxy-middleware error callback typing**: The `on.error` callback receives
  `ServerResponse | Socket` as the response parameter, not Express's `Response`. Must use
  type guard (`"writeHead" in res`) before writing HTTP responses — otherwise you get a
  TypeScript error at compile time.
- **changeOrigin: true** is essential for upstream services that validate the Host header.
  Without it, the original client's Host header is forwarded, which confuses some frameworks.
- **Timeout configuration**: Each upstream has a different acceptable latency profile.
  Weather service can timeout faster (3s) while sim-orchestrator needs more headroom (10s)
  due to its reset/seed operations. These should be configurable via environment variables.
- **502 responses on upstream failure**: The error handler must check `res.headersSent` before
  attempting to write, since partial responses may already be flushed.

### 2. Kafka → WebSocket fan-out challenges

- **Topic key mapping**: Kafka topics use dotted names (`flights.events`) but WebSocket
  subscriptions use simple keys (`flights`). The mapping table must be maintained in sync.
- **sim.clock volume**: `SimClockTick` events fire once per simulated minute (at 60× speed,
  that's one per real second). Forwarding all of these to every client would be wasteful.
  The current design only relays clock ticks if clients subscribe to the `sim` topic.
- **JSON parse resilience**: Invalid Kafka messages must never crash the consumer loop.
  A silent catch-and-log is the correct pattern — the consumer must keep running.
- **Consumer group isolation**: The gateway's `api-gateway` consumer group must be distinct
  from all domain service groups to avoid stealing messages from business logic consumers.

### 3. Backpressure and memory risks

- **No internal buffering**: Events go straight from Kafka `eachMessage` to `fanOut()`.
  No event queue accumulates in memory. This is intentional — if a WebSocket client can't
  keep up, it will naturally apply TCP backpressure on its socket, and the `ws.send()` call
  will buffer at the OS level.
- **Client set cleanup**: Dead clients are cleaned up in three places: `ws.close` event,
  `ws.error` event, and the heartbeat interval (which terminates clients that don't respond
  to pings within one interval). This prevents unbounded growth of the client set.
- **Heartbeat dual mechanism**: We send both a WebSocket protocol-level `ping` (binary frame)
  and an application-level `{"type":"ping"}` JSON message. The protocol ping handles the
  `alive` flag for automatic cleanup. The JSON ping gives the client sim_time context.

### 4. Auth design tradeoffs

- **Development mode accepts any credentials**: When `NODE_ENV !== "production"`, the
  `handleToken` endpoint issues a JWT for any `client_id` without validating the secret.
  This simplifies local development but must never reach production.
- **Stateless JWT**: No token revocation list, no session store. Tokens are valid for 24h.
  For a simulation/portfolio project this is acceptable. In production, you'd add a
  revocation list backed by Redis.
- **WebSocket auth**: Token is validated during the `verifyClient` upgrade handshake.
  Once connected, the WebSocket session is not re-validated. A long-lived WS connection
  survives token expiry — acceptable for the simulation's short-lived sessions.

### 5. Rate limiting tuning issues

- **Default tier (200/min)** is generous for human dashboard use but tight enough to
  catch runaway loops. The test script fires 205 requests sequentially, so ~5 should
  hit 429.
- **Heavy endpoint (10/min) for /airport**: This aggregates 6 upstream calls, so each
  client request multiplies into 6 internal HTTP requests. Rate limiting here is essential
  to protect upstream services.
- **express-rate-limit uses in-memory store by default**: Acceptable for single-instance
  deployment. For horizontal scaling, you'd need a Redis-backed store.
- **Limiter ordering matters**: Specific path limiters (`/api/v1/airport`, `/sim/reset`)
  must be registered before the default limiter, otherwise the default limiter consumes
  the request first and the specific one never fires.

### 6. Failure handling (partial responses)

- **Promise.allSettled** is the correct pattern for the aggregate endpoint. Individual
  service failures return `null` for that service's data section, and a `degraded_services`
  array lists which services failed.
- **/api/v1/health/services** checks each upstream independently. A single failure doesn't
  affect the overall response — each service gets its own status field.
- **Proxy 502 fallback**: If an upstream is completely unreachable, the proxy middleware's
  error handler returns a structured JSON 502 instead of crashing or hanging.

### 7. What I would redesign

- **WebSocket snapshot on connect** currently only sends `sim_time`. It should fetch a
  mini-aggregate from all services to give the client a full state bootstrap on reconnect.
  This was deferred to keep the initial implementation simple.
- **Rate limiter per-IP vs per-token**: Currently rate limiting is per-IP (express-rate-limit
  default). Per-token limiting would be more accurate for multi-client scenarios.
- **Aggregate endpoint caching**: The `/airport` endpoint hits 6 services every time.
  A short TTL cache (5-10 seconds) would reduce upstream load significantly without
  sacrificing data freshness.
- **Kafka consumer health integration**: The readiness probe checks `isKafkaConnected()`
  but this is a simple boolean flag. A more robust check would verify the consumer is
  actually receiving messages (heartbeat-based staleness detection).
