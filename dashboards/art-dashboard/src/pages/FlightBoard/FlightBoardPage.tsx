import { useState, useEffect, useMemo, useCallback, useRef, memo } from "react";
import { useFlightStore } from "../../stores/flightStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { useFlightBoardQueries } from "../../hooks/useQueries";
import { useWeatherStore } from "../../stores/weatherStore";
import { StatusBadge } from "../../components/StatusBadge";
import { ExportMenu } from "../../components/ExportMenu";
import { useSort, compare, SortArrow } from "../../hooks/useSort";
import { exportData } from "../../utils/exportData";
import type { ExportFormat } from "../../utils/exportData";
import type { Flight, Runway, WeatherState } from "../../types";

type FlightSortCol =
  | "flight_number"
  | "type"
  | "destination"
  | "gate"
  | "time"
  | "status"
  | "delay";

/* ──────── Flight Type Badge ──────── */
const FLIGHT_TYPE_STYLES: Record<string, { label: string; cls: string }> = {
  domestic: { label: "DOM", cls: "bg-sky-900 text-sky-300" },
  international_short: {
    label: "INT-S",
    cls: "bg-emerald-900 text-emerald-300",
  },
  international_long: { label: "INT-L", cls: "bg-purple-900 text-purple-300" },
  cargo: { label: "CGO", cls: "bg-amber-900 text-amber-300" },
  charter: { label: "CHR", cls: "bg-rose-900 text-rose-300" },
};

function FlightTypeBadge({ type }: { type: string | null }) {
  if (!type) return <span className="text-gray-600 text-xs">—</span>;
  const style = FLIGHT_TYPE_STYLES[type] ?? {
    label: type,
    cls: "bg-gray-700 text-gray-300",
  };
  return (
    <span
      className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${style.cls}`}
    >
      {style.label}
    </span>
  );
}

/* ──────── Flight Row ──────── */
const FlightRow = memo(function FlightRow({
  flight,
  isFlashing,
  onClick,
}: {
  flight: Flight;
  isFlashing: boolean;
  onClick: () => void;
}) {
  const statusFlash = isFlashing ? "ring-2 ring-blue-400 bg-gray-700" : "";

  return (
    <tr
      className={`border-b border-gray-800 hover:bg-gray-800/60 cursor-pointer transition-all duration-500 ${statusFlash}`}
      onClick={onClick}
    >
      <td className="px-3 py-2">
        <span className="font-bold text-white">{flight.flight_number}</span>
        <span className="ml-2 text-xs bg-gray-700 text-gray-300 px-1.5 rounded">
          {flight.airline_code}
        </span>
      </td>
      <td className="px-3 py-2">
        <FlightTypeBadge type={flight.flight_type} />
      </td>
      <td className="px-3 py-2 text-sm text-gray-300">
        {flight.direction === "departure"
          ? flight.destination_iata
          : flight.origin_iata}
      </td>
      <td className="px-3 py-2 text-sm text-gray-400 font-mono">
        {flight.gate_id ?? "—"}
      </td>
      <td className="px-3 py-2 text-sm font-mono">
        {flight.delay_minutes > 0 &&
        flight.estimated_time &&
        formatTime(flight.estimated_time) !==
          formatTime(flight.scheduled_time) ? (
          <>
            <span className="line-through text-gray-500">
              {formatTime(flight.scheduled_time)}
            </span>
            <span
              className={`ml-2 ${
                flight.delay_minutes >= 30
                  ? "text-red-400"
                  : flight.delay_minutes >= 10
                    ? "text-amber-400"
                    : "text-amber-400"
              }`}
            >
              {formatTime(flight.estimated_time)}
            </span>
          </>
        ) : (
          <span
            className={
              flight.status === "airborne" || flight.status === "departed"
                ? "text-green-400"
                : "text-gray-300"
            }
          >
            {formatTime(flight.scheduled_time)}
          </span>
        )}
      </td>
      <td className="px-3 py-2">
        <StatusBadge status={flight.status} delay={flight.delay_minutes} direction={flight.direction} />
      </td>
      <td className="px-3 py-2">
        {flight.status === "boarding" && (
          <div className="flex items-center gap-2">
            <div className="w-20 bg-gray-700 rounded-full h-2">
              <div
                className="bg-green-500 h-2 rounded-full transition-all duration-700"
                style={{
                  width: `${flight.pax_count > 0 ? Math.round((flight.pax_boarded / flight.pax_count) * 100) : 0}%`,
                }}
              />
            </div>
            <span className="text-xs text-gray-400">
              {flight.pax_boarded}/{flight.pax_count}
            </span>
          </div>
        )}
        {flight.direction === "arrival" &&
          ["approach", "landed", "taxiing", "at_gate", "arrived"].includes(
            flight.status,
          ) && (
            <span className="text-xs text-gray-400">
              {flight.pax_count > 0 ? `${flight.pax_count} pax` : "—"}
            </span>
          )}
        {flight.direction === "departure" &&
          ["airborne", "arrived"].includes(flight.status) &&
          flight.arrival_estimated_time && (
            <span className="text-xs text-gray-400">
              ETA {formatTime(flight.arrival_estimated_time)}
              {flight.status === "arrived" && (
                <span className="ml-1 text-green-400">✓</span>
              )}
            </span>
          )}
      </td>
    </tr>
  );
});

/* ──────── Flight Detail Drawer ──────── */
function FlightDetailDrawer({
  flight,
  onClose,
}: {
  flight: Flight;
  onClose: () => void;
}) {
  return (
    <div className="fixed right-0 top-0 h-full w-[400px] bg-gray-800 border-l border-gray-700 shadow-2xl z-50 overflow-y-auto">
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <h2 className="text-lg font-bold text-white">{flight.flight_number}</h2>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white text-xl"
        >
          ✕
        </button>
      </div>
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Info label="Airline" value={flight.airline_code} />
          <Info label="Aircraft" value={flight.aircraft_type} />
          <Info label="Registration" value={flight.registration} />
          <Info label="Flight Type" value={flight.flight_type ?? "—"} />
          <Info label="Route" value={flight.route_category ?? "—"} />
          <Info label="Direction" value={flight.direction} />
          <Info label="Origin" value={flight.origin_iata} />
          <Info label="Destination" value={flight.destination_iata} />
          <Info label="Gate" value={flight.gate_id ?? "Unassigned"} />
          <Info label="Runway" value={flight.runway_id ?? "—"} />
          <Info label="Terminal" value={flight.terminal} />
          <Info
            label="Delay"
            value={
              flight.delay_minutes > 0 ? `+${flight.delay_minutes} min` : "None"
            }
          />
        </div>

        <div>
          <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Status
          </h3>
          <StatusBadge
            status={flight.status}
            delay={flight.delay_minutes}
            direction={flight.direction}
            className="text-sm"
          />
        </div>

        <div>
          <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Passengers
          </h3>
          <div className="flex items-center gap-3">
            <div className="w-full bg-gray-700 rounded-full h-3">
              <div
                className="bg-blue-500 h-3 rounded-full transition-all"
                style={{
                  width: `${flight.pax_count > 0 ? Math.round((flight.pax_boarded / flight.pax_count) * 100) : 0}%`,
                }}
              />
            </div>
            <span className="text-sm text-gray-300 whitespace-nowrap">
              {flight.pax_boarded} / {flight.pax_count}
            </span>
          </div>
        </div>

        <div>
          <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            {flight.direction === "arrival" ? "Baggage Claimed" : "Baggage"}
          </h3>
          <div className="flex items-center gap-3">
            <div className="w-full bg-gray-700 rounded-full h-3">
              <div
                className="bg-teal-500 h-3 rounded-full transition-all"
                style={{
                  width: `${flight.baggage_count > 0 ? Math.round((flight.baggage_loaded / flight.baggage_count) * 100) : 0}%`,
                }}
              />
            </div>
            <span className="text-sm text-gray-300 whitespace-nowrap">
              {flight.baggage_loaded} / {flight.baggage_count}
            </span>
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <h3 className="text-xs text-gray-400 uppercase tracking-wide">
            Schedule
          </h3>
        </div>
        <div className="text-sm space-y-1 text-gray-300">
          <div>
            Scheduled:{" "}
            <span className="font-mono">
              {formatTime(flight.scheduled_time)}
            </span>
          </div>
          {flight.estimated_time &&
            formatTime(flight.estimated_time) !==
              formatTime(flight.scheduled_time) && (
              <div>
                Estimated:{" "}
                <span className="font-mono text-amber-400">
                  {formatTime(flight.estimated_time)}
                </span>
              </div>
            )}
          {flight.actual_time && (
            <div>
              Actual:{" "}
              <span className="font-mono text-green-400">
                {formatTime(flight.actual_time)}
              </span>
            </div>
          )}
          {flight.direction === "departure" &&
            flight.arrival_estimated_time && (
              <div>
                Arrival ETA:{" "}
                <span className="font-mono text-blue-400">
                  {formatTime(flight.arrival_estimated_time)}
                </span>
                {flight.status === "arrived" && (
                  <span className="ml-2 text-green-400 text-xs">✓ Arrived</span>
                )}
              </div>
            )}
          {flight.flight_duration_minutes != null &&
            flight.flight_duration_minutes > 0 && (
              <div>
                Flight duration:{" "}
                <span className="font-mono text-gray-400">
                  {Math.floor(flight.flight_duration_minutes / 60)}h{" "}
                  {flight.flight_duration_minutes % 60}m
                </span>
              </div>
            )}
        </div>
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-400 font-medium">{label}</div>
      <div className="text-gray-100">{value}</div>
    </div>
  );
}

/* ──────── Runway Throughput Chart (P1-4-4) ──────── */
function RunwayThroughputChart({ runways }: { runways: Runway[] }) {
  if (runways.length === 0) return null;

  const maxCapacity = Math.max(...runways.map((rw) => rw.capacity_per_hour), 1);

  return (
    <div className="bg-gray-800 rounded-lg p-3 border border-gray-700/50">
      <h3 className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-3">
        Runway Throughput — Actual vs Capacity
      </h3>
      <div className="flex gap-4">
        {runways.map((rw) => {
          const actualPct = (rw.current_rate / maxCapacity) * 100;
          const capacityPct = (rw.capacity_per_hour / maxCapacity) * 100;
          const utilisation =
            rw.capacity_per_hour > 0
              ? Math.round((rw.current_rate / rw.capacity_per_hour) * 100)
              : 0;
          const barColor =
            utilisation > 90
              ? "bg-red-500"
              : utilisation > 70
                ? "bg-amber-500"
                : "bg-blue-500";
          const divergence = rw.capacity_per_hour - rw.current_rate;

          return (
            <div key={rw.runway_id} className="flex-1">
              <div className="text-xs font-mono font-bold text-white mb-2 text-center">
                {rw.runway_id}
              </div>
              <div className="flex items-end gap-1 h-24 justify-center">
                {/* Actual bar */}
                <div className="flex flex-col items-center w-8">
                  <span className="text-[10px] text-gray-300 mb-1">
                    {rw.current_rate}
                  </span>
                  <div
                    className={`w-full ${barColor} rounded-t transition-all duration-700`}
                    style={{ height: `${Math.max(actualPct, 2)}%` }}
                  />
                  <span className="text-[9px] text-gray-400 mt-1">Act</span>
                </div>
                {/* Capacity bar */}
                <div className="flex flex-col items-center w-8">
                  <span className="text-[10px] text-gray-400 mb-1">
                    {rw.capacity_per_hour}
                  </span>
                  <div
                    className="w-full bg-gray-600 rounded-t border border-gray-500 border-dashed transition-all duration-700"
                    style={{ height: `${Math.max(capacityPct, 2)}%` }}
                  />
                  <span className="text-[9px] text-gray-400 mt-1">Cap</span>
                </div>
              </div>
              <div className="text-center mt-1">
                <span
                  className={`text-[10px] font-bold ${
                    utilisation > 90
                      ? "text-red-400"
                      : utilisation > 70
                        ? "text-amber-400"
                        : "text-green-400"
                  }`}
                >
                  {utilisation}%
                </span>
                {divergence > 0 && (
                  <span className="text-[9px] text-gray-400 ml-1">
                    ({divergence} spare)
                  </span>
                )}
              </div>
              <div className="text-center text-[9px] text-gray-400 mt-0.5">
                Arr: {rw.arrivals_queued} · Dep: {rw.departures_queued}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ──────── Runway Status Bar ──────── */
function RunwayStatusBar({ runways }: { runways: Runway[] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {runways.map((rw) => {
        const pct =
          rw.capacity_per_hour > 0
            ? Math.round((rw.current_rate / rw.capacity_per_hour) * 100)
            : 0;
        const statusColor =
          rw.status === "open"
            ? "text-green-400"
            : rw.status === "restricted"
              ? "text-amber-400"
              : "text-red-400";

        return (
          <div key={rw.runway_id} className="bg-gray-800 rounded p-3">
            <div className="flex items-center justify-between mb-1">
              <span className="font-mono font-bold text-white">
                {rw.runway_id}
              </span>
              <span className={`text-xs font-bold ${statusColor} uppercase`}>
                {rw.operation ?? rw.status}
              </span>
            </div>
            <div className="w-full bg-gray-700 rounded-full h-2 mb-1">
              <div
                className="bg-blue-500 h-2 rounded-full transition-all"
                style={{ width: `${Math.min(pct, 100)}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-400">
              <span>
                {rw.current_rate}/{rw.capacity_per_hour} mvts/hr
              </span>
              <span>
                Arr: {rw.arrivals_queued} · Dep: {rw.departures_queued}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ──────── FIDS Panel ──────── */
function flightSortValue(
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

const FLIGHT_TYPE_OPTIONS = [
  { value: "", label: "All types" },
  { value: "domestic", label: "Domestic" },
  { value: "international_short", label: "Int'l Short" },
  { value: "international_long", label: "Int'l Long" },
  { value: "cargo", label: "Cargo" },
  { value: "charter", label: "Charter" },
];

const STATUS_OPTIONS = [
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

/* ──────── Filter Popup Component ──────── */
function FilterIcon({ active }: { active: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="10"
      height="10"
      viewBox="0 0 24 24"
      fill={active ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`inline-block ml-1 ${active ? "text-blue-400" : "text-gray-500"}`}
    >
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  );
}

function ColumnFilterPopup({
  type,
  value,
  onChange,
  options,
  placeholder,
}: {
  type: "text" | "select";
  value: string;
  onChange: (v: string) => void;
  options?: { value: string; label: string }[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const isActive = value !== "";

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        className={`p-0.5 rounded transition-colors ${
          isActive
            ? "text-blue-400 hover:text-blue-300"
            : "text-gray-500 hover:text-gray-300"
        }`}
        title={isActive ? `Filtered: ${value}` : "Filter this column"}
      >
        <FilterIcon active={isActive} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-2 min-w-[140px]">
          {type === "text" ? (
            <input
              type="text"
              placeholder={placeholder ?? "Filter…"}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              autoFocus
              className="text-xs bg-gray-700 text-gray-200 border border-gray-600 rounded px-2 py-1.5 w-full focus:outline-none focus:ring-1 focus:ring-blue-500/50 placeholder-gray-500"
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpen(false);
                if (e.key === "Enter") setOpen(false);
              }}
            />
          ) : (
            <select
              value={value}
              onChange={(e) => {
                onChange(e.target.value);
                setOpen(false);
              }}
              autoFocus
              className="text-xs bg-gray-700 text-gray-200 border border-gray-600 rounded px-2 py-1.5 w-full focus:outline-none focus:ring-1 focus:ring-blue-500/50"
            >
              {options?.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          )}
          {isActive && (
            <button
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
              className="mt-1.5 text-[10px] text-gray-400 hover:text-white w-full text-center py-0.5 rounded hover:bg-gray-700 transition-colors"
            >
              Clear filter
            </button>
          )}
        </div>
      )}
    </div>
  );
}

interface ColumnFilters {
  flightSearch: string;
  typeFilter: string;
  destinationSearch: string;
  gateSearch: string;
  statusFilter: string;
  airlineFilter: string;
}

const EMPTY_FILTERS: ColumnFilters = {
  flightSearch: "",
  typeFilter: "",
  destinationSearch: "",
  gateSearch: "",
  statusFilter: "",
  airlineFilter: "",
};

function applyFilters(
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

function FIDSPanel({
  flights,
  direction,
  flashIds,
  onSelect,
}: {
  flights: Flight[];
  direction: "departure" | "arrival";
  flashIds: Set<string>;
  onSelect: (f: Flight) => void;
}) {
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<ColumnFilters>({ ...EMPTY_FILTERS });
  const PAGE_SIZE = 20;
  const { sort, toggle } = useSort<FlightSortCol>("time");

  // Build airline list from current flights
  const airlines = useMemo(() => {
    const codes = new Set(flights.map((f) => f.airline_code));
    return [...codes].sort();
  }, [flights]);

  const filtered = useMemo(
    () => applyFilters(flights, filters, direction),
    [flights, filters, direction],
  );

  const sorted = useMemo(() => {
    const list = [...filtered];
    // New flights (flashing) go to top, rest sorted normally
    list.sort((a, b) => {
      const aNew = flashIds.has(a.id) ? 1 : 0;
      const bNew = flashIds.has(b.id) ? 1 : 0;
      if (aNew !== bNew) return bNew - aNew; // flashing first
      return compare(
        flightSortValue(a, sort.column, direction),
        flightSortValue(b, sort.column, direction),
        sort.direction,
      );
    });
    return list;
  }, [filtered, sort, direction, flashIds]);

  const hasAnyFilter = Object.values(filters).some((v) => v !== "");

  // Reset page when filter changes
  useEffect(() => {
    setPage(0);
  }, [filters]);

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const pageFlights = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2.5 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-bold text-white uppercase tracking-wide">
            {direction === "departure" ? "✈ Departures" : "🛬 Arrivals"} (
            {filtered.length}
            {hasAnyFilter ? `/${flights.length}` : ""})
          </h3>
          {hasAnyFilter && (
            <button
              onClick={() => setFilters({ ...EMPTY_FILTERS })}
              className="text-[10px] text-gray-400 hover:text-white bg-gray-700 hover:bg-gray-600 rounded px-1.5 py-0.5 transition-colors"
              title="Clear all filters"
            >
              Clear filters
            </button>
          )}
        </div>
        {totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              className="text-gray-300 hover:text-white hover:bg-gray-700 disabled:opacity-30 px-2 py-1 rounded transition-colors"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              ‹
            </button>
            <span className="text-xs text-gray-300 font-medium px-2">
              {page + 1}/{totalPages}
            </span>
            <button
              className="text-gray-300 hover:text-white hover:bg-gray-700 disabled:opacity-30 px-2 py-1 rounded transition-colors"
              disabled={page >= totalPages - 1}
              onClick={() => setPage(page + 1)}
            >
              ›
            </button>
          </div>
        )}
      </div>
      <div className="overflow-y-auto flex-1">
        <table className="w-full text-left">
          <thead>
            <tr className="text-xs text-gray-400 uppercase tracking-wide border-b border-gray-700/50">
              <th
                className="px-3 py-2 cursor-pointer select-none hover:text-gray-200 transition-colors"
                onClick={() => toggle("flight_number")}
              >
                <span className="inline-flex items-center gap-1">
                  Flight <SortArrow column="flight_number" sort={sort} />
                  <ColumnFilterPopup
                    type="text"
                    value={filters.flightSearch}
                    onChange={(v) =>
                      setFilters({ ...filters, flightSearch: v })
                    }
                    placeholder="Flight #…"
                  />
                  <ColumnFilterPopup
                    type="select"
                    value={filters.airlineFilter}
                    onChange={(v) =>
                      setFilters({ ...filters, airlineFilter: v })
                    }
                    options={[
                      { value: "", label: "All airlines" },
                      ...airlines.map((a) => ({ value: a, label: a })),
                    ]}
                  />
                </span>
              </th>
              <th
                className="px-3 py-2 cursor-pointer select-none hover:text-gray-200 transition-colors"
                onClick={() => toggle("type")}
              >
                <span className="inline-flex items-center gap-1">
                  Type <SortArrow column="type" sort={sort} />
                  <ColumnFilterPopup
                    type="select"
                    value={filters.typeFilter}
                    onChange={(v) => setFilters({ ...filters, typeFilter: v })}
                    options={FLIGHT_TYPE_OPTIONS.map((o) => ({
                      value: o.value,
                      label: o.label,
                    }))}
                  />
                </span>
              </th>
              <th
                className="px-3 py-2 cursor-pointer select-none hover:text-gray-200 transition-colors"
                onClick={() => toggle("destination")}
              >
                <span className="inline-flex items-center gap-1">
                  {direction === "departure" ? "To" : "From"}{" "}
                  <SortArrow column="destination" sort={sort} />
                  <ColumnFilterPopup
                    type="text"
                    value={filters.destinationSearch}
                    onChange={(v) =>
                      setFilters({ ...filters, destinationSearch: v })
                    }
                    placeholder={
                      direction === "departure" ? "Dest…" : "Origin…"
                    }
                  />
                </span>
              </th>
              <th
                className="px-3 py-2 cursor-pointer select-none hover:text-gray-200 transition-colors"
                onClick={() => toggle("gate")}
              >
                <span className="inline-flex items-center gap-1">
                  Gate <SortArrow column="gate" sort={sort} />
                  <ColumnFilterPopup
                    type="text"
                    value={filters.gateSearch}
                    onChange={(v) => setFilters({ ...filters, gateSearch: v })}
                    placeholder="Gate…"
                  />
                </span>
              </th>
              <th
                className="px-3 py-2 cursor-pointer select-none hover:text-gray-200 transition-colors"
                onClick={() => toggle("time")}
              >
                Time <SortArrow column="time" sort={sort} />
              </th>
              <th
                className="px-3 py-2 cursor-pointer select-none hover:text-gray-200 transition-colors"
                onClick={() => toggle("status")}
              >
                <span className="inline-flex items-center gap-1">
                  Status <SortArrow column="status" sort={sort} />
                  <ColumnFilterPopup
                    type="select"
                    value={filters.statusFilter}
                    onChange={(v) =>
                      setFilters({ ...filters, statusFilter: v })
                    }
                    options={[
                      { value: "", label: "All" },
                      ...STATUS_OPTIONS.map((s) => ({ value: s, label: s })),
                    ]}
                  />
                </span>
              </th>
              <th className="px-3 py-2">Progress</th>
            </tr>
          </thead>
          <tbody>
            {pageFlights.map((f) => (
              <FlightRow
                key={f.id}
                flight={f}
                isFlashing={flashIds.has(f.id)}
                onClick={() => onSelect(f)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ──────── Flight Stats ──────── */
function FlightStats({ flights }: { flights: Flight[] }) {
  const stats = useMemo(() => {
    let delayed = 0,
      cancelled = 0,
      airborne = 0,
      boarding = 0,
      arrived = 0,
      completed = 0;
    const byType: Record<string, number> = {};
    for (const f of flights) {
      if (f.status === "delayed") delayed++;
      else if (f.status === "cancelled") cancelled++;
      else if (f.status === "airborne") airborne++;
      else if (f.status === "boarding") boarding++;
      else if (f.status === "arrived" && f.direction === "departure") completed++;
      else if (f.status === "arrived") arrived++;
      const ft = f.flight_type ?? "unknown";
      byType[ft] = (byType[ft] ?? 0) + 1;
    }
    return {
      delayed,
      cancelled,
      airborne,
      boarding,
      arrived,
      completed,
      total: flights.length,
      byType,
    };
  }, [flights]);

  return (
    <div className="space-y-2">
      <div className="flex gap-3 text-sm flex-wrap">
        <StatPill label="Total" value={stats.total} />
        <StatPill
          label="Boarding"
          value={stats.boarding}
          color="text-green-400"
        />
        <StatPill
          label="Airborne"
          value={stats.airborne}
          color="text-blue-400"
        />
        <StatPill
          label="Arrived"
          value={stats.arrived}
          color="text-emerald-400"
        />
        <StatPill
          label="Completed"
          value={stats.completed}
          color="text-indigo-400"
        />
        <StatPill
          label="Delayed"
          value={stats.delayed}
          color="text-amber-400"
        />
        <StatPill
          label="Cancelled"
          value={stats.cancelled}
          color="text-red-400"
        />
        <div className="border-l border-gray-700 mx-1" />
        {Object.entries(stats.byType)
          .sort((a, b) => b[1] - a[1])
          .map(([type, count]) => {
            const style = FLIGHT_TYPE_STYLES[type];
            return (
              <StatPill
                key={type}
                label={style?.label ?? type}
                value={count}
                color="text-gray-300"
              />
            );
          })}
      </div>
    </div>
  );
}

function StatPill({
  label,
  value,
  color = "text-gray-200",
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <div className="bg-gray-800/80 rounded-lg px-3 py-1.5 border border-gray-700/50">
      <div className="text-xs text-gray-400 font-medium">{label}</div>
      <div className={`font-bold text-lg ${color}`}>{value}</div>
    </div>
  );
}

/* ──────── Critical Incident Banner ──────── */
function CriticalBanner() {
  const incidents = useIncidentStore((s) => s.incidents);
  const critical = Object.values(incidents).find(
    (i) => i.severity === "critical" && i.status === "active",
  );
  if (!critical) return null;

  return (
    <div className="bg-red-900/80 border border-red-600 text-white px-4 py-2 text-sm font-bold animate-pulse">
      ⚠ CRITICAL: {critical.title} — {critical.location}
    </div>
  );
}

/* ──────── Main Page ──────── */
export default function FlightBoardPage() {
  const flights = useFlightStore((s) => s.flights);
  const runways = useFlightStore((s) => s.runways);
  const flashIds = useFlightStore((s) => s.flashIds);
  const setFlights = useFlightStore((s) => s.setFlights);
  const setRunways = useFlightStore((s) => s.setRunways);
  const setCurrent = useWeatherStore((s) => s.setCurrent);
  const [selectedFlight, setSelectedFlight] = useState<Flight | null>(null);
  const [bottomExpanded, setBottomExpanded] = useState(true);

  const queries = useFlightBoardQueries();

  useEffect(() => {
    if (queries.flights.data) setFlights(queries.flights.data);
  }, [queries.flights.data, setFlights]);

  useEffect(() => {
    if (queries.runways.data) setRunways(queries.runways.data);
  }, [queries.runways.data, setRunways]);

  useEffect(() => {
    if (queries.weather.data) setCurrent(queries.weather.data as WeatherState);
  }, [queries.weather.data, setCurrent]);

  const flightList = Object.values(flights);
  const departures = useMemo(
    () => flightList.filter((f) => f.direction === "departure"),
    [flightList],
  );
  const arrivals = useMemo(
    () => flightList.filter((f) => f.direction === "arrival"),
    [flightList],
  );

  const handleSelect = useCallback((f: Flight) => setSelectedFlight(f), []);

  const handleExport = useCallback(
    (format: ExportFormat) => {
      const rows = flightList.map((f) => ({
        flight_number: f.flight_number,
        airline: f.airline_code,
        direction: f.direction,
        origin: f.origin_iata,
        destination: f.destination_iata,
        gate: f.gate_id ?? "",
        terminal: f.terminal,
        status: f.status,
        scheduled_time: f.scheduled_time,
        estimated_time: f.estimated_time ?? "",
        delay_minutes: f.delay_minutes,
        pax_count: f.pax_count,
        pax_boarded: f.pax_boarded,
        flight_duration_minutes: f.flight_duration_minutes ?? "",
        arrival_estimated_time: f.arrival_estimated_time ?? "",
      }));
      exportData(rows, "flights", format);
    },
    [flightList],
  );

  return (
    <div className="flex flex-col h-full">
      <CriticalBanner />

      {/* FIDS panels */}
      <div className="flex-1 grid grid-cols-2 gap-px bg-gray-700 min-h-0">
        <div className="bg-gray-900 overflow-hidden">
          <FIDSPanel
            flights={departures}
            direction="departure"
            flashIds={flashIds}
            onSelect={handleSelect}
          />
        </div>
        <div className="bg-gray-900 overflow-hidden">
          <FIDSPanel
            flights={arrivals}
            direction="arrival"
            flashIds={flashIds}
            onSelect={handleSelect}
          />
        </div>
      </div>

      {/* Bottom bar — collapsible */}
      <div className="bg-gray-800 border-t border-gray-700/80">
        <div className="flex items-center justify-between px-3 py-2">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setBottomExpanded(!bottomExpanded)}
              className="text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-gray-700"
              title={
                bottomExpanded ? "Collapse stats panel" : "Expand stats panel"
              }
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`transform transition-transform duration-200 ${bottomExpanded ? "rotate-180" : ""}`}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
            <span className="text-xs text-gray-400 font-medium uppercase tracking-wide">
              Stats &amp; Runways
            </span>
          </div>
          <ExportMenu onExport={handleExport} />
        </div>
        {bottomExpanded && (
          <div className="px-3 pb-3 space-y-3">
            <FlightStats flights={flightList} />
            {runways.length > 0 && (
              <div className="grid grid-cols-2 gap-3">
                <RunwayStatusBar runways={runways} />
                <RunwayThroughputChart runways={runways} />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Detail drawer */}
      {selectedFlight && (
        <>
          <div
            className="fixed inset-0 bg-black/40 z-40"
            onClick={() => setSelectedFlight(null)}
          />
          <FlightDetailDrawer
            flight={selectedFlight}
            onClose={() => setSelectedFlight(null)}
          />
        </>
      )}
    </div>
  );
}

/* ──────── util ──────── */
function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCHours().toString().padStart(2, "0")}:${d.getUTCMinutes().toString().padStart(2, "0")}`;
}
