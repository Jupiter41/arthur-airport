import { describe, it, after } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { createServer } from "http";
process.env.PUBLIC_DEPLOYMENT = "true";
const { Controller, pathIsCanonical, publicRouteAllowed, accessPolicy, setupControl, readCache } = require("./access") as typeof import("./access");

describe("exclusive controller sessions", () => {
  it("isolates tabs of the same account, expires leases, and serializes writes", () => {
    let now = 1000;
    const c = new Controller(() => now, 100);
    const a = { sub: "operator", role: "operator", jti: "tab-a" };
    const b = { ...a, jti: "tab-b" };
    const lease = c.acquire(a)!;
    assert.ok(lease.lease);
    assert.equal(c.acquire(b), null);
    assert.equal(c.acquire(a), null); // cannot renew without the lease secret
    assert.equal(c.owns(b, lease.lease), false);
    assert.equal(c.begin(a, lease.lease), true);
    assert.equal(c.begin(a, lease.lease), false);
    assert.equal(c.release(a, lease.lease), false);
    now += 101;
    assert.equal(c.acquire(b), null); // expired owner cannot be replaced mid-write
    c.finish();
    const next = c.acquire(b)!;
    assert.notEqual(next.lease, lease.lease);
    assert.equal(c.owns(a, lease.lease), false);
    assert.equal(c.release(b, next.lease), true);
  });
});

describe("public route boundaries", () => {
  it("rejects encoded paths, dot segments and all admin routes", () => {
    for (const p of ["/api/v1/debug/cypher", "/api/v1/sim/reset", "/api/v1/planning/scenarios", "/api/v1/analysis/training/start", "/api/v1/analysis/query", "/api/v1/weather/source"]) {
      assert.equal(publicRouteAllowed("POST", p), false, p);
    }
    for (const p of ["/api/v1/sim/%72eset", "/api//v1/sim/status", "/api/v1/../debug", "/api/v1\\debug"]) {
      assert.equal(pathIsCanonical(p), false, p);
    }
    assert.equal(publicRouteAllowed("PATCH", "/api/v1/sim/settings"), true);
    assert.equal(publicRouteAllowed("GET", "/api/v1/flights"), true);
  });
});

if (process.env.PUBLIC_DEPLOYMENT === "true") {
  const app = express(); app.use(express.json());
  app.use((req, _res, next) => {
    (req as unknown as { user: object }).user = {
      sub: "test", jti: req.get("test-session") ?? "one", role: req.get("test-role") ?? "viewer",
    }; next();
  });
  setupControl(app); app.use(accessPolicy); app.use(readCache);
  let upstreamCalls = 0;
  app.get("/api/v1/flights", (_req, res) => {
    upstreamCalls++; setTimeout(() => res.json({ flights: [], upstreamCalls }), 20);
  });
  app.patch("/api/v1/sim/settings", (_req, res) => setTimeout(() => res.json({ updated: true }), 50));
  const server = createServer(app);
  const listening = new Promise<string>(resolve => server.listen(0, "127.0.0.1", () => {
    resolve(`http://127.0.0.1:${(server.address() as { port: number }).port}`);
  }));
  after(() => { server.closeAllConnections(); server.close(); });
  it("blocks viewer writes and requires operator lease; merges concurrent reads", async () => {
    const base = await listening;
    const viewers = await Promise.all(Array.from({ length: 8 }, () => fetch(`${base}/api/v1/flights`)));
    assert.ok(viewers.every(r => r.status === 200));
    assert.equal(upstreamCalls, 1);
    const send = (path: string, method: string, headers = {}, body = {}) => fetch(base + path, {
      method, headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body),
    });
    assert.equal((await send("/api/v1/sim/settings", "PATCH")).status, 403);
    assert.equal((await send("/api/v1/control", "POST")).status, 403);
    const h = { "test-role": "operator" };
    assert.equal((await send("/api/v1/sim/settings", "PATCH", h)).status, 423);
    const first = await send("/api/v1/control", "POST", h);
    const { lease } = await first.json() as { lease: string };
    assert.equal((await send("/api/v1/control", "POST", { ...h, "test-session": "two" })).status, 409);
    const owns = { ...h, "X-Control-Lease": lease };
    assert.equal((await send("/api/v1/sim/settings", "PATCH", owns, { daily_flights: 5000 })).status, 400);
    const writes = await Promise.all([send("/api/v1/sim/settings", "PATCH", owns, { daily_flights: 75 }), send("/api/v1/sim/settings", "PATCH", owns, { daily_flights: 60 })]);
    assert.deepEqual(writes.map(r => r.status).sort(), [200, 409]);
  });
}
