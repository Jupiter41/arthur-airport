import type { FlightStatus, IncidentSeverity, IncidentStatus } from "../types";

const FLIGHT_STATUS_COLORS: Record<FlightStatus, string> = {
  scheduled: "bg-gray-600 text-gray-200",
  boarding: "bg-green-600 text-white",
  departed: "bg-blue-600 text-white",
  airborne: "bg-blue-500 text-white",
  approach: "bg-teal-600 text-white",
  landed: "bg-teal-500 text-white",
  taxiing: "bg-teal-400 text-white",
  at_gate: "bg-purple-600 text-white",
  arrived: "bg-indigo-600 text-white",
  delayed: "bg-amber-600 text-white",
  cancelled: "bg-red-600 text-white",
  diverted: "bg-red-500 text-white",
};

const FLIGHT_STATUS_LABELS: Record<FlightStatus, string> = {
  scheduled: "SCHEDULED",
  boarding: "BOARDING",
  departed: "DEPARTED",
  airborne: "AIRBORNE",
  approach: "APPROACH",
  landed: "LANDED",
  taxiing: "TAXIING",
  at_gate: "AT GATE",
  arrived: "ARRIVED",
  delayed: "DELAYED",
  cancelled: "CANCELLED",
  diverted: "DIVERTED",
};

const SEVERITY_COLORS: Record<IncidentSeverity, string> = {
  low: "bg-gray-500 text-white",
  medium: "bg-amber-500 text-white",
  high: "bg-orange-600 text-white",
  critical: "bg-red-600 text-white",
};

const INCIDENT_STATUS_COLORS: Record<IncidentStatus, string> = {
  active: "bg-red-600 text-white animate-pulse",
  contained: "bg-amber-600 text-white",
  resolved: "bg-green-600 text-white",
};

interface StatusBadgeProps {
  status: string;
  label?: string;
  delay?: number;
  direction?: "arrival" | "departure";
  className?: string;
}

export function StatusBadge({
  status,
  label,
  delay,
  direction,
  className = "",
}: StatusBadgeProps) {
  const colorClass =
    FLIGHT_STATUS_COLORS[status as FlightStatus] ??
    SEVERITY_COLORS[status as IncidentSeverity] ??
    INCIDENT_STATUS_COLORS[status as IncidentStatus] ??
    "bg-gray-600 text-gray-200";

  let displayLabel =
    label ??
    FLIGHT_STATUS_LABELS[status as FlightStatus] ??
    status.toUpperCase();

  // Departure flights with 'arrived' status means they reached their
  // destination — show "COMPLETED" instead of "ARRIVED" which is
  // confusing on a departure board.
  if (!label && status === "arrived" && direction === "departure") {
    displayLabel = "COMPLETED";
  }

  const delayStr =
    status === "delayed" && delay && delay > 0 ? ` +${delay}` : "";

  return (
    <span
      className={`inline-block text-xs font-bold px-2 py-0.5 rounded whitespace-nowrap ${colorClass} ${className}`}
    >
      {displayLabel}
      {delayStr}
    </span>
  );
}
