import { useMemo } from "react";
import type { Flight } from "../../types";
import { FLIGHT_TYPE_STYLES } from "./constants";

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

export function FlightStats({ flights }: { flights: Flight[] }) {
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
