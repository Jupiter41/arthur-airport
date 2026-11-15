import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import * as T from "three";
import type { Flight, Runway } from "../types";
import { atcPicture, clockText, stripKey, type RunwayQueueSnapshot } from "../pages/Airport3D/atc";
import { AtcBoard } from "../pages/Airport3D/AtcBoard";
import { buildLayout, entities, flightPose, holdingOrder, parseSimSeconds, type SceneData } from "../pages/Airport3D/model";
import { buildScene } from "../pages/Airport3D/scenes";
import { disposeTree } from "../pages/Airport3D/primitives";

const T0 = parseSimSeconds("2026-01-01T12:00:00Z")!;
const f = (values: Partial<Flight>): Flight => ({ id: "x", flight_number: "XX1", aircraft_type: "A320", direction: "arrival", status: "approach",
  gate_id: "A01", runway_id: "09L", estimated_time: "2026-01-01T12:10:00Z", actual_time: null, delay_minutes: 0, pax_count: 100, pax_boarded: 0,
  taxi_initial_minutes: 2, taxi_total_minutes: 8, ...values } as Flight);
const runways: Runway[] = ["09L", "27R", "09R", "27L"].map(id => ({ runway_id: id, status: "open", current_use: id === "09L" ? "landing" : "idle", arrivals_queued: 1, departures_queued: 2 } as unknown as Runway));
const queue: RunwayQueueSnapshot = { sim_time: "2026-01-01T12:00:00", weather_category: "IMC", ils_required: true, arrival_rate: 24, departure_rate: 20,
  capacity_per_hour: 44, current_rate: 12, runway_free_at: "2026-01-01T12:00:50", runway_occupied: true, last_arrival_type: "A320", last_departure_type: null,
  arrivals: [{ position: 1, flight_id: "q1", aircraft_type: "B77W", weight_category: "HEAVY", estimated_time: "2026-01-01T12:30:00", emergency: true, wake_separation_seconds: 83 }], departures: [] };
function scene(): SceneData {
  return { gates: [{ gate_id: "A01", terminal: "T-A", status: "occupied", flight_id: null, flight_number: null }], vehicles: [], zones: [], runways, runwayQueue: queue,
    flights: [
      f({ id: "a1", flight_number: "AR1", estimated_time: "2026-01-01T12:04:00Z" }),
      f({ id: "a2", flight_number: "AR2", estimated_time: "2026-01-01T12:01:30Z" }),
      f({ id: "a3", flight_number: "AR3", runway_id: "09R", estimated_time: "2026-01-01T12:06:00Z" }),
      f({ id: "h1", flight_number: "HD1", status: "delayed", delay_minutes: 12 }),
      f({ id: "l1", flight_number: "LD1", status: "landed", runway_id: "27R", actual_time: "2026-01-01T11:59:00Z" }),
      f({ id: "d1", flight_number: "DP1", direction: "departure", status: "boarding", pax_boarded: 96, estimated_time: "2026-01-01T12:05:00Z" }),
      f({ id: "q1", flight_number: "QQ1", status: "scheduled" }),
    ] };
}
const picture = (data = scene(), t = T0) => {
  const layout = buildLayout(data), holding = holdingOrder(data.flights);
  return atcPicture(data.flights, data.runways, layout, t, x => flightPose(x, data, t, layout, holding));
};

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ fillRect: vi.fn(), fillText: vi.fn() } as unknown as ReturnType<typeof HTMLCanvasElement.prototype.getContext>);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("ATC traffic picture", () => {
  it("pairs reciprocal runway ends into physical strips", () => {
    const layout = buildLayout(scene());
    expect(stripKey(layout, "09L")).toBe(stripKey(layout, "27R"));
    expect(stripKey(layout, "09L")).not.toBe(stripKey(layout, "09R"));
    expect(picture().strips).toHaveLength(2);
  });
  it("sequences arrivals by owner ETA with per-strip spacing", () => {
    const rows = picture().arrivals;
    expect(rows.map(r => r.flight.id)).toEqual(["a2", "a1", "a3"]);
    expect(rows.map(r => r.secondsToTouchdown)).toEqual([90, 240, 360]);
    expect(rows.map(r => r.spacingSeconds)).toEqual([null, 150, null]); // a3 is first on 09R
  });
  it("marks the strip occupied only by aircraft in a runway phase, plus short final", () => {
    const [strip09L] = picture().strips.filter(s => s.ends.some(e => e.runway_id === "09L"));
    expect(strip09L.occupant?.flight.id).toBe("l1"); // landed on 27R = same physical strip
    expect(strip09L.occupant?.phase).toBe("Landing rollout");
    expect(strip09L.shortFinal?.flight.id).toBe("a2");
    const vacated = scene(); vacated.flights = vacated.flights.map(x => x.id === "l1" ? { ...x, status: "taxiing" } : x);
    const later = picture(vacated, T0 + 180).strips.find(s => s.ends.some(e => e.runway_id === "09L"))!;
    expect(later.occupant).toBeNull(); // owner moved it to taxiing: strip clear
  });
  it("lists the holding stack and the FSM boarding readiness", () => {
    const p = picture();
    expect(p.holding.map(r => r.flight.id)).toEqual(["h1"]);
    expect(p.boarding[0]).toMatchObject({ ready: true, secondsToOffBlock: 300 });
    expect(clockText(-65)).toBe("−1:05"); expect(clockText(null)).toBe("—");
  });
});

describe("ATC scene and board", () => {
  it("adds approach corridors and data blocks without changing aircraft timeline poses", () => {
    const data = scene();
    const atc = buildScene(data, { view: "atc", terminal: "A", quality: "low" }, T0);
    const airfield = buildScene(data, { view: "airport", terminal: "A", quality: "low" }, T0);
    expect(atc.locate("a1")!.toArray()).toEqual(airfield.locate("a1")!.toArray());
    const lines = (root: T.Object3D) => { let n = 0; root.traverse(o => { if (o instanceof T.Line) n++; }); return n; };
    expect(lines(atc.root)).toBeGreaterThanOrEqual(lines(airfield.root) + 8); // glide path + ground track per runway end
    expect(atc.entities.map(e => e.id).sort()).toEqual(["09L", "09R", "27L", "27R", "a1", "a2", "a3", "h1", "l1"]);
    expect(entities(data, { view: "atc", terminal: "A", quality: "low" }, T0).some(e => e.kind === "vehicle" || e.kind === "gate")).toBe(false);
    disposeTree(atc.root); disposeTree(airfield.root);
  });
  it("renders owner sequence, capacity and selection without clearance controls", () => {
    const onSelect = vi.fn();
    render(<AtcBoard data={scene()} seconds={T0} onSelect={onSelect} />);
    expect(screen.getByText("IMC · ILS req.")).toBeInTheDocument();
    expect(screen.getByText("Blocked to 12:00:50")).toBeInTheDocument();
    const sequence = within(screen.getByRole("region", { name: "Owner runway sequence" }));
    expect(sequence.getByText("EMERG")).toBeInTheDocument(); expect(sequence.getByText("+1:23")).toBeInTheDocument();
    const approach = within(screen.getByRole("region", { name: "Final approach sequence" }));
    fireEvent.click(approach.getByRole("button", { name: "AR2" }));
    expect(onSelect).toHaveBeenCalledWith("a2");
    expect(screen.queryByRole("button", { name: /clear|cleared|land|takeoff/i })).not.toBeInTheDocument();
    expect(screen.getByText(/does not model ATC clearances/)).toBeInTheDocument();
  });
  it("labels an unavailable runway queue instead of inventing one", () => {
    render(<AtcBoard data={{ ...scene(), runwayQueue: undefined }} seconds={T0} />);
    expect(screen.getByText("Runway queue unavailable.")).toBeInTheDocument();
  });
});
