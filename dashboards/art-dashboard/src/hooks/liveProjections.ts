import type { BaggageZone, GroundVehicle, GroundVehicleSummary, PassengerFlowSummary } from "../types";
import { queryClient } from "../queryClient";
import { useGroundVehicleStore } from "../stores/groundVehicleStore";

const observedAt = new Map<string, number>();
const pending = new Set<string>();
export function resetLiveProjectionGuards() { observedAt.clear(); pending.clear(); }
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const numeric = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
function fresh(key: string, at: unknown): boolean {
  if (typeof at !== "string") return false;
  const time = Date.parse(/Z$|[+-]\d\d:\d\d$/.test(at) ? at : `${at}Z`);
  if (!Number.isFinite(time) || time < (observedAt.get(key) ?? -Infinity)) return false;
  observedAt.set(key, time); return true;
}
// RC9: at most one invalidation per query key per window. A microtask only
// merged calls within one frame, so each FlightStatusChanged still refetched
// flights, gates and runways (~290 ms each) on every event.
export const RECONCILE_WINDOW_MS = 1000;
export function reconcileLiveQueries(...key: string[]) {
  const id = JSON.stringify(key); if (pending.has(id)) return;
  pending.add(id);
  setTimeout(() => { pending.delete(id); void queryClient.invalidateQueries({ queryKey: key }); }, RECONCILE_WINDOW_MS);
}
export function applySecurityObservation(payload: Record<string, unknown>, at: string) {
  const terminal = payload.terminal;
  if (typeof terminal !== "string" || !["A", "B", "C"].includes(terminal) ||
      !numeric(payload.queue_depth) || payload.queue_depth < 0 || !numeric(payload.wait_minutes) ||
      !numeric(payload.lanes_open) || payload.lanes_open < 0 || !Number.isInteger(payload.lanes_open) ||
      typeof payload.frozen !== "boolean" || !fresh(`security:${terminal}`, payload.at ?? at)) return;
  // A partial terminal event cannot initialize a whole-airport summary. Let the
  // initial REST load supply counts and the other terminals instead of zeros.
  queryClient.setQueryData<PassengerFlowSummary>(["passengers", "summary"], old => {
    if (!old) { reconcileLiveQueries("passengers", "summary"); return old; }
    const key = Object.keys(old.security).find(k => k.replace(/^T-|^Terminal |^terminal_/i, "").toUpperCase() === terminal) ?? terminal;
    return { ...old, security: { ...old.security, [key]: { queue_length: payload.queue_depth as number,
      wait_minutes: payload.wait_minutes as number, lanes_open: payload.lanes_open as number, frozen: payload.frozen as boolean, observed_at: String(payload.at ?? at) } } };
  });
}
export function applyBaggageObservation(payload: Record<string, unknown>, at: string) {
  if (!Array.isArray(payload.zones) || !payload.zones.every(z => record(z) && typeof z.zone_id === "string" &&
      typeof z.status === "string" && numeric(z.items) && z.items >= 0 && numeric(z.throughput_per_hour) && numeric(z.utilisation_pct)) || !fresh("baggage", payload.at ?? at)) return;
  queryClient.setQueryData<BaggageZone[]>(["baggage", "map"], (payload.zones as BaggageZone[]).map(zone => ({ ...zone, observed_at: String(payload.at ?? at) })));
  reconcileLiveQueries("baggage", "summary");
}
export function applyVehicleObservation(payload: Record<string, unknown>, at: string) {
  if (!Array.isArray(payload.vehicles) || !payload.vehicles.every(v => record(v) && typeof v.id === "string" &&
      typeof v.type === "string" && typeof v.status === "string" && numeric(v.position_x) && numeric(v.position_y)) || !fresh("vehicles", payload.at ?? at)) return;
  const vehicles = payload.vehicles as GroundVehicle[];
  useGroundVehicleStore.getState().setVehicles(vehicles);
  queryClient.setQueryData<GroundVehicleSummary>(["ground-vehicles"], old => old ? { ...old, vehicles, total: vehicles.length } : old);
}
