import express, { Request, Response } from "express";
import client from "prom-client";

const app = express();
const PORT = parseInt(process.env.PORT || "3000", 10);

// Collect default metrics (CPU, memory, event loop, etc.)
client.collectDefaultMetrics();

app.use(express.json());

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok" });
});

app.get("/ready", async (_req: Request, res: Response) => {
  // In later sprints, check Kafka connectivity here
  res.json({ status: "ready" });
});

app.get("/metrics", async (_req: Request, res: Response) => {
  res.set("Content-Type", client.register.contentType);
  res.end(await client.register.metrics());
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`api-gateway listening on port ${PORT}`);
});
