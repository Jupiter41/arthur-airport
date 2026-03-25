import { useState, useEffect, useMemo } from "react";
import { usePassengerStore } from "../../stores/passengerStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { usePassengerFlowQueries } from "../../hooks/useQueries";
import type {
  ZoneDensity,
  PassengerFlowSummary,
  ConnectionAtRisk,
} from "../../types";

/* ──────── Heat color from load percentage ──────── */
function heatColor(loadPct: number, locked: boolean): string {
  if (locked) return "#6b7280"; // gray
  if (loadPct <= 25) return "#86efac"; // light green
  if (loadPct <= 50) return "#22c55e"; // green
  if (loadPct <= 70) return "#a3e635"; // yellow-green
  if (loadPct <= 85) return "#f59e0b"; // amber
  if (loadPct <= 95) return "#f97316"; // orange
  return "#ef4444"; // red
}

/* ──────── Zone cell for heatmap ──────── */
function ZoneCell({
  zone,
  locked,
  onClick,
}: {
  zone: ZoneDensity;
  locked: boolean;
  onClick: () => void;
}) {
  const bg = heatColor(zone.load_pct, locked);

  return (
    <div
      className="relative rounded p-2 cursor-pointer transition-all duration-700 hover:ring-2 hover:ring-white/40 min-h-[56px]"
      style={{ backgroundColor: bg, opacity: locked ? 0.5 : 1 }}
      onClick={onClick}
    >
      <div className="text-[10px] font-bold text-white/90 truncate">
        {zone.zone_id}
      </div>
      <div className="text-xs text-white/80">{zone.density} pax</div>
      <div className="text-[9px] text-white/60">{zone.load_pct}%</div>
      {locked && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg">🔒</span>
        </div>
      )}
    </div>
  );
}

/* ──────── Heatmap grid ──────── */
function AirportHeatmap({
  zones,
  lockedZones,
  onSelect,
}: {
  zones: ZoneDensity[];
  lockedZones: Set<string>;
  onSelect: (z: ZoneDensity) => void;
}) {
  // Group zones by type and terminal
  const grouped = useMemo(() => {
    const byType: Record<string, ZoneDensity[]> = {};
    for (const z of zones) {
      const key = z.zone_type || z.zone_id.split("-")[0];
      (byType[key] ??= []).push(z);
    }
    return byType;
  }, [zones]);

  const terminals = ["A", "B", "C"];
  const columns = ["check-in", "security", "airside", "gate"];

  return (
    <div className="bg-gray-900 rounded-lg p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">
        Airport Heatmap
      </div>
      {/* Header row */}
      <div className="grid grid-cols-4 gap-2 mb-2">
        {columns.map((col) => (
          <div
            key={col}
            className="text-xs text-gray-500 text-center uppercase"
          >
            {col}
          </div>
        ))}
      </div>

      {/* Terminal rows */}
      {terminals.map((term) => (
        <div key={term} className="grid grid-cols-4 gap-2 mb-2">
          {columns.map((col) => {
            const key = `${col}-${term}`;
            // Find matching zone(s)
            const matching = zones.filter(
              (z) =>
                z.zone_id
                  .toLowerCase()
                  .includes(`${col}-${term.toLowerCase()}`) ||
                z.zone_id
                  .toLowerCase()
                  .includes(`${col.replace("-", "")}-${term.toLowerCase()}`),
            );

            // For gates, aggregate multiple gate zones
            if (col === "gate" && matching.length === 0) {
              const gateZones = zones.filter(
                (z) =>
                  z.zone_id
                    .toLowerCase()
                    .startsWith("gate-") &&
                  z.zone_id
                    .toLowerCase()
                    .startsWith(`gate-${term.toLowerCase()}`),
              );
              if (gateZones.length > 0) {
                const totalDensity = gateZones.reduce(
                  (s, z) => s + z.density,
                  0,
                );
                const totalCap = gateZones.reduce((s, z) => s + z.capacity, 0);
                const avgLoad =
                  totalCap > 0
                    ? Math.round((totalDensity / totalCap) * 100)
                    : 0;
                const agg: ZoneDensity = {
                  zone_id: `gates-${term}`,
                  zone_type: "gate",
                  terminal: term,
                  density: totalDensity,
                  capacity: totalCap,
                  load_pct: avgLoad,
                };
                return (
                  <ZoneCell
                    key={key}
                    zone={agg}
                    locked={lockedZones.has(`terminal-${term}`)}
                    onClick={() => onSelect(agg)}
                  />
                );
              }
            }

            if (matching.length > 0) {
              return (
                <ZoneCell
                  key={key}
                  zone={matching[0]}
                  locked={lockedZones.has(matching[0].zone_id)}
                  onClick={() => onSelect(matching[0])}
                />
              );
            }

            // Empty placeholder
            const placeholder: ZoneDensity = {
              zone_id: key,
              zone_type: col,
              terminal: term,
              density: 0,
              capacity: 100,
              load_pct: 0,
            };
            return (
              <ZoneCell
                key={key}
                zone={placeholder}
                locked={false}
                onClick={() => onSelect(placeholder)}
              />
            );
          })}
        </div>
      ))}

      {/* Carousel row */}
      <div className="mt-3">
        <div className="text-xs text-gray-500 uppercase mb-1">
          Arrival Carousels
        </div>
        <div className="grid grid-cols-6 gap-2">
          {[1, 2, 3, 4, 5, 6].map((n) => {
            const z = zones.find((z) => z.zone_id === `carousel-${n}`);
            const zone: ZoneDensity = z ?? {
              zone_id: `carousel-${n}`,
              zone_type: "carousel",
              terminal: "",
              density: 0,
              capacity: 200,
              load_pct: 0,
            };
            return (
              <ZoneCell
                key={zone.zone_id}
                zone={zone}
                locked={false}
                onClick={() => onSelect(zone)}
              />
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 mt-3 text-[10px] text-gray-400">
        {[
          { pct: 10, label: "Low" },
          { pct: 40, label: "Moderate" },
          { pct: 65, label: "Busy" },
          { pct: 80, label: "High" },
          { pct: 92, label: "Near Cap" },
          { pct: 100, label: "Full" },
        ].map(({ pct, label }) => (
          <div key={pct} className="flex items-center gap-1">
            <div
              className="w-3 h-3 rounded"
              style={{ backgroundColor: heatColor(pct, false) }}
            />
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── KPI Bar ──────── */
function KPIBar({ summary }: { summary: PassengerFlowSummary | null }) {
  if (!summary) return null;
  return (
    <div className="flex gap-4">
      <KPI
        label="In Airport"
        value={summary.total_in_airport.toLocaleString()}
      />
      <KPI
        label="Connections at Risk"
        value={String(summary.connections_at_risk)}
        color={summary.connections_at_risk > 0 ? "text-amber-400" : undefined}
      />
      <KPI
        label="Missed"
        value={String(summary.connections_missed)}
        color={summary.connections_missed > 0 ? "text-red-400" : undefined}
      />
      {/* Security queues */}
      {summary.security &&
        Object.entries(summary.security).map(([term, data]) => (
          <div key={term} className="bg-gray-800 rounded px-3 py-2">
            <div className="text-xs text-gray-500">Security {term}</div>
            <div className="font-bold text-white">{data.queue_length} pax</div>
            <div
              className={`text-xs ${data.wait_minutes > 20 ? "text-amber-400" : "text-gray-400"}`}
            >
              ~{data.wait_minutes} min
            </div>
          </div>
        ))}
    </div>
  );
}

function KPI({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-gray-800 rounded px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`font-bold ${color ?? "text-white"}`}>{value}</div>
    </div>
  );
}

/* ──────── Connection Risk List ──────── */
function ConnectionRiskList({
  connections,
}: {
  connections: ConnectionAtRisk[];
}) {
  if (connections.length === 0) return null;

  const riskColors: Record<string, string> = {
    watch: "bg-gray-600 text-gray-200",
    at_risk: "bg-amber-600 text-white",
    missed: "bg-red-600 text-white",
  };

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Connections at Risk
      </h3>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {connections.map((c) => (
          <div
            key={c.passenger_id}
            className="flex items-center justify-between text-sm bg-gray-700 rounded p-2"
          >
            <div>
              <span className="text-white font-medium">{c.passenger_name}</span>
              <span className="ml-2 text-xs text-gray-400">
                {c.inbound_flight}
                {c.inbound_delay_minutes > 0 &&
                  ` +${c.inbound_delay_minutes}min`}
                {" → "}
                {c.connection_flight}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">
                {c.time_until_departure_min} min
              </span>
              <span
                className={`text-xs font-bold px-2 py-0.5 rounded ${riskColors[c.risk_level] ?? "bg-gray-600"}`}
              >
                {c.risk_level.toUpperCase().replace("_", " ")}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Zone Detail Panel ──────── */
function ZoneDetailPanel({ zone }: { zone: ZoneDensity | null }) {
  if (!zone) return null;
  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-sm font-bold text-white mb-2">{zone.zone_id}</h3>
      <div className="text-sm space-y-1 text-gray-300">
        <div className="flex justify-between">
          <span>Density</span>
          <span>{zone.density} pax</span>
        </div>
        <div className="flex justify-between">
          <span>Capacity</span>
          <span>{zone.capacity}</span>
        </div>
        <div className="flex justify-between">
          <span>Load</span>
          <span
            className={zone.load_pct > 85 ? "text-amber-400 font-bold" : ""}
          >
            {zone.load_pct}%
          </span>
        </div>
      </div>
    </div>
  );
}

/* ──────── Main Page ──────── */
export default function PassengerFlowPage() {
  const zones = usePassengerStore((s) => s.zones);
  const summary = usePassengerStore((s) => s.summary);
  const connectionsAtRisk = usePassengerStore((s) => s.connectionsAtRisk);
  const setZones = usePassengerStore((s) => s.setZones);
  const setSummary = usePassengerStore((s) => s.setSummary);
  const setConnectionsAtRisk = usePassengerStore((s) => s.setConnectionsAtRisk);
  const incidents = useIncidentStore((s) => s.incidents);

  const [selectedZone, setSelectedZone] = useState<ZoneDensity | null>(null);

  // Determine locked zones from security incidents
  const lockedZones = useMemo(() => {
    const set = new Set<string>();
    for (const inc of Object.values(incidents)) {
      if (inc.type === "security_breach" && inc.status !== "resolved") {
        set.add(inc.location);
      }
    }
    return set;
  }, [incidents]);

  const queries = usePassengerFlowQueries();

  useEffect(() => {
    if (queries.heatmap.data) setZones(queries.heatmap.data);
  }, [queries.heatmap.data, setZones]);

  useEffect(() => {
    if (queries.summary.data) setSummary(queries.summary.data);
  }, [queries.summary.data, setSummary]);

  useEffect(() => {
    if (queries.atRisk.data) setConnectionsAtRisk(queries.atRisk.data);
  }, [queries.atRisk.data, setConnectionsAtRisk]);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <h2 className="text-lg font-bold text-white">Passenger Flow</h2>

      <KPIBar summary={summary} />

      <AirportHeatmap
        zones={zones}
        lockedZones={lockedZones}
        onSelect={setSelectedZone}
      />

      <div className="grid grid-cols-2 gap-4">
        <ConnectionRiskList connections={connectionsAtRisk} />
        <ZoneDetailPanel zone={selectedZone} />
      </div>
    </div>
  );
}
