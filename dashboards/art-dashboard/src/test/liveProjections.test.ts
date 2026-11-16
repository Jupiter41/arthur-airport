import { afterEach, beforeEach, expect, it } from "vitest";
import { queryClient } from "../queryClient";
import { eventHandlers } from "../hooks/useWebSocket";
import { resetLiveProjectionGuards } from "../hooks/liveProjections";
import { useGroundVehicleStore } from "../stores/groundVehicleStore";
import type { KafkaEvent, PassengerFlowSummary } from "../types";

const at = "2026-01-01T12:00:00Z";
function send(type: string, payload: Record<string, unknown>, time = at) { eventHandlers[type](payload, time, { event_type: type, payload, sim_time: time } as KafkaEvent); }
beforeEach(() => { queryClient.clear(); resetLiveProjectionGuards(); useGroundVehicleStore.getState().clear(); });
afterEach(() => queryClient.clear());
it("updates both dimensions' canonical queue cache without inventing other terminal counts", () => {
  const summary: PassengerFlowSummary = { total_in_airport: 200, by_status: {}, connections_at_risk: 0, connections_missed: 0, security: { A: { queue_length: 9, wait_minutes: 3, lanes_open: 1 }, B: { queue_length: 17, wait_minutes: 4, lanes_open: 2 } } };
  queryClient.setQueryData(["passengers", "summary"], summary);
  send("SecurityQueueUpdated", { terminal: "A", queue_depth: 30, lanes_open: 4, wait_minutes: 2.5, frozen: false, at });
  const next = queryClient.getQueryData<PassengerFlowSummary>(["passengers", "summary"])!;
  expect(next.security.A.observed_at).toBe(at); expect(next.security.A.queue_length).toBe(30); expect(next.security.B).toEqual(summary.security.B);
  expect(next.total_in_airport).toBe(200);
  send("SecurityQueueUpdated", { terminal: "A", queue_depth: 1, lanes_open: 1, wait_minutes: 1, frozen: false, at: "2026-01-01T11:59:00Z" });
  expect(queryClient.getQueryData<PassengerFlowSummary>(["passengers", "summary"])!.security.A.queue_length).toBe(30);
});
it("waits for a full initial summary instead of initializing missing fields to healthy zeros", () => {
  send("SecurityQueueUpdated", { terminal: "A", queue_depth: 30, lanes_open: 4, wait_minutes: 2.5, frozen: false, at });
  expect(queryClient.getQueryData(["passengers", "summary"])).toBeUndefined();
});
it("replaces baggage occupancy and failures from full owner snapshots, including empty snapshots", () => {
  const zones = [{ zone_id: "induction-A", items: 50, status: "offline", throughput_per_hour: 0, utilisation_pct: 100 }];
  send("BaggageZoneSnapshot", { zones, at });
  expect(queryClient.getQueryData(["baggage", "map"])).toEqual(zones.map(zone => ({ ...zone, observed_at: at })));
  send("BaggageZoneSnapshot", { zones: [{ zone_id: "bad" }], at });
  expect(queryClient.getQueryData(["baggage", "map"])).toEqual(zones.map(zone => ({ ...zone, observed_at: at })));
  send("BaggageZoneSnapshot", { zones: [], at: "2026-01-01T12:01:00Z" });
  expect(queryClient.getQueryData(["baggage", "map"])).toEqual([]);
});
it("uses reported fleet coordinates and does not teleport dispatches to zero", () => {
  const vehicle = { id: "v1", type: "fuel_truck", status: "available", position_x: 600, position_y: 300, current_gate: null, task_name: null, flight_id: null };
  send("GroundVehicleSnapshot", { vehicles: [vehicle], at });
  send("GroundVehicleDispatched", { vehicle_id: "v1", gate_id: "A01" });
  expect(useGroundVehicleStore.getState().vehicles.v1.position_x).toBe(600);
  expect(useGroundVehicleStore.getState().vehicles.v1.status).toBe("dispatched");
  send("GroundVehicleSnapshot", { vehicles: [{ ...vehicle, position_x: 650, status: "at_gate" }], at: "2026-01-01T12:01:00Z" });
  expect(useGroundVehicleStore.getState().vehicles.v1.position_x).toBe(650);
  send("GroundVehicleSnapshot", { vehicles: [], at: "2026-01-01T12:02:00Z" });
  expect(useGroundVehicleStore.getState().vehicles).toEqual({});
});
