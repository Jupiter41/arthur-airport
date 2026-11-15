import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as T from "three";
import type { Flight, Gate, Runway } from "../types";
import { entities, flightPose, gatePoint, gridPoint, normalizeGate, parseSimSeconds, representativeCount, runwayPoint, zoneInTerminal, type SceneData, type SceneOptions } from "../pages/Airport3D/model";
import { buildScene } from "../pages/Airport3D/scenes";
import { disposeTree } from "../pages/Airport3D/primitives";

const gridToScene = (p: { x: number; y: number }) => [(p.x - 500) / 5, (p.y - 500) / 5];

const gate: Gate = { gate_id: "A01", terminal: "T-A", status: "occupied", flight_id: "f1", flight_number: "AX101" };
const flight = (values: Partial<Flight> = {}): Flight => ({ id: "f1", flight_number: "AX101", aircraft_type: "A320", direction: "departure", gate_id: "A01", status: "boarding", actual_time: "2026-01-01T12:00:00Z", estimated_time: "2026-01-01T12:30:00Z", runway_id: "09L", ...values } as Flight);
const options: SceneOptions = { view: "airport", terminal: "A", quality: "balanced" };
function data(): SceneData {
  return { flights: [flight()], gates: [gate], runways: [], vehicles: [],
    passenger: { total_in_airport: 1000, by_status: {}, connections_at_risk: 0, connections_missed: 0, security: { A: { queue_length: 1000, wait_minutes: 45, lanes_open: 2 } } },
    zones: [{ zone_id: "induction-A", zone_type: "induction", status: "active", items: 1000, capacity: 2000, utilisation_pct: 90, throughput_per_hour: 600 }, { zone_id: "induction-B", zone_type: "induction", status: "offline", items: 20, capacity: 50, utilisation_pct: 100, throughput_per_hour: 0 }] };
}
beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ fillRect: vi.fn(), fillText: vi.fn() } as unknown as ReturnType<typeof HTMLCanvasElement.prototype.getContext>);
});
afterEach(() => vi.restoreAllMocks());

describe("3D operational adapters", () => {
  it("maps the owner grid consistently and accepts the actual gate API identity", () => {
    expect(gridPoint(500, 300, 1)).toEqual([0, 1, -40]);
    expect(gatePoint(gate)).toEqual([-68, 0, -70]);
    expect(normalizeGate({ ...gate, gate_id: "", id: "A02" }).gate_id).toBe("A02");
    expect(gatePoint({ ...gate, position_x: 600, position_y: 400 } as Gate)).toEqual([20, 0, -20]);
  });
  it("never displays future/cancelled flights as aircraft and does not invent gates", () => {
    for (const status of ["scheduled", "cancelled", "arrived"] as const) expect(flightPose(flight({ status }), data(), 0)).toBeNull();
    expect(flightPose(flight({ status: "airborne", direction: "arrival" }), data(), 0)).toBeNull();
    expect(flightPose(flight({ gate_id: null }), data(), 0)).toBeNull();
    const parked = flightPose(flight(), data(), 0)!;
    expect(gridToScene(parked)).toEqual([-68, -61]);
  });
  it("places reciprocal runway ends on the same physical strip", () => {
    expect(runwayPoint({ runway_id: "09L" } as Runway)).toEqual(runwayPoint({ runway_id: "27R" } as Runway));
    expect(runwayPoint({ runway_id: "09R" } as Runway)).toEqual(runwayPoint({ runway_id: "27L" } as Runway));
    expect(runwayPoint({ runway_id: "09L" } as Runway)).not.toEqual(runwayPoint({ runway_id: "09R" } as Runway));
  });
  it("places taxiing aircraft on the owner timeline and accepts reported owner coordinates", () => {
    const time = parseSimSeconds("2026-01-01T12:00:00")!;
    expect(time).toBe(parseSimSeconds("2026-01-01T12:00:00Z"));
    expect(parseSimSeconds("invalid")).toBeNull();
    const taxi = flight({ status: "taxiing", direction: "arrival", taxi_initial_minutes: 2, taxi_total_minutes: 8 } as Partial<Flight>);
    const start = flightPose(taxi, data(), time + 120)!, middle = flightPose(taxi, data(), time + 300)!, end = flightPose(taxi, data(), time + 480)!;
    expect(start.progress).toBe(0); expect(middle.progress).toBeCloseTo(0.5); expect(end.progress).toBe(1);
    expect(gridToScene(end)).toEqual([-68, -61]); // on the assigned stand at ATA + owner taxi total
    expect(flightPose(taxi, data(), time + 900)!.phase).toBe("Holding short of gate");
    expect(flightPose({ ...taxi, runway_id: null }, data(), time + 300)).toBeNull();
    expect(gridToScene(flightPose({ ...taxi, position_x: 600, position_y: 300 } as Flight, data(), 0)!)).toEqual([20, -40]);
    const view = entities({ ...data(), flights: [taxi] }, options, time + 300);
    expect(view.find(e => e.id === taxi.id)?.positionAvailable).toBe(true);
  });
  it("bounds representative geometry independently of elapsed time", () => {
    expect(representativeCount(10000, 600)).toBe(600);
    expect(representativeCount(-1, 600)).toBe(0);
  });
  it("preserves exact counts and terminal scope while labelling illustrative representations", () => {
    const source = data();
    const checkpoint = entities(source, { ...options, view: "passengers" }, 0)[0];
    expect(checkpoint.facts).toContainEqual(["Queue", "1000 passengers"]);
    expect(entities(source, { ...options, view: "baggage" }, 0).map(e => e.id)).toEqual(["induction-A"]);
    expect(entities({ ...source, passenger: undefined }, { ...options, view: "passengers" }, 0)).toEqual([]);
    expect(zoneInTerminal("screening-unit-3", "B")).toBe(true);
    expect(zoneInTerminal("screening-unit-1", "B")).toBe(false);
    expect(zoneInTerminal("arrival-belt-6", "C")).toBe(true);
  });
  it("includes live non-security passenger areas and shared arrival observations", () => {
    const source: SceneData = { ...data(), passengerZones: [
      { zone_id: "check-in-A", terminal: "A", zone_type: "checkin", density: 15, capacity: 100, load_pct: 15 },
      { zone_id: "airside-A", terminal: "A", zone_type: "airside", density: 20, capacity: 100, load_pct: 20 },
      { zone_id: "carousel-2", terminal: "", zone_type: "carousel", density: 10, capacity: 100, load_pct: 10 },
      { zone_id: "carousel-3", terminal: "", zone_type: "carousel", density: 5, capacity: 100, load_pct: 5 },
    ] };
    const rows = entities(source, { ...options, view: "passengers" }, 0);
    expect(rows.map(e => e.id)).toEqual(["security-A", "check-in-A", "airside-A", "carousel-2"]);
    const scene = buildScene(source, { ...options, view: "passengers", quality: "low" }, 0);
    expect(scene.representatives).toBeLessThanOrEqual(150); disposeTree(scene.root);
  });
});

describe("3D scene behavior", () => {
  it("renders the airport's real aircraft/gate selection identities without fabricating traffic", () => {
    const scene = buildScene(data(), options, 0);
    expect(scene.entities.map(e => e.id)).toEqual(["A01", "f1"]);
    const ids = new Set<string>(); scene.root.traverse(o => { if (o.userData.entityId) ids.add(o.userData.entityId); });
    expect(ids.has("f1")).toBe(true); expect(ids.has("A01")).toBe(true);
    disposeTree(scene.root);
  });
  it("caps crowds, displays frozen lanes and prevents their illustrative motion", () => {
    const source = data(); source.passenger!.security.A.frozen = true;
    const scene = buildScene(source, { ...options, view: "passengers", quality: "low" }, 0);
    expect(scene.representatives).toBe(150); expect(scene.entities[0].status).toBe("frozen");
    const instances: T.InstancedMesh[] = []; scene.root.traverse(o => { if (o instanceof T.InstancedMesh) instances.push(o); });
    const before = Array.from(instances[0].instanceMatrix.array); scene.update(500);
    expect(Array.from(instances[0].instanceMatrix.array)).toEqual(before);
    disposeTree(scene.root);
  });
  it("moves bags at the observed dwell time and stops offline belts", () => {
    const source = data(); source.zones[0].status = "offline";
    const scene = buildScene(source, { ...options, view: "baggage" }, 0);
    const instances: T.InstancedMesh[] = []; scene.root.traverse(o => { if (o instanceof T.InstancedMesh) instances.push(o); });
    const before = Array.from(instances[0].instanceMatrix.array); scene.update(300);
    expect(Array.from(instances[0].instanceMatrix.array)).toEqual(before); disposeTree(scene.root);
    source.zones[0].status = "normal"; // 1000 items at 600/h: a bag crosses its belt in 100 sim minutes
    const moving = buildScene(source, { ...options, view: "baggage" }, 0);
    const mesh = moving.root.children.find(o => o instanceof T.InstancedMesh) as T.InstancedMesh;
    const start = Array.from(mesh.instanceMatrix.array);
    moving.update(1500); expect(Array.from(mesh.instanceMatrix.array)).not.toEqual(start);
    moving.update(6000); // one full dwell cycle
    Array.from(mesh.instanceMatrix.array).forEach((v, i) => expect(v).toBeCloseTo(start[i], 3));
    disposeTree(moving.root);
  });
  it("advances the security queue at the reported wait and keeps the pause frozen", () => {
    const scene = buildScene(data(), { ...options, view: "passengers", quality: "low" }, 0);
    const instances: T.InstancedMesh[] = []; scene.root.traverse(o => { if (o instanceof T.InstancedMesh) instances.push(o); });
    const queue = instances[instances.length - 2]; const start = Array.from(queue.instanceMatrix.array);
    scene.update(600); expect(Array.from(queue.instanceMatrix.array)).not.toEqual(start);
    scene.update(45 * 60); // one reported wait later the crowd pattern repeats
    Array.from(queue.instanceMatrix.array).forEach((v, i) => expect(v).toBeCloseTo(start[i], 3));
    disposeTree(scene.root);
  });
  it("moves aircraft and vehicles with simulation time and reports their live location", () => {
    const t0 = parseSimSeconds("2026-01-01T12:00:00")!;
    const source = data();
    source.runways = [{ runway_id: "09L", status: "open", threshold_x: 100, threshold_y: 800, end_x: 900, end_y: 800 } as Runway];
    source.flights = [flight({ id: "f2", flight_number: "AX202", direction: "arrival", status: "approach", estimated_time: "2026-01-01T12:20:00Z", gate_id: null })];
    source.vehicles = [{ id: "GV-FUE-001", type: "fuel_truck", status: "dispatched", current_gate: "A01", position_x: 160, position_y: 150, task_name: "fueling", flight_id: "f1",
      origin_x: 500, origin_y: 300, target_x: 160, target_y: 150, dispatched_at: "2026-01-01T12:00:00Z", arrives_at: "2026-01-01T12:04:00Z" }];
    const scene = buildScene(source, options, t0);
    const early = scene.locate("f2")!.clone(); scene.update(t0 + 1190); const late = scene.locate("f2")!;
    expect(late.x).toBeGreaterThan(early.x); expect(late.y).toBeLessThan(early.y); // descending towards the 09L threshold
    expect(late.x).toBeCloseTo(-80, 0);
    scene.update(t0 + 120); expect(scene.locate("GV-FUE-001")!.x).toBeCloseTo(-34, 1); // halfway along its owner trip
    scene.update(t0 + 600); expect(scene.locate("GV-FUE-001")!.x).toBeCloseTo(-70.8, 1); // parked beside the A01 stand
    disposeTree(scene.root);
  });
  it("does not create bags or passenger figures when observations are unavailable", () => {
    const source = { ...data(), passenger: undefined, zones: [] };
    for (const view of ["passengers", "baggage"] as const) {
      const scene = buildScene(source, { ...options, view }, 0);
      expect(scene.representatives).toBe(0); expect(scene.entities).toEqual([]); disposeTree(scene.root);
    }
  });
});
