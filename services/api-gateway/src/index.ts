import express, { Request, Response } from "express";
import { createServer } from "http";
import client from "prom-client";
import { handleToken, authMiddleware } from "./auth";
import { setupProxy } from "./proxy";
import { handleAggregate } from "./aggregate";
import { handleServicesHealth, handleReady } from "./health";
import { setupKafka, shutdownKafka } from "./kafka";
import { setupWebSocket } from "./websocket";
import {
  defaultLimiter,
  heavyLimiter,
  simResetLimiter,
  injectLimiter,
} from "./rateLimit";

const app = express();
const server = createServer(app);
const PORT = parseInt(process.env.PORT || "3000", 10);

// Prometheus metrics
client.collectDefaultMetrics();

const requestsTotal = new client.Counter({
  name: "gateway_requests_total",
  help: "All HTTP requests by method, path, status",
  labelNames: ["method", "path", "status"],
});

const requestDuration = new client.Histogram({
  name: "gateway_request_duration_ms",
  help: "Response time by upstream",
  labelNames: ["path"],
  buckets: [10, 50, 100, 250, 500, 1000, 2500, 5000],
});

const upstreamErrors = new client.Counter({
  name: "gateway_upstream_errors_total",
  help: "Upstream errors by service",
  labelNames: ["service"],
});

// Request logging / metrics middleware
app.use((req: Request, res: Response, next) => {
  const start = Date.now();
  res.on("finish", () => {
    const duration = Date.now() - start;
    const pathLabel = req.path.split("/").slice(0, 4).join("/") || req.path;
    requestsTotal.inc({
      method: req.method,
      path: pathLabel,
      status: String(res.statusCode),
    });
    requestDuration.observe({ path: pathLabel }, duration);
  });
  next();
});

app.use(express.json());

// --- Public routes (no auth) ---
app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok" });
});

app.get("/ready", handleReady);

app.get("/metrics", async (_req: Request, res: Response) => {
  res.set("Content-Type", client.register.contentType);
  res.end(await client.register.metrics());
});

app.post("/auth/token", handleToken);

// --- Protected routes (auth required) ---
app.use(authMiddleware);

// Rate limiting: apply specific limiters before default
app.use("/api/v1/airport", heavyLimiter);
app.use("/api/v1/sim/reset", simResetLimiter);
app.use("/api/v1/incidents/inject", injectLimiter);
app.use(defaultLimiter);

// Aggregate and health
app.get("/api/v1/airport", handleAggregate);
app.get("/api/v1/health/services", handleServicesHealth);

// Proxy routes to upstream services
setupProxy(app);

// WebSocket server
setupWebSocket(server);

// Start server
server.listen(PORT, "0.0.0.0", async () => {
  console.log(`api-gateway listening on port ${PORT}`);

  // Start Kafka consumer (non-blocking — retries internally)
  try {
    await setupKafka();
  } catch (err) {
    console.error(
      "[Gateway] Kafka setup failed, will retry on reconnect:",
      err,
    );
  }
});

// Graceful shutdown
async function shutdown(): Promise<void> {
  console.log("[Gateway] Shutting down...");
  await shutdownKafka();
  server.close();
  process.exit(0);
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
