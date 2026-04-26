import { useQuery } from "@tanstack/react-query";
import {
  flightsApi,
  weatherApi,
  passengersApi,
  baggageApi,
  incidentsApi,
  analysisApi,
  networkApi,
} from "./useApi";
import type {
  Flight,
  Runway,
  Gate,
  WeatherState,
  ZoneDensity,
  PassengerFlowSummary,
  ConnectionAtRisk,
  BaggageZone,
  BaggageFlowSummary,
  FlaggedBaggage,
  Incident,
  IncidentAlert,
  ADSBFeatureCollection,
  GroundVehicleSummary,
} from "../types";

/* ──────── Flight Board ──────── */

export function useFlightBoardQueries() {
  const flights = useQuery({
    queryKey: ["flights", "board"],
    queryFn: async () => {
      const data = await flightsApi.list({ limit: "500" });
      return (data as { flights: Flight[] }).flights ?? [];
    },
    refetchInterval: 10_000,
  });

  const runways = useQuery({
    queryKey: ["runways"],
    queryFn: async () => {
      const data = await flightsApi.runways();
      const rd = data as { runways?: Runway[] };
      return rd.runways ?? (Array.isArray(data) ? (data as Runway[]) : []);
    },
  });

  const weather = useQuery({
    queryKey: ["weather", "current"],
    queryFn: () => weatherApi.current(),
  });

  return { flights, runways, weather };
}

/* ──────── Passenger Flow ──────── */

export function usePassengerFlowQueries() {
  const heatmap = useQuery({
    queryKey: ["passengers", "heatmap"],
    queryFn: async () => {
      const data = await passengersApi.heatmap();
      const hd = data as { zones?: ZoneDensity[] };
      return hd.zones ?? (Array.isArray(data) ? (data as ZoneDensity[]) : []);
    },
  });

  const summary = useQuery({
    queryKey: ["passengers", "summary"],
    queryFn: () => passengersApi.summary() as Promise<PassengerFlowSummary>,
  });

  const atRisk = useQuery({
    queryKey: ["passengers", "atRisk"],
    queryFn: async () => {
      const data = await passengersApi.atRisk();
      const rd = data as { at_risk?: ConnectionAtRisk[] };
      return (
        rd.at_risk ?? (Array.isArray(data) ? (data as ConnectionAtRisk[]) : [])
      );
    },
  });

  return { heatmap, summary, atRisk };
}

/* ──────── Baggage Tracker ──────── */

export function useBaggageTrackerQueries() {
  const map = useQuery({
    queryKey: ["baggage", "map"],
    queryFn: async () => {
      const data = await baggageApi.map();
      const md = data as { zones?: BaggageZone[] };
      return md.zones ?? (Array.isArray(data) ? (data as BaggageZone[]) : []);
    },
    refetchInterval: 5_000,
  });

  const summary = useQuery({
    queryKey: ["baggage", "summary"],
    queryFn: async () => {
      const data = await baggageApi.summary();
      const sd = data as Record<string, unknown>;
      return {
        total_in_system: (sd.total_in_system as number) ?? 0,
        by_status: (sd.by_status as Record<string, number>) ?? {},
        flagged_count:
          (sd.flagged_count as number) ?? (sd.flagged_active as number) ?? 0,
        loaded_count:
          (sd.loaded_count as number) ??
          (sd.by_status as Record<string, number> | undefined)?.loaded ??
          0,
      } as BaggageFlowSummary;
    },
    refetchInterval: 5_000,
  });

  const flagged = useQuery({
    queryKey: ["baggage", "flagged"],
    queryFn: async () => {
      const data = await baggageApi.flagged();
      const fd = data as { flagged?: FlaggedBaggage[] };
      return (
        fd.flagged ?? (Array.isArray(data) ? (data as FlaggedBaggage[]) : [])
      );
    },
    refetchInterval: 5_000,
  });

  const flights = useQuery({
    queryKey: ["flights", "departures"],
    queryFn: async () => {
      const data = await flightsApi.list({
        direction: "departure",
        limit: "100",
      });
      return (data as { flights?: Flight[] }).flights ?? [];
    },
  });

  return { map, summary, flagged, flights };
}

/* ──────── Ground Ops ──────── */

export function useGroundOpsQueries() {
  const runways = useQuery({
    queryKey: ["runways"],
    queryFn: async () => {
      const data = await flightsApi.runways();
      const rd = data as { runways?: Runway[] };
      return rd.runways ?? (Array.isArray(data) ? (data as Runway[]) : []);
    },
  });

  const gates = useQuery({
    queryKey: ["gates"],
    queryFn: async () => {
      const data = await flightsApi.gates();
      const gd = data as { gates?: Gate[] };
      return gd.gates ?? (Array.isArray(data) ? (data as Gate[]) : []);
    },
  });

  const flights = useQuery({
    queryKey: ["flights", "ground"],
    queryFn: async () => {
      const data = await flightsApi.list({
        status: "approach,taxiing,boarding,at_gate,arrived,departed",
        limit: "200",
      });
      return (data as { flights: Flight[] }).flights ?? [];
    },
  });

  const weather = useQuery({
    queryKey: ["weather", "current"],
    queryFn: () => weatherApi.current(),
  });

  const incidents = useQuery({
    queryKey: ["incidents", "active"],
    queryFn: async () => {
      const data = await incidentsApi.list({ status: "active,contained" });
      return (data as { incidents: Incident[] }).incidents ?? [];
    },
  });

  return { runways, gates, flights, weather, incidents };
}

/* ──────── Incident Console ──────── */

export function useIncidentConsoleQueries() {
  const active = useQuery({
    queryKey: ["incidents", "active"],
    queryFn: async () => {
      const data = await incidentsApi.list({ status: "active,contained" });
      return (data as { incidents: Incident[] }).incidents ?? [];
    },
  });

  const resolved = useQuery({
    queryKey: ["incidents", "resolved"],
    queryFn: async () => {
      const data = await incidentsApi.list({ status: "resolved" });
      return (data as { incidents: Incident[] }).incidents ?? [];
    },
  });

  const alerts = useQuery({
    queryKey: ["incidents", "alerts"],
    queryFn: async () => {
      const data = await incidentsApi.alerts();
      const ad = data as { alerts?: IncidentAlert[] };
      return (
        ad.alerts ?? (Array.isArray(data) ? (data as IncidentAlert[]) : [])
      );
    },
  });

  return { active, resolved, alerts };
}

/* ──────── ADS-B States ──────── */

export function useADSBQuery(enabled = true) {
  return useQuery({
    queryKey: ["adsb", "states"],
    queryFn: async () => {
      const data = await flightsApi.adsbStates();
      return data as ADSBFeatureCollection;
    },
    refetchInterval: 15_000,
    enabled,
    retry: 1,
  });
}

/* ──────── Ground Vehicles ──────── */

export function useGroundVehiclesQuery() {
  return useQuery({
    queryKey: ["ground-vehicles"],
    queryFn: async () => {
      const data = await flightsApi.groundVehicles();
      return data as GroundVehicleSummary;
    },
    refetchInterval: 5_000,
  });
}

/* ──────── Analysis ──────── */

export function useBottlenecksQuery() {
  return useQuery({
    queryKey: ["analysis", "bottlenecks"],
    queryFn: async () => {
      const data = await analysisApi.bottlenecks();
      return data.bottlenecks ?? [];
    },
    refetchInterval: 10_000,
  });
}

export function useRecommendationsQuery() {
  return useQuery({
    queryKey: ["analysis", "recommendations"],
    queryFn: async () => {
      const data = await analysisApi.recommendations();
      return data.recommendations ?? [];
    },
    refetchInterval: 10_000,
  });
}

export function useAutonomousSettingsQuery() {
  return useQuery({
    queryKey: ["analysis", "autonomous"],
    queryFn: async () => {
      const data = await analysisApi.autonomousSettings();
      return (data as Record<string, unknown>).autonomous ?? {};
    },
    refetchInterval: 30_000,
  });
}

export function useNetworkStatusQuery(enabled = true) {
  return useQuery({
    queryKey: ["network", "status"],
    queryFn: () => networkApi.status(),
    refetchInterval: 10_000,
    enabled,
    retry: false,
  });
}
