import type { Flight, GroundVehicle } from "../../types";

/**
 * Simulation-time kinematics for the 3D twin.
 *
 * Every pose is a pure function of owner facts (status, ETA/ATA/ATD, assigned
 * runway and gate, owner-computed taxi durations, vehicle trip timestamps)
 * and the simulation clock. Timing windows mirror the flight-service state
 * machine (`services/flight-service/services/state_machine.py`):
 *
 *   approach  ETA-20 min → ETA            (touchdown at ETA)
 *   landed    ATA → ATA + taxi_initial    (rollout)
 *   taxiing   ATA + taxi_initial → ATA + taxi_total
 *   departed  ATD → ATD + 5 min           (then airborne)
 *
 * Paths (approach geometry, taxi routes, take-off roll) are schematic: the
 * owner models durations and endpoints, not trajectories. Coordinates use the
 * owner's 0–1000 grid (1 unit ≈ 1 m, x east, y south).
 */

export interface GridXY { x: number; y: number }
export interface RunwayGeometry { id: string; threshold: GridXY; end: GridXY }
export interface Layout {
  gates: Map<string, GridXY>;
  runways: Map<string, RunwayGeometry>;
  terminalY: (terminal: string) => number;
}
export interface Pose {
  x: number; y: number;
  /** Height in scene units (already exaggerated for legibility where airborne). */
  altitude: number;
  /** Rotation about the vertical axis for models whose nose points to -z. */
  heading: number;
  phase: string;
  detail: string;
  progress: number | null;
}

export const APPROACH_WINDOW_S = 20 * 60;
export const DEPARTED_WINDOW_S = 5 * 60;
/** Departures stay visible while climbing out for this long after becoming airborne. */
export const CLIMB_VISIBLE_S = 7 * 60;
export const HOLD_PERIOD_S = 4 * 60;
/** Approach distance is compressed so the full 20-minute window fits the scene. */
export const APPROACH_DISTANCE = 1500;
const GLIDE = Math.tan(3 * Math.PI / 180) * 2; // vertical ×2 for legibility
const EXIT_FRACTION = 0.55;
const STAND_OFFSET = 45;
const WEST_TAXIWAY_X = -25;
const APRON_LINE_OFFSET = 125;
const DEPOT = { x: 500, y: 300 };

/** Layout fallback mirrors `services/sim-orchestrator/fixtures/layout.json`. */
const FALLBACK_RUNWAYS: Record<string, [number, number, number, number]> = {
  "09L": [100, 800, 900, 800], "27R": [900, 800, 100, 800],
  "09R": [100, 900, 900, 900], "27L": [900, 900, 100, 900],
};

export function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isFinite(ms) ? ms / 1000 : null;
}
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
/** Heading for a model whose nose points to -z, travelling along grid (dx, dy). */
export const headingOf = (dx: number, dy: number) => Math.atan2(-dx, -dy);

export function runwayGeometry(row: { runway_id?: string; id?: string; threshold_x?: number; threshold_y?: number; end_x?: number; end_y?: number }): RunwayGeometry | null {
  const id = row.runway_id || row.id || "";
  const reported = [row.threshold_x, row.threshold_y, row.end_x, row.end_y];
  const values = reported.every(v => Number.isFinite(v)) ? reported as number[] : FALLBACK_RUNWAYS[id];
  if (!values) return null;
  return { id, threshold: { x: values[0], y: values[1] }, end: { x: values[2], y: values[3] } };
}

export function runwayFor(layout: Layout, id: string | null | undefined): RunwayGeometry | null {
  if (!id) return null;
  return layout.runways.get(id) ?? runwayGeometry({ runway_id: id });
}

export function along(runway: RunwayGeometry, distance: number): GridXY {
  const dx = runway.end.x - runway.threshold.x, dy = runway.end.y - runway.threshold.y;
  const length = Math.hypot(dx, dy) || 1;
  return { x: runway.threshold.x + dx / length * distance, y: runway.threshold.y + dy / length * distance };
}
const runwayLength = (r: RunwayGeometry) => Math.hypot(r.end.x - r.threshold.x, r.end.y - r.threshold.y);
const runwayHeading = (r: RunwayGeometry) => headingOf(r.end.x - r.threshold.x, r.end.y - r.threshold.y);

/** Grid point and scene height on the compressed final approach, `minutes` before touchdown. */
export function approachPoint(runway: RunwayGeometry, minutes: number): { point: GridXY; altitude: number } {
  const p = clamp01(1 - minutes * 60 / APPROACH_WINDOW_S);
  const distance = APPROACH_DISTANCE * (1 - p) ** 1.5;
  return { point: along(runway, -distance), altitude: distance / 5 * GLIDE + 0.6 };
}
/** Centre of the schematic holding pattern used for delayed arrivals. */
export function holdingFix(runway: RunwayGeometry): GridXY { return along(runway, -APPROACH_DISTANCE); }
export const HOLD_RADII = { x: 160, y: 70 };

export function standPoint(gate: GridXY): GridXY { return { x: gate.x, y: gate.y + STAND_OFFSET }; }

/**
 * Schematic taxi route between a runway point and a gate stand, following the
 * drawn apron lines and the western taxiway. Returned from runway to stand.
 */
export function taxiRoute(from: GridXY, gate: GridXY, terminalY: number, runwayY: number): GridXY[] {
  const southApron = Math.min(runwayY - 25, 775);
  const apron = terminalY + APRON_LINE_OFFSET;
  const stand = standPoint(gate);
  const route: GridXY[] = [from, { x: from.x, y: southApron }];
  if (Math.abs(apron - southApron) < 1) route.push({ x: gate.x, y: southApron });
  else route.push({ x: WEST_TAXIWAY_X, y: southApron }, { x: WEST_TAXIWAY_X, y: apron }, { x: gate.x, y: apron });
  route.push(stand);
  return route;
}

export function pointOnRoute(route: GridXY[], fraction: number): { point: GridXY; heading: number } {
  const lengths = route.slice(1).map((p, i) => Math.hypot(p.x - route[i].x, p.y - route[i].y));
  const total = lengths.reduce((a, b) => a + b, 0);
  let remaining = clamp01(fraction) * total;
  for (let i = 0; i < lengths.length; i++) {
    const a = route[i], b = route[i + 1];
    if (remaining <= lengths[i] || i === lengths.length - 1) {
      const t = lengths[i] ? Math.min(1, remaining / lengths[i]) : 1;
      return { point: { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }, heading: headingOf(b.x - a.x, b.y - a.y) };
    }
    remaining -= lengths[i];
  }
  const last = route[route.length - 1];
  return { point: last, heading: 0 };
}

type FlightFacts = Flight & { taxi_initial_minutes?: number; taxi_total_minutes?: number };
const pose = (point: GridXY, altitude: number, heading: number, phase: string, detail: string, progress: number | null): Pose =>
  ({ x: point.x, y: point.y, altitude, heading, phase, detail, progress });

function gateFor(flight: Flight, layout: Layout) {
  return flight.gate_id ? layout.gates.get(flight.gate_id) ?? null : null;
}
function terminalOf(flight: Flight) {
  return (flight.gate_id || flight.terminal || "B").replace(/^T-/, "")[0];
}

/**
 * Pose of an aircraft at simulation time `t` (epoch seconds), or null when
 * the owner state places it outside the scene (en route, not yet active,
 * cancelled) or when an essential owner fact (runway/gate/time) is missing.
 */
export function aircraftPose(raw: Flight, layout: Layout, t: number, holdingIndex = 0): Pose | null {
  const flight = raw as FlightFacts;
  const eta = parseTime(flight.estimated_time ?? flight.scheduled_time);
  const actual = parseTime(flight.actual_time);
  const runway = runwayFor(layout, flight.runway_id);
  const gate = gateFor(flight, layout);
  const arrival = flight.direction === "arrival";
  const terminalY = layout.terminalY(terminalOf(flight));

  switch (flight.status) {
    case "approach": {
      if (!runway || eta === null) return null;
      const p = clamp01((t - (eta - APPROACH_WINDOW_S)) / APPROACH_WINDOW_S);
      const minutes = Math.max(0, (eta - t) / 60);
      const { point, altitude } = approachPoint(runway, (1 - p) * APPROACH_WINDOW_S / 60);
      return pose(point, altitude, runwayHeading(runway), "Final approach",
        `Runway ${runway.id} · touchdown at owner ETA in ${minutes.toFixed(1)} min · distance compressed`, p);
    }
    case "delayed": {
      if (!arrival) return gate ? pose(standPoint(gate), 0.2, 0, "At gate · delayed", "Departure held at gate", null) : null;
      const reference = runway ?? [...layout.runways.values()][0];
      if (!reference) return null;
      const fix = holdingFix(reference);
      const angle = 2 * Math.PI * (((t % HOLD_PERIOD_S) + HOLD_PERIOD_S) % HOLD_PERIOD_S) / HOLD_PERIOD_S + holdingIndex * 0.9;
      const point = { x: fix.x + Math.cos(angle) * HOLD_RADII.x, y: fix.y + Math.sin(angle) * HOLD_RADII.y };
      return pose(point, 32 + holdingIndex * 4, headingOf(-Math.sin(angle) * HOLD_RADII.x, Math.cos(angle) * HOLD_RADII.y), "Holding",
        `Stack position ${holdingIndex + 1} · schematic holding fix · ${flight.delay_minutes} min delay`, null);
    }
    case "landed": {
      if (!runway || actual === null) return null;
      const duration = (flight.taxi_initial_minutes ?? 2) * 60;
      const p = clamp01((t - actual) / duration);
      const s = runwayLength(runway) * EXIT_FRACTION * (1 - (1 - p) ** 2);
      return pose(along(runway, s), 0.2, runwayHeading(runway), "Landing rollout",
        `Runway ${runway.id} · vacating ${Math.max(0, (actual + duration - t) / 60).toFixed(1)} min after touchdown`, p);
    }
    case "taxiing": {
      if (!runway || actual === null) return null;
      const exit = along(runway, runwayLength(runway) * EXIT_FRACTION);
      if (!gate) return pose(exit, 0.2, runwayHeading(runway), "Taxiing · awaiting gate", "Owner has not assigned a gate", null);
      const start = actual + (flight.taxi_initial_minutes ?? 2) * 60;
      const end = actual + (flight.taxi_total_minutes ?? 8) * 60;
      const route = taxiRoute(exit, gate, terminalY, runway.threshold.y);
      if (t > end + 120) {
        const holdShort = route[route.length - 2];
        return pose(holdShort, 0.2, 0, "Holding short of gate", `Taxi time elapsed; owner has not confirmed gate ${flight.gate_id} available`, 1);
      }
      const p = clamp01((t - start) / Math.max(1, end - start));
      const { point, heading } = pointOnRoute(route, p);
      return pose(point, 0.2, heading, "Taxiing to gate", `To ${flight.gate_id} · arrival on stand in ${Math.max(0, (end - t) / 60).toFixed(1)} min · schematic route`, p);
    }
    case "at_gate":
    case "boarding": {
      if (!gate) return null;
      const detail = flight.status === "boarding"
        ? `Boarding ${flight.pax_boarded ?? 0}/${flight.pax_count ?? 0} · off-block at ${flight.estimated_time?.slice(11, 16) ?? "—"}`
        : "Deplaning / turnaround";
      return pose(standPoint(gate), 0.2, 0, flight.status === "boarding" ? "At gate · boarding" : "At gate", detail, null);
    }
    case "departed":
    case "airborne": {
      if (arrival || !runway || actual === null) return null;
      const elapsed = t - actual;
      if (elapsed > DEPARTED_WINDOW_S + CLIMB_VISIBLE_S || elapsed < 0) return null;
      const length = runwayLength(runway);
      if (elapsed > DEPARTED_WINDOW_S || flight.status === "airborne") {
        const q = clamp01((elapsed - DEPARTED_WINDOW_S) / CLIMB_VISIBLE_S);
        const distance = length * 0.75 + q * 1800;
        return pose(along(runway, distance), 4 + q * 60, runwayHeading(runway), "Climb-out", `Runway ${runway.id} departure · leaving the terminal area`, q);
      }
      const p = elapsed / DEPARTED_WINDOW_S;
      const stand = gate ? standPoint(gate) : null;
      if (stand && p < 0.12) {
        const q = p / 0.12;
        return pose({ x: stand.x, y: stand.y + q * 30 }, 0.2, 0, "Pushback", `From ${flight.gate_id} · owner models off-block → airborne as 5 min (compressed)`, p);
      }
      if (stand && p < 0.62) {
        const route = taxiRoute(runway.threshold, gate!, terminalY, runway.threshold.y).reverse();
        route[0] = { x: stand.x, y: stand.y + 30 };
        const { point, heading } = pointOnRoute(route, (p - 0.12) / 0.5);
        return pose(point, 0.2, heading, "Taxi-out", `To runway ${runway.id} · compressed into the owner's 5-min departure window`, p);
      }
      const q = clamp01((p - 0.62) / 0.38);
      if (q < 0.6) {
        const s = length * 0.6 * (q / 0.6) ** 2;
        return pose(along(runway, s), 0.2, runwayHeading(runway), "Take-off roll", `Runway ${runway.id}`, p);
      }
      const c = (q - 0.6) / 0.4;
      return pose(along(runway, length * (0.6 + 0.15 * c)), 0.2 + c * 3.8, runwayHeading(runway), "Rotation / initial climb", `Runway ${runway.id}`, p);
    }
    default:
      return null;
  }
}

export interface VehiclePose { x: number; y: number; heading: number; moving: boolean; progress: number | null }
type VehicleFacts = GroundVehicle & { origin_x?: number | null; origin_y?: number | null; target_x?: number | null; target_y?: number | null; dispatched_at?: string | null; arrives_at?: string | null };

/** Vehicles travel the owner's straight apron segment between its trip timestamps. */
export function vehiclePose(raw: GroundVehicle, t: number): VehiclePose {
  const v = raw as VehicleFacts;
  const from = Number.isFinite(v.origin_x) && Number.isFinite(v.origin_y) ? { x: v.origin_x!, y: v.origin_y! } : null;
  const to = Number.isFinite(v.target_x) && Number.isFinite(v.target_y) ? { x: v.target_x!, y: v.target_y! }
    : v.status === "returning" ? DEPOT : { x: v.position_x, y: v.position_y };
  const start = parseTime(v.dispatched_at), end = parseTime(v.arrives_at);
  if ((v.status === "dispatched" || v.status === "returning") && from && start !== null && end !== null && end > start) {
    const p = clamp01((t - start) / (end - start));
    return { x: from.x + (to.x - from.x) * p, y: from.y + (to.y - from.y) * p, heading: headingOf(to.x - from.x, to.y - from.y), moving: p < 1, progress: p };
  }
  return { x: v.position_x, y: v.position_y, heading: 0, moving: false, progress: null };
}

export function isAtDepot(x: number, y: number) { return Math.abs(x - DEPOT.x) < 1 && Math.abs(y - DEPOT.y) < 1; }
