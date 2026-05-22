import type { Flight } from "../../types";
import type { FlightSortCol, ColumnFilters } from "./constants";

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCHours().toString().padStart(2, "0")}:${d.getUTCMinutes().toString().padStart(2, "0")}`;
}

export function flightSortValue(
  f: Flight,
  col: FlightSortCol,
  dir: "departure" | "arrival",
): unknown {
  switch (col) {
    case "flight_number":
      return f.flight_number;
    case "type":
      return f.flight_type ?? "";
    case "destination":
      return dir === "departure" ? f.destination_iata : f.origin_iata;
    case "gate":
      return f.gate_id ?? "";
    case "time":
      return f.scheduled_time;
    case "status":
      return f.status;
    case "delay":
      return f.delay_minutes;
  }
}

export function applyFilters(
  flights: Flight[],
  filters: ColumnFilters,
  direction: "departure" | "arrival",
): Flight[] {
  return flights.filter((f) => {
    if (
      filters.flightSearch &&
      !f.flight_number
        .toLowerCase()
        .includes(filters.flightSearch.toLowerCase())
    )
      return false;
    if (filters.airlineFilter && f.airline_code !== filters.airlineFilter)
      return false;
    if (filters.typeFilter && f.flight_type !== filters.typeFilter)
      return false;
    const city = direction === "departure" ? f.destination_iata : f.origin_iata;
    if (
      filters.destinationSearch &&
      !city.toLowerCase().includes(filters.destinationSearch.toLowerCase())
    )
      return false;
    if (
      filters.gateSearch &&
      !(f.gate_id ?? "")
        .toLowerCase()
        .includes(filters.gateSearch.toLowerCase())
    )
      return false;
    if (filters.statusFilter && f.status !== filters.statusFilter) return false;
    return true;
  });
}
