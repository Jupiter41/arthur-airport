import type { GroundVehicleSummary } from "../../types";

/* ──────── Ground Vehicle Status Panel ──────── */
export function GroundVehicleStatusPanel({
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
  baggage_loader: { color: "#10b981", symbol: "L" },
  stairs: { color: "#ec4899", symbol: "S" },
};

export function GroundVehicleOverlay({
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
  const activeVehicles = vehicles.filter((v) => v.status !== "available");
  const depotVehicles = vehicles.filter((v) => v.status === "available");

  const depotByType = new Map<string, number>();
  for (const v of depotVehicles) {
    depotByType.set(v.type, (depotByType.get(v.type) ?? 0) + 1);
  }

  return (
    <div className="absolute inset-0 pointer-events-none">
      <svg viewBox="0 0 560 330" className="w-full h-auto">
        {/* Vehicle depot area */}
        <g transform="translate(10, 275)">
          <rect
            width={180}
            height={48}
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
              <g key={type} transform={`translate(${5 + i * 34}, 18)`}>
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

        {/* Active vehicles */}
        {activeVehicles.map((v) => {
          const meta = VEHICLE_ICONS[v.type] ?? { color: "#999", symbol: "?" };
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

/* ──────── Vehicle Position Table ──────── */
const VEHICLE_TYPE_LABELS: Record<string, { label: string; icon: string }> = {
  fuel_truck: { label: "Fuel Truck", icon: "⛽" },
  catering_truck: { label: "Catering", icon: "🍽️" },
  pushback_tug: { label: "Pushback Tug", icon: "🚜" },
  baggage_loader: { label: "Baggage Loader", icon: "🧳" },
  stairs: { label: "Stairs", icon: "🪜" },
};

const STATUS_COLORS: Record<string, string> = {
  available: "text-gray-400",
  dispatched: "text-amber-400",
  at_gate: "text-green-400",
  returning: "text-blue-400",
};

export function VehiclePositionTable({
  vehicles,
}: {
  vehicles: {
    id: string;
    type: string;
    status: string;
    current_gate: string | null;
    position_x: number;
    position_y: number;
    task_name: string | null;
    flight_id: string | null;
  }[];
}) {
  const activeFirst = [...vehicles].sort((a, b) => {
    const order = { at_gate: 0, dispatched: 1, returning: 2, available: 3 };
    return (
      (order[a.status as keyof typeof order] ?? 4) -
      (order[b.status as keyof typeof order] ?? 4)
    );
  });

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-white mb-3">
        🚗 Vehicle Position Tracker
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="pb-2 pr-4">Type</th>
              <th className="pb-2 pr-4">Status</th>
              <th className="pb-2 pr-4">Gate</th>
              <th className="pb-2 pr-4">Task</th>
              <th className="pb-2 pr-4">Position</th>
            </tr>
          </thead>
          <tbody>
            {activeFirst.map((v) => {
              const meta = VEHICLE_TYPE_LABELS[v.type] ?? {
                label: v.type,
                icon: "🚗",
              };
              const statusColor = STATUS_COLORS[v.status] ?? "text-gray-400";
              return (
                <tr
                  key={v.id}
                  className="border-b border-gray-700/50 hover:bg-gray-700/30"
                >
                  <td className="py-1.5 pr-4 text-gray-200">
                    {meta.icon} {meta.label}
                  </td>
                  <td className={`py-1.5 pr-4 font-medium ${statusColor}`}>
                    {v.status === "dispatched" && (
                      <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 mr-1 animate-pulse" />
                    )}
                    {v.status}
                  </td>
                  <td className="py-1.5 pr-4 text-gray-300">
                    {v.current_gate ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-gray-400">
                    {v.task_name ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-gray-500 font-mono">
                    ({v.position_x}, {v.position_y})
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
