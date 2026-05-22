export type FlightSortCol =
  | "flight_number"
  | "type"
  | "destination"
  | "gate"
  | "time"
  | "status"
  | "delay";

export const FLIGHT_TYPE_STYLES: Record<string, { label: string; cls: string }> = {
  domestic: { label: "DOM", cls: "bg-sky-900 text-sky-300" },
  international_short: {
    label: "INT-S",
    cls: "bg-emerald-900 text-emerald-300",
  },
  international_long: { label: "INT-L", cls: "bg-purple-900 text-purple-300" },
  cargo: { label: "CGO", cls: "bg-amber-900 text-amber-300" },
  charter: { label: "CHR", cls: "bg-rose-900 text-rose-300" },
};

export const FLIGHT_TYPE_OPTIONS = [
  { value: "", label: "All types" },
  { value: "domestic", label: "Domestic" },
  { value: "international_short", label: "Int'l Short" },
  { value: "international_long", label: "Int'l Long" },
  { value: "cargo", label: "Cargo" },
  { value: "charter", label: "Charter" },
];

export const STATUS_OPTIONS = [
  "scheduled",
  "boarding",
  "delayed",
  "departed",
  "airborne",
  "approach",
  "landed",
  "taxiing",
  "at_gate",
  "arrived",
  "cancelled",
];

export interface ColumnFilters {
  flightSearch: string;
  typeFilter: string;
  destinationSearch: string;
  gateSearch: string;
  statusFilter: string;
  airlineFilter: string;
}

export const EMPTY_FILTERS: ColumnFilters = {
  flightSearch: "",
  typeFilter: "",
  destinationSearch: "",
  gateSearch: "",
  statusFilter: "",
  airlineFilter: "",
};
