import { create } from "zustand";
import type { Flight, Runway, Gate } from "../types";

interface FlightStoreState {
  flights: Record<string, Flight>;
  runways: Runway[];
  gates: Gate[];
  flashIds: Set<string>;

  setFlights: (list: Flight[]) => void;
  upsertFlight: (f: Flight) => void;
  updateFlightStatus: (
    flightId: string,
    status: string,
    delay?: number,
  ) => void;
  updateFlightGate: (flightId: string, gateId: string) => void;
  cancelFlight: (flightId: string) => void;
  setRunways: (r: Runway[]) => void;
  setGates: (g: Gate[]) => void;
  flashRow: (flightId: string) => void;
  clearFlash: (flightId: string) => void;
}

export const useFlightStore = create<FlightStoreState>((set) => ({
  flights: {},
  runways: [],
  gates: [],
  flashIds: new Set(),

  setFlights: (list) =>
    set({
      flights: Object.fromEntries(list.map((f) => [f.id, f])),
    }),

  upsertFlight: (f) => set((s) => ({ flights: { ...s.flights, [f.id]: f } })),

  updateFlightStatus: (flightId, status, delay) =>
    set((s) => {
      const existing = s.flights[flightId];
      if (!existing) return s;
      return {
        flights: {
          ...s.flights,
          [flightId]: {
            ...existing,
            status: status as Flight["status"],
            delay_minutes: delay ?? existing.delay_minutes,
          },
        },
      };
    }),

  updateFlightGate: (flightId, gateId) =>
    set((s) => {
      const existing = s.flights[flightId];
      if (!existing) return s;
      return {
        flights: {
          ...s.flights,
          [flightId]: { ...existing, gate_id: gateId },
        },
      };
    }),

  cancelFlight: (flightId) =>
    set((s) => {
      const existing = s.flights[flightId];
      if (!existing) return s;
      return {
        flights: {
          ...s.flights,
          [flightId]: { ...existing, status: "cancelled" },
        },
      };
    }),

  setRunways: (r) => set({ runways: r }),
  setGates: (g) => set({ gates: g }),

  flashRow: (flightId) =>
    set((s) => {
      const next = new Set(s.flashIds);
      next.add(flightId);
      return { flashIds: next };
    }),

  clearFlash: (flightId) =>
    set((s) => {
      const next = new Set(s.flashIds);
      next.delete(flightId);
      return { flashIds: next };
    }),
}));
