/**
 * k6 REST API load test for Arthur Airport API Gateway.
 *
 * Simulates 1,000 requests/minute across key REST endpoints.
 *
 * Usage:
 *   k6 run tests/load/rest_load.js
 *   k6 run tests/load/rest_load.js --env BASE_URL=http://localhost:3000
 */

import http from "k6/http";
import { check, group } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:3000";

// Custom metrics
const errorRate = new Rate("errors");
const flightLatency = new Trend("flight_latency", true);
const passengerLatency = new Trend("passenger_latency", true);
const weatherLatency = new Trend("weather_latency", true);

export const options = {
  stages: [
    { duration: "30s", target: 10 }, // ramp up
    { duration: "2m", target: 17 }, // ~1000 req/min (17 VUs × ~1 req/s)
    { duration: "1m", target: 30 }, // spike
    { duration: "30s", target: 0 }, // ramp down
  ],
  thresholds: {
    http_req_duration: ["p(95)<500", "p(99)<1000"],
    errors: ["rate<0.05"],
  },
};

// Get auth token
export function setup() {
  const tokenRes = http.post(
    `${BASE_URL}/auth/token`,
    JSON.stringify({ client_id: "dashboard", secret: "art-dev-secret" }),
    { headers: { "Content-Type": "application/json" } },
  );
  const token = tokenRes.json("token");
  return { token };
}

export default function (data) {
  const headers = {
    Authorization: `Bearer ${data.token}`,
    "Content-Type": "application/json",
  };
  const params = { headers };

  group("Flights", () => {
    const res = http.get(`${BASE_URL}/api/v1/flights`, params);
    flightLatency.add(res.timings.duration);
    check(res, { "flights 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Passengers flow", () => {
    const res = http.get(`${BASE_URL}/api/v1/passengers/flow`, params);
    passengerLatency.add(res.timings.duration);
    check(res, { "passenger flow 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Weather", () => {
    const res = http.get(`${BASE_URL}/api/v1/weather/current`, params);
    weatherLatency.add(res.timings.duration);
    check(res, { "weather 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Baggage flow", () => {
    const res = http.get(`${BASE_URL}/api/v1/baggage/flow`, params);
    check(res, { "baggage flow 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Incidents", () => {
    const res = http.get(`${BASE_URL}/api/v1/incidents`, params);
    check(res, { "incidents 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Sim status", () => {
    const res = http.get(`${BASE_URL}/api/v1/sim/status`, params);
    check(res, { "sim status 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Analysis bottlenecks", () => {
    const res = http.get(`${BASE_URL}/api/v1/analysis/bottlenecks`, params);
    check(res, { "bottlenecks 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Health check", () => {
    const res = http.get(`${BASE_URL}/health`);
    check(res, { "health 200": (r) => r.status === 200 });
  });
}
