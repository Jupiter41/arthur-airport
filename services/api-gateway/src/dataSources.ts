import { Request, Response } from "express";
import { UPSTREAM } from "./proxy";

interface DataSourceStatus {
  id: string;
  name: string;
  service: string;
  type: "weather" | "flights" | "passengers" | "baggage" | "incidents" | "infrastructure";
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
      current_source: adsbEnabled ? "adsb.lol" : "disabled",
      available_sources: ["disabled", "adsb.lol"],
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
      available_sources: ["disabled", "adsb.lol"],
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
    const paxSourceUrl = `${UPSTREAM.passengers}/api/v1/passengers/source`;
    const paxSourceData = (await fetchWithTimeout(paxSourceUrl, 5000)) as Record<
      string,
      unknown
    >;
    const currentSource = String(paxSourceData?.source ?? "simulation");
    const availableSources = (paxSourceData?.available ?? ["simulation", "bts_historical"]) as string[];
    const details: Record<string, unknown> = {};

    // Also fetch flow summary for stats
    try {
      const paxFlowUrl = `${UPSTREAM.passengers}/api/v1/flow/summary`;
      const paxData = (await fetchWithTimeout(paxFlowUrl, 5000)) as Record<
        string,
        unknown
      >;
      details.total_passengers = paxData?.total_in_airport;
      details.zone_counts = paxData?.by_status;
      if (paxData?.bts_overlay) {
        details.bts_overlay = paxData.bts_overlay;
      }
    } catch { /* flow summary optional */ }

    if (paxSourceData?.bts_summary) {
      details.bts_summary = paxSourceData.bts_summary;
    }

    sources.push({
      id: "passengers",
      name: "Passenger Flow",
      service: "passenger-service",
      type: "passengers",
      current_source: currentSource,
      available_sources: availableSources,
      status: "active",
      last_updated: new Date().toISOString(),
      details,
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

  // 6. Infrastructure data — OurAirports (offline fixture, always active)
  sources.push({
    id: "infrastructure",
    name: "Airport Infrastructure",
    service: "config",
    type: "infrastructure",
    current_source: "ourairports",
    available_sources: ["ourairports"],
    status: "active",
    last_updated: null,
    details: {
      description:
        "Offline fixture data — runways, frequencies, navaids from OurAirports open dataset",
    },
  });

  // 7. Incident calibration source (sim-orchestrator)
  try {
    const incidentSourceUrl = `${UPSTREAM.sim}/api/v1/sim/incident-source`;
    const incidentData = (await fetchWithTimeout(
      incidentSourceUrl,
      5000,
    )) as Record<string, unknown>;
    const active = String(incidentData?.active ?? "simulated");
    const availableList = (incidentData?.available ?? []) as Array<{
      id: string;
    }>;
    sources.push({
      id: "incidents",
      name: "Incident Calibration",
      service: "sim-orchestrator",
      type: "incidents",
      current_source: active,
      available_sources:
        availableList.length > 0
          ? availableList.map((p) => p.id)
          : ["simulated", "asrs_historical"],
      status: "active",
      last_updated: new Date().toISOString(),
      details: incidentData,
    });
  } catch {
    sources.push({
      id: "incidents",
      name: "Incident Calibration",
      service: "sim-orchestrator",
      type: "incidents",
      current_source: "simulated",
      available_sources: ["simulated", "asrs_historical"],
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
