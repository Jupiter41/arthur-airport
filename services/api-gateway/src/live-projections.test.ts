import { after, it } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "http";
import jwt from "jsonwebtoken";
import { WebSocket } from "ws";

process.env.NODE_ENV = "test";
process.env.JWT_SECRET = "test-only-live-projection-secret";
const { setupWebSocket, cacheLatestEvent, getBootstrapState, fanOut, setSimMode } = require("./websocket") as typeof import("./websocket");
const server = createServer(); const wss = setupWebSocket(server);
const ready = new Promise<number>(resolve => server.listen(0, "127.0.0.1", () => resolve((server.address() as { port: number }).port)));
after(() => { for (const ws of wss.clients) ws.terminate(); wss.close(); server.close(); });

it("retains independent security terminals and full fleet snapshots across unrelated events", () => {
  for (const terminal of ["A", "B", "C"]) cacheLatestEvent("passengers", { event_type: "SecurityQueueUpdated", payload: { terminal, queue_depth: 12 } });
  cacheLatestEvent("passengers", { event_type: "PassengerStatusChanged", payload: {} });
  cacheLatestEvent("flights", { event_type: "GroundVehicleSnapshot", payload: { vehicles: [] } });
  cacheLatestEvent("flights", { event_type: "FlightStatusChanged", payload: {} });
  const state = Object.values(getBootstrapState()) as Array<{ event_type: string; payload: { terminal?: string } }>;
  assert.deepEqual(state.filter(e => e.event_type === "SecurityQueueUpdated").map(e => e.payload.terminal).sort(), ["A", "B", "C"]);
  assert.equal(state.filter(e => e.event_type === "GroundVehicleSnapshot").length, 1);
});

it("relays all operational snapshots immediately in BULK mode", { timeout: 5000 }, async () => {
  const port = await ready;
  const token = jwt.sign({ sub: "test-viewer", role: "viewer", jti: "live-test" }, process.env.JWT_SECRET!, { expiresIn: 60 });
  const socket = new WebSocket(`ws://127.0.0.1:${port}/ws`, { headers: { Authorization: `Bearer ${token}` } });
  const expected = ["GroundVehicleSnapshot", "SecurityQueueUpdated", "BaggageZoneSnapshot"];
  try {
    await new Promise<void>((resolve, reject) => {
      socket.on("error", reject);
      socket.on("message", raw => {
        const event = JSON.parse(raw.toString()) as { type?: string; event_type?: string };
        if (event.type === "snapshot") socket.send(JSON.stringify({ action: "subscribe", topics: ["flights", "passengers", "baggage"] }));
        if (event.type === "subscribed") {
          setSimMode("BULK");
          fanOut("flights", { event_type: expected[0], payload: { vehicles: [] } });
          fanOut("passengers", { event_type: expected[1], payload: { terminal: "A" } });
          fanOut("baggage", { event_type: expected[2], payload: { zones: [] } });
        }
        if (event.event_type) {
          assert.equal(event.event_type, expected.shift());
          if (!expected.length) resolve();
        }
      });
    });
  } finally { socket.terminate(); setSimMode("REALTIME"); }
});
