import { create } from "zustand";
import type { GroundVehicle } from "../types";

interface GroundVehicleState {
  vehicles: Record<string, GroundVehicle>;
  utilisationPct: Record<string, number>;

  upsertVehicle: (vehicle: GroundVehicle) => void;
  setVehicles: (vehicles: GroundVehicle[]) => void;
  updateVehicleStatus: (vehicleId: string, status: string, gateId?: string | null) => void;
  setUtilisation: (pct: Record<string, number>) => void;
  clear: () => void;
}

export const useGroundVehicleStore = create<GroundVehicleState>((set) => ({
  vehicles: {},
  utilisationPct: {},

  setVehicles: (vehicles) => set({ vehicles: Object.fromEntries(vehicles.map(v => [v.id, v])) }),

  upsertVehicle: (vehicle) =>
    set((state) => ({
      vehicles: { ...state.vehicles, [vehicle.id]: vehicle },
    })),

  updateVehicleStatus: (vehicleId, status, gateId) =>
    set((state) => {
      const existing = state.vehicles[vehicleId];
      if (!existing) return state;
      return {
        vehicles: {
          ...state.vehicles,
          [vehicleId]: {
            ...existing,
            status: status as GroundVehicle["status"],
            current_gate: gateId ?? null,
          },
        },
      };
    }),

  setUtilisation: (pct) => set({ utilisationPct: pct }),

  clear: () => set({ vehicles: {}, utilisationPct: {} }),
}));
