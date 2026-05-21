/* ──────── Types ──────── */

export interface ScenarioSummary {
  name: string;
  description: string;
  duration_sim_minutes: number;
  event_count: number;
  outcome_count: number;
  is_base?: boolean;
}

export interface ScenarioEvent {
  at_sim_offset_minutes: number;
  type: string;
  severity: string;
  location: string;
  trigger: string;
  description?: string;
}

export interface ExpectedOutcome {
  metric: string;
  condition: string;
  within_sim_minutes: number;
}

export interface SeedOverrides {
  weather?: string;
  daily_flights?: number;
  load_factor?: number;
}

export interface ScenarioDefinition {
  name: string;
  description: string;
  sim_speed: number;
  start_time: string;
  duration_sim_minutes: number;
  seed_overrides?: SeedOverrides;
  events: ScenarioEvent[];
  expected_outcomes: ExpectedOutcome[];
  is_base?: boolean;
}

export type ScenarioPayload = Omit<ScenarioDefinition, "is_base">;
export type EditorMode = "create" | "edit" | "fork";

export interface MetricSnapshot {
  sim_time: string;
  offset_minutes: number;
  flights_delayed_current: number;
  holding_stack_depth: number;
  cascade_depth_max: number;
  avg_delay_minutes: number;
  missed_connections: number;
  security_queue_max: number;
  incident_count_active: number;
  flights_cancelled: number;
  total_delay_minutes: number;
  pax_disrupted: number;
}

export interface OutcomeResult {
  metric: string;
  condition: string;
  expected: string;
  actual: number;
  passed: boolean;
  evaluated_at_offset_minutes: number;
}

export interface ScenarioRunResult {
  run_id: string;
  scenario_name: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  sim_start_time: string;
  sim_end_time: string;
  duration_sim_minutes: number;
  events_injected: number;
  metric_snapshots: MetricSnapshot[];
  outcome_results: OutcomeResult[];
  summary: string;
  pass_rate?: number;
}

export interface ActiveScenario {
  active: boolean;
  run_id?: string;
  scenario_name?: string;
  status?: string;
  events_injected?: number;
  snapshots_collected?: number;
  latest_metrics?: MetricSnapshot;
  sim_time?: string;
}

/* ──────── Constants ──────── */

export const EMPTY_SCENARIO: ScenarioPayload = {
  name: "",
  description: "",
  sim_speed: 600,
  start_time: "2024-06-15T07:30:00",
  duration_sim_minutes: 120,
  seed_overrides: {
    weather: "CAVOK",
    daily_flights: 420,
    load_factor: 0.85,
  },
  events: [
    {
      at_sim_offset_minutes: 30,
      type: "runway_incursion",
      severity: "high",
      location: "runway-09L",
      trigger: "manual",
      description: "",
    },
  ],
  expected_outcomes: [
    {
      metric: "flights_delayed_current",
      condition: ">= 5",
      within_sim_minutes: 60,
    },
  ],
};

export const SEVERITY_COLOR: Record<string, string> = {
  critical: "text-red-400",
  high: "text-orange-400",
  medium: "text-amber-400",
  low: "text-gray-400",
};

export const TYPE_EMOJI: Record<string, string> = {
  runway_incursion: "🛬",
  baggage_fire: "🔥",
  security_breach: "🚨",
  system_failure: "⚙️",
  severe_weather: "🌧️",
};
