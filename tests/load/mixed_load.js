/**
 * k6 mixed load test — REST + WebSocket combined.
 *
 * Simulates realistic dashboard usage: WebSocket connections for live updates
 * plus periodic REST polling for state snapshots.
 *
 * Usage:
 *   k6 run tests/load/mixed_load.js
 */

import http from "k6/http";
import ws from "k6/ws";
import { check, group } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:3000";
const WS_URL = __ENV.WS_URL || "ws://localhost:3000/ws";

const errorRate = new Rate("errors");
const wsMessages = new Counter("ws_messages_total");
const restLatency = new Trend("rest_latency", true);

export const options = {
  scenarios: {
    // REST polling: 10 VUs doing periodic requests
    rest_polling: {
      executor: "constant-vus",
      vus: 10,
      duration: "3m",
      exec: "restPolling",
    },
    // WebSocket connections: ramp to 50
    ws_connections: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 20 },
        { duration: "1m30s", target: 50 },
        { duration: "30s", target: 50 },
        { duration: "30s", target: 0 },
      ],
      exec: "wsConnection",
    },
  },
  thresholds: {
    rest_latency: ["p(95)<500"],
    errors: ["rate<0.05"],
    ws_messages_total: ["count>100"],
  },
};

export function setup() {
  const tokenRes = http.post(
    `${BASE_URL}/auth/token`,
    JSON.stringify({ client_id: "dashboard", secret: "art-dev-secret" }),
    { headers: { "Content-Type": "application/json" } },
  );
  return { token: tokenRes.json("token") };
}

export function restPolling(data) {
  const headers = {
    Authorization: `Bearer ${data.token}`,
    "Content-Type": "application/json",
  };

  const endpoints = [
    "/api/v1/flights",
    "/api/v1/passengers/flow",
    "/api/v1/weather/current",
    "/api/v1/baggage/flow",
    "/api/v1/incidents",
    "/api/v1/sim/status",
    "/api/v1/analysis/bottlenecks",
    "/api/v1/analysis/recommendations",
  ];

  // Pick a random endpoint each iteration
  const endpoint = endpoints[Math.floor(Math.random() * endpoints.length)];

  group("REST polling", () => {
    const res = http.get(`${BASE_URL}${endpoint}`, { headers });
    restLatency.add(res.timings.duration);
    check(res, { "status 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });
}

export function wsConnection(data) {
  const url = `${WS_URL}?token=${data.token}`;

  ws.connect(url, {}, function (socket) {
    socket.on("open", () => {
      socket.send(
        JSON.stringify({
          type: "subscribe",
          topics: ["flights.events", "weather.events", "incidents.events"],
        }),
      );
    });

    socket.on("message", () => {
      wsMessages.add(1);
    });

    socket.setTimeout(() => {
      socket.close();
    }, 45000);
  });
}
