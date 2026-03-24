import { create } from "zustand";
import type { BaggageFlowSummary, BaggageZone, FlaggedBaggage } from "../types";

interface BaggageStoreState {
  summary: BaggageFlowSummary | null;
  zones: BaggageZone[];
  flagged: FlaggedBaggage[];

  setSummary: (s: BaggageFlowSummary) => void;
  setZones: (z: BaggageZone[]) => void;
  updateZone: (zoneId: string, patch: Partial<BaggageZone>) => void;
  setFlagged: (f: FlaggedBaggage[]) => void;
  addFlagged: (f: FlaggedBaggage) => void;
}

export const useBaggageStore = create<BaggageStoreState>((set) => ({
  summary: null,
  zones: [],
  flagged: [],

  setSummary: (s) => set({ summary: s }),
  setZones: (z) => set({ zones: z }),

  updateZone: (zoneId, patch) =>
    set((s) => ({
      zones: s.zones.map((z) =>
        z.zone_id === zoneId ? { ...z, ...patch } : z,
      ),
    })),

  setFlagged: (f) => set({ flagged: f }),
  addFlagged: (f) =>
    set((s) => ({
      flagged: [f, ...s.flagged],
    })),
}));
