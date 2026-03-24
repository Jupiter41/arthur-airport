import { create } from "zustand";
import type { SimStatus } from "../types";

interface SimState {
  status: SimStatus;
  updateFromTick: (simTime: string) => void;
  setStatus: (status: SimStatus) => void;
  setPaused: (paused: boolean) => void;
  setSpeed: (speed: number) => void;
}

export const useSimStore = create<SimState>((set) => ({
  status: {
    running: false,
    paused: false,
    speed_multiplier: 60,
    sim_time: new Date().toISOString(),
    day_number: 1,
    tick_count: 0,
  },
  updateFromTick: (simTime) =>
    set((s) => ({
      status: {
        ...s.status,
        sim_time: simTime,
        tick_count: s.status.tick_count + 1,
      },
    })),
  setStatus: (status) => set({ status }),
  setPaused: (paused) =>
    set((s) => ({ status: { ...s.status, paused, running: !paused } })),
  setSpeed: (speed) =>
    set((s) => ({ status: { ...s.status, speed_multiplier: speed } })),
}));
