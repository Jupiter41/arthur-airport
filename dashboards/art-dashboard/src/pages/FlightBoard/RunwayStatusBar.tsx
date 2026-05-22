import type { Runway } from "../../types";

export function RunwayStatusBar({ runways }: { runways: Runway[] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {runways.map((rw) => {
        const pct =
          rw.capacity_per_hour > 0
            ? Math.round((rw.current_rate / rw.capacity_per_hour) * 100)
            : 0;
        const statusColor =
          rw.status === "open"
            ? "text-green-400"
            : rw.status === "restricted"
              ? "text-amber-400"
              : "text-red-400";

        return (
          <div key={rw.runway_id} className="bg-gray-800 rounded p-3">
            <div className="flex items-center justify-between mb-1">
              <span className="font-mono font-bold text-white">
                {rw.runway_id}
              </span>
              <span className={`text-xs font-bold ${statusColor} uppercase`}>
                {rw.operation ?? rw.status}
              </span>
            </div>
            <div className="w-full bg-gray-700 rounded-full h-2 mb-1">
              <div
                className="bg-blue-500 h-2 rounded-full transition-all"
                style={{ width: `${Math.min(pct, 100)}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-400">
              <span>
                {rw.current_rate}/{rw.capacity_per_hour} mvts/hr
              </span>
              <span>
                Arr: {rw.arrivals_queued} · Dep: {rw.departures_queued}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
