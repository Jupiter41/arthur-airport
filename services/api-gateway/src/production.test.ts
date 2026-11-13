import { it, after } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import jwt from "jsonwebtoken";
import { createServer } from "http";
import { WebSocket } from "ws";

process.env.NODE_ENV = "production";
process.env.PUBLIC_DEPLOYMENT = "true";
process.env.PUBLIC_ORIGIN = "https://airportdt.duckdns.org";
process.env.JWT_SECRET = "test-only-random-secret-with-at-least-32-bytes";
process.env.AUTH_CLIENTS = JSON.stringify({ admin: { secret: "test-only-operator-password-with-32-bytes", role: "approver" } });
const auth = require("./auth") as typeof import("./auth");
const { setupWebSocket } = require("./websocket") as typeof import("./websocket");
const { loginLimiter } = require("./rateLimit") as typeof import("./rateLimit");
const { accessPolicy, setupControl } = require("./access") as typeof import("./access");
const app = express(); app.use(express.json({ limit: "16kb" }));
app.post("/auth/token", loginLimiter, auth.handleToken);
app.post("/auth/viewer", auth.handleViewer);
app.use(auth.authMiddleware); setupControl(app); app.use(accessPolicy);
app.get("/api/v1/flights", (_req, res) => res.json({ flights: [] }));
const server = createServer(app); const wss = setupWebSocket(server);
const ready = new Promise<string>(resolve => server.listen(0, "127.0.0.1", () => {
  resolve(`http://127.0.0.1:${(server.address() as { port: number }).port}`);
}));
after(() => { for (const ws of wss.clients) ws.terminate(); wss.close(); server.closeAllConnections(); server.close(); });

it("production rejects invalid identities, forged claims, admin endpoints, and brute-force attempts", async () => {
  const base = await ready;
  const login = (body: unknown) => fetch(base + "/auth/token", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  for (const client_id of ["__proto__", "constructor", "toString", [], {}, 7]) {
    assert.ok([400, 401].includes((await login({ client_id, secret: "bad" })).status));
  }
  const response = await login({ client_id: "admin", secret: "test-only-operator-password-with-32-bytes" });
  assert.equal(response.status, 200);
  const { token } = await response.json() as { token: string };
  const headers = { Authorization: `Bearer ${token}` };
  assert.equal((await fetch(base + "/api/v1/flights", { headers })).status, 200);
  for (const path of ["/api/v1/debug/cypher", "/api/v1/sim/reset", "/api/v1/analysis/training/start", "/api/v1/analysis/query", "/api/v1/planning/scenarios"]) {
    assert.equal((await fetch(base + path, { method: "POST", headers })).status, 403, path);
  }
  const badTokens = ["garbage",
    jwt.sign({ sub: "admin", role: "approver", jti: "x" }, "wrong-secret", { expiresIn: 60 }),
    jwt.sign({ sub: "admin", role: "approver", jti: "x" }, process.env.JWT_SECRET!, { expiresIn: 60, algorithm: "HS384" }),
    jwt.sign({ sub: "admin", role: "approver", jti: "x" }, process.env.JWT_SECRET!),
    jwt.sign({ sub: "admin", role: "__proto__", jti: "x" }, process.env.JWT_SECRET!, { expiresIn: 60 }),
    jwt.sign({ sub: "admin", role: "approver", jti: "x" }, process.env.JWT_SECRET!, { expiresIn: -1 }),
  ];
  for (const bad of badTokens) assert.equal((await fetch(base + "/api/v1/flights", { headers: { Authorization: `Bearer ${bad}` } })).status, 401);
  const viewer = await fetch(base + "/auth/viewer", { method: "POST" });
  const v = await viewer.json() as { token: string };
  assert.equal((await fetch(base + "/api/v1/sim/pause", { method: "POST", headers: { Authorization: `Bearer ${v.token}` } })).status, 403);
  let status = 0;
  for (let i = 0; i < 16; i++) status = (await login({ client_id: "admin", secret: "wrong" })).status;
  assert.equal(status, 429);
});

it("WebSocket requires same-site origin and JWT; rejects oversized frames", async () => {
  const base = await ready;
  const response = await fetch(base + "/auth/viewer", { method: "POST" });
  const { token } = await response.json() as { token: string };
  const wsBase = base.replace("http:", "ws:") + "/ws";
  const rejected = (url: string, origin?: string) => new Promise<number>((resolve, reject) => {
    const ws = new WebSocket(url, origin ? { origin } : {});
    ws.on("unexpected-response", (_req, res) => { resolve(res.statusCode ?? 0); res.resume(); });
    ws.on("open", () => { ws.close(); reject(new Error("Unexpected upgrade")); });
    ws.on("error", () => undefined);
  });
  assert.equal(await rejected(wsBase, process.env.PUBLIC_ORIGIN), 401);
  assert.equal(await rejected(`${wsBase}?token=${token}`, "https://attacker.example"), 401);
  assert.equal(await rejected(`${wsBase}?token=${token}`), 401);
  const code = await new Promise<number>((resolve, reject) => {
    const ws = new WebSocket(`${wsBase}?token=${token}`, { origin: process.env.PUBLIC_ORIGIN });
    ws.on("open", () => ws.send("x".repeat(5000)));
    ws.on("close", resolve); ws.on("error", reject);
  });
  assert.equal(code, 1009);
});
