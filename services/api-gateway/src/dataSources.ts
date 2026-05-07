import { Request, Response } from "express";
import { UPSTREAM } from "./proxy";

interface DataSourceStatus {
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

interface DataSourcesResponse {
  sources: DataSourceStatus[];
  timestamp: string;
}

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

export async function handleDataSources(
  _req: Request,
  res: Response,
): Promise<void> {
  const sources: DataSourceStatus[] = [];

  // 1. Weather source
  try {
    const weatherUrl = `${UPSTREAM.weather}/api/v1/weather/source`;
    const weatherData = (await fetchWithTimeout(weatherUrl, 5000)) as Record<
      string,
      unknown
    >;
    sources.push({
      id: "weather",
      name: "Weather Data",
      service: "weather-service",
      type: "weather",
      current_source: String(weatherData.source ?? "simulated"),
      available_sources: ["simulated", "historical", "live"],
      status: "active",
      last_updated: new Date().toISOString(),
      details: weatherData,
    });
  } catch {
    sources.push({
      id: "weather",
      name: "Weather Data",
      service: "weather-service",
      type: "weather",
      current_source: "unknown",
      available_sources: ["simulated", "historical", "live"],
      status: "unavailable",
      last_updated: null,
      details: {},
    });
  }

  // 2. Flight / ADS-B source
  try {
    const flightUrl = `${UPSTREAM.flights}/api/v1/flights/adsb-states`;
    const adsbData = (await fetchWithTimeout(flightUrl, 5000)) as Record<
      string,
      unknown
    >;
    const adsbEnabled =
      adsbData &&
      typeof adsbData === "object" &&
      "metadata" in adsbData;
    sources.push({
      id: "flights-adsb",
      name: "ADS-B Live Flights",
      service: "flight-service",
      type: "flights",
      current_source: adsbEnabled ? "opensky" : "disabled",
      available_sources: ["disabled", "opensky"],
      status: adsbEnabled ? "active" : "degraded",
      last_updated: new Date().toISOString(),
      details: adsbEnabled
        ? { aircraft_count: (adsbData as Record<string, unknown>).metadata }
        : { reason: "ADS-B polling not enabled or no data" },
    });
  } catch {
    sources.push({
      id: "flights-adsb",
      name: "ADS-B Live Flights",
      service: "flight-service",
      type: "flights",
      current_source: "disabled",
      available_sources: ["disabled", "opensky"],
      status: "unavailable",
      last_updated: null,
      details: {},
    });
  }

  // 3. Flight simulation source
  try {
    const simUrl = `${UPSTREAM.sim}/api/v1/sim/status`;
    const simData = (await fetchWithTimeout(simUrl, 5000)) as Record<
      string,
      unknown
    >;
    sources.push({
      id: "flights-sim",
      name: "Simulated Flights",
      service: "sim-orchestrator",
      type: "flights",
      current_source: "simulation",
      available_sources: ["simulation"],
      status: simData ? "active" : "degraded",
      last_updated: (simData?.sim_time as string) ?? null,
      details: {
        speed_multiplier: simData?.speed_multiplier,
        state: simData?.state,
        day_number: simData?.day_number,
      },
    });
  } catch {
    sources.push({
      id: "flights-sim",
      name: "Simulated Flights",
      service: "sim-orchestrator",
      type: "flights",
      current_source: "simulation",
      available_sources: ["simulation"],
      status: "unavailable",
      last_updated: null,
      details: {},
    });
  }

  // 4. Passenger simulation source
  try {
    const paxUrl = `${UPSTREAM.passengers}/api/v1/flow/summary`;
    const paxData = (await fetchWithTimeout(paxUrl, 5000)) as Record<
      string,
      unknown
    >;
    sources.push({
      id: "passengers",
      name: "Passenger Flow",
      service: "passenger-service",
      type: "passengers",
      current_source: "simulation",
      available_sources: ["simulation", "bts_historical"],
      status: paxData ? "active" : "degraded",
      last_updated: new Date().toISOString(),
      details: {
        total_passengers: paxData?.total_passengers,
        zone_counts: paxData?.zone_counts,
      },
    });
  } catch {
    sources.push({
      id: "passengers",
      name: "Passenger Flow",
      service: "passenger-service",
      type: "passengers",
      current_source: "simulation",
      available_sources: ["simulation", "bts_historical"],
      status: "unavailable",
      last_updated: null,
      details: {},
    });
  }

  // 5. Baggage simulation source
  try {
    const bagUrl = `${UPSTREAM.baggage}/api/v1/flow/summary`;
    const bagData = (await fetchWithTimeout(bagUrl, 5000)) as Record<
      string,
      unknown
    >;
    sources.push({
      id: "baggage",
      name: "Baggage Handling",
      service: "baggage-service",
      type: "baggage",
      current_source: "simulation",
      available_sources: ["simulation"],
      status: bagData ? "active" : "degraded",
      last_updated: new Date().toISOString(),
      details: {
        total_bags: bagData?.total_bags,
        zones: bagData?.zone_summary,
      },
    });
  } catch {
    sources.push({
      id: "baggage",
      name: "Baggage Handling",
      service: "baggage-service",
      type: "baggage",
      current_source: "simulation",
      available_sources: ["simulation"],
      status: "unavailable",
      last_updated: null,
      details: {},
    });
  }

  const response: DataSourcesResponse = {
    sources,
    timestamp: new Date().toISOString(),
  };

  res.json(response);
}
