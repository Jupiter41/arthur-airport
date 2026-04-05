import { create } from "zustand";

export interface AnalysisBottleneck {
  id: string;
  type: string;
  severity: "warning" | "critical";
  zone: string;
  root_cause: string;
  estimated_duration_minutes: number;
  affected_entity_count: number;
  detected_at: string;
  metrics: Record<string, unknown>;
  resolved_at: string | null;
}

export interface AnalysisRecommendation {
  id: string;
  bottleneck_id: string;
  action_type: string;
  description: string;
  expected_impact: string;
  cost: string;
  confidence_score: number;
  expiry_sim_time: string;
  priority_rank: number;
  parameters: Record<string, unknown>;
  applied: boolean;
  applied_at: string | null;
}

interface AnalysisStoreState {
  bottlenecks: AnalysisBottleneck[];
  recommendations: AnalysisRecommendation[];

  setBottlenecks: (list: AnalysisBottleneck[]) => void;
  setRecommendations: (list: AnalysisRecommendation[]) => void;
  handleAnalysisEvent: (payload: Record<string, unknown>) => void;
}

export const useAnalysisStore = create<AnalysisStoreState>((set) => ({
  bottlenecks: [],
  recommendations: [],

  setBottlenecks: (list) => set({ bottlenecks: list }),
  setRecommendations: (list) => set({ recommendations: list }),

  handleAnalysisEvent: (payload) => {
    const eventType = payload.event_type as string | undefined;
    const data = (payload.payload ?? payload) as Record<string, unknown>;

    if (eventType === "BottleneckDetected") {
      set((state) => ({
        bottlenecks: [
          ...state.bottlenecks.filter((b) => b.id !== data.id),
          data as unknown as AnalysisBottleneck,
        ],
      }));
    } else if (eventType === "BottleneckResolved") {
      const bnId = data.bottleneck_id as string;
      set((state) => ({
        bottlenecks: state.bottlenecks.filter((b) => b.id !== bnId),
      }));
    } else if (eventType === "RecommendationGenerated") {
      set((state) => ({
        recommendations: [
          ...state.recommendations.filter((r) => r.id !== data.id),
          data as unknown as AnalysisRecommendation,
        ].slice(-10),
      }));
    }
  },
}));
