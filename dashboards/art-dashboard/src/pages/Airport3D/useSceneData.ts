import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { baggageApi, flightsApi, passengersApi } from "../../hooks/useApi";
import { useFlightStore } from "../../stores/flightStore";
import { useGroundVehicleStore } from "../../stores/groundVehicleStore";
import type { BaggageZone, Flight, Gate, GroundVehicleSummary, PassengerFlowSummary, Runway, ZoneDensity } from "../../types";
import { normalizeGate, type SceneData, type View } from "./model";
import type { RunwayQueueSnapshot } from "./atc";

export function useSceneData(view?: View) {
  const flights = useFlightStore(s => s.flights);
  const gates = useFlightStore(s => s.gates);
  const runways = useFlightStore(s => s.runways);
  const vehicles = useGroundVehicleStore(s => s.vehicles);
  const flightLoad = useQuery({ queryKey: ["flights", "3d"], queryFn: async () => (await flightsApi.list({ limit: "500" })).flights.map(raw => {
    const flight = raw as Flight & { aircraft_registration?: string };
    return { ...flight, registration: flight.registration || flight.aircraft_registration || "Unavailable" };
  }), refetchInterval: 15_000 });
  const gateLoad = useQuery({ queryKey: ["gates"], queryFn: async () => (await flightsApi.gates()).gates.map(g => normalizeGate(g as Gate & { id?: string })), refetchInterval: 15_000 });
  const runwayLoad = useQuery({ queryKey: ["runways"], queryFn: async () => (await flightsApi.runways()).runways as Runway[], refetchInterval: 15_000 });
  const vehicleLoad = useQuery({ queryKey: ["ground-vehicles"], queryFn: () => flightsApi.groundVehicles() as Promise<GroundVehicleSummary>, refetchInterval: 5000 });
  const passenger = useQuery({ queryKey: ["passengers", "summary"], queryFn: () => passengersApi.summary() as Promise<PassengerFlowSummary>, refetchInterval: 5000 });
  const heatmap = useQuery({ queryKey: ["passengers", "heatmap"], queryFn: async () => (await passengersApi.heatmap() as { zones: ZoneDensity[] }).zones, refetchInterval: 5000 });
  const runwayQueue = useQuery({ queryKey: ["runways", "queue"], queryFn: () => flightsApi.runwayQueue() as Promise<RunwayQueueSnapshot>, refetchInterval: 5000, enabled: view === "atc" });
  const baggage = useQuery({ queryKey: ["baggage", "map"], queryFn: async () => (await baggageApi.map() as { zones: BaggageZone[] }).zones, refetchInterval: 5000 });
  useEffect(() => { if (flightLoad.data) useFlightStore.getState().setFlights(flightLoad.data); }, [flightLoad.data]);
  useEffect(() => { if (gateLoad.data) useFlightStore.getState().setGates(gateLoad.data.map(normalizeGate)); }, [gateLoad.data]);
  useEffect(() => { if (runwayLoad.data) useFlightStore.getState().setRunways(runwayLoad.data); }, [runwayLoad.data]);
  useEffect(() => { if (vehicleLoad.data) useGroundVehicleStore.getState().setVehicles(vehicleLoad.data.vehicles); }, [vehicleLoad.data]);
  const data: SceneData = useMemo(() => ({ flights: Object.values(flights), gates: gates.map(normalizeGate), runways, vehicles: Object.values(vehicles), passenger: passenger.data, passengerZones: heatmap.data, zones: baggage.data ?? [], runwayQueue: runwayQueue.data }), [flights, gates, runways, vehicles, passenger.data, heatmap.data, baggage.data, runwayQueue.data]);
  const sources = [["Flights", flightLoad], ["Gates", gateLoad], ["Runways", runwayLoad], ["Vehicles", vehicleLoad], ["Passengers", passenger], ["Passenger zones", heatmap], ["Baggage", baggage], ["Runway queue", runwayQueue]] as const;
  return { data, unavailable: sources.filter(([, q]) => q.isError).map(([name]) => name), loading: sources.some(([, q]) => q.isLoading),
    refresh: () => { sources.forEach(([name, q]) => { if (name !== "Runway queue" || view === "atc") void q.refetch(); }); } };
}
