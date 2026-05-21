import { useEffect, useMemo } from "react";
import { useFlightStore } from "../../stores/flightStore";
import { useWeatherStore } from "../../stores/weatherStore";
import { useIncidentStore } from "../../stores/incidentStore";
import {
  useGroundOpsQueries,
  useADSBQuery,
  useGroundVehiclesQuery,
} from "../../hooks/useQueries";
import { LoadingState, ErrorState } from "../../components/LoadingState";
import { WeatherHistoryChart } from "../Debug/DebugPage";
import { TerminalBlock, RunwayStripSVG } from "./AirfieldComponents";
import {
  HoldingStackPanel,
  GroundStopPanel,
  RunwayQueuePanel,
} from "./StatusPanels";
import { WeatherSidePanel } from "./WeatherSidePanel";
import { TurnaroundPanel } from "./TurnaroundPanel";
import { TerminalActivityPanel } from "./TerminalActivityPanel";
import { NearbyFlightsPanel } from "./NearbyFlightsPanel";
import {
  GroundVehicleStatusPanel,
  GroundVehicleOverlay,
  VehiclePositionTable,
} from "./GroundVehicles";
import type {
  Gate,
  WeatherState,
  ADSBFeatureCollection,
  GroundVehicleSummary,
} from "../../types";

/* ──────── Main Page ──────── */
export default function GroundOpsPage() {
  const flights = useFlightStore((s) => s.flights);
  const runways = useFlightStore((s) => s.runways);
  const gates = useFlightStore((s) => s.gates);
  const weather = useWeatherStore((s) => s.current);
  const incidents = useIncidentStore((s) => s.incidents);
  const setFlights = useFlightStore((s) => s.setFlights);
  const setRunways = useFlightStore((s) => s.setRunways);
  const setGates = useFlightStore((s) => s.setGates);
  const setCurrent = useWeatherStore((s) => s.setCurrent);
  const setIncidents = useIncidentStore((s) => s.setIncidents);

  const queries = useGroundOpsQueries();
  const adsbQuery = useADSBQuery(true);
  const vehiclesQuery = useGroundVehiclesQuery();

  useEffect(() => {
    if (queries.runways.data) setRunways(queries.runways.data);
  }, [queries.runways.data, setRunways]);

  useEffect(() => {
    if (queries.gates.data) setGates(queries.gates.data);
  }, [queries.gates.data, setGates]);

  useEffect(() => {
    if (queries.flights.data) setFlights(queries.flights.data);
  }, [queries.flights.data, setFlights]);

  useEffect(() => {
    if (queries.weather.data) setCurrent(queries.weather.data as WeatherState);
  }, [queries.weather.data, setCurrent]);

  useEffect(() => {
    if (queries.incidents.data) setIncidents(queries.incidents.data);
  }, [queries.incidents.data, setIncidents]);

  const flightList = useMemo(() => Object.values(flights), [flights]);
  const activeIncidents = useMemo(
    () => Object.values(incidents).filter((i) => i.status !== "resolved"),
    [incidents],
  );

  const runwayIncidents = useMemo(
    () =>
      new Set(
        activeIncidents
          .filter((i) => i.type === "runway_incursion")
          .map((i) => i.location.replace("runway-", "")),
      ),
    [activeIncidents],
  );

  // Group gates by terminal
  const gatesByTerminal = useMemo(() => {
    const m: Record<string, Gate[]> = { A: [], B: [], C: [] };
    for (const g of gates) {
      // terminal_id from backend is "T-A"/"T-B"/"T-C"; normalize to single letter
      const raw = g.terminal || g.gate_id.charAt(0);
      const term = raw.replace(/^T-/, "");
      (m[term] ??= []).push(g);
    }
    return m;
  }, [gates]);

  const isLoading =
    queries.flights.isLoading && Object.keys(flights).length === 0;
  const hasError = queries.flights.isError && Object.keys(flights).length === 0;

  if (isLoading) return <LoadingState message="Loading ground operations…" />;
  if (hasError)
    return (
      <ErrorState
        message="Failed to load ground ops data"
        onRetry={() => queries.flights.refetch()}
      />
    );

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <h2 className="text-lg font-bold text-white">Ground Operations — KART</h2>

      <div className="grid grid-cols-4 gap-4">
        {/* Airfield schematic (3 cols) */}
        <div className="col-span-3">
          <div className="bg-gray-900 rounded-lg p-4 relative">
            <svg viewBox="0 0 560 330" className="w-full h-auto">
              {/* Background */}
              <rect width={560} height={330} rx={8} className="fill-gray-900" />

              {/* Terminal blocks */}
              <TerminalBlock
                terminal="A"
                gates={gatesByTerminal["A"] ?? []}
                x={40}
                y={20}
              />
              <TerminalBlock
                terminal="B"
                gates={gatesByTerminal["B"] ?? []}
                x={40}
                y={70}
              />
              <TerminalBlock
                terminal="C"
                gates={gatesByTerminal["C"] ?? []}
                x={40}
                y={120}
              />

              {/* Runway strips */}
              {runways.length > 0 ? (
                <>
                  <RunwayStripSVG
                    runway={runways[0]}
                    y={190}
                    flights={flightList}
                    hasIncident={runwayIncidents.has(runways[0].runway_id)}
                  />
                  {runways.length > 1 && (
                    <RunwayStripSVG
                      runway={runways[1]}
                      y={240}
                      flights={flightList}
                      hasIncident={runwayIncidents.has(runways[1].runway_id)}
                    />
                  )}
                </>
              ) : (
                <>
                  <g transform="translate(30, 190)">
                    <rect
                      width={500}
                      height={30}
                      rx={2}
                      className="fill-gray-700/50"
                    />
                    <text
                      x={250}
                      y={20}
                      textAnchor="middle"
                      className="fill-gray-500 text-[9px]"
                    >
                      Runway 09L/27R
                    </text>
                  </g>
                  <g transform="translate(30, 240)">
                    <rect
                      width={500}
                      height={30}
                      rx={2}
                      className="fill-gray-700/50"
                    />
                    <text
                      x={250}
                      y={20}
                      textAnchor="middle"
                      className="fill-gray-500 text-[9px]"
                    >
                      Runway 09R/27L
                    </text>
                  </g>
                </>
              )}

              {/* Holding stack visual */}
              {flightList.filter((f) => f.status === "approach").length > 0 && (
                <g transform="translate(500, 20)">
                  <text x={0} y={10} className="fill-gray-400 text-[8px]">
                    HOLD
                  </text>
                  {flightList
                    .filter((f) => f.status === "approach")
                    .slice(0, 5)
                    .map((f, i) => (
                      <g key={f.id} transform={`translate(0, ${18 + i * 18})`}>
                        <circle
                          cx={15}
                          cy={6}
                          r={5}
                          className="fill-teal-600/40 stroke-teal-400"
                          strokeWidth={0.5}
                        >
                          <animateTransform
                            attributeName="transform"
                            type="rotate"
                            values="0 15 6;360 15 6"
                            dur={`${3 + i}s`}
                            repeatCount="indefinite"
                          />
                        </circle>
                        <text x={25} y={9} className="fill-white text-[7px]">
                          {f.flight_number}
                        </text>
                      </g>
                    ))}
                </g>
              )}
            </svg>

            {/* Ground vehicle overlay on schematic */}
            {vehiclesQuery.data && (
              <GroundVehicleOverlay vehicles={vehiclesQuery.data.vehicles} />
            )}
          </div>
        </div>

        {/* Weather side panel (1 col) */}
        <div className="space-y-4">
          <WeatherSidePanel weather={weather} />
          <GroundVehicleStatusPanel
            data={vehiclesQuery.data as GroundVehicleSummary | undefined}
          />
        </div>
      </div>

      {/* Weather history sparkline */}
      <WeatherHistoryChart />

      {/* Bottom bar */}
      <div className="grid grid-cols-5 gap-4">
        <HoldingStackPanel flights={flightList} />
        <GroundStopPanel incidents={activeIncidents} />
        <RunwayQueuePanel runways={runways} flights={flightList} />
        <TurnaroundPanel />
        <NearbyFlightsPanel
          data={adsbQuery.data as ADSBFeatureCollection | undefined}
        />
      </div>

      {/* Terminal Activity — flight/passenger/baggage links */}
      <TerminalActivityPanel
        terminals={["A", "B", "C"]}
        gates={gates}
        flights={flightList}
      />

      {/* Vehicle Position Tracker */}
      {vehiclesQuery.data && vehiclesQuery.data.vehicles.length > 0 && (
        <VehiclePositionTable vehicles={vehiclesQuery.data.vehicles} />
      )}
    </div>
  );
}
