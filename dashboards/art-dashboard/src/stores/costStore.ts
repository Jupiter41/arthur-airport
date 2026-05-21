import { create } from "zustand";
import type { CostSummary } from "../types";

interface CostState {
  summary: CostSummary | null;
  lastEvent: {
    category: string;
    amount_eur: number;
    is_revenue: boolean;
    description: string;
  } | null;
  updateSummary: (s: CostSummary) => void;
  handleCostEvent: (payload: Record<string, unknown>) => void;
}

export const useCostStore = create<CostState>((set) => ({
  summary: null,
  lastEvent: null,

  updateSummary: (s) => set({ summary: s }),

  handleCostEvent: (payload) => {
    set({
      lastEvent: {
        category: String(payload.category ?? ""),
        amount_eur: Number(payload.amount_eur ?? 0),
        is_revenue: Boolean(payload.is_revenue),
        description: String(payload.description ?? ""),
      },
    });
  },
}));
