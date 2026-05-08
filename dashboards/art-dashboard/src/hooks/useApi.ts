import { getAuthToken } from "./auth";
import { useConnectionStore } from "../stores/connectionStore";
import type { WeatherState } from "../types";

const RAW_API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL as string | undefined
)
  ?.trim()
  .replace(/\/+$/, "");

const API_BASE = RAW_API_BASE_URL ? `${RAW_API_BASE_URL}/api/v1` : "/api/v1";

function normalizeWeatherResponse(data: unknown): WeatherState {
  const raw = (data ?? {}) as Record<string, unknown>;
  const impact = (raw.runway_impact ?? {}) as Record<string, unknown>;

  const windDirection =
    (raw.wind_direction_deg as number | undefined) ??
    (raw.wind_direction as number | undefined) ??
    0;
  const windSpeed = (raw.wind_speed_kt as number | undefined) ?? 0;
  const windGust = (raw.wind_gust_kt as number | null | undefined) ?? null;
  const temperature = (raw.temperature_c as number | undefined) ?? 0;
  const dewpoint =
    (raw.dewpoint_c as number | undefined) ??
    (raw.dew_point_c as number | undefined) ??
    0;
  const pressure =
    (raw.pressure_hpa as number | undefined) ??
    (raw.qnh_hpa as number | undefined) ??
    1013;
  const visibility = (raw.visibility_m as number | undefined) ?? 9999;
  const arrivalRate =
    (raw.arrival_rate as number | undefined) ??
    (impact.arrival_rate as number | undefined) ??
    0;
  const departureRate =
    (raw.departure_rate as number | undefined) ??
    (impact.departure_rate as number | undefined) ??
    0;

  return {
    ...raw,
    visibility_m: visibility,
    wind_speed_kt: windSpeed,
    wind_gust_kt: windGust,
    temperature_c: temperature,
    wind_direction_deg: windDirection,
    dewpoint_c: dewpoint,
    pressure_hpa: pressure,
    cloud_layers: (raw.cloud_layers ?? []) as string[],
    runway_impact:
      typeof impact.category === "string"
        ? impact.category
        : (raw.runway_impact as string | undefined),
    arrival_rate: arrivalRate,
    departure_rate: departureRate,
  } as WeatherState;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const token = await getAuthToken();

    const request = async (bearer: string) =>
      fetch(`${API_BASE}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${bearer}`,
          ...init?.headers,
        },
      });

    let res = await request(token);

    if (res.status === 401) {
      const refreshed = await getAuthToken(true);
      res = await request(refreshed);
    }

    if (!res.ok) {
      const msg = `API ${res.status}: ${res.statusText}`;
      useConnectionStore.getState().setApiConnected(false, msg);
      throw new Error(msg);
    }

    useConnectionStore.getState().setApiConnected(true, null);
    return res.json() as Promise<T>;
  } catch (err) {
    const message = err instanceof Error ? err.message : "API request failed";
    useConnectionStore.getState().setApiConnected(false, message);
    throw err;
  }
}

// ── Flights ──
export const flightsApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return apiFetch<{ flights: unknown[]; total: number }>(`/flights${qs}`);
  },
  get: (id: string) => apiFetch<unknown>(`/flights/${encodeURIComponent(id)}`),
  cascade: (id: string) =>
    apiFetch<unknown>(`/flights/${encodeURIComponent(id)}/cascade`),
  hold: (id: string, reason: string, duration: number) =>
    apiFetch<unknown>(`/flights/${encodeURIComponent(id)}/hold`, {
      method: "POST",
      body: JSON.stringify({ reason, expected_duration_minutes: duration }),
    }),
  release: (id: string) =>
    apiFetch<unknown>(`/flights/${encodeURIComponent(id)}/release`, {
      method: "POST",
    }),
  runways: () => apiFetch<{ runways: unknown[] }>("/runways"),
  gates: () => apiFetch<{ gates: unknown[] }>("/gates"),
  turnarounds: () =>
    apiFetch<{ turnarounds: unknown[]; total: number }>("/turnarounds"),
  adsbStates: () => apiFetch<unknown>("/flights/adsb-states"),
  groundVehicles: () => apiFetch<unknown>("/ground-vehicles"),
};

// ── Weather ──
export const weatherApi = {
  current: async () =>
    normalizeWeatherResponse(await apiFetch<unknown>("/weather/current")),
  metar: async () => {
    try {
      const token = await getAuthToken();
      const res = await fetch(`${API_BASE}/weather/metar`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const msg = `API ${res.status}: ${res.statusText}`;
        useConnectionStore.getState().setApiConnected(false, msg);
        throw new Error(msg);
      }
      useConnectionStore.getState().setApiConnected(true, null);
      return res.text();
    } catch (err) {
      const message = err instanceof Error ? err.message : "API request failed";
      useConnectionStore.getState().setApiConnected(false, message);
      throw err;
    }
  },
  impact: () => apiFetch<unknown>("/weather/impact"),
  history: (hours = 12) => apiFetch<unknown>(`/weather/history?hours=${hours}`),
  compare: () => apiFetch<unknown>("/weather/compare"),
  source: () => apiFetch<unknown>("/weather/source"),
  switchSource: (source: string, csvPath?: string, liveIcao?: string) =>
    apiFetch<unknown>("/weather/source", {
      method: "POST",
      body: JSON.stringify({ source, csv_path: csvPath, live_icao: liveIcao }),
    }),
  getOverrides: () => apiFetch<unknown>("/weather/overrides"),
  setOverrides: (overrides: Record<string, number | null>) =>
    apiFetch<unknown>("/weather/overrides", {
      method: "POST",
      body: JSON.stringify(overrides),
    }),
};

// ── Passengers ──
export const passengersApi = {
  summary: () => apiFetch<unknown>("/passengers/flow/summary"),
  heatmap: () => apiFetch<unknown>("/passengers/flow/heatmap"),
  atRisk: () => apiFetch<unknown>("/passengers/connections/at-risk"),
  search: (q: string) =>
    apiFetch<unknown>(`/passengers/search?q=${encodeURIComponent(q)}`),
  get: (id: string) =>
    apiFetch<unknown>(`/passengers/${encodeURIComponent(id)}`),
};

// ── Baggage ──
export const baggageApi = {
  summary: () => apiFetch<unknown>("/baggage/flow/summary"),
  map: () => apiFetch<unknown>("/baggage/flow/map"),
  flagged: () => apiFetch<unknown>("/baggage/flagged"),
  search: (q: string) =>
    apiFetch<unknown>(`/baggage/search?q=${encodeURIComponent(q)}`),
  get: (id: string) => apiFetch<unknown>(`/baggage/${encodeURIComponent(id)}`),
};

// ── Incidents ──
export const incidentsApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return apiFetch<{ incidents: unknown[]; total: number }>(`/incidents${qs}`);
  },
  get: (id: string) =>
    apiFetch<unknown>(`/incidents/${encodeURIComponent(id)}`),
  inject: (body: {
    type: string;
    severity: string;
    location: string;
    description?: string;
  }) =>
    apiFetch<unknown>("/incidents/inject", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  contain: (id: string) =>
    apiFetch<unknown>(`/incidents/${encodeURIComponent(id)}/contain`, {
      method: "POST",
    }),
  resolve: (id: string) =>
    apiFetch<unknown>(`/incidents/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
    }),
  report: (id: string) =>
    apiFetch<unknown>(`/incidents/${encodeURIComponent(id)}/report`),
  alerts: async (limit = 100) => {
    const data = (await apiFetch<unknown>(
      `/incidents/alerts?limit=${limit}`,
    )) as {
      alerts?: Array<Record<string, unknown>>;
    };

    const alerts = (data.alerts ?? []).map((a, index) => ({
      id:
        (a.id as string | undefined) ??
        `${String(a.incident_id ?? "incident")}-${String(a.at ?? index)}`,
      sim_time: String(a.at ?? ""),
      severity: String(a.severity ?? "medium"),
      message: String(a.short_message ?? a.title ?? ""),
      incident_id: String(a.incident_id ?? ""),
    }));

    return { alerts };
  },
};

// ── Simulation ──
export const simApi = {
  status: () => apiFetch<unknown>("/sim/status"),
  pause: () => apiFetch<unknown>("/sim/pause", { method: "POST" }),
  resume: () => apiFetch<unknown>("/sim/resume", { method: "POST" }),
  speed: (multiplier: number) =>
    apiFetch<unknown>("/sim/speed", {
      method: "PATCH",
      body: JSON.stringify({ speed_multiplier: multiplier }),
    }),
  reset: () =>
    apiFetch<unknown>("/sim/reset", {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
  history: () => apiFetch<unknown>("/sim/history"),
  settings: () => apiFetch<unknown>("/sim/settings"),
  updateSettings: (body: Record<string, unknown>) =>
    apiFetch<unknown>("/sim/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};

// ── Airport aggregate ──
export const airportApi = {
  snapshot: () => apiFetch<unknown>("/airport"),
};

// ── Analysis ──
export const analysisApi = {
  bottlenecks: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return apiFetch<{ bottlenecks: unknown[]; count: number }>(
      `/analysis/bottlenecks${qs}`,
    );
  },
  recommendations: () =>
    apiFetch<{ recommendations: unknown[]; count: number }>(
      "/analysis/recommendations",
    ),
  whatIf: (body: {
    actions: Array<{
      action_type: string;
      description?: string;
      parameters?: Record<string, unknown>;
    }>;
    horizon_minutes?: number;
  }) =>
    apiFetch<unknown>("/analysis/what-if", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  whatIfLog: (limit = 50) =>
    apiFetch<{ entries: unknown[]; total: number }>(
      `/analysis/what-if/log?limit=${limit}`,
    ),
  autonomousSettings: () => apiFetch<unknown>("/analysis/autonomous"),
  updateAutonomous: (body: Record<string, unknown>) =>
    apiFetch<unknown>("/analysis/autonomous", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  autonomousLog: (limit = 50) =>
    apiFetch<{ actions: unknown[]; total: number }>(
      `/analysis/autonomous/log?limit=${limit}`,
    ),
  // Phase 5: Anomaly detection (P5-3-1)
  anomalies: () => apiFetch<unknown>("/analysis/anomalies"),
  // Phase 5: Natural language query (P5-2-1)
  query: (question: string) =>
    apiFetch<{ answer: string; source: string; context_summary?: string }>(
      "/analysis/query",
      { method: "POST", body: JSON.stringify({ question }) },
    ),
  // Phase 5: Natural language incident injection (P5-2-2)
  nlInject: (command: string) =>
    apiFetch<unknown>("/analysis/nl-inject", {
      method: "POST",
      body: JSON.stringify({ command }),
    }),
  // Phase 5: Narration (P5-2-3)
  narration: (limit = 20) =>
    apiFetch<{ settings: unknown; history: unknown[] }>(
      `/analysis/narration?limit=${limit}`,
    ),
  updateNarration: (body: Record<string, unknown>) =>
    apiFetch<unknown>("/analysis/narration", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  // Phase 5: After-action report (P5-2-4)
  generateReport: (scenarioName?: string) =>
    apiFetch<{ report: string; source: string }>("/analysis/report", {
      method: "POST",
      body: JSON.stringify(scenarioName ? { scenario_name: scenarioName } : {}),
    }),
  // Phase 5: LLM config
  llmConfig: () => apiFetch<unknown>("/analysis/llm-config"),
  // Training management
  trainingStatus: () => apiFetch<unknown>("/analysis/training/status"),
  trainingConfig: () => apiFetch<unknown>("/analysis/training/config"),
  trainingStart: (modelType = "rl", timesteps = 50000) =>
    apiFetch<unknown>(
      "/analysis/training/start" +
        `?model_type=${encodeURIComponent(modelType)}&timesteps=${timesteps}`,
      {
        method: "POST",
      },
    ),
  trainingStop: () =>
    apiFetch<unknown>("/analysis/training/stop", { method: "POST" }),
};

// ── Scenarios ──
export const scenariosApi = {
  list: () => apiFetch<{ scenarios: unknown[] }>("/scenarios"),
  get: (name: string) =>
    apiFetch<unknown>(`/scenarios/${encodeURIComponent(name)}`),
  create: (body: Record<string, unknown>) =>
    apiFetch<unknown>("/scenarios", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (name: string, body: Record<string, unknown>) =>
    apiFetch<unknown>(`/scenarios/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  delete: (name: string) =>
    apiFetch<unknown>(`/scenarios/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  fork: (name: string, newName: string) =>
    apiFetch<unknown>(`/scenarios/${encodeURIComponent(name)}/fork`, {
      method: "POST",
      body: JSON.stringify({ name: newName }),
    }),
  run: (name: string, speed?: number) =>
    apiFetch<unknown>(`/scenarios/${encodeURIComponent(name)}/run`, {
      method: "POST",
      body: JSON.stringify(speed ? { speed } : {}),
    }),
  active: () => apiFetch<unknown>("/scenarios/active"),
  stop: () => apiFetch<unknown>("/scenarios/active/stop", { method: "POST" }),
  results: () => apiFetch<{ results: unknown[] }>("/scenarios/results"),
  result: (runId: string) =>
    apiFetch<unknown>(`/scenarios/results/${encodeURIComponent(runId)}`),
};

// ── Debug ──
export const debugApi = {
  cypher: (query: string, params?: Record<string, unknown>) =>
    apiFetch<{
      columns: string[];
      rows: Record<string, unknown>[];
      row_count: number;
    }>("/debug/cypher", {
      method: "POST",
      body: JSON.stringify({ query, params: params ?? {} }),
    }),
  getEntity: (label: string, entityId: string) =>
    apiFetch<unknown>(
      `/debug/entity/${encodeURIComponent(label)}/${encodeURIComponent(entityId)}`,
    ),
  updateEntity: (
    label: string,
    entityId: string,
    properties: Record<string, unknown>,
  ) =>
    apiFetch<unknown>("/debug/entity", {
      method: "PATCH",
      body: JSON.stringify({ label, entity_id: entityId, properties }),
    }),
  injectPassengers: (flightId: string, count: number, status: string) =>
    apiFetch<unknown>("/debug/inject/passengers", {
      method: "POST",
      body: JSON.stringify({ flight_id: flightId, count, status }),
    }),
  injectFlight: (body: Record<string, unknown>) =>
    apiFetch<unknown>("/debug/inject/flight", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  injectBaggage: (flightId: string, count: number, zoneStatus: string) =>
    apiFetch<unknown>("/debug/inject/baggage", {
      method: "POST",
      body: JSON.stringify({
        flight_id: flightId,
        count,
        zone_status: zoneStatus,
      }),
    }),
  listSnapshots: () =>
    apiFetch<{ snapshots: unknown[]; count: number }>("/debug/snapshots"),
  createSnapshot: (name: string) =>
    apiFetch<unknown>("/debug/snapshot", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  restoreSnapshot: (filename: string) =>
    apiFetch<unknown>("/debug/snapshot/restore", {
      method: "POST",
      body: JSON.stringify({ filename }),
    }),
  deleteSnapshot: (filename: string) =>
    apiFetch<unknown>("/debug/snapshot", {
      method: "DELETE",
      body: JSON.stringify({ filename }),
    }),
};

// ── Network ──
export interface NetworkStatus {
  enabled: boolean;
  name: string;
  home: string;
  airports: NetworkAirportStatus[];
  active_gdps: NetworkGDP[];
  recent_propagations: NetworkPropagation[];
  arcs: NetworkArc[];
}

export interface NetworkAirportStatus {
  icao: string;
  iata: string;
  name: string;
  lat: number;
  lon: number;
  role: string;
  daily_movements: number;
  current_delay_minutes: number;
  disruption_level: string;
  gdp_active: boolean;
  gdp_departure_rate_pct: number;
  recovery_eta_minutes: number;
  active_incidents: number;
}

export interface NetworkGDP {
  airport_icao: string;
  start_time: string;
  reason: string;
  capacity_reduction_pct: number;
  affected_feeder_airports: string[];
  departure_rate_pct: number;
}

export interface NetworkPropagation {
  source_icao: string;
  target_icao: string;
  flight_number: string;
  original_delay_minutes: number;
  propagated_delay_minutes: number;
  sim_time: string;
  cascade_depth: number;
}

export interface NetworkArc {
  source: { icao: string; iata: string; lat: number; lon: number };
  target: { icao: string; iata: string; lat: number; lon: number };
  status: string;
  outbound_delay_minutes: number;
  inbound_delay_minutes: number;
  gdp_active: boolean;
}

export const networkApi = {
  status: () => apiFetch<NetworkStatus>("/network/status"),
  airports: () =>
    apiFetch<{ airports: NetworkAirportStatus[] }>("/network/airports"),
  arcs: () => apiFetch<{ arcs: NetworkArc[] }>("/network/arcs"),
  gdps: () => apiFetch<{ gdps: NetworkGDP[] }>("/network/gdps"),
  propagations: () =>
    apiFetch<{ propagations: NetworkPropagation[] }>("/network/propagations"),
};

// ── Data Sources ──
export interface DataSourceStatus {
  id: string;
  name: string;
  service: string;
  type: "weather" | "flights" | "passengers" | "baggage" | "incidents";
  current_source: string;
  available_sources: string[];
  status: "active" | "degraded" | "unavailable";
  last_updated: string | null;
  details: Record<string, unknown>;
}

export interface DataSourcesResponse {
  sources: DataSourceStatus[];
  timestamp: string;
}

export const dataSourcesApi = {
  list: () => apiFetch<DataSourcesResponse>("/data-sources"),
  switchWeatherSource: (source: string, csvPath?: string, liveIcao?: string) =>
    weatherApi.switchSource(source, csvPath, liveIcao),
  getWeatherCurrent: () => weatherApi.current(),
};
