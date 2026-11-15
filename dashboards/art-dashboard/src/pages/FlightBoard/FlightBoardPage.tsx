import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { flightsApi } from "../../hooks/useApi";
import { normalizeTerminal } from "../Airport3D/model";
import { useSimStore } from "../../stores/simStore";
import { STATUS_OPTIONS } from "./constants";
import { useFlightStore } from "../../stores/flightStore";
import { useFlightBoardQueries } from "../../hooks/useQueries";
import { useWeatherStore } from "../../stores/weatherStore";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import type { ExportFormat } from "../../utils/exportData";
import type { Flight, WeatherState } from "../../types";
import { CriticalBanner } from "./CriticalBanner";
import { FIDSPanel } from "./FIDSPanel";
import { FlightStats } from "./FlightStats";
import { FlightDetailDrawer } from "./FlightDetailDrawer";
import { RunwayStatusBar } from "./RunwayStatusBar";
import { RunwayThroughputChart } from "./RunwayThroughputChart";

/* ──────── Main Page ──────── */
export default function FlightBoardPage() {
  const flights = useFlightStore((s) => s.flights);
  const runways = useFlightStore((s) => s.runways);
  const flashIds = useFlightStore((s) => s.flashIds);
  const setFlights = useFlightStore((s) => s.setFlights);
  const setRunways = useFlightStore((s) => s.setRunways);
  const setCurrent = useWeatherStore((s) => s.setCurrent);
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("flight");
  const [bottomExpanded, setBottomExpanded] = useState(false);
  const simTime = useSimStore((s) => s.status.sim_time);
  const detail = useQuery({
    queryKey: ["flights", "detail", selectedId],
    queryFn: () => flightsApi.get(selectedId!) as Promise<Flight>,
    enabled: !!selectedId,
    refetchInterval: 30000,
  });
  useEffect(() => {
    if (detail.data) useFlightStore.getState().upsertFlight(detail.data);
  }, [detail.data]);
  const selectedFlight = selectedId ? flights[selectedId] : undefined;
  const layout = params.get("layout") ?? "all";
  const view = params.get("view") ?? "all";
  function patch(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("page");
    next.delete("departure_page");
    next.delete("arrival_page");
    setParams(next, { replace: true });
  }
  function select(flight: Flight) {
    patch("flight", flight.id);
  }

  const queries = useFlightBoardQueries();

  useEffect(() => {
    if (queries.flights.data) {
      const current = selectedId
        ? useFlightStore.getState().flights[selectedId]
        : undefined;
      setFlights(
        current && !queries.flights.data.some((f) => f.id === current.id)
          ? [...queries.flights.data, current]
          : queries.flights.data,
      );
    }
  }, [queries.flights.data, setFlights]);

  useEffect(() => {
    if (queries.runways.data) setRunways(queries.runways.data);
  }, [queries.runways.data, setRunways]);

  useEffect(() => {
    if (queries.weather.data) setCurrent(queries.weather.data as WeatherState);
  }, [queries.weather.data, setCurrent]);

  const isLoading =
    queries.flights.isLoading && Object.keys(flights).length === 0;
  const hasError = queries.flights.isError && Object.keys(flights).length === 0;

  const flightList = Object.values(flights);
  const filtered = flightList.filter((f) => {
    const q = (params.get("q") ?? "").toLowerCase();
    if (
      q &&
      !`${f.flight_number} ${f.origin_iata} ${f.destination_iata} ${f.gate_id ?? ""}`
        .toLowerCase()
        .includes(q)
    )
      return false;
    if (
      params.get("terminal") &&
      params.get("terminal") !== "all" &&
      normalizeTerminal(f.terminal || f.gate_id?.[0] || "") !==
        params.get("terminal")
    )
      return false;
    if (params.get("status") && f.status !== params.get("status")) return false;
    if (
      view === "delayed" &&
      (f.delay_minutes <= 15 ||
        ["completed", "arrived", "cancelled", "diverted"].includes(f.status))
    )
      return false;
    if (
      view === "soon" &&
      (f.direction !== "departure" ||
        Date.parse(f.estimated_time || f.scheduled_time) <
          Date.parse(simTime) ||
        Date.parse(f.estimated_time || f.scheduled_time) >
          Date.parse(simTime) + 3600000)
    )
      return false;
    return true;
  });
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
    <div className="page-container space-y-4">
      <header className="flex flex-wrap justify-between gap-3">
        <div>
          <h1>Flights</h1>
          <p className="text-sm text-gray-400 mt-1">
            Current movements · times in UTC · up to 500 loaded records
          </p>
        </div>
        <ExportMenu onExport={handleExport} />
      </header>
      <div className="flex flex-wrap gap-3 items-end">
        <label className="text-xs text-gray-400">
          Search
          <input
            aria-label="Search flights"
            value={params.get("q") ?? ""}
            onChange={(e) => patch("q", e.target.value)}
            placeholder="Flight, route or gate"
            className="block mt-1"
          />
        </label>
        <label className="text-xs text-gray-400">
          Terminal
          <select
            className="block mt-1"
            value={params.get("terminal") ?? "all"}
            onChange={(e) => patch("terminal", e.target.value)}
          >
            <option value="all">All terminals</option>
            {["A", "B", "C"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Status
          <select
            className="block mt-1"
            value={params.get("status") ?? ""}
            onChange={(e) => patch("status", e.target.value)}
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Saved view
          <select
            className="block mt-1"
            value={view}
            onChange={(e) => patch("view", e.target.value)}
          >
            <option value="all">All movements</option>
            <option value="delayed">Delayed &gt;15 min</option>
            <option value="soon">Departing in next hour</option>
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Layout
          <select
            className="block mt-1"
            value={layout}
            onChange={(e) => patch("layout", e.target.value)}
          >
            <option value="all">All flights</option>
            <option value="departure">Departures</option>
            <option value="arrival">Arrivals</option>
            <option value="split">Split board</option>
          </select>
        </label>
      </div>
      <CriticalBanner />

      {isLoading && (
        <div className="flex items-center justify-center flex-1 text-gray-400">
          <div className="flex flex-col items-center gap-2">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
            <span>Loading flight data…</span>
          </div>
        </div>
      )}

      {hasError && (
        <div className="flex items-center justify-center flex-1 text-gray-400">
          <div className="flex flex-col items-center gap-2 text-center">
            <span className="text-red-400 text-lg">
              ⚠️ Failed to load flight data
            </span>
            <span className="text-sm text-gray-500">
              The flight-service may not be running. Check that the simulation
              is active.
            </span>
            <button
              onClick={() => queries.flights.refetch()}
              className="mt-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {!isLoading && !hasError && (
        <>
          <div
            className={
              layout === "split" ? "grid grid-cols-1 2xl:grid-cols-2 gap-5" : ""
            }
          >
            {layout === "split" ? (
              (["departure", "arrival"] as const).map((direction) => (
                <FIDSPanel
                  key={direction}
                  flights={filtered.filter((f) => f.direction === direction)}
                  direction={direction}
                  flashIds={flashIds}
                  onSelect={select}
                />
              ))
            ) : (
              <FIDSPanel
                flights={
                  layout === "departure" || layout === "arrival"
                    ? filtered.filter((f) => f.direction === layout)
                    : filtered
                }
                direction={
                  layout === "departure" || layout === "arrival"
                    ? layout
                    : "all"
                }
                flashIds={flashIds}
                onSelect={select}
              />
            )}
          </div>
          {/* Bottom bar — collapsible */}
          <div className="bg-gray-800 border-t border-gray-700/80">
            <div className="flex items-center justify-between px-3 py-2">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setBottomExpanded(!bottomExpanded)}
                  className="text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-gray-700"
                  title={
                    bottomExpanded
                      ? "Collapse stats panel"
                      : "Expand stats panel"
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

          {selectedId && detail.isError && !selectedFlight && (
            <p role="alert" className="card">
              Selected flight unavailable.{" "}
              <button onClick={() => detail.refetch()}>Retry</button>
            </p>
          )}
          {/* Detail drawer */}
          {selectedFlight && (
            <>
              <FlightDetailDrawer
                flight={selectedFlight}
                onClose={() => patch("flight", "")}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
