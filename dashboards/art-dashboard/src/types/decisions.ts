import type { AnalysisBottleneck, AnalysisRecommendation } from "../types";

export interface DecisionStage {
  stage: string;
  at: string | null;
  details: Record<string, unknown>;
}

export interface EffectPrediction {
  metric?: string;
  delta?: number;
  probability?: number;
}

export interface DecisionOutcome {
  measurable: boolean;
  reason?: string;
  current_wait_minutes?: number;
  attribution?: {
    metric?: string;
    method: string;
    calibration_eligible: boolean;
    causal_claim: boolean;
    attributed_effect?: number;
    treated_change?: number;
    treated_before?: number;
    treated_after?: number;
    counterfactual_after?: number;
    control_count?: number;
    reason?: string;
  };
}

export interface DecisionTimeline {
  id: string;
  bottleneck_id: string | null;
  bottleneck: AnalysisBottleneck | null;
  recommendation: AnalysisRecommendation | null;
  alternatives: AnalysisRecommendation[];
  description: string;
  status: string;
  proposal_status: string | null;
  proposal_id: string | null;
  action_type: string | null;
  parameters: Record<string, unknown>;
  stages: DecisionStage[];
  predicted: EffectPrediction | null;
  outcome: DecisionOutcome | null;
  receipt: { event_type: string; topic: string; sim_time: string; payload: Record<string, unknown> } | null;
  dispatch_attempts: number;
  failure_reason: string | null;
  effect_model_version: string;
  context_available: boolean;
  action_available: boolean;
  financial_signals: Record<string, number | string | null>;
  updated_at: string | null;
}

export interface DecisionList {
  decisions: DecisionTimeline[];
  total: number;
  limit: number;
  offset: number;
}
