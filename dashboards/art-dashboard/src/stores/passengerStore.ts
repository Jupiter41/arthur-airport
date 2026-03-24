import { create } from "zustand";
import type {
  PassengerFlowSummary,
  ZoneDensity,
  ConnectionAtRisk,
} from "../types";

interface PassengerStoreState {
  summary: PassengerFlowSummary | null;
  zones: ZoneDensity[];
  connectionsAtRisk: ConnectionAtRisk[];

  setSummary: (s: PassengerFlowSummary) => void;
  setZones: (z: ZoneDensity[]) => void;
  updateZoneDensity: (zoneId: string, density: number, loadPct: number) => void;
  setConnectionsAtRisk: (c: ConnectionAtRisk[]) => void;
}

export const usePassengerStore = create<PassengerStoreState>((set) => ({
  summary: null,
  zones: [],
  connectionsAtRisk: [],

  setSummary: (s) => set({ summary: s }),
  setZones: (z) => set({ zones: z }),

  updateZoneDensity: (zoneId, density, loadPct) =>
    set((s) => ({
      zones: s.zones.map((z) =>
        z.zone_id === zoneId ? { ...z, density, load_pct: loadPct } : z,
      ),
    })),

  setConnectionsAtRisk: (c) => set({ connectionsAtRisk: c }),
}));
