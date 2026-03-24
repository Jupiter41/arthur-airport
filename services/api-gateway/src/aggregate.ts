import { Request, Response } from "express";
import { UPSTREAM } from "./proxy";

interface FetchResult {
  key: string;
  data: unknown | null;
}

const AGGREGATE_ENDPOINTS: Record<string, string> = {
  sim: "/api/v1/sim/status",
  weather: "/api/v1/weather/current",
  flights: "/api/v1/flights",
  passengers: "/api/v1/flow/summary",
  baggage: "/api/v1/flow/summary",
  incidents: "/api/v1/incidents?status=active",
};

async function fetchWithTimeout(
  url: string,
  timeoutMs: number,
): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { signal: controller.signal });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

export async function handleAggregate(
  _req: Request,
  res: Response,
): Promise<void> {
  const keys = Object.keys(AGGREGATE_ENDPOINTS);
  const promises = keys.map(async (key): Promise<FetchResult> => {
    const baseUrl = UPSTREAM[key];
    const path = AGGREGATE_ENDPOINTS[key];
    const timeout = key === "sim" ? 10_000 : key === "weather" ? 3_000 : 5_000;
    try {
      const data = await fetchWithTimeout(`${baseUrl}${path}`, timeout);
      return { key, data };
    } catch {
      return { key, data: null };
    }
  });

  const results = await Promise.allSettled(promises);

  const dataMap: Record<string, unknown | null> = {};
  const degradedServices: string[] = [];

  for (const result of results) {
    if (result.status === "fulfilled") {
      dataMap[result.value.key] = result.value.data;
      if (result.value.data === null) {
        degradedServices.push(result.value.key);
      }
    } else {
      // Should not happen since inner catch returns null
      degradedServices.push("unknown");
    }
  }

  const simData = dataMap.sim as Record<string, unknown> | null;

  res.json({
    sim_time: simData?.sim_time ?? null,
    airport: {
      iata: "ART",
      icao: "KART",
      name: "Arthur International Airport",
    },
    simulation: simData ?? null,
    weather: dataMap.weather ?? null,
    flights: dataMap.flights ?? null,
    passengers: dataMap.passengers ?? null,
    baggage: dataMap.baggage ?? null,
    incidents: dataMap.incidents ?? null,
    degraded_services:
      degradedServices.length > 0 ? degradedServices : undefined,
  });
}
