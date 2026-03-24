const API_BASE = "/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
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
};

// ── Weather ──
export const weatherApi = {
  current: () => apiFetch<unknown>("/weather/current"),
  metar: () => fetch(`${API_BASE}/weather/metar`).then((r) => r.text()),
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
  alerts: (limit = 100) =>
    apiFetch<unknown>(`/incidents/alerts?limit=${limit}`),
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
  reset: () => apiFetch<unknown>("/sim/reset", { method: "POST" }),
};

// ── Airport aggregate ──
export const airportApi = {
  snapshot: () => apiFetch<unknown>("/airport"),
};
