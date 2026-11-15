import { describe, expect, it } from "vitest";
import type { Flight, GroundVehicle } from "../types";
import { aircraftPose, parseTime, vehiclePose, type Layout } from "../pages/Airport3D/kinematics";
import { maxLead, simSecondsAt, VisualClock } from "../pages/Airport3D/simClock";

const layout: Layout = {
  gates: new Map([["A01", { x: 160, y: 150 }], ["C03", { x: 280, y: 650 }]]),
  runways: new Map([["09L", { id: "09L", threshold: { x: 100, y: 800 }, end: { x: 900, y: 800 } }]]),
  terminalY: t => ({ A: 150, B: 400, C: 650 })[t] ?? 400,
};
const T0 = parseTime("2026-01-01T12:00:00Z")!;
const at = (minutes: number) => T0 + minutes * 60;
const arrival = (values: Partial<Flight>) => ({ id: "a1", flight_number: "AR1", direction: "arrival", runway_id: "09L", gate_id: "A01",
  estimated_time: "2026-01-01T12:00:00Z", actual_time: "2026-01-01T12:00:00Z", taxi_initial_minutes: 2, taxi_total_minutes: 8, delay_minutes: 0, ...values } as Flight);
const departure = (values: Partial<Flight>) => arrival({ direction: "departure", status: "departed", ...values });

describe("aircraft follow the owner state-machine timeline", () => {
  it("descends the final approach from ETA−20 and reaches the threshold at ETA", () => {
    const f = arrival({ status: "approach" });
    const start = aircraftPose(f, layout, at(-20))!, mid = aircraftPose(f, layout, at(-10))!, end = aircraftPose(f, layout, at(0))!;
    expect(start.progress).toBe(0); expect(end.progress).toBe(1);
    expect(start.x).toBeLessThan(mid.x); expect(mid.x).toBeLessThan(end.x);
    expect(start.altitude).toBeGreaterThan(mid.altitude); expect(end.x).toBeCloseTo(100); expect(end.y).toBe(800);
    expect(aircraftPose({ ...f, runway_id: null }, layout, at(-5))).toBeNull(); // no runway assigned → not invented
  });
  it("rolls out over taxi_initial, then taxis to the gate stand over taxi_total", () => {
    const touchdown = aircraftPose(arrival({ status: "landed" }), layout, at(0))!;
    const vacate = aircraftPose(arrival({ status: "landed" }), layout, at(2))!;
    expect(touchdown.x).toBeCloseTo(100); expect(vacate.x).toBeCloseTo(100 + 800 * 0.55);
    const taxiStart = aircraftPose(arrival({ status: "taxiing" }), layout, at(2))!;
    expect(taxiStart.x).toBeCloseTo(vacate.x); expect(taxiStart.y).toBeCloseTo(800);
    const onStand = aircraftPose(arrival({ status: "taxiing" }), layout, at(8))!;
    expect([onStand.x, onStand.y]).toEqual([160, 195]);
    expect(aircraftPose(arrival({ status: "at_gate" }), layout, at(30))!.phase).toBe("At gate");
  });
  it("stays out of the scene while en route or after leaving", () => {
    expect(aircraftPose(arrival({ status: "airborne" }), layout, at(-30))).toBeNull();
    expect(aircraftPose(arrival({ status: "scheduled" }), layout, at(-30))).toBeNull();
    expect(aircraftPose(departure({ status: "airborne" }), layout, at(30))).toBeNull();
    expect(aircraftPose(departure({ status: "arrived" }), layout, at(1))).toBeNull();
  });
  it("pushes back, taxis, rolls and climbs inside the 5-minute departure window", () => {
    const phases = [0.2, 1.5, 3.6, 4.8, 7].map(m => aircraftPose(departure({}), layout, at(m))!.phase);
    expect(phases).toEqual(["Pushback", "Taxi-out", "Take-off roll", "Rotation / initial climb", "Climb-out"]);
    const roll = aircraftPose(departure({}), layout, at(4.2))!, climb = aircraftPose(departure({}), layout, at(9))!;
    expect(roll.y).toBe(800); expect(climb.altitude).toBeGreaterThan(roll.altitude);
  });
  it("circles a stable holding stack while an arrival is delayed", () => {
    const f = arrival({ status: "delayed" });
    const a = aircraftPose(f, layout, at(0), 0)!, b = aircraftPose(f, layout, at(1), 0)!, upper = aircraftPose(f, layout, at(0), 2)!;
    expect(a.phase).toBe("Holding"); expect([a.x, a.y]).not.toEqual([b.x, b.y]);
    expect(upper.altitude).toBeGreaterThan(a.altitude);
    const lap = aircraftPose(f, layout, at(4), 0)!; expect(lap.x).toBeCloseTo(a.x); expect(lap.y).toBeCloseTo(a.y);
  });
  it("holds short when the owner has not confirmed the gate after the taxi time", () => {
    const pose = aircraftPose(arrival({ status: "taxiing" }), layout, at(12))!;
    expect(pose.phase).toBe("Holding short of gate"); expect(pose.y).toBe(275);
  });
});

describe("vehicles interpolate their owner trip", () => {
  const truck = { id: "v", type: "fuel_truck", status: "dispatched", current_gate: "A01", position_x: 160, position_y: 150, task_name: null, flight_id: null,
    origin_x: 500, origin_y: 300, target_x: 160, target_y: 150, dispatched_at: "2026-01-01T12:00:00Z", arrives_at: "2026-01-01T12:04:00Z" } as GroundVehicle;
  it("moves linearly between dispatched_at and arrives_at", () => {
    expect(vehiclePose(truck, at(0))).toMatchObject({ x: 500, y: 300, moving: true });
    expect(vehiclePose(truck, at(2))).toMatchObject({ x: 330, y: 225 });
    expect(vehiclePose(truck, at(9))).toMatchObject({ x: 160, y: 150, moving: false });
  });
  it("falls back to the owner position without trip facts", () => {
    expect(vehiclePose({ ...truck, origin_x: null, dispatched_at: null }, at(2))).toMatchObject({ x: 160, y: 150, moving: false });
  });
});

describe("visual simulation clock", () => {
  it("extrapolates at source speed, caps the lead and freezes when paused", () => {
    const anchor = { sim: 1000, wall: 0, speed: 60, paused: false };
    expect(simSecondsAt(anchor, 500)).toBe(1030);
    expect(simSecondsAt(anchor, 60_000)).toBe(1000 + maxLead(60));
    expect(simSecondsAt({ ...anchor, paused: true }, 500)).toBe(1000);
    expect(simSecondsAt(anchor, 500, true)).toBe(1000);
  });
  it("never rewinds on a slightly late tick but follows a genuine reset", () => {
    const clock = new VisualClock();
    clock.observe(1000, 0, 60, false); expect(clock.now(1500)).toBe(1090);
    clock.observe(1060, 1500, 60, false); expect(clock.now(1500)).toBe(1090);
    expect(clock.now(2500)).toBe(1120);
    clock.observe(100, 3000, 60, false); expect(clock.now(3000)).toBe(100);
    clock.observe(100, 3000, 60, true); expect(clock.now(9000)).toBe(100);
  });
});
