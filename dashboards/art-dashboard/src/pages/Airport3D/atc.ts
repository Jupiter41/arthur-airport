import type { Flight, Runway } from "../../types";
import { parseTime, runwayFor, type Layout, type Pose } from "./kinematics";

/**
 * Read-only air-traffic picture derived from owner facts at simulation time.
 *
 * Everything here is either an owner fact (status, ETA, runway, queue order,
 * wake separation, ROT block, capacity) or arithmetic on owner facts
 * (time-to-touchdown, spacing between consecutive ETAs, which aircraft is in
 * a runway phase of the flight state-machine timeline). The flight owner
 * models no clearances, so none are shown or offered.
 */

export interface RunwayQueueEntry {
  position: number; flight_id: string; aircraft_type: string; weight_category: string;
  estimated_time: string; emergency: boolean; wake_separation_seconds: number | null;
}
export interface RunwayQueueSnapshot {
  sim_time: string | null; weather_category: string; ils_required: boolean;
  arrival_rate: number; departure_rate: number; capacity_per_hour: number; current_rate: number;
  runway_free_at: string | null; runway_occupied: boolean;
  last_arrival_type: string | null; last_departure_type: string | null;
  arrivals: RunwayQueueEntry[]; departures: RunwayQueueEntry[];
}

export type PoseOf = (flight: Flight) => Pose | null;
export const RUNWAY_PHASES = new Set(["Landing rollout", "Take-off roll", "Rotation / initial climb"]);
const SHORT_FINAL_S = 2 * 60;
/** FSM departure threshold (`state_machine._eval_boarding`). */
export const BOARDED_READY = 0.95;

export interface Strip {
  key: string; ends: Runway[];
  occupant: { flight: Flight; phase: string } | null;
  shortFinal: { flight: Flight; seconds: number } | null;
}
export interface ArrivalRow { flight: Flight; runway: string; secondsToTouchdown: number; spacingSeconds: number | null }
export interface MovementRow { flight: Flight; phase: string; detail: string }
export interface BoardingRow { flight: Flight; boardedPct: number; ready: boolean; secondsToOffBlock: number | null }
export interface AtcPicture {
  strips: Strip[]; arrivals: ArrivalRow[]; holding: MovementRow[]; groundIn: MovementRow[];
  departing: MovementRow[]; boarding: BoardingRow[];
}

/** Reciprocal designators (09L/27R) share one physical strip. */
export function stripKey(layout: Layout, id: string): string {
  const g = runwayFor(layout, id);
  if (!g) return id;
  const ends = [`${g.threshold.x},${g.threshold.y}`, `${g.end.x},${g.end.y}`].sort();
  return ends.join("|");
}

export function atcPicture(flights: Flight[], runways: Runway[], layout: Layout, t: number, poseOf: PoseOf): AtcPicture {
  const poses = new Map(flights.map(f => [f.id, poseOf(f)] as const));
  const strips = new Map<string, Strip>();
  for (const r of runways) {
    const key = stripKey(layout, r.runway_id);
    const strip = strips.get(key) ?? { key, ends: [], occupant: null, shortFinal: null };
    strip.ends.push(r); strips.set(key, strip);
  }
  const arrivals: ArrivalRow[] = [], holding: MovementRow[] = [], groundIn: MovementRow[] = [], departing: MovementRow[] = [], boarding: BoardingRow[] = [];
  for (const flight of flights) {
    const pose = poses.get(flight.id) ?? null;
    if (pose && RUNWAY_PHASES.has(pose.phase) && flight.runway_id) {
      const strip = strips.get(stripKey(layout, flight.runway_id));
      if (strip && !strip.occupant) strip.occupant = { flight, phase: pose.phase };
    }
    const eta = parseTime(flight.estimated_time ?? flight.scheduled_time);
    if (flight.status === "approach" && flight.direction === "arrival" && eta !== null) {
      arrivals.push({ flight, runway: flight.runway_id || "—", secondsToTouchdown: Math.max(0, eta - t), spacingSeconds: null });
    } else if (flight.status === "delayed" && flight.direction === "arrival") {
      holding.push({ flight, phase: "Holding", detail: `${flight.delay_minutes} min delay` });
    } else if ((flight.status === "landed" || flight.status === "taxiing") && pose) {
      groundIn.push({ flight, phase: pose.phase, detail: pose.detail });
    } else if (flight.direction === "departure" && (flight.status === "departed" || flight.status === "airborne") && pose) {
      departing.push({ flight, phase: pose.phase, detail: pose.detail });
    } else if (flight.direction === "departure" && (flight.status === "boarding" || flight.status === "delayed")) {
      const pct = flight.pax_count > 0 ? (flight.pax_boarded ?? 0) / flight.pax_count : 0;
      boarding.push({ flight, boardedPct: pct, ready: pct >= BOARDED_READY, secondsToOffBlock: eta === null ? null : eta - t });
    }
  }
  arrivals.sort((a, b) => a.secondsToTouchdown - b.secondsToTouchdown);
  const lastOnRunway = new Map<string, number>();
  for (const row of arrivals) {
    const key = row.flight.runway_id ? stripKey(layout, row.flight.runway_id) : "—";
    const previous = lastOnRunway.get(key);
    row.spacingSeconds = previous === undefined ? null : row.secondsToTouchdown - previous;
    lastOnRunway.set(key, row.secondsToTouchdown);
    const strip = strips.get(key);
    if (strip && !strip.shortFinal && row.secondsToTouchdown <= SHORT_FINAL_S) strip.shortFinal = { flight: row.flight, seconds: row.secondsToTouchdown };
  }
  holding.sort((a, b) => a.flight.id.localeCompare(b.flight.id));
  boarding.sort((a, b) => (a.secondsToOffBlock ?? Infinity) - (b.secondsToOffBlock ?? Infinity));
  return { strips: [...strips.values()], arrivals, holding, groundIn, departing, boarding };
}

export function clockText(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const sign = seconds < 0 ? "−" : "";
  const s = Math.round(Math.abs(seconds));
  return `${sign}${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
