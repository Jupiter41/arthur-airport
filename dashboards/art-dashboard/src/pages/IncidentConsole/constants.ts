import type { IncidentSeverity } from "../../types";

export const SEVERITY_BORDER: Record<IncidentSeverity, string> = {
  critical: "border-red-600",
  high: "border-orange-500",
  medium: "border-amber-500",
  low: "border-gray-500",
};

export const SEVERITY_BG: Record<IncidentSeverity, string> = {
  critical: "bg-red-900/30",
  high: "bg-orange-900/20",
  medium: "bg-amber-900/20",
  low: "bg-gray-800",
};

export const INCIDENT_TYPES = [
  "runway_incursion",
  "baggage_fire",
  "security_breach",
  "severe_weather",
  "system_failure",
] as const;

export const SEVERITY_OPTIONS = ["low", "medium", "high", "critical"] as const;

export const LOCATIONS: Record<string, string[]> = {
  runway_incursion: ["runway-09L", "runway-09R", "runway-27R", "runway-27L"],
  baggage_fire: [
    "make-up-A-1",
    "make-up-A-2",
    "make-up-A-3",
    "make-up-A-4",
    "make-up-A-5",
    "make-up-B-1",
    "make-up-B-2",
    "make-up-B-3",
    "make-up-B-4",
    "make-up-B-5",
    "make-up-C-1",
    "make-up-C-2",
    "make-up-C-3",
    "make-up-C-4",
    "make-up-C-5",
  ],
  security_breach: [
    "terminal-A",
    "terminal-B",
    "terminal-C",
    "airside-A",
    "airside-B",
    "airside-C",
  ],
  severe_weather: ["airport-wide"],
  system_failure: [
    "conveyor-sorting",
    "conveyor-induction-A",
    "conveyor-induction-B",
    "conveyor-induction-C",
    "power-A",
    "power-B",
    "power-C",
    "screening-unit-1",
    "screening-unit-2",
    "screening-unit-3",
    "screening-unit-4",
    "screening-unit-5",
    "screening-unit-6",
  ],
};

export const EXPECTED_EFFECTS: Record<string, string> = {
  runway_incursion:
    "→ Runway closed immediately\n→ ~6 aircraft go-around / enter holding\n→ RUNWAY_STOP protocol activates\n→ ~18–34 min disruption",
  baggage_fire:
    "→ Affected make-up zone shut down\n→ Baggage rerouted to alternate zones\n→ BAGGAGE_HOLD protocol activates",
  security_breach:
    "→ Zone lockdown activated\n→ Passengers held in place\n→ TERMINAL_LOCKDOWN protocol possible",
  severe_weather:
    "→ Weather transitions to LIFR\n→ Arrival/departure rates reduced\n→ GROUND_STOP possible",
  system_failure:
    "→ Affected conveyor zone goes offline\n→ Baggage flow disrupted\n→ Recovery after TTR",
};

export const SEVERITY_RING: Record<string, string> = {
  critical: "ring-red-500",
  warning: "ring-amber-500",
};

export const ACTION_ICON: Record<string, string> = {
  open_security_lane: "🚪",
  early_gate_call: "📢",
  redirect_checkin: "🔄",
  reassign_gate: "🔀",
  delay_taxi: "⏸",
  swap_gates: "↔",
  hold_connecting_flight: "✋",
  fast_track_passengers: "⚡",
  rebook_passengers: "📋",
  ground_delay_program: "🛬",
  redistribute_vehicles: "🚛",
  defer_task: "⏳",
  redirect_baggage: "🧳",
  expedite_loading: "📦",
};

export const TABS = [
  { id: "ops", label: "Operations", icon: "🚨" },
  { id: "analysis", label: "Analysis", icon: "📊" },
  { id: "ai", label: "AI Tools", icon: "🤖" },
  { id: "autonomous", label: "Autonomous", icon: "⚙️" },
] as const;

export type TabId = (typeof TABS)[number]["id"];
