import { useState, useMemo, useEffect } from "react";
import type { Flight } from "../../types";
import { useSort, compare, SortArrow } from "../../hooks/useSort";
import type { FlightSortCol, ColumnFilters } from "./constants";
import { FLIGHT_TYPE_OPTIONS, STATUS_OPTIONS, EMPTY_FILTERS } from "./constants";
import { flightSortValue, applyFilters } from "./helpers";
import { FlightRow } from "./FlightRow";
import { ColumnFilterPopup } from "./ColumnFilterPopup";

export function FIDSPanel({
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
    list.sort((a, b) => {
      const aNew = flashIds.has(a.id) ? 1 : 0;
      const bNew = flashIds.has(b.id) ? 1 : 0;
      if (aNew !== bNew) return bNew - aNew;
      return compare(
        flightSortValue(a, sort.column, direction),
        flightSortValue(b, sort.column, direction),
        sort.direction,
      );
    });
    return list;
  }, [filtered, sort, direction, flashIds]);

  const hasAnyFilter = Object.values(filters).some((v) => v !== "");

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
            {pageFlights.length === 0 && (
              <tr>
                <td colSpan={7} className="text-center text-gray-500 py-8 text-sm">
                  {hasAnyFilter ? "No flights match current filters" : "No flights scheduled"}
                </td>
              </tr>
            )}
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
