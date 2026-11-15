import type { BaggageZone, Flight, Gate, GroundVehicle, PassengerFlowSummary, Runway, ZoneDensity } from "../../types";
import { aircraftPose, runwayGeometry, vehiclePose, type Layout, type Pose } from "./kinematics";
import type { RunwayQueueSnapshot } from "./atc";

export type View = "airport" | "passengers" | "baggage" | "atc";
export type Terminal = "A" | "B" | "C";
export type Quality = "low" | "balanced" | "high";
export type Point = [number, number, number];
export interface Entity {
  id: string;
  kind: "flight" | "gate" | "runway" | "vehicle" | "checkpoint" | "zone" | "passenger_zone";
  label: string;
  status: string;
  position: Point;
  positionAvailable?: boolean;
  facts: Array<[string, string]>;
  href: string;
}
export interface BagItem {
  id: string; tag: string; status: string; last_scan_zone?: string | null;
  flight_number?: string | null; last_scan_at?: string | null;
}
export interface BagDetail extends BagItem {
  scan_history?: Array<{ zone: string; status: string; at: string }>;
}
export interface SceneData {
  flights: Flight[]; gates: Gate[]; runways: Runway[]; vehicles: GroundVehicle[];
  passenger?: PassengerFlowSummary; passengerZones?: ZoneDensity[]; zones: BaggageZone[];
  runwayQueue?: RunwayQueueSnapshot;
}
export interface SceneOptions {
  view: View; terminal: Terminal; quality: Quality;
}
export const QUALITY = {
  low: { ratio: 1, people: 150, bags: 100 },
  balanced: { ratio: 1.5, people: 600, bags: 400 },
  high: { ratio: 2, people: 900, bags: 600 },
} satisfies Record<Quality, { ratio: number; people: number; bags: number }>;

export const terminalY = (terminal: string) => ({ A: 150, B: 400, C: 650 })[terminal] ?? 400;
export const gridPoint = (x: number, y: number, height = 0): Point => [(x - 500) / 5, height, (y - 500) / 5];
export const normalizeTerminal = (value: string) => value.replace(/^(?:T-|terminal[-_ ]?)/i, "").toUpperCase();

// Gate API historically returns `id`; accept both without rewriting owner data.
export function normalizeGate(raw: Gate & { id?: string }): Gate {
  return { ...raw, gate_id: raw.gate_id || raw.id || "" };
}
export function gatePoint(gate: Gate): Point {
  const spatial = gate as Gate & { position_x?: number; position_y?: number };
  if (Number.isFinite(spatial.position_x) && Number.isFinite(spatial.position_y)) {
    return gridPoint(spatial.position_x!, spatial.position_y!);
  }
  const n = Number(gate.gate_id.match(/\d+/)?.[0] ?? 1);
  return gridPoint(160 + (n - 1) * 60, terminalY(normalizeTerminal(gate.terminal || gate.gate_id[0])));
}
export function checkpoint(data: SceneData, terminal: Terminal) {
  const values = data.passenger?.security;
  return values?.[terminal] ?? values?.[`terminal_${terminal.toLowerCase()}`] ?? values?.[`Terminal ${terminal}`];
}
export { parseTime as parseSimSeconds } from "./kinematics";

export function representativeCount(actual: number, cap: number): number {
  return Math.min(Math.max(0, Math.floor(actual)), cap);
}

export function runwayPoint(runway: Runway, index = 0): Point {
  const row = runway as Runway & { threshold_x?: number; threshold_y?: number; end_x?: number; end_y?: number };
  if ([row.threshold_x, row.threshold_y, row.end_x, row.end_y].every(v => Number.isFinite(v))) {
    return gridPoint((row.threshold_x! + row.end_x!) / 2, (row.threshold_y! + row.end_y!) / 2);
  }
  // Reciprocal designators describe two ends of the same physical strip.
  return [0, 0, ["09L", "27R"].includes(runway.runway_id) ? 60 : ["09R", "27L"].includes(runway.runway_id) ? 80 : 100 + index * 20];
}

export function gateGrid(gate: Gate): { x: number; y: number } {
  const [x, , z] = gatePoint(gate);
  return { x: x * 5 + 500, y: z * 5 + 500 };
}
/** Layout from owner coordinates, with the documented fixture as fallback. */
export function buildLayout(data: SceneData): Layout {
  const runways = new Map(data.runways.map(r => [r.runway_id, runwayGeometry(r)] as const).filter((e): e is [string, NonNullable<typeof e[1]>] => !!e[1]));
  return { gates: new Map(data.gates.map(g => [g.gate_id, gateGrid(g)])), runways, terminalY };
}
/** Arrivals currently in the holding stack, ordered for stable stack positions. */
export function holdingOrder(flights: Flight[]): Map<string, number> {
  return new Map(flights.filter(f => f.status === "delayed" && f.direction === "arrival").map(f => f.id).sort().map((id, i) => [id, i]));
}
export function flightPose(flight: Flight, data: SceneData, seconds: number, layout = buildLayout(data), holding = holdingOrder(data.flights)): Pose | null {
  const reported = flight as Flight & { position_x?: number; position_y?: number };
  if (Number.isFinite(reported.position_x) && Number.isFinite(reported.position_y)) {
    return { x: reported.position_x!, y: reported.position_y!, altitude: 0.2, heading: 0, phase: "Owner-reported position", detail: "", progress: null };
  }
  return aircraftPose(flight, layout, seconds, holding.get(flight.id) ?? 0);
}
export const poseToScene = (pose: { x: number; y: number }, altitude = 0): Point => gridPoint(pose.x, pose.y, altitude);

export function zonePoint(zone: string, index = 0): Point {
  const terminal = zone.match(/(?:induction|make-up)-([ABC])/)?.[1] ?? "B";
  const x = ({ A: -35, B: 0, C: 35 })[terminal] ?? 0;
  const n = Number(zone.match(/(\d+)$/)?.[1] ?? 1) - 1;
  if (zone.startsWith("induction")) return [x, 0, -30];
  if (zone.startsWith("screening")) return [-37.5 + n * 15, 0, -10];
  if (zone === "sorting-matrix") return [0, 0, 12];
  if (zone.startsWith("make-up")) return [x + (n - 2) * 5, 0, 40 + n % 2 * 7];
  if (zone.startsWith("arrival")) return [-45 + n * 18, 0, 70];
  return [-45 + index % 6 * 18, 0, 92 + Math.floor(index / 6) * 15];
}
export function zoneInTerminal(id: string, terminal: Terminal): boolean {
  const scoped = id.match(/(?:induction|make-up)-([ABC])/)?.[1];
  if (scoped) return scoped === terminal;
  const numbered = id.match(/^(?:screening-unit|arrival-belt)-(\d+)$/);
  if (numbered) return "ABC"[Math.floor((Number(numbered[1]) - 1) / 2)] === terminal;
  return true;
}

export function passengerZones(data: SceneData, terminal: Terminal): ZoneDensity[] {
  return (data.passengerZones ?? []).filter(z => {
    const assigned = normalizeTerminal(z.terminal || z.zone_id.match(/-([ABC])/)?.[1] || "");
    if (assigned) return assigned === terminal;
    const carousel = z.zone_id.match(/^carousel-(\d+)$/);
    // The domain's documented arrival allocation is A=1/2, B=3/4, C=5/6.
    return carousel ? "ABC"[Math.floor((Number(carousel[1]) - 1) / 2)] === terminal : true;
  });
}
export function passengerZonePoint(zone: ZoneDensity): Point {
  if (/check.?in/i.test(zone.zone_id)) return [-22, 0, 66];
  if (/airside/i.test(zone.zone_id)) return [0, 0, -47];
  if (/security/i.test(zone.zone_id)) return [0, 0, 0];
  if (/gate/i.test(zone.zone_id)) {
    const number = Number(zone.zone_id.match(/\d+/)?.[0] ?? 7);
    return [(number - 7) * 10, 0, -77];
  }
  return [72, 0, 15 + Number(zone.zone_id.match(/\d+/)?.[0] ?? 1) % 2 * 30];
}

export function entities(data: SceneData, options: SceneOptions, seconds: number): Entity[] {
  if (options.view === "passengers") {
    const s = checkpoint(data, options.terminal);
    const queue: Entity[] = s ? [{ id: `security-${options.terminal}`, kind: "checkpoint", label: `Terminal ${options.terminal} security`,
      status: s.frozen ? "frozen" : `${s.lanes_open} lanes open`, position: [0, 0, 0],
      facts: [["Queue", `${s.queue_length} passengers`], ["Wait", `${s.wait_minutes.toFixed(1)} min`], ["Open lanes", String(s.lanes_open)], ["Representation", "Aggregate figures; no tracked passenger positions"]], href: "/passengers" }] : [];
    return [...queue, ...passengerZones(data, options.terminal).filter(z => !/security/i.test(z.zone_id)).map(z => ({
      id: z.zone_id, kind: "passenger_zone" as const, label: z.zone_id, status: `${z.load_pct.toFixed(1)}% occupied`, position: passengerZonePoint(z),
      facts: [["Passengers", String(z.density)], ["Capacity", String(z.capacity)], ["Load", `${z.load_pct.toFixed(1)}%`], ["Position", "Schematic zone; individual coordinates unavailable"]] as Array<[string, string]>, href: "/passengers",
    }))];
  }
  const scopedZones = data.zones.filter(z => zoneInTerminal(z.zone_id, options.terminal));
  if (options.view === "baggage") return scopedZones.map((z, i) => ({
    id: z.zone_id, kind: "zone", label: z.zone_id, status: z.status, position: zonePoint(z.zone_id, i),
    facts: [["Items", String(z.items)], ["Utilisation", `${z.utilisation_pct}%`], ["Throughput", `${z.throughput_per_hour}/hour`], ["3D representation", `${representativeCount(z.items, Math.max(1, Math.floor(QUALITY[options.quality].bags / Math.max(1, scopedZones.length))))} figures represent ${z.items} items`], ["Placement", "Illustrative conveyor layout"]], href: "/baggage",
  }));
  const airfield: Entity[] = [
    ...data.gates.map(g => ({ id: g.gate_id, kind: "gate" as const, label: `Gate ${g.gate_id}`, status: g.status, position: gatePoint(g),
      facts: [["Terminal", g.terminal], ["Assigned flight", g.flight_number || "None observed"]] as Array<[string, string]>, href: "/ground-ops" })),
    ...data.runways.map((r, i) => ({ id: r.runway_id, kind: "runway" as const, label: `Runway ${r.runway_id}`, status: r.status, position: runwayPoint(r, i),
      facts: [["Arrivals queued", String(r.arrivals_queued)], ["Departures queued", String(r.departures_queued)], ["Capacity", `${r.capacity_per_hour}/hour`]] as Array<[string, string]>, href: "/ground-ops" })),
    ...(() => {
      const layout = buildLayout(data); const holding = holdingOrder(data.flights);
      return data.flights.map(f => {
        const pose = flightPose(f, data, seconds, layout, holding);
        const where = pose ? `${pose.phase}${pose.detail ? ` — ${pose.detail}` : ""}`
          : ["scheduled", "airborne"].includes(f.status) && f.direction === "arrival" ? "En route — enters the scene when the owner starts its approach (ETA−20 min)"
            : ["arrived", "cancelled", "diverted"].includes(f.status) ? "Not on the airfield" : "Unavailable — owner has not assigned the runway/gate or time this phase needs";
        return { id: f.id, kind: "flight" as const, label: f.flight_number, status: f.status, position: pose ? poseToScene(pose, pose.altitude) : [0, 0, 0] as Point, positionAvailable: pose !== null,
          facts: [["Aircraft", f.aircraft_type || "Unavailable"], ["Registration", f.registration || "Unavailable"], ["Gate", f.gate_id || "Unassigned"], ["Runway", f.runway_id || "Unassigned"], ["Delay", `${f.delay_minutes} min`], ["Phase", where], ["Timing", "Owner state-machine windows in simulation time; paths schematic"]] as Array<[string, string]>, href: "/flights" };
      });
    })(),
    ...data.vehicles.filter(v => Number.isFinite(v.position_x) && Number.isFinite(v.position_y)).map(v => {
      const p = vehiclePose(v, seconds);
      return { id: v.id, kind: "vehicle" as const, label: `${v.type.replace(/_/g, " ")} · ${v.id}`, status: v.status, position: gridPoint(p.x, p.y, 0.6),
        facts: [["Gate", v.current_gate || (v.status === "returning" ? "Returning to depot" : "Depot")], ["Task", v.task_name || "None"], ["Trip", p.progress === null ? "Stationary" : `${Math.round(p.progress * 100)}% of owner transit`], ["Coordinates", `${p.x.toFixed(1)}, ${p.y.toFixed(1)}`]] as Array<[string, string]>, href: "/ground-ops" };
    }),
  ];
  if (options.view !== "atc") return airfield;
  // ATC lists runways and aircraft in the air or on the movement area.
  const active = new Set(["approach", "delayed", "landed", "taxiing", "departed", "airborne"]);
  return airfield.filter(e => e.kind === "runway" || e.kind === "flight" && active.has(e.status) && e.positionAvailable !== false)
    .map(e => e.kind === "flight" ? { ...e, href: "/flights" } : e);
}
