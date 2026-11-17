import { after, it } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "http";
import jwt from "jsonwebtoken";
import { WebSocket } from "ws";
import { Coalescer, deliveryClass, coalesceKey } from "./wsDelivery";

process.env.NODE_ENV = "test";
process.env.JWT_SECRET = "test-only-ws-delivery-secret";
const ws = require("./websocket") as typeof import("./websocket");

it("classifies UI events and drops per-entity firehose facts (RC9)", () => {
  assert.equal(deliveryClass("FlightStatusChanged"), "immediate");
  assert.equal(deliveryClass("SimClockTick"), "latest");
  assert.equal(deliveryClass("CostRecorded"), "latest");   // UI only refetches the cost summary
  assert.equal(deliveryClass("BaggageStatusBatchChanged"), "hint");
  for (const type of ["BaggageStatusChanged", "PassengerStatusChanged", "BoardingProgress", "EntitiesArchived", undefined]) {
    assert.equal(deliveryClass(type), null, String(type));
  }
});

it("coalesces to the newest envelope per key and strips hint payloads", () => {
  const sent: Array<[string, Record<string, unknown>]> = [];
  let replaced = 0;
  const c = new Coalescer(60_000, (topic, event) => sent.push([topic, event]), () => { replaced += 1; });
  for (let i = 0; i < 5; i++) c.offer("sim", { event_type: "SimClockTick", payload: { i } }, "latest");
  for (const t of ["A", "B", "A"]) c.offer("passengers", { event_type: "SecurityQueueUpdated", payload: { terminal: t, n: t } }, "latest");
  for (let i = 0; i < 300; i++) c.offer("baggage", { event_type: "BaggageStatusBatchChanged", event_id: `b${i}`, payload: { status_changes: new Array(50).fill({}) } }, "hint");
  c.flush();
  assert.equal(replaced, 4 + 1 + 299);
  assert.deepEqual(sent.map(([, e]) => e.event_type), ["SimClockTick", "SecurityQueueUpdated", "SecurityQueueUpdated", "BaggageStatusBatchChanged"]);
  assert.deepEqual(sent[0][1].payload, { i: 4 });
  const batch = sent[3][1];
  assert.equal(batch.event_id, "b299");
  assert.deepEqual(batch.payload, { hint: true, coalesced: 300 });
  assert.equal(c.size, 0);
  assert.equal(coalesceKey("passengers", { event_type: "SecurityQueueUpdated", payload: { terminal: "C" } }), "passengers:SecurityQueueUpdated:C");
});

it("bootstrap keeps only delivered, replayable envelopes", () => {
  ws.cacheLatestEvent("baggage", { event_type: "BaggageStatusChanged", payload: {} });
  ws.cacheLatestEvent("baggage", { event_type: "BaggageStatusBatchChanged", payload: {} });
  const types = Object.values(ws.getBootstrapState()).map(e => (e as { event_type: string }).event_type);
  assert.ok(!types.includes("BaggageStatusChanged"));
  assert.ok(!types.includes("BaggageStatusBatchChanged"));
});

const server = createServer(); const wss = ws.setupWebSocket(server);
const ready = new Promise<number>(resolve => server.listen(0, "127.0.0.1", () => resolve((server.address() as { port: number }).port)));
after(() => { for (const c of wss.clients) c.terminate(); wss.close(); server.close(); });

it("a browser receives one coalesced frame instead of the firehose", { timeout: 5000 }, async () => {
  const port = await ready;
  const token = jwt.sign({ sub: "test-viewer", role: "viewer", jti: "rc9" }, process.env.JWT_SECRET!, { expiresIn: 60 });
  const socket = new WebSocket(`ws://127.0.0.1:${port}/ws`, { headers: { Authorization: `Bearer ${token}` } });
  const received: Array<{ event_type: string; payload: Record<string, unknown> }> = [];
  try {
    await new Promise<void>((resolve, reject) => {
      socket.on("error", reject);
      socket.on("message", raw => {
        const event = JSON.parse(raw.toString());
        if (event.type === "snapshot") socket.send(JSON.stringify({ action: "subscribe", topics: ["baggage", "flights"] }));
        if (event.type === "subscribed") {
          for (let i = 0; i < 500; i++) ws.fanOut("baggage", { event_type: "BaggageStatusChanged", payload: { i } });
          for (let i = 0; i < 20; i++) ws.fanOut("baggage", { event_type: "BaggageStatusBatchChanged", payload: { status_changes: [i] } });
          ws.fanOut("flights", { event_type: "FlightStatusChanged", payload: { flight_id: "F1" } });
          ws.flushCoalesced();
          setTimeout(resolve, 200);
        }
        if (event.event_type) received.push(event);
      });
    });
  } finally { socket.terminate(); }
  assert.deepEqual(received.map(e => e.event_type), ["FlightStatusChanged", "BaggageStatusBatchChanged"]);
  assert.deepEqual(received[1].payload, { hint: true, coalesced: 20 });
});
