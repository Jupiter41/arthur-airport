/* ── Domain types for the Arthur Airport dashboard ── */

// ---------- Simulation ----------
export interface SimStatus {
  running: boolean;
  paused: boolean;
  speed_multiplier: number;
  sim_time: string;
  day_number: number;
  tick_count: number;
}

// ---------- Weather ----------
export interface WeatherState {
  category: "CAVOK" | "VMC" | "IMC" | "LIFR";
  visibility_m: number;
  wind_speed_kt: number;
  wind_direction_deg: number;
  wind_gust_kt: number | null;
  temperature_c: number;
  dewpoint_c: number;
  pressure_hpa: number;
  ceiling_ft: number | null;
  cloud_layers: string[];
  phenomena: string[];
  metar_raw: string;
  runway_impact: string;
  arrival_rate: number;
  departure_rate: number;
  sim_time: string;
}

// ---------- Flights ----------
export type FlightStatus =
  | "scheduled"
  | "boarding"
  | "departed"
  | "airborne"
  | "approach"
  | "landed"
  | "taxiing"
  | "at_gate"
  | "delayed"
  | "cancelled"
  | "diverted";

export type FlightDirection = "departure" | "arrival";

export interface Flight {
  id: string;
  flight_number: string;
  airline_code: string;
  aircraft_type: string;
  registration: string;
  direction: FlightDirection;
  origin_iata: string;
  destination_iata: string;
  gate_id: string | null;
  runway_id: string | null;
  terminal: string;
  status: FlightStatus;
  scheduled_time: string;
  estimated_time: string | null;
  actual_time: string | null;
  delay_minutes: number;
  pax_count: number;
  pax_boarded: number;
  baggage_count: number;
  baggage_loaded: number;
}

export interface Runway {
  runway_id: string;
  status: string;
  operation: string;
  arrivals_queued: number;
  departures_queued: number;
  capacity_per_hour: number;
  current_rate: number;
  queue: string[];
}

export interface Gate {
  gate_id: string;
  terminal: string;
  status: string;
  flight_id: string | null;
  flight_number: string | null;
}

// ---------- Passengers ----------
export interface PassengerFlowSummary {
  total_in_airport: number;
  by_status: Record<string, number>;
  security: Record<
    string,
    { queue_length: number; wait_minutes: number; lanes_open: number }
  >;
  connections_at_risk: number;
  connections_missed: number;
}

export interface ZoneDensity {
  zone_id: string;
  zone_type: string;
  terminal: string;
  density: number;
  capacity: number;
  load_pct: number;
}

export interface ConnectionAtRisk {
  passenger_id: string;
  passenger_name: string;
  inbound_flight: string;
  inbound_delay_minutes: number;
  connection_flight: string;
  connection_departure: string;
  time_until_departure_min: number;
  risk_level: "watch" | "at_risk" | "missed";
  checked_bags: number;
}

// ---------- Baggage ----------
export interface BaggageFlowSummary {
  total_in_system: number;
  by_status: Record<string, number>;
  flagged_count: number;
  loaded_count: number;
}

export interface BaggageZone {
  zone_id: string;
  zone_type: string;
  status: "active" | "offline" | "idle";
  items: number;
  capacity: number;
  utilisation_pct: number;
  throughput_per_hour: number;
}

export interface FlaggedBaggage {
  id: string;
  tag: string;
  flag_reason: string;
  dg_class: number | null;
  passenger_name: string;
  flight_number: string;
  current_zone: string;
  review_status: string;
}

// ---------- Incidents ----------
export type IncidentSeverity = "low" | "medium" | "high" | "critical";
export type IncidentStatus = "active" | "contained" | "resolved";
export type IncidentType =
  | "runway_incursion"
  | "baggage_fire"
  | "security_breach"
  | "severe_weather"
  | "system_failure";

export interface Incident {
  id: string;
  type: IncidentType;
  title: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  location: string;
  description: string;
  started_at: string;
  contained_at: string | null;
  resolved_at: string | null;
  ttr_remaining_min: number | null;
  protocols: string[];
  cascade_depth: number;
  cascade_tree: CascadeNode | null;
}

export interface CascadeNode {
  id: string;
  type: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  description: string;
  affected_count: number;
  depth: number;
  children: CascadeNode[];
}

export interface IncidentAlert {
  id: string;
  sim_time: string;
  severity: IncidentSeverity;
  message: string;
  incident_id: string;
}

// ---------- Kafka event envelope ----------
export interface KafkaEvent {
  event_id: string;
  event_type: string;
  schema_version: string;
  produced_at: string;
  sim_time: string;
  producer: string;
  payload: Record<string, unknown>;
}

// ---------- Airport aggregate ----------
export interface AirportAggregate {
  sim_time: string;
  airport: { iata: string; icao: string; name: string };
  simulation: {
    running: boolean;
    speed_multiplier: number;
    day_number: number;
  };
  weather: {
    category: string;
    visibility_m: number;
    wind_speed_kt: number;
    runway_impact: string;
    metar_raw: string;
  };
  flights: {
    total_today: number;
    active: number;
    delayed: number;
    cancelled: number;
    airborne: number;
  };
  passengers: {
    in_airport: number;
    security_queued: number;
    connections_at_risk: number;
  };
  baggage: {
    in_system: number;
    flagged: number;
    system_failures: number;
  };
  incidents: {
    active: number;
    highest_severity: string;
    latest: { type: string; title: string; started_at: string } | null;
  };
}
