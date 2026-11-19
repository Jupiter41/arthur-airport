import { it } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { createServer, Server } from "http";
import { UPSTREAM } from "./proxy";
import { handleSettings } from "./settings";

function listen(server: Server): Promise<string> {
  return new Promise(resolve => server.listen(0, "127.0.0.1", () =>
    resolve(`http://127.0.0.1:${(server.address() as { port: number }).port}`)));
}

it("reports owner values separately from restored requests and degrades without inventing application", async () => {
  const backend = express();
  let passenger: unknown = { sim_time: "2024-06-15T12:00:00Z", values: { lanes_a: 8, lanes_b: 12, lanes_c: 8, mct_minutes: 45 } };
  let bagStatus = 200;
  let simStatus = 200;
  const requested = { lanes_a: 4, sorting_capacity: 1800, requested: { lanes_a: 4, sorting_capacity: 1800 },
    application: { lanes_a: "owner_command", sorting_capacity: "configuration_restart" } };
  backend.get("/api/v1/sim/settings", (_req, res) => res.status(simStatus).json(requested));
  backend.get("/api/v1/flow/configuration", (_req, res) => res.json(passenger));
  backend.get("/api/v1/baggage/configuration", (_req, res) => res.status(bagStatus).json({ sim_time: null,
    values: { screening_units: 6, sorting_capacity: 5400, dg_false_positive_rate: 0.003 } }));
  const upstream = createServer(backend);
  const base = await listen(upstream);
  const original = { sim: UPSTREAM.sim, passengers: UPSTREAM.passengers, baggage: UPSTREAM.baggage };
  Object.assign(UPSTREAM, { sim: base, passengers: base, baggage: base });
  const app = express(); app.get("/api/v1/sim/settings", handleSettings);
  const server = createServer(app); const gateway = await listen(server);
  interface SettingsResult {
    requested: Record<string, number>;
    effective: Record<string, { status: string; sim_time: string | null; values: Record<string, number> | null }>;
  }
  const get = async () => (await (await fetch(`${gateway}/api/v1/sim/settings`)).json()) as SettingsResult;
  try {
    const response = await get();
    assert.equal(response.requested.lanes_a, 4);
    assert.equal(response.effective.passenger.values?.lanes_a, 8);
    assert.equal(response.effective.baggage.values?.sorting_capacity, 5400);
    assert.equal(response.effective.passenger.sim_time, "2024-06-15T12:00:00Z");
    bagStatus = 503;
    passenger = { values: { lanes_a: 4 } }; // mixed-version/malformed response
    const degraded = await get();
    assert.deepEqual(degraded.effective.passenger, { status: "unavailable", sim_time: null, values: null });
    assert.equal(degraded.effective.baggage.values, null);
    assert.equal(degraded.requested.sorting_capacity, 1800);
    passenger = { sim_time: null, values: "x".repeat(600_000) };
    assert.equal((await get()).effective.passenger.status, "unavailable");
    simStatus = 503;
    assert.equal((await fetch(`${gateway}/api/v1/sim/settings`)).status, 502);
  } finally {
    Object.assign(UPSTREAM, original);
    server.closeAllConnections(); upstream.closeAllConnections(); server.close(); upstream.close();
  }
});
