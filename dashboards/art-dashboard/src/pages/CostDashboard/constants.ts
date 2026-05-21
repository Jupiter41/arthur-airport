export const CATEGORY_COLORS: Record<string, string> = {
  landing_fee: "#3b82f6",
  gate_fee: "#6366f1",
  passenger_fee: "#8b5cf6",
  eu261_compensation: "#ef4444",
  crew_overtime: "#f97316",
  holding_fuel: "#f59e0b",
  ground_handling: "#14b8a6",
  incident_direct: "#dc2626",
  incident_response: "#e11d48",
  staffing: "#64748b",
  retail_revenue: "#22c55e",
  slot_revenue: "#10b981",
};

export const CATEGORY_LABELS: Record<string, string> = {
  landing_fee: "Landing Fees",
  gate_fee: "Gate Fees",
  passenger_fee: "Passenger Fees",
  eu261_compensation: "EU261 Compensation",
  crew_overtime: "Crew Overtime",
  holding_fuel: "Holding Fuel",
  ground_handling: "Ground Handling",
  incident_direct: "Incident Direct",
  incident_response: "Incident Response",
  staffing: "Staffing",
  retail_revenue: "Retail Revenue",
  slot_revenue: "Slot Revenue",
};

export const COST_PRESETS: Record<
  string,
  { label: string; description: string; overrides: Record<string, unknown> }
> = {
  default: {
    label: "Default (Eurocontrol)",
    description: "Standard rates based on Eurocontrol reference data",
    overrides: {
      airport_fees: {
        landing_rate_per_tonne_eur: 12.0,
        gate_rate_per_hour_eur: 150.0,
        passenger_departure_fee_eur: 12.0,
      },
      staffing: {
        security_officer_per_hour_eur: 35.0,
        checkin_agent_per_hour_eur: 28.0,
        gate_agent_per_hour_eur: 28.0,
        ground_crew_per_hour_eur: 25.0,
      },
      revenue: {
        retail_spend_per_pax_per_hour_airside_eur: 12.0,
        slot_fee_eur: 2000.0,
      },
    },
  },
  low_cost: {
    label: "Low-Cost Hub",
    description: "Reduced fees typical of budget airline hubs",
    overrides: {
      airport_fees: {
        landing_rate_per_tonne_eur: 7.5,
        gate_rate_per_hour_eur: 90.0,
        passenger_departure_fee_eur: 8.0,
      },
      staffing: {
        security_officer_per_hour_eur: 28.0,
        checkin_agent_per_hour_eur: 22.0,
        gate_agent_per_hour_eur: 22.0,
        ground_crew_per_hour_eur: 20.0,
      },
      revenue: {
        retail_spend_per_pax_per_hour_airside_eur: 8.0,
        slot_fee_eur: 1200.0,
      },
    },
  },
  premium_hub: {
    label: "Premium Hub",
    description: "Higher fees and retail revenue for a major international hub",
    overrides: {
      airport_fees: {
        landing_rate_per_tonne_eur: 18.0,
        gate_rate_per_hour_eur: 250.0,
        passenger_departure_fee_eur: 18.0,
      },
      staffing: {
        security_officer_per_hour_eur: 45.0,
        checkin_agent_per_hour_eur: 35.0,
        gate_agent_per_hour_eur: 35.0,
        ground_crew_per_hour_eur: 32.0,
      },
      revenue: {
        retail_spend_per_pax_per_hour_airside_eur: 22.0,
        slot_fee_eur: 4000.0,
      },
    },
  },
  high_incident: {
    label: "High Incident Cost",
    description:
      "Elevated incident costs for stress-testing financial resilience",
    overrides: {
      incident_costs: {
        runway_incursion: { direct_eur: 50000, response_eur: 30000 },
        baggage_fire: { direct_eur: 80000, response_eur: 40000 },
        security_breach: { direct_eur: 150000, response_eur: 60000 },
        system_failure: { direct_eur: 20000, response_eur: 5000 },
        severe_weather: { direct_eur: 0, response_eur: 10000 },
      },
    },
  },
};

export const EDITABLE_CATEGORIES = [
  {
    key: "airport_fees",
    label: "Airport Fees",
    fields: [
      {
        key: "landing_rate_per_tonne_eur",
        label: "Landing (€/tonne)",
        step: 0.5,
      },
      { key: "gate_rate_per_hour_eur", label: "Gate (€/hour)", step: 10 },
      {
        key: "passenger_departure_fee_eur",
        label: "Passenger fee (€)",
        step: 1,
      },
    ],
  },
  {
    key: "staffing",
    label: "Staffing",
    fields: [
      {
        key: "security_officer_per_hour_eur",
        label: "Security (€/h)",
        step: 1,
      },
      { key: "checkin_agent_per_hour_eur", label: "Check-in (€/h)", step: 1 },
      { key: "gate_agent_per_hour_eur", label: "Gate agent (€/h)", step: 1 },
      { key: "ground_crew_per_hour_eur", label: "Ground crew (€/h)", step: 1 },
    ],
  },
  {
    key: "revenue",
    label: "Revenue",
    fields: [
      {
        key: "retail_spend_per_pax_per_hour_airside_eur",
        label: "Retail (€/pax/h)",
        step: 1,
      },
      { key: "slot_fee_eur", label: "Slot fee (€)", step: 100 },
    ],
  },
  {
    key: "ground_handling",
    label: "Ground Handling",
    fields: [
      { key: "pushback_eur", label: "Pushback (€)", step: 50 },
      { key: "catering_narrow_eur", label: "Catering narrow (€)", step: 100 },
      { key: "catering_wide_eur", label: "Catering wide (€)", step: 200 },
      { key: "cleaning_narrow_eur", label: "Cleaning narrow (€)", step: 50 },
      { key: "cleaning_wide_eur", label: "Cleaning wide (€)", step: 100 },
      {
        key: "baggage_loader_per_bag_eur",
        label: "Bag loader (€/bag)",
        step: 0.5,
      },
    ],
  },
];
