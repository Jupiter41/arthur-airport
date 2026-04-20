import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useFlightStore } from "../../stores/flightStore";
import { useWeatherStore } from "../../stores/weatherStore";
import { useIncidentStore } from "../../stores/incidentStore";
import {
  useGroundOpsQueries,
  useADSBQuery,
  useGroundVehiclesQuery,
} from "../../hooks/useQueries";
import { StatusBadge } from "../../components/StatusBadge";
import { flightsApi } from "../../hooks/useApi";
import { WeatherHistoryChart } from "../Debug/DebugPage";
import type {
  Flight,
  Runway,
  Gate,
  WeatherState,
  Incident,
  ADSBFeatureCollection,
  GroundVehicleSummary,
} from "../../types";

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
                <span className="text-gray-400 ml-2">
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

/* ──────── Turnaround Panel ──────── */
interface TurnaroundTask {
  name: string;
  status: string;
  duration_min: number;
  started_at: string | null;
  completed_at: string | null;
}

interface TurnaroundPlan {
  aircraft_registration: string;
  arrival_flight_id: string;
  paired_departure_id: string | null;
  aircraft_type: string;
  is_complete: boolean;
  ready_for_boarding: boolean;
  critical_path_minutes: number;
  tasks: TurnaroundTask[];
}

function TurnaroundPanel() {
  const turnaroundsQuery = useQuery({
    queryKey: ["turnarounds"],
    queryFn: () => flightsApi.turnarounds(),
    refetchInterval: 5_000,
  });

  const plans = (turnaroundsQuery.data?.turnarounds ?? []) as TurnaroundPlan[];
  const active = plans.filter((p) => !p.is_complete);

  if (active.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-3">
        <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          Active Turnarounds
        </h3>
        <div className="text-xs text-gray-400">No active turnarounds</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Active Turnarounds ({active.length})
      </h3>
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {active.map((plan) => (
          <div
            key={plan.aircraft_registration}
            className="bg-gray-900 rounded p-2 text-xs"
          >
            <div className="flex justify-between items-center mb-1">
              <span className="font-bold text-white">
                {plan.aircraft_registration}
              </span>
              <span className="text-gray-400">
                CP: {plan.critical_path_minutes}m
              </span>
            </div>
            <div className="flex gap-0.5">
              {plan.tasks.map((t) => (
                <div
                  key={t.name}
                  className={`h-2 flex-1 rounded-sm ${
                    t.status === "completed"
                      ? "bg-green-600"
                      : t.status === "in_progress"
                        ? "bg-blue-500 animate-pulse"
                        : "bg-gray-600"
                  }`}
                  title={`${t.name} (${t.duration_min}m) — ${t.status}`}
                />
              ))}
            </div>
            {plan.ready_for_boarding && (
              <div className="text-green-400 text-[10px] mt-1">
                Ready for boarding
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Terminal Activity Panel ──────── */
function TerminalActivityPanel({
  terminals,
  gates,
  flights,
}: {
  terminals: string[];
  gates: Gate[];
  flights: Flight[];
}) {
  const flightByGate = useMemo(() => {
    const m: Record<string, Flight> = {};
    for (const f of flights) {
      if (f.gate_id) m[f.gate_id] = f;
    }
    return m;
  }, [flights]);

  return (
    <div className="bg-gray-900 rounded-lg p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Terminal Activity — Flight / Passenger / Baggage
      </h3>
      <div className="grid grid-cols-3 gap-4">
        {terminals.map((term) => {
          const termGates = gates
            .filter((g) => {
              const raw = g.terminal || g.gate_id.charAt(0);
              return raw.replace(/^T-/, "") === term;
            })
            .filter(
              (g) =>
                g.status === "occupied" ||
                g.status === "boarding" ||
                g.status === "departing",
            );
          return (
            <div key={term} className="bg-gray-800 rounded p-3">
              <div className="text-sm font-bold text-white mb-2">
                Terminal {term}
                <span className="text-xs text-gray-400 ml-2">
                  {termGates.length} active gate
                  {termGates.length !== 1 ? "s" : ""}
                </span>
              </div>
              {termGates.length === 0 ? (
                <div className="text-xs text-gray-400">No active flights</div>
              ) : (
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {termGates.map((g) => {
                    const flight = flightByGate[g.gate_id];
                    if (!flight) return null;
                    const paxPct =
                      flight.pax_count > 0
                        ? Math.round(
                            (flight.pax_boarded / flight.pax_count) * 100,
                          )
                        : 0;
                    const bagPct =
                      flight.baggage_count > 0
                        ? Math.round(
                            (flight.baggage_loaded / flight.baggage_count) *
                              100,
                          )
                        : 0;
                    return (
                      <div
                        key={g.gate_id}
                        className="bg-gray-700 rounded p-2 text-xs"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono font-bold text-white">
                            {g.gate_id}
                          </span>
                          <span className="text-cyan-400 font-semibold">
                            {flight.flight_number}
                          </span>
                          <StatusBadge status={flight.status} />
                        </div>
                        <div className="text-gray-400 text-[10px] mb-1">
                          {flight.direction === "departure" ? "→" : "←"}{" "}
                          {flight.direction === "departure"
                            ? flight.destination_iata
                            : flight.origin_iata}{" "}
                          · {flight.aircraft_type}
                          {flight.delay_minutes > 0 && (
                            <span className="text-amber-400 ml-1">
                              +{flight.delay_minutes}min
                            </span>
                          )}
                        </div>
                        {/* Passengers */}
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-gray-400 w-8">PAX</span>
                          <div className="flex-1 bg-gray-600 rounded-full h-1.5">
                            <div
                              className="bg-green-500 h-1.5 rounded-full transition-all duration-700"
                              style={{ width: `${paxPct}%` }}
                            />
                          </div>
                          <span className="text-gray-400 w-16 text-right">
                            {flight.pax_boarded}/{flight.pax_count}
                          </span>
                        </div>
                        {/* Baggage */}
                        <div className="flex items-center gap-2">
                          <span className="text-gray-400 w-8">BAG</span>
                          <div className="flex-1 bg-gray-600 rounded-full h-1.5">
                            <div
                              className="bg-blue-500 h-1.5 rounded-full transition-all duration-700"
                              style={{ width: `${bagPct}%` }}
                            />
                          </div>
                          <span className="text-gray-400 w-16 text-right">
                            {flight.baggage_loaded}/{flight.baggage_count}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ──────── Real Flights Nearby (ADS-B) Panel ──────── */
function NearbyFlightsPanel({
  data,
}: {
  data: ADSBFeatureCollection | undefined;
}) {
  if (!data || data.features.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-3">
        <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          📡 Real Flights Nearby
        </h3>
        <div className="text-xs text-gray-400">
          ADS-B disabled or no aircraft detected
        </div>
      </div>
    );
  }

  const sorted = [...data.features].sort(
    (a, b) => a.properties.distance_km - b.properties.distance_km,
  );

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        📡 Real Flights Nearby ({data.metadata.aircraft_count})
      </h3>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {sorted.slice(0, 12).map((f) => {
          const alt =
            f.properties.altitude_m != null
              ? `FL${Math.round(f.properties.altitude_m / 30.48 / 100)}`
              : "—";
          const speed =
            f.properties.velocity_ms != null
              ? `${Math.round(f.properties.velocity_ms * 1.944)}kt`
              : "—";
          return (
            <div
              key={f.properties.icao24}
              className="flex items-center justify-between text-xs bg-gray-700 rounded px-2 py-1"
            >
              <span className="font-mono font-bold text-orange-300 w-20 truncate">
                {f.properties.callsign?.trim() || f.properties.icao24}
              </span>
              <span className="text-gray-400">{alt}</span>
              <span className="text-gray-400">{speed}</span>
              <span className="text-gray-300 font-mono">
                {f.properties.distance_km.toFixed(0)} km
              </span>
            </div>
          );
        })}
      </div>
      {data.metadata.last_update && (
        <div className="mt-2 text-[10px] text-gray-400">
          Updated: {new Date(data.metadata.last_update).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}

/* ──────── Ground Vehicle Status Panel ──────── */
function GroundVehicleStatusPanel({
  data,
}: {
  data: GroundVehicleSummary | undefined;
}) {
  if (!data) {
    return (
      <div className="bg-gray-800 rounded p-3">
        <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          Ground Vehicles
        </h3>
        <div className="text-xs text-gray-400">Loading...</div>
      </div>
    );
  }

  const VEHICLE_LABELS: Record<string, { label: string; icon: string }> = {
    fuel_truck: { label: "Fuel", icon: "⛽" },
    catering_truck: { label: "Cater", icon: "🍽️" },
    pushback_tug: { label: "Tug", icon: "🚜" },
    baggage_loader: { label: "Bags", icon: "🧳" },
    stairs: { label: "Stairs", icon: "🪜" },
  };

  const byType = new Map<string, { total: number; busy: number }>();
  for (const v of data.vehicles) {
    const entry = byType.get(v.type) ?? { total: 0, busy: 0 };
    entry.total++;
    if (v.status !== "available") entry.busy++;
    byType.set(v.type, entry);
  }

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Ground Vehicles ({data.total})
        {data.pending_requests > 0 && (
          <span className="ml-2 text-amber-400">
            ⚠ {data.pending_requests} queued
          </span>
        )}
      </h3>
      <div className="space-y-2">
        {[...byType.entries()].map(([type, counts]) => {
          const meta = VEHICLE_LABELS[type] ?? { label: type, icon: "🚗" };
          const pct = data.utilisation_pct[type] ?? 0;
          const barColor =
            pct > 85
              ? "bg-red-500"
              : pct > 60
                ? "bg-amber-500"
                : "bg-green-500";
          return (
            <div key={type} className="text-xs">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-gray-300">
                  {meta.icon} {meta.label}
                </span>
                <span className="text-gray-400">
                  {counts.busy}/{counts.total} busy · {Math.round(pct)}%
                </span>
              </div>
              <div className="w-full bg-gray-600 rounded-full h-1.5">
                <div
                  className={`${barColor} h-1.5 rounded-full transition-all duration-700`}
                  style={{ width: `${Math.min(pct, 100)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ──────── Ground Vehicle SVG Overlay ──────── */
const VEHICLE_ICONS: Record<string, { color: string; symbol: string }> = {
  fuel_truck: { color: "#f59e0b", symbol: "F" },
  catering_truck: { color: "#8b5cf6", symbol: "C" },
  pushback_tug: { color: "#3b82f6", symbol: "T" },
  baggage_loader: { color: "#10b981", symbol: "B" },
  stairs: { color: "#ec4899", symbol: "S" },
};

function GroundVehicleOverlay({
  vehicles,
}: {
  vehicles: {
    id: string;
    type: string;
    status: string;
    current_gate: string | null;
    position_x: number;
    position_y: number;
  }[];
}) {
  // Map vehicle grid positions to a small SVG overlay area
  // Vehicle positions are in grid coordinates (0-1000). We scale to SVG viewport.
  const activeVehicles = vehicles.filter((v) => v.status !== "available");
  const depotVehicles = vehicles.filter((v) => v.status === "available");

  // Count available by type for the depot area
  const depotByType = new Map<string, number>();
  for (const v of depotVehicles) {
    depotByType.set(v.type, (depotByType.get(v.type) ?? 0) + 1);
  }

  return (
    <div className="absolute inset-0 pointer-events-none">
      <svg viewBox="0 0 560 330" className="w-full h-auto">
        {/* Vehicle depot area */}
        <g transform="translate(10, 280)">
          <rect
            width={120}
            height={40}
            rx={4}
            className="fill-gray-800/60 stroke-gray-600"
            strokeWidth={0.5}
          />
          <text x={5} y={12} className="fill-gray-400 text-[7px]">
            VEHICLE DEPOT
          </text>
          {[...depotByType.entries()].map(([type, count], i) => {
            const meta = VEHICLE_ICONS[type] ?? { color: "#999", symbol: "?" };
            return (
              <g key={type} transform={`translate(${5 + i * 24}, 16)`}>
                <circle cx={8} cy={8} r={7} fill={meta.color} opacity={0.6} />
                <text
                  x={8}
                  y={11}
                  textAnchor="middle"
                  className="text-[7px] font-bold"
                  fill="white"
                >
                  {meta.symbol}
                </text>
                <text x={18} y={11} className="fill-gray-300 text-[6px]">
                  ×{count}
                </text>
              </g>
            );
          })}
        </g>

        {/* Active vehicles moving between gates and depot */}
        {activeVehicles.map((v) => {
          const meta = VEHICLE_ICONS[v.type] ?? { color: "#999", symbol: "?" };
          // Scale positions: x 0-1000 → 40-520, y 0-600 → 20-270
          const sx = 40 + (v.position_x / 1000) * 480;
          const sy = 20 + (v.position_y / 600) * 250;
          const isAtGate = v.status === "at_gate";
          return (
            <g key={v.id}>
              <circle
                cx={sx}
                cy={sy}
                r={5}
                fill={meta.color}
                opacity={isAtGate ? 0.9 : 0.7}
                stroke={isAtGate ? "#fff" : "none"}
                strokeWidth={isAtGate ? 1 : 0}
              >
                {v.status === "dispatched" && (
                  <animate
                    attributeName="opacity"
                    values="0.4;0.9;0.4"
                    dur="1.5s"
                    repeatCount="indefinite"
                  />
                )}
              </circle>
              <text
                x={sx}
                y={sy + 3}
                textAnchor="middle"
                className="text-[5px] font-bold"
                fill="white"
              >
                {meta.symbol}
              </text>
              {v.current_gate && (
                <text
                  x={sx}
                  y={sy + 12}
                  textAnchor="middle"
                  className="fill-gray-400 text-[5px]"
                >
                  {v.current_gate}
                </text>
              )}
            </g>
          );
        })}
      </svg>
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
    </div>
  );
}
