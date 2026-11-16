import { afterEach, it, mock } from "node:test";
import assert from "node:assert/strict";

process.env.NODE_ENV = "test";
const ds = require("./dataSources") as typeof import("./dataSources");
const ws = require("./websocket") as typeof import("./websocket");

const WALL = Date.parse("2026-11-16T18:00:00Z");
const SIM = "2024-07-08T09:54:00";
afterEach(() => mock.restoreAll());

it("derives status from owner-reported health, first match wins (RC10)", () => {
  const d = (h: Parameters<typeof ds.deriveStatus>[0], limit = {}) => ds.deriveStatus(h, limit, SIM, WALL).status;
  assert.equal(d(null), "unavailable");
  assert.equal(d({ enabled: false, last_ingest_at: "2026-11-16T17:59:00Z" }), "disabled");
  assert.equal(d({ enabled: true, last_error: "boom", last_error_at: "2026-11-16T17:59:00Z" }), "error");
  assert.equal(d({ enabled: true, last_ingest_at: "2026-11-16T17:58:00Z", last_error_at: "2026-11-16T17:59:00Z" }), "error");
  assert.equal(d({ enabled: true, last_ingest_at: "2026-11-16T17:59:00Z", last_error_at: "2026-11-16T17:58:00Z" }), "active");
  assert.equal(d({ enabled: true }), "stale");
  // the review's weather case: state from 21:00 the evening before
  assert.equal(d({ enabled: true, last_observation_at: "2024-07-07T21:00:00" }, { simMinutes: 90 }), "stale");
  assert.equal(d({ enabled: true, last_observation_at: "2024-07-08T09:00:00" }, { simMinutes: 90 }), "active");
  assert.equal(d({ enabled: true, last_ingest_at: "2026-11-16T17:50:00Z" }, { wallMinutes: 5 }), "stale");
});

it("labels the clock of last_updated and never uses request time", () => {
  const sim = ds.deriveStatus({ last_observation_at: "2024-07-08T09:00:00", last_ingest_at: "2026-11-16T17:59:00Z" }, {}, SIM, WALL);
  assert.deepEqual([sim.last_updated, sim.clock], ["2024-07-08T09:00:00", "sim"]);
  const wall = ds.deriveStatus({ last_ingest_at: "2026-11-16T17:59:00Z" }, {}, SIM, WALL);
  assert.deepEqual([wall.last_updated, wall.clock], ["2026-11-16T17:59:00Z", "wall"]);
  assert.equal(ds.deriveStatus({ enabled: true }, {}, SIM, WALL).last_updated, null);
});

it("reports ADS-B as disabled when the owner says so, not adsb.lol/active", async () => {
  ws.setCurrentSimTime(SIM);
  const replies: Record<string, unknown> = {
    "/api/v1/weather/source": { source: "simulated", current_category: "VMC", health: { enabled: true, last_observation_at: "2024-07-07T21:00:00", last_ingest_at: new Date().toISOString() } },
    "/api/v1/flights/adsb/source": { source: "disabled", aircraft_count: 0, health: { enabled: false } },
    "/api/v1/sim/status": { sim_time: SIM, speed_multiplier: 60, paused: false, day_number: 24 },
    "/api/v1/passengers/source": { source: "simulation", available: ["simulation"], health: { enabled: true, last_observation_at: SIM } },
    "/api/v1/flow/summary": { total_in_airport: 1234, by_status: { departed_airport: 1578851 }, total_in_system: 9, sim_time: "2024-07-08T09:20:00" },
    "/api/v1/sim/incident-source": { active: "simulated", available: [{ id: "simulated" }] },
  };
  mock.method(globalThis, "fetch", async (url: string) => {
    const path = Object.keys(replies).find(p => url.endsWith(p));
    return { ok: !!path, json: async () => (path ? replies[path] : {}) } as Response;
  });
  let body: { sources: Array<Record<string, unknown>> } = { sources: [] };
  await ds.handleDataSources({} as never, { json: (b: typeof body) => { body = b; } } as never);
  const byId = Object.fromEntries(body.sources.map(s => [s.id, s]));
  assert.equal(byId["flights-adsb"].status, "disabled");
  assert.equal(byId["flights-adsb"].current_source, "disabled");
  assert.equal(byId.weather.status, "stale");
  assert.equal(byId.passengers.status, "active");
  assert.equal((byId.passengers.details as Record<string, unknown>).total_in_airport, 1234);
  assert.ok("status_counts" in (byId.passengers.details as object));
  assert.equal(byId.baggage.status, "stale");          // owner clock 34 sim-min behind
  assert.equal(byId.baggage.last_updated_clock, "sim");
  assert.equal(byId.infrastructure.last_updated, null);
});

it("reports an owner that does not answer as unavailable", async () => {
  mock.method(globalThis, "fetch", async () => { throw new Error("ECONNREFUSED"); });
  let body: { sources: Array<Record<string, unknown>> } = { sources: [] };
  await ds.handleDataSources({} as never, { json: (b: typeof body) => { body = b; } } as never);
  const statuses = new Set(body.sources.filter(s => s.id !== "infrastructure").map(s => s.status));
  assert.deepEqual(statuses, new Set(["unavailable"]));
});
