# SKILL — api-gateway

## Proxy pattern · WebSocket fan-out · Aggregate endpoint · Auth · Rate limiting

> Full specification: `docs/services/api-gateway/SPEC.md`
> This is Node.js/TypeScript — read `docs/skills/kafka.SKILL.md` for Kafka patterns.

---

## Project structure

```
services/api-gateway/
├── src/
│   ├── index.ts           # Express app, lifespan
│   ├── auth.ts            # JWT middleware
│   ├── proxy.ts           # Upstream proxy routes
│   ├── aggregate.ts       # /airport aggregate endpoint
│   ├── websocket.ts       # WS server + fan-out
│   ├── kafka.ts           # Kafka consumer
│   ├── rateLimit.ts       # Per-route rate limiting
│   └── health.ts          # /health, /ready, /health/services
├── package.json
└── tsconfig.json
```

---

## Express app skeleton

```typescript
import express from "express";
import { createServer } from "http";
import { setupProxy } from "./proxy";
import { setupWebSocket } from "./websocket";
import { setupKafka } from "./kafka";
import { authMiddleware } from "./auth";
import { rateLimiter } from "./rateLimit";

const app = express();
const server = createServer(app);

app.use(express.json());

// Public routes — no auth
app.get("/health", (_, res) => res.json({ status: "ok" }));
app.post("/auth/token", handleToken);

// Protected routes
app.use(authMiddleware);
app.use(rateLimiter);
setupProxy(app);
app.get("/api/v1/airport", handleAggregate);
app.get("/api/v1/health/services", handleServicesHealth);

setupWebSocket(server);

server.listen(process.env.PORT ?? 3000, async () => {
  await setupKafka();
  console.log("Gateway ready on port 3000");
});
```

---

## JWT auth middleware

```typescript
import jwt from "jsonwebtoken";
import { Request, Response, NextFunction } from "express";

const JWT_SECRET = process.env.JWT_SECRET ?? "art-digital-twin-dev";

export function handleToken(req: Request, res: Response) {
  // Stub — accept any client_id in development
  const { client_id } = req.body;
  if (!client_id) {
    return res.status(400).json({ error: "client_id required" });
  }
  const token = jwt.sign({ sub: client_id, role: "operator" }, JWT_SECRET, {
    expiresIn: "24h",
  });
  res.json({ token, expires_in: 86400 });
}

export function authMiddleware(
  req: Request,
  res: Response,
  next: NextFunction,
) {
  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token) return res.status(401).json({ error: "missing token" });
  try {
    jwt.verify(token, JWT_SECRET);
    next();
  } catch {
    res.status(401).json({ error: "invalid or expired token" });
  }
}
```

---

## Proxy setup

```typescript
import { createProxyMiddleware } from "http-proxy-middleware";
import { Express } from "express";

const UPSTREAM = {
  flights: process.env.FLIGHT_SERVICE_URL ?? "http://flight-service:8001",
  passengers:
    process.env.PASSENGER_SERVICE_URL ?? "http://passenger-service:8002",
  baggage: process.env.BAGGAGE_SERVICE_URL ?? "http://baggage-service:8003",
  weather: process.env.WEATHER_SERVICE_URL ?? "http://weather-service:8004",
  incidents: process.env.INCIDENT_SERVICE_URL ?? "http://incident-service:8005",
  sim: process.env.SIM_ORCHESTRATOR_URL ?? "http://sim-orchestrator:8006",
};

export function setupProxy(app: Express) {
  for (const [key, target] of Object.entries(UPSTREAM)) {
    app.use(
      `/api/v1/${key}`,
      createProxyMiddleware({
        target,
        changeOrigin: true,
        on: {
          error: (err, req, res: any) => {
            res.status(502).json({
              error: `${key} service unavailable`,
              service: key,
            });
          },
        },
      }),
    );
  }
}
```

---

## Airport aggregate endpoint

```typescript
export async function handleAggregate(req: Request, res: Response) {
  const [sim, weather, flights, passengers, baggage, incidents] =
    await Promise.allSettled([
      fetch(`${UPSTREAM.sim}/api/v1/sim/status`).then((r) => r.json()),
      fetch(`${UPSTREAM.weather}/api/v1/weather/current`).then((r) => r.json()),
      fetch(`${UPSTREAM.flights}/api/v1/flights/summary`).then((r) => r.json()),
      fetch(`${UPSTREAM.passengers}/api/v1/flow/summary`).then((r) => r.json()),
      fetch(`${UPSTREAM.baggage}/api/v1/flow/summary`).then((r) => r.json()),
      fetch(`${UPSTREAM.incidents}/api/v1/incidents?status=active`).then((r) =>
        r.json(),
      ),
    ]);

  const get = (r: PromiseSettledResult<any>) =>
    r.status === "fulfilled" ? r.value : null;

  const degraded = [sim, weather, flights, passengers, baggage, incidents]
    .map((r, i) =>
      r.status === "rejected"
        ? ["sim", "weather", "flights", "passengers", "baggage", "incidents"][i]
        : null,
    )
    .filter(Boolean);

  res.json({
    sim_time: get(sim)?.sim_time ?? null,
    simulation: get(sim),
    weather: get(weather),
    flights: get(flights),
    passengers: get(passengers),
    baggage: get(baggage),
    incidents: get(incidents),
    degraded_services: degraded,
  });
}
```

---

## WebSocket fan-out

```typescript
import { WebSocketServer, WebSocket } from "ws";
import { IncomingMessage } from "http";
import { Server } from "http";

interface Client {
  ws: WebSocket;
  subscriptions: Set<string>;
}

const clients = new Set<Client>();

export function setupWebSocket(server: Server) {
  const wss = new WebSocketServer({ server, path: "/ws" });

  wss.on("connection", (ws: WebSocket, req: IncomingMessage) => {
    const client: Client = { ws, subscriptions: new Set() };
    clients.add(client);

    // Send snapshot on connect
    ws.send(
      JSON.stringify({ type: "snapshot", sim_time: getCurrentSimTime() }),
    );

    ws.on("message", (raw) => {
      try {
        const msg = JSON.parse(raw.toString());
        if (msg.action === "subscribe" && Array.isArray(msg.topics)) {
          msg.topics.forEach((t: string) => client.subscriptions.add(t));
        }
        if (msg.type === "pong") {
          // heartbeat acknowledged
        }
      } catch {
        /* ignore malformed frames */
      }
    });

    ws.on("close", () => clients.delete(client));
  });

  // Heartbeat every 15 real seconds
  setInterval(() => {
    const simTime = getCurrentSimTime();
    clients.forEach(({ ws }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping", sim_time: simTime }));
      }
    });
  }, 15_000);
}

// Called by Kafka consumer when a new event arrives
export function fanOut(topicKey: string, event: object) {
  const payload = JSON.stringify(event);
  clients.forEach(({ ws, subscriptions }) => {
    if (subscriptions.has(topicKey) && ws.readyState === WebSocket.OPEN) {
      ws.send(payload);
    }
  });
}
```

---

## Kafka consumer (feeds the WebSocket fan-out)

```typescript
import { Kafka } from "kafkajs";
import { fanOut } from "./websocket";

const TOPIC_KEY_MAP: Record<string, string> = {
  "flights.events": "flights",
  "passengers.events": "passengers",
  "baggage.events": "baggage",
  "weather.events": "weather",
  "incidents.events": "incidents",
  "incidents.alerts": "alerts",
};

export async function setupKafka() {
  const kafka = new Kafka({
    brokers: [process.env.KAFKA_BROKERS ?? "kafka:9092"],
  });
  const consumer = kafka.consumer({ groupId: "api-gateway" });

  await consumer.connect();
  await consumer.subscribe({
    topics: Object.keys(TOPIC_KEY_MAP),
    fromBeginning: false,
  });

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      try {
        const event = JSON.parse(message.value?.toString() ?? "{}");
        const topicKey = TOPIC_KEY_MAP[topic] ?? topic;
        fanOut(topicKey, event);

        // Cache sim_time from clock ticks
        if (event.event_type === "SimClockTick") {
          setCurrentSimTime(event.payload.sim_time);
        }
      } catch {
        /* log and continue */
      }
    },
  });
}
```

---

## Rate limiting

```typescript
import rateLimit from "express-rate-limit";

export const rateLimiter = rateLimit({
  windowMs: 60_000,
  max: 200,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: "rate limit exceeded" },
  skip: (req) => req.path === "/health" || req.path === "/ready",
});

// Stricter limiter for heavy/destructive endpoints
export const strictLimiter = rateLimit({ windowMs: 60_000, max: 5 });
// Apply on router: app.post('/api/v1/incidents/inject', strictLimiter, ...)
```

---

## Gotchas

- **No business logic in the gateway.** If you find yourself adding domain rules, move them to the relevant service.
- **`Promise.allSettled` not `Promise.all`** in the aggregate endpoint — one failing upstream must not crash the whole response.
- **WebSocket auth** — verify the JWT on the initial HTTP upgrade request (`req.headers.authorization`) before accepting the connection. Reject with 401 if missing or invalid.
- **Disconnect clients that miss heartbeat pong** — track last pong time per client, close if no pong within 5 real seconds of a ping.
- **`kafkajs` consumer must reconnect on broker failure** — wrap in try/catch with exponential backoff. KafkaJS handles this automatically if you let errors propagate to its internal retry logic.
- **The `/ws` path must be handled by the WebSocket server, not Express.** Attach the `WebSocketServer` to the raw `http.Server`, not to the Express app.
