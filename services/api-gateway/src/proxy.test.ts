import { it } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { createServer, Server } from "http";
import { setupProxy, UPSTREAM } from "./proxy";

async function listen(server: Server): Promise<string> {
  return new Promise(resolve => server.listen(0, "127.0.0.1", () => resolve(`http://127.0.0.1:${(server.address() as { port: number }).port}`)));
}
it("native proxy preserves queries/JSON, follows only slash redirects, and caps responses", async () => {
  const upstream = express(); upstream.enable("strict routing"); upstream.use(express.json());
  upstream.get("/api/v1/flights", (req, res) => res.json({ query: req.query, auth: req.get("authorization") ?? null }));
  upstream.post("/api/v1/flights/:id/hold", (req, res) => res.status(201).json(req.body));
  upstream.get("/api/v1/flights/large", (_req, res) => res.send("x".repeat(2 * 1024 * 1024 + 1)));
  upstream.get("/api/v1/flights/redirect", (_req, res) => res.redirect(307, "http://attacker.example/"));
  upstream.get("/api/v1/flights/slash", (_req, res) => res.redirect(307, "/api/v1/flights/slash/"));
  upstream.get("/api/v1/flights/slash/", (_req, res) => res.json({ slash: true }));
  const backend = createServer(upstream); const backendURL = await listen(backend);
  UPSTREAM.flights = backendURL;
  const app = express(); app.use(express.json()); setupProxy(app);
  const server = createServer(app); const base = await listen(server);
  try {
    const list = await fetch(base + "/api/v1/flights?limit=10", { headers: { Authorization: "Bearer secret" } });
    assert.deepEqual(await list.json(), { query: { limit: "10" }, auth: null });
    const hold = await fetch(base + "/api/v1/flights/fake-id/hold", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "test" }) });
    assert.equal(hold.status, 201); assert.deepEqual(await hold.json(), { reason: "test" });
    assert.equal((await fetch(base + "/api/v1/flights/large")).status, 502);
    assert.equal((await fetch(base + "/api/v1/flights/redirect")).status, 502);
    assert.deepEqual(await (await fetch(base + "/api/v1/flights/slash")).json(), { slash: true });
  } finally { server.closeAllConnections(); backend.closeAllConnections(); server.close(); backend.close(); }
});
