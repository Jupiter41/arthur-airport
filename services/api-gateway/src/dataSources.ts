import { Request, Response } from "express";
import { UPSTREAM } from "./proxy";
import { getCurrentSimTime } from "./websocket";

/**
 * RC10 — data-source status is derived from what each owner reports (its
 * `health` block, see `_common.data_sources.SourceHealth`), never asserted by
 * the gateway. api-gateway SPEC §5a.
 */

export type SourceState = "active" | "stale" | "disabled" | "error" | "unavailable";
export type Clock = "sim" | "wall" | null;

export interface SourceHealth {
  enabled?: boolean;
  items?: number | null;
  last_ingest_at?: string | null;
  last_observation_at?: string | null;
  last_error?: string | null;
  last_error_at?: string | null;
}

export interface FreshnessLimit {
  /** Max age of `last_observation_at` behind the gateway's sim clock. */
  simMinutes?: number;
  /** Max age of `last_ingest_at` behind the gateway's wall clock. */
  wallMinutes?: number;
}

interface DataSourceStatus {
  id: string;
  name: string;
  service: string;
  type: "weather" | "flights" | "passengers" | "baggage" | "incidents" | "infrastructure";
  current_source: string;
  available_sources: string[];
  status: SourceState;
  status_reason: string;
  last_updated: string | null;
  last_updated_clock: Clock;
  health: SourceHealth | null;
  details: Record<string, unknown>;
}

/** Parse an ISO time; naive (offset-less) strings are UTC, like the simulator's. */
export function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = Date.parse(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isFinite(time) ? time : null;
}

/** First-match status rules from api-gateway SPEC §5a. */
export function deriveStatus(
  health: SourceHealth | null,
  limit: FreshnessLimit,
  simNow: string | null,
  wallNow: number = Date.now(),
): { status: SourceState; reason: string; last_updated: string | null; clock: Clock } {
  if (!health) return { status: "unavailable", reason: "owner did not answer", last_updated: null, clock: null };
  const ingest = parseTime(health.last_ingest_at);
  const observation = parseTime(health.last_observation_at);
  const error = parseTime(health.last_error_at);
  const last_updated = health.last_observation_at ?? health.last_ingest_at ?? null;
  const clock: Clock = health.last_observation_at ? "sim" : health.last_ingest_at ? "wall" : null;
  const result = (status: SourceState, reason: string) => ({ status, reason, last_updated, clock });

  if (health.enabled === false) return result("disabled", "disabled by configuration");
  if (error !== null && (ingest === null || error > ingest)) {
    return result("error", health.last_error ?? "last attempt failed");
  }
  if (ingest === null && observation === null) return result("stale", "no data received yet");
  if (limit.simMinutes !== undefined && observation !== null) {
    const sim = parseTime(simNow);
    if (sim !== null && sim - observation > limit.simMinutes * 60_000) {
      return result("stale", `observation ${Math.round((sim - observation) / 60_000)} sim-min behind the clock`);
    }
  }
  if (limit.wallMinutes !== undefined && ingest !== null && wallNow - ingest > limit.wallMinutes * 60_000) {
    return result("stale", `last ingest ${Math.round((wallNow - ingest) / 60_000)} min ago`);
  }
  return result("active", "fresh");
}

async function fetchJson(url: string, timeoutMs = 5000): Promise<Record<string, unknown> | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { signal: controller.signal });
    if (!resp.ok) return null;
    return (await resp.json()) as Record<string, unknown>;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function source(
  base: Omit<DataSourceStatus, "status" | "status_reason" | "last_updated" | "last_updated_clock" | "health">,
  health: SourceHealth | null,
  limit: FreshnessLimit,
  simNow: string | null,
): DataSourceStatus {
  const derived = deriveStatus(health, limit, simNow);
  return {
    ...base, health, status: derived.status, status_reason: derived.reason,
    last_updated: derived.last_updated, last_updated_clock: derived.clock,
  };
}

const staticSource = (base: Omit<DataSourceStatus, "status" | "status_reason" | "last_updated" | "last_updated_clock" | "health">): DataSourceStatus => ({
  ...base, status: "active", status_reason: "static reference data", last_updated: null, last_updated_clock: null, health: null,
});

export async function handleDataSources(_req: Request, res: Response): Promise<void> {
  const simNow = getCurrentSimTime();
  const [weather, adsb, sim, paxSource, paxFlow, bagFlow, incidents] = await Promise.all([
    fetchJson(`${UPSTREAM.weather}/api/v1/weather/source`),
    fetchJson(`${UPSTREAM.flights}/api/v1/flights/adsb/source`),
    fetchJson(`${UPSTREAM.sim}/api/v1/sim/status`),
    fetchJson(`${UPSTREAM.passengers}/api/v1/passengers/source`),
    fetchJson(`${UPSTREAM.passengers}/api/v1/flow/summary`),
    fetchJson(`${UPSTREAM.baggage}/api/v1/flow/summary`),
    fetchJson(`${UPSTREAM.sim}/api/v1/sim/incident-source`),
  ]);
  const clockSim = simNow ?? (sim?.sim_time as string | undefined) ?? null;
  const ownerClock = (at: unknown): SourceHealth | null =>
    typeof at === "string" ? { enabled: true, last_observation_at: at } : { enabled: true };

  const sources: DataSourceStatus[] = [
    source({
      id: "weather", name: "Weather Data", service: "weather-service", type: "weather",
      current_source: String(weather?.source ?? "unknown"),
      available_sources: ["simulated", "historical", "live"],
      details: weather ? { current_category: weather.current_category, ...(weather.file ? { file: weather.file } : {}), ...(weather.icao ? { icao: weather.icao } : {}) } : {},
    }, weather ? (weather.health as SourceHealth) ?? null : null, { simMinutes: 90 }, clockSim),

    source({
      id: "flights-adsb", name: "ADS-B Live Flights", service: "flight-service", type: "flights",
      current_source: String(adsb?.source ?? "unknown"),
      available_sources: ["disabled", "adsb.lol", "opensky", "synthetic"],
      details: adsb ? { aircraft_count: adsb.aircraft_count } : {},
    }, adsb ? (adsb.health as SourceHealth) ?? null : null, { wallMinutes: 5 }, clockSim),

    source({
      id: "flights-sim", name: "Simulated Flights", service: "sim-orchestrator", type: "flights",
      current_source: "simulation", available_sources: ["simulation"],
      details: sim ? { speed_multiplier: sim.speed_multiplier, paused: sim.paused, day_number: sim.day_number, flights_today: sim.flights_today } : {},
    }, sim ? ownerClock(sim.sim_time) : null, {}, clockSim),

    source({
      id: "passengers", name: "Passenger Flow", service: "passenger-service", type: "passengers",
      current_source: String(paxSource?.source ?? "unknown"),
      available_sources: (paxSource?.available as string[] | undefined) ?? ["simulation", "bts_historical"],
      details: {
        total_in_airport: paxFlow?.total_in_airport ?? null,
        status_counts: paxFlow?.by_status ?? null,
        ...(paxFlow?.bts_overlay ? { bts_overlay: paxFlow.bts_overlay } : {}),
        ...(paxSource?.bts_summary ? { bts_summary: paxSource.bts_summary } : {}),
      },
    }, paxSource ? (paxSource.health as SourceHealth) ?? null : null, { simMinutes: 10 }, clockSim),

    source({
      id: "baggage", name: "Baggage Handling", service: "baggage-service", type: "baggage",
      current_source: "simulation", available_sources: ["simulation"],
      details: bagFlow ? { total_in_system: bagFlow.total_in_system, by_status: bagFlow.by_status, sim_time: bagFlow.sim_time } : {},
    }, bagFlow ? ownerClock(bagFlow.sim_time) : null, { simMinutes: 10 }, clockSim),

    staticSource({
      id: "infrastructure", name: "Airport Infrastructure", service: "config", type: "infrastructure",
      current_source: "ourairports", available_sources: ["ourairports"],
      details: { description: "Offline fixture data — runways, frequencies, navaids from OurAirports open dataset" },
    }),
  ];

  const incidentProfiles = (incidents?.available ?? []) as Array<{ id: string }>;
  sources.push(incidents
    ? staticSource({
      id: "incidents", name: "Incident Calibration", service: "sim-orchestrator", type: "incidents",
      current_source: String(incidents.active ?? "simulated"),
      available_sources: incidentProfiles.length ? incidentProfiles.map(p => p.id) : ["simulated", "asrs_historical"],
      details: incidents,
    })
    : source({
      id: "incidents", name: "Incident Calibration", service: "sim-orchestrator", type: "incidents",
      current_source: "unknown", available_sources: ["simulated", "asrs_historical"], details: {},
    }, null, {}, clockSim));

  res.json({ sources, timestamp: new Date().toISOString(), timestamp_clock: "wall", sim_time: clockSim });
}
