import { formatEur } from "../../utils/formatCurrency";

/* ─── Shared types ────────────────────────────────────────── */

export type Tab = "builder" | "results" | "investment" | "audit";

export interface KpiDist {
  mean: number;
  std: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

export interface DeltaEntry {
  baseline_mean: number;
  scenario_mean: number;
  absolute_change: number;
  pct_change: number;
}

export interface ScenarioSummary {
  id: string;
  name: string;
  status: string;
  horizon: string;
  monte_carlo_runs: number;
  created_at: string;
  completed_at?: string;
}

export interface InfraChange {
  parameter: string;
  baseline: number;
  scenario: number;
  change: number;
}

export const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: "builder", label: "Scenario Builder", icon: "🏗️" },
  { key: "results", label: "Results", icon: "📊" },
  { key: "investment", label: "Investment", icon: "💰" },
  { key: "audit", label: "Decision Audit", icon: "📋" },
];

/* ─── KPI metadata ────────────────────────────────────────── */

export const KPI_META: Record<
  string,
  {
    label: string;
    unit: string;
    description: string;
    lowerIsBetter: boolean;
    format: (v: number) => string;
  }
> = {
  avg_delay_minutes: {
    label: "Avg Delay",
    unit: "min",
    description:
      "Average departure delay per flight. Eurocontrol defines >15 min as 'delayed'. Lower is better.",
    lowerIsBetter: true,
    format: (v) => `${v.toFixed(1)} min`,
  },
  on_time_rate: {
    label: "On-Time Rate",
    unit: "%",
    description:
      "Fraction of flights departing within 15 minutes of schedule. Industry benchmark: 80%+. Higher is better.",
    lowerIsBetter: false,
    format: (v) => `${(v * 100).toFixed(1)}%`,
  },
  missed_connections: {
    label: "Missed Connections",
    unit: "/day",
    description:
      "Passengers who miss connecting flights due to delays. Each costs ~€285 in rebooking. Lower is better.",
    lowerIsBetter: true,
    format: (v) => v.toFixed(1),
  },
  gate_utilisation_pct: {
    label: "Gate Utilisation",
    unit: "%",
    description:
      "Percentage of gate-hours used vs available. 70-85% is optimal; above 90% causes conflicts. Moderate is better.",
    lowerIsBetter: false,
    format: (v) => `${v.toFixed(1)}%`,
  },
  runway_utilisation_pct: {
    label: "Runway Utilisation",
    unit: "%",
    description:
      "Peak-hour runway throughput vs theoretical max. Above 85% causes queuing delays. Moderate is better.",
    lowerIsBetter: false,
    format: (v) => `${v.toFixed(1)}%`,
  },
  eu261_liability_eur: {
    label: "EU261 Liability",
    unit: "€/day",
    description:
      "Daily compensation liability under EU Regulation 261/2004. €250-600 per qualifying passenger. Lower is better.",
    lowerIsBetter: true,
    format: (v) => formatEur(v),
  },
  total_cost_eur: {
    label: "Total Cost",
    unit: "€/day",
    description:
      "Total daily operating cost including delay costs, EU261, landing fees, and gate fees. Lower is better.",
    lowerIsBetter: true,
    format: (v) => formatEur(v),
  },
  total_revenue_eur: {
    label: "Total Revenue",
    unit: "€/day",
    description:
      "Total daily revenue from passenger fees, landing fees, and gate fees. Higher is better.",
    lowerIsBetter: false,
    format: (v) => formatEur(v),
  },
  gate_conflicts: {
    label: "Gate Conflicts",
    unit: "/day",
    description:
      "Flights that couldn't find an available gate at boarding time, causing delays. Lower is better.",
    lowerIsBetter: true,
    format: (v) => v.toFixed(1),
  },
  security_wait_max_minutes: {
    label: "Max Security Wait",
    unit: "min",
    description:
      "Longest security queue wait across all terminals. EU benchmark: <20 min. Lower is better.",
    lowerIsBetter: true,
    format: (v) => `${v.toFixed(1)} min`,
  },
};
