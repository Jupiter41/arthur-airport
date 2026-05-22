export interface SimSettings {
  daily_flights: number;
  load_factor_mean: number;
  pax_multiplier: number;
  special_event: string | null;
  hourly_weights: Record<string, number>;
  weather_lock: string | null;
  wind_kt: number;
  gust_enabled: boolean;
  runway_incursion_rate: number;
  baggage_fire_rate: number;
  security_breach_rate: number;
  system_failure_rate: number;
  suppression_window_h: number;
  lanes_a: number;
  lanes_b: number;
  lanes_c: number;
  mct_minutes: number;
  screening_units: number;
  sorting_capacity: number;
  dg_false_positive_rate: number;
}

export interface SimStatus {
  running: boolean;
  paused: boolean;
  sim_time: string;
  speed_multiplier: number;
  day_number: number;
}

export type AutonomousMode = "off" | "rule_based" | "threshold" | "rl_agent";

export interface AutonomousState {
  enabled: boolean;
  mode: AutonomousMode;
  confidence_threshold: number;
  check_interval_sim_minutes: number;
  blocked_actions: string[];
}

export const SPEEDS = [1, 10, 60, 600, 3600];

export const DEFAULT_HOURS = [
  5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
];

export const WEATHER_OPTIONS = [
  { value: "", label: "FSM (auto)" },
  { value: "CAVOK", label: "CAVOK" },
  { value: "VMC", label: "VMC" },
  { value: "IMC", label: "IMC" },
  { value: "LIFR", label: "LIFR" },
];
