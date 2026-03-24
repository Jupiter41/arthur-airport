import { useState, useEffect, useMemo } from "react";
import { useFlightStore } from "../../stores/flightStore";
import { useWeatherStore } from "../../stores/weatherStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { flightsApi, weatherApi, incidentsApi } from "../../hooks/useApi";
import { StatusBadge } from "../../components/StatusBadge";
import type { Flight, Runway, Gate, WeatherState, Incident } from "../../types";

/* ──────── Gate Cell ──────── */
function GateCell({ gate }: { gate: Gate }) {
  const gateColors: Record<string, string> = {
    available: "fill-gray-700",
    occupied: "fill-blue-800",
    boarding: "fill-green-700",
    departing: "fill-green-600",
    delayed: "fill-amber-700",
    incident: "fill-red-700",
    maintenance: "fill-gray-600",
  };

  return (
    <g>
      <rect
        width={28}
        height={22}
        rx={3}
        className={`${gateColors[gate.status] ?? "fill-gray-700"} transition-all duration-500`}
      />
      <text
        x={14}
        y={12}
        textAnchor="middle"
        className="fill-white text-[7px] font-bold"
      >
        {gate.gate_id}
      </text>
      {gate.flight_number && (
        <text
          x={14}
          y={20}
          textAnchor="middle"
          className="fill-gray-300 text-[5px]"
        >
          {gate.flight_number}
        </text>
      )}
    </g>
  );
}

/* ──────── Terminal Block ──────── */
function TerminalBlock({
  terminal,
  gates,
  x,
  y,
}: {
  terminal: string;
  gates: Gate[];
  x: number;
  y: number;
}) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect
        width={440}
        height={40}
        rx={4}
        className="fill-gray-800/80 stroke-gray-600"
        strokeWidth={0.5}
      />
      <text x={10} y={15} className="fill-gray-400 text-[9px] font-bold">
        Terminal {terminal}
      </text>
      {gates.slice(0, 14).map((g, i) => (
        <g key={g.gate_id} transform={`translate(${10 + i * 30}, 18)`}>
          <GateCell gate={g} />
        </g>
      ))}
    </g>
  );
}

/* ──────── Runway Strip ──────── */
function RunwayStripSVG({
  runway,
  y,
  flights,
  hasIncident,
}: {
  runway: Runway;
  y: number;
  flights: Flight[];
  hasIncident: boolean;
}) {
  const bgColor = hasIncident
    ? "fill-red-900/60"
    : runway.status === "restricted"
      ? "fill-amber-900/30"
      : "fill-gray-700/50";

  const activeFlights = flights.filter(
    (f) =>
      f.runway_id === runway.runway_id &&
      ["approach", "landed", "taxiing", "departed", "airborne"].includes(
        f.status,
      ),
  );

  return (
    <g transform={`translate(30, ${y})`}>
      {/* Runway background */}
      <rect width={500} height={30} rx={2} className={bgColor} />
      {/* Runway markings */}
      <line
        x1={20}
        y1={15}
        x2={480}
        y2={15}
        stroke="#6b7280"
        strokeWidth={1}
        strokeDasharray="8 4"
      />
      {/* Runway ID */}
      <text x={5} y={20} className="fill-white text-[10px] font-bold">
        {runway.runway_id}
      </text>
      <text x={460} y={20} className="fill-gray-400 text-[8px]">
        {runway.status === "open" ? "OPEN" : runway.status?.toUpperCase()}
      </text>

      {/* Aircraft arrows */}
      {activeFlights.slice(0, 4).map((f, i) => {
        const xPos = 80 + i * 100;
        const isLanding = ["approach", "landed"].includes(f.status);
        return (
          <g key={f.id} transform={`translate(${xPos}, 5)`}>
            <polygon
              points={isLanding ? "20,10 0,5 0,15" : "0,10 20,5 20,15"}
              className={isLanding ? "fill-teal-400" : "fill-blue-400"}
            >
              <animateTransform
                attributeName="transform"
                type="translate"
                values={isLanding ? "10,0;-5,0;10,0" : "-5,0;10,0;-5,0"}
                dur="3s"
                repeatCount="indefinite"
              />
            </polygon>
            <text
              x={10}
              y={25}
              textAnchor="middle"
              className="fill-white text-[7px] font-bold"
            >
              {f.flight_number}
            </text>
          </g>
        );
      })}

      {/* Incident overlay */}
      {hasIncident && (
        <>
          <rect width={500} height={30} rx={2} className="fill-red-600/20" />
          <text
            x={250}
            y={12}
            textAnchor="middle"
            className="fill-red-400 text-[9px] font-bold"
          >
            ⚠ INCURSION
          </text>
        </>
      )}
    </g>
  );
}

/* ──────── Holding Stack ──────── */
function HoldingStackPanel({ flights }: { flights: Flight[] }) {
  const holding = flights.filter((f) => f.status === "approach");

  if (holding.length === 0) return null;

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Holding Stack ({holding.length})
      </h3>
      <div className="space-y-1">
        {holding.slice(0, 8).map((f) => (
          <div
            key={f.id}
            className="flex items-center justify-between text-sm bg-gray-700 rounded px-2 py-1"
          >
            <span className="font-bold text-white">{f.flight_number}</span>
            <span className="text-xs text-gray-400">
              {f.delay_minutes > 0 ? `+${f.delay_minutes}min` : "on time"}
            </span>
            <StatusBadge status={f.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Ground Stop Panel ──────── */
function GroundStopPanel({ incidents }: { incidents: Incident[] }) {
  const groundStop = incidents.some(
    (i) => i.type === "runway_incursion" && i.status !== "resolved",
  );

  return (
    <div
      className={`rounded p-3 ${groundStop ? "bg-red-900/50 border border-red-700" : "bg-gray-800"}`}
    >
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-1">
        Ground Stop
      </h3>
      {groundStop ? (
        <div className="text-sm text-red-400 font-bold animate-pulse">
          ⛔ GROUND STOP — Departures suspended
        </div>
      ) : (
        <div className="text-sm text-green-400">NORMAL — Departures active</div>
      )}
    </div>
  );
}

/* ──────── Runway Queue Panel ──────── */
function RunwayQueuePanel({
  runways,
  flights,
}: {
  runways: Runway[];
  flights: Flight[];
}) {
  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Runway Queues
      </h3>
      <div className="space-y-2">
        {runways.map((rw) => {
          const queued = flights.filter(
            (f) =>
              f.runway_id === rw.runway_id &&
              ["taxiing", "departed"].includes(f.status),
          );
          return (
            <div key={rw.runway_id} className="text-xs">
              <span className="font-mono font-bold text-white">
                {rw.runway_id}
              </span>
              <span className="text-gray-400 ml-2">
                Arr: {rw.arrivals_queued} · Dep: {rw.departures_queued}
              </span>
              {queued.length > 0 && (
                <span className="text-gray-500 ml-2">
                  {queued.map((f) => f.flight_number).join(" · ")}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ──────── Weather Side Panel ──────── */
function WeatherSidePanel({ weather }: { weather: WeatherState | null }) {
  if (!weather) return null;

  const catColors: Record<string, string> = {
    CAVOK: "bg-green-600",
    VMC: "bg-teal-600",
    IMC: "bg-amber-600",
    LIFR: "bg-red-600",
  };

  const windDir = weather.wind_direction_deg;

  return (
    <div className="bg-gray-800 rounded p-3 space-y-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">Weather</h3>

      {/* Category badge */}
      <div className="flex justify-center">
        <span
          className={`${catColors[weather.category] ?? "bg-gray-600"} text-white text-lg font-bold px-4 py-2 rounded`}
        >
          {weather.category}
        </span>
      </div>

      {/* METAR */}
      <div className="font-mono text-[10px] text-gray-300 bg-gray-900 rounded p-2 break-all">
        {weather.metar_raw}
      </div>

      {/* Wind compass */}
      <div className="flex justify-center">
        <svg width={80} height={80} viewBox="0 0 80 80">
          <circle
            cx={40}
            cy={40}
            r={35}
            className="fill-none stroke-gray-600"
            strokeWidth={1}
          />
          <text
            x={40}
            y={10}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            N
          </text>
          <text
            x={72}
            y={43}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            E
          </text>
          <text
            x={40}
            y={76}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            S
          </text>
          <text
            x={8}
            y={43}
            textAnchor="middle"
            className="fill-gray-500 text-[8px]"
          >
            W
          </text>
          {/* Wind arrow */}
          <g transform={`rotate(${windDir}, 40, 40)`}>
            <line
              x1={40}
              y1={40}
              x2={40}
              y2={12}
              className="stroke-cyan-400"
              strokeWidth={2}
            />
            <polygon points="40,8 36,16 44,16" className="fill-cyan-400" />
          </g>
          <text
            x={40}
            y={44}
            textAnchor="middle"
            className="fill-white text-[9px] font-bold"
          >
            {weather.wind_speed_kt}kt
          </text>
        </svg>
      </div>

      {/* Impact */}
      <div className="text-xs text-gray-300 space-y-1">
        <div className="flex justify-between">
          <span>Arrival rate</span>
          <span className="text-white font-bold">
            {weather.arrival_rate}/hr
          </span>
        </div>
        <div className="flex justify-between">
          <span>Departure rate</span>
          <span className="text-white font-bold">
            {weather.departure_rate}/hr
          </span>
        </div>
      </div>
    </div>
  );
}

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

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [rwData, gateData, flData, wxData, incData] = await Promise.all([
          flightsApi.runways(),
          flightsApi.gates(),
          flightsApi.list({
            status: "approach,taxiing,boarding,at_gate,departed",
            limit: "200",
          }),
          weatherApi.current(),
          incidentsApi.list({ status: "active,contained" }),
        ]);
        if (cancelled) {
          return;
        }
        setRunways(rwData as Runway[]);
        const gd = gateData as { gates?: Gate[] };
        setGates(gd.gates ?? (Array.isArray(gateData) ? (gateData as Gate[]) : []));
        const fd = flData as { flights: Flight[] };
        setFlights(fd.flights ?? []);
        setCurrent(wxData as WeatherState);
        const id = incData as { incidents: Incident[] };
        setIncidents(id.incidents ?? []);
      } catch {
        // Keep existing state and retry on next interval tick.
      }
    };

    void load();
    const interval = setInterval(() => {
      void load();
    }, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setRunways, setGates, setFlights, setCurrent, setIncidents]);

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
      const term = g.terminal || g.gate_id.charAt(0);
      (m[term] ??= []).push(g);
    }
    return m;
  }, [gates]);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <h2 className="text-lg font-bold text-white">Ground Operations — KART</h2>

      <div className="grid grid-cols-4 gap-4">
        {/* Airfield schematic (3 cols) */}
        <div className="col-span-3">
          <div className="bg-gray-900 rounded-lg p-4">
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
          </div>
        </div>

        {/* Weather side panel (1 col) */}
        <div>
          <WeatherSidePanel weather={weather} />
        </div>
      </div>

      {/* Bottom bar */}
      <div className="grid grid-cols-3 gap-4">
        <HoldingStackPanel flights={flightList} />
        <GroundStopPanel incidents={activeIncidents} />
        <RunwayQueuePanel runways={runways} flights={flightList} />
      </div>
    </div>
  );
}
