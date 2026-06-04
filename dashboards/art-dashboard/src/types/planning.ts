/**
 * Typed shapes for the planning-service REST API.
 *
 * Mirrors the response shapes produced by `services/planning-service`. Kept
 * hand-written (vs OpenAPI-generated) because most planning endpoints return
 * untyped Python `dict`s — generating types from the OpenAPI schema would
 * just round-trip back to `object`. When a planning response model is added
 * in FastAPI, replace the matching block here with the generated type.
 */

import type { KpiDist, DeltaEntry } from "../pages/Planning/types";

export interface InfrastructureConfig {
  gates_per_terminal: Record<string, number>;
  security_lanes_per_terminal: Record<string, number>;
  gate_wide_body_capable: Record<string, string[]>;
  gate_international_capable: Record<string, string[]>;
  runway_count: number;
  screening_units: number;
  sorting_capacity_per_hour: number;
  daily_flight_target: number;
  load_factor_mean: number;
  [key: string]: unknown;
}

export interface NewRoute {
  origin: string;
  destination: string;
  daily_flights: number;
  aircraft_type: string;
  distance_km?: number;
  load_factor?: number;
}

export interface InterventionPayload {
  action: string;
  params?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DisruptionPayload {
  kind: string;
  params?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface PlanningScenario {
  id: string;
  name: string;
  description: string;
  status: "pending" | "running" | "completed" | "failed";
  horizon: "day" | "week" | "month" | "year" | "10year";
  monte_carlo_runs: number;
  random_seed: number | null;
  infrastructure: InfrastructureConfig;
  demand_source: string;
  weather_source: string;
  demand_multiplier: number;
  new_routes: NewRoute[];
  removed_routes: string[];
  capex_eur: number;
  opex_delta_eur: number;
  years_horizon: number;
  discount_rate: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  progress_pct: number;
  runs_completed: number;
  interventions: InterventionPayload[];
  disruption: DisruptionPayload | null;
  parent_scenario_id: string | null;
}

export interface InvestmentResult {
  capex_eur: number;
  annual_benefit_eur: number;
  annual_opex_eur: number;
  net_annual_eur: number;
  npv_eur: number;
  irr_pct: number | null;
  irr_meaningful: boolean;
  payback_years: number;
  recommendation: string;
  cumulative_cash_flows?: number[];
}

export interface AnnualBenefitBreakdown {
  eu261_avoided_annual: number;
  delay_cost_avoided_annual: number;
  missed_connections_avoided_annual: number;
  revenue_uplift_annual: number;
  total_annual_benefit: number;
}

export interface ScenarioResults {
  scenario_id: string;
  scenario_name: string;
  status: string;
  kpis: Record<string, KpiDist>;
  baseline_kpis: Record<string, KpiDist>;
  delta_vs_baseline: Record<string, DeltaEntry>;
  financials: Partial<InvestmentResult> & {
    cumulative_cash_flows?: number[];
  };
  annual_benefit_breakdown: AnnualBenefitBreakdown;
  infrastructure_changes: {
    parameter: string;
    baseline: number | string;
    scenario: number | string;
    change: number;
  }[];
  run_duration_seconds: number;
  computed_at: string;
}

export interface ScenarioStatus {
  scenario_id: string;
  status: string;
  progress_pct: number;
  runs_completed: number;
  error: string | null;
}

export interface PlanningScenarioSummary {
  id: string;
  name: string;
  status: PlanningScenario["status"];
  horizon: PlanningScenario["horizon"];
  monte_carlo_runs: number;
  created_at: string;
  completed_at: string | null;
}

export interface ScenarioListResponse {
  total: number;
  scenarios: PlanningScenarioSummary[];
}

export interface TemplateCatalogue {
  templates: Record<
    string,
    {
      name: string;
      description: string;
      params: Record<string, unknown>;
    }
  >;
}

export interface ServiceStatus {
  service: string;
  status: string;
  scenarios: {
    pending: number;
    running: number;
    completed: number;
    failed: number;
    total: number;
  };
  metrics?: Record<string, number>;
}

export interface AuditLogEntry {
  id: string;
  type: string;
  recommendation_text: string;
  action_type: string;
  predicted_saving_eur: number;
  confidence: number;
  was_applied: boolean;
  applied_at: string | null;
  actual_saving_eur: number | null;
  prediction_error_eur: number | null;
  sim_day: number;
  sim_time: string;
  model_version: string;
  target_type: string;
  target_id: string;
  created_at: string;
  [key: string]: unknown;
}

export interface AuditLogResponse {
  total: number;
  entries: AuditLogEntry[];
}

export interface AuditSummary {
  total_recommendations: number;
  applied_count: number;
  applied_pct: number;
  total_predicted_saving_eur: number;
  total_actual_saving_eur: number;
  prediction_accuracy_pct: number;
  avg_confidence: number;
  measured_count?: number;
  [key: string]: unknown;
}

export interface DemandForecast {
  origin: string;
  destination: string;
  date: string;
  daily_pax: number;
  source: string;
}

export interface DemandGrowth {
  base_year_pax: number;
  years_ahead: number;
  growth_rate_pct: number;
  yearly: { year: number; annual_pax: number }[];
}

export interface MLStatus {
  demand_model_version: string | null;
  delay_model_version: string | null;
  trained_at: string | null;
  feature_count: number;
  metrics: Record<string, number>;
}
