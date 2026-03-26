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
  runways: () => apiFetch<unknown[]>("/runways"),
  gates: () => apiFetch<unknown[]>("/gates"),
  turnarounds: () =>
    apiFetch<{ turnarounds: unknown[]; total: number }>("/turnarounds"),
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
};

// ── Airport aggregate ──
export const airportApi = {
  snapshot: () => apiFetch<unknown>("/airport"),
};
