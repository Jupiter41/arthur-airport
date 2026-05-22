import { useState, useEffect, useMemo, useCallback } from "react";
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

  const isLoading = queries.flights.isLoading && Object.keys(flights).length === 0;
  const hasError = queries.flights.isError && Object.keys(flights).length === 0;

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
            <span className="text-red-400 text-lg">⚠️ Failed to load flight data</span>
            <span className="text-sm text-gray-500">
              The flight-service may not be running. Check that the simulation is active.
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
      </>
      )}
    </div>
  );
}
