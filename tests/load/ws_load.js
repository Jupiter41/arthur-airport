/**
 * k6 WebSocket load test for Arthur Airport API Gateway.
 *
 * Simulates 100 concurrent WebSocket connections, each subscribing to
 * all event topics and counting received messages.
 *
 * Usage:
 *   k6 run tests/load/ws_load.js
 *   k6 run tests/load/ws_load.js --env WS_URL=ws://localhost:3000/ws
 */

import ws from "k6/ws";
import { check } from "k6";
import { Counter, Trend } from "k6/metrics";

const WS_URL = __ENV.WS_URL || "ws://localhost:3000/ws";
const BASE_URL = __ENV.BASE_URL || "http://localhost:3000";

const wsMessages = new Counter("ws_messages_received");
const wsLatency = new Trend("ws_connect_duration", true);

export const options = {
  stages: [
    { duration: "15s", target: 25 }, // ramp up
    { duration: "1m", target: 100 }, // hold at 100 connections
    { duration: "1m", target: 100 }, // sustain
    { duration: "15s", target: 0 }, // ramp down
  ],
  thresholds: {
    ws_messages_received: ["count>0"],
  },
};

// Get auth token for WebSocket
export function setup() {
  const http = require("k6/http");
  const tokenRes = http.default.post(
    `${BASE_URL}/auth/token`,
    JSON.stringify({ client_id: "dashboard", secret: "art-dev-secret" }),
    { headers: { "Content-Type": "application/json" } },
  );
  return { token: tokenRes.json("token") };
}

export default function (data) {
  const url = `${WS_URL}?token=${data.token}`;

  const res = ws.connect(url, {}, function (socket) {
    socket.on("open", () => {
      // Subscribe to topics
      socket.send(
        JSON.stringify({
          type: "subscribe",
          topics: [
            "flights.events",
            "passengers.events",
            "baggage.events",
            "weather.events",
            "incidents.events",
          ],
        }),
      );
    });

    socket.on("message", (msg) => {
      wsMessages.add(1);
    });

    socket.on("error", (e) => {
      console.error("WebSocket error:", e);
    });

    // Keep connection open for 30 seconds
    socket.setTimeout(() => {
      socket.close();
    }, 30000);
  });

  wsLatency.add(res.timings ? res.timings.duration : 0);
  check(res, { "ws connected": (r) => r && r.status === 101 });
}
