import type { FlightStatus } from "../types";

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
  const colorClass = [
    "critical",
    "high",
    "cancelled",
    "diverted",
    "failed",
  ].includes(status)
    ? "badge-danger"
    : ["medium", "delayed", "contained", "pending"].includes(status)
      ? "badge-warning"
      : ["resolved", "executed", "measured"].includes(status)
        ? "badge-success"
        : "badge-neutral";

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
      className={`inline-block border text-xs font-medium px-2 py-1 rounded whitespace-nowrap ${colorClass} ${className}`}
    >
      {displayLabel}
      {delayStr}
    </span>
  );
}
