import { useState, useEffect, useMemo } from "react";
import { usePassengerStore } from "../../stores/passengerStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { usePassengerFlowQueries } from "../../hooks/useQueries";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData, exportRaw } from "../../utils/exportData";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { ExportFormat } from "../../utils/exportData";
import type {
  ZoneDensity,
  PassengerFlowSummary,
  ConnectionAtRisk,
} from "../../types";

/* ──────── Heat color from load percentage ──────── */
function heatColor(loadPct: number, locked: boolean): string {
  if (locked) return "#4b5563"; // gray-600
  if (loadPct <= 15) return "#065f46"; // emerald-800 (very calm)
  if (loadPct <= 35) return "#047857"; // emerald-700 (low)
  if (loadPct <= 55) return "#0d9488"; // teal-600 (moderate)
  if (loadPct <= 70) return "#d97706"; // amber-600 (busy)
  if (loadPct <= 85) return "#ea580c"; // orange-600 (high)
  if (loadPct <= 95) return "#dc2626"; // red-600 (near cap)
  return "#991b1b"; // red-800 (full)
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
      className="relative rounded-lg p-2.5 cursor-pointer transition-all duration-700 hover:ring-2 hover:ring-white/40 min-h-[60px] shadow-sm"
      style={{ backgroundColor: bg, opacity: locked ? 0.5 : 1 }}
      onClick={onClick}
    >
      <div className="text-[10px] font-bold text-white drop-shadow-sm truncate">
        {zone.zone_id}
      </div>
      <div className="text-sm font-semibold text-white drop-shadow-sm">
        {zone.density} pax
      </div>
      <div className="text-[9px] text-white/70">
        {zone.load_pct}% ·{" "}
        {zone.capacity - zone.density > 0 ? zone.capacity - zone.density : 0}{" "}
        free
      </div>
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
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Airport Heatmap
      </div>
      {/* Header row */}
      <div className="grid grid-cols-4 gap-2 mb-2">
        {columns.map((col) => (
          <div
            key={col}
            className="text-xs text-gray-400 text-center uppercase"
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
                  z.zone_id.toLowerCase().startsWith("gate-") &&
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
        <div className="text-xs text-gray-400 uppercase mb-1">
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
          { pct: 10, label: "Calm" },
          { pct: 30, label: "Low" },
          { pct: 50, label: "Moderate" },
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

/* ──────── Security Queue Chart ──────── */
function SecurityQueueChart({
  summary,
}: {
  summary: PassengerFlowSummary | null;
}) {
  if (!summary?.security) return null;

  const data = Object.entries(summary.security).map(([term, info]) => ({
    terminal: `Terminal ${term.replace("terminal_", "")}`,
    queue: info.queue_length,
    wait: info.wait_minutes,
    lanes: info.lanes_open,
  }));

  function barColor(wait: number): string {
    if (wait <= 10) return "#22c55e";
    if (wait <= 20) return "#f59e0b";
    return "#ef4444";
  }

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Security Queue Depth &amp; Wait Time
      </h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart
              data={data}
              margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="terminal"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
              />
              <YAxis tick={{ fill: "#9ca3af", fontSize: 10 }} width={32} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #4b5563",
                  borderRadius: 4,
                }}
                labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
                itemStyle={{ fontSize: 11, color: "#e5e7eb" }}
              />
              <Bar dataKey="queue" name="Queue Depth" radius={[4, 4, 0, 0]}>
                {data.map((d, i) => (
                  <Cell key={i} fill={barColor(d.wait)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart
              data={data}
              margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="terminal"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
              />
              <YAxis
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                width={32}
                unit=" min"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #4b5563",
                  borderRadius: 4,
                }}
                labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
                itemStyle={{ fontSize: 11, color: "#e5e7eb" }}
                formatter={(value) => [`${value} min`, "Est. Wait"]}
              />
              <Bar dataKey="wait" name="Est. Wait" radius={[4, 4, 0, 0]}>
                {data.map((d, i) => (
                  <Cell key={i} fill={barColor(d.wait)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

/* ──────── KPI Bar ──────── */
function KPIBar({
  summary,
  zones,
}: {
  summary: PassengerFlowSummary | null;
  zones: ZoneDensity[];
}) {
  if (!summary) return null;

  const totalCapacity = zones.reduce((sum, z) => sum + z.capacity, 0);
  const totalDensity = zones.reduce((sum, z) => sum + z.density, 0);
  const overallLoadPct =
    totalCapacity > 0 ? Math.round((totalDensity / totalCapacity) * 100) : 0;

  return (
    <div className="flex gap-4 flex-wrap">
      <KPI
        label="In Airport"
        value={summary.total_in_airport.toLocaleString()}
      />
      <div className="bg-gray-800 rounded px-3 py-2">
        <div className="text-xs text-gray-400">Overall Capacity</div>
        <div
          className={`font-bold ${overallLoadPct > 85 ? "text-red-400" : overallLoadPct > 70 ? "text-amber-400" : "text-white"}`}
        >
          {overallLoadPct}%
        </div>
        <div className="w-full bg-gray-700 rounded-full h-1.5 mt-1">
          <div
            className={`h-1.5 rounded-full transition-all duration-700 ${
              overallLoadPct > 85
                ? "bg-red-500"
                : overallLoadPct > 70
                  ? "bg-amber-500"
                  : "bg-green-500"
            }`}
            style={{ width: `${Math.min(100, overallLoadPct)}%` }}
          />
        </div>
      </div>
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
      {/* Security queues with wait time + capacity bar */}
      {summary.security &&
        Object.entries(summary.security).map(([term, data]) => (
          <div
            key={term}
            className="bg-gray-800 rounded px-3 py-2 min-w-[120px]"
          >
            <div className="text-xs text-gray-400">Security {term}</div>
            <div className="font-bold text-white">{data.queue_length} pax</div>
            <div className="flex items-center gap-2 mt-0.5">
              <div
                className={`text-xs font-semibold ${
                  data.wait_minutes > 20
                    ? "text-red-400"
                    : data.wait_minutes > 10
                      ? "text-amber-400"
                      : "text-green-400"
                }`}
              >
                ~{data.wait_minutes} min wait
              </div>
            </div>
            <div className="text-[10px] text-gray-400">
              {data.lanes_open} lanes open
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
      <div className="text-xs text-gray-400">{label}</div>
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
  const remaining = Math.max(0, zone.capacity - zone.density);
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
          <span>Remaining</span>
          <span className={remaining < 10 ? "text-red-400 font-bold" : ""}>
            {remaining} slots
          </span>
        </div>
        <div className="flex justify-between">
          <span>Load</span>
          <span
            className={
              zone.load_pct > 85
                ? "text-red-400 font-bold"
                : zone.load_pct > 70
                  ? "text-amber-400 font-bold"
                  : ""
            }
          >
            {zone.load_pct}%
          </span>
        </div>
        <div className="w-full bg-gray-700 rounded-full h-2 mt-2">
          <div
            className={`h-2 rounded-full transition-all duration-700 ${
              zone.load_pct > 85
                ? "bg-red-500"
                : zone.load_pct > 70
                  ? "bg-amber-500"
                  : "bg-green-500"
            }`}
            style={{ width: `${Math.min(100, zone.load_pct)}%` }}
          />
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
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">Passenger Flow</h2>
        <ExportMenu
          onExport={(fmt: ExportFormat) => {
            const rows = zones.map((z) => ({
              zone_id: z.zone_id,
              zone_type: z.zone_type,
              terminal: z.terminal,
              density: z.density,
              capacity: z.capacity,
              load_pct: z.load_pct,
            }));
            exportData(rows, "passenger-flow", fmt);
          }}
        />
      </div>

      <KPIBar summary={summary} zones={zones} />

      <SecurityQueueChart summary={summary} />

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
