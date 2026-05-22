import type { Runway } from "../../types";

export function RunwayThroughputChart({ runways }: { runways: Runway[] }) {
  if (runways.length === 0) return null;

  const maxCapacity = Math.max(...runways.map((rw) => rw.capacity_per_hour), 1);

  return (
    <div className="bg-gray-800 rounded-lg p-3 border border-gray-700/50">
      <h3 className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-3">
        Runway Throughput — Actual vs Capacity
      </h3>
      <div className="flex gap-4">
        {runways.map((rw) => {
          const actualPct = (rw.current_rate / maxCapacity) * 100;
          const capacityPct = (rw.capacity_per_hour / maxCapacity) * 100;
          const utilisation =
            rw.capacity_per_hour > 0
              ? Math.round((rw.current_rate / rw.capacity_per_hour) * 100)
              : 0;
          const barColor =
            utilisation > 90
              ? "bg-red-500"
              : utilisation > 70
                ? "bg-amber-500"
                : "bg-blue-500";
          const divergence = rw.capacity_per_hour - rw.current_rate;

          return (
            <div key={rw.runway_id} className="flex-1">
              <div className="text-xs font-mono font-bold text-white mb-2 text-center">
                {rw.runway_id}
              </div>
              <div className="flex items-end gap-1 h-24 justify-center">
                {/* Actual bar */}
                <div className="flex flex-col items-center w-8">
                  <span className="text-[10px] text-gray-300 mb-1">
                    {rw.current_rate}
                  </span>
                  <div
                    className={`w-full ${barColor} rounded-t transition-all duration-700`}
                    style={{ height: `${Math.max(actualPct, 2)}%` }}
                  />
                  <span className="text-[9px] text-gray-400 mt-1">Act</span>
                </div>
                {/* Capacity bar */}
                <div className="flex flex-col items-center w-8">
                  <span className="text-[10px] text-gray-400 mb-1">
                    {rw.capacity_per_hour}
                  </span>
                  <div
                    className="w-full bg-gray-600 rounded-t border border-gray-500 border-dashed transition-all duration-700"
                    style={{ height: `${Math.max(capacityPct, 2)}%` }}
                  />
                  <span className="text-[9px] text-gray-400 mt-1">Cap</span>
                </div>
              </div>
              <div className="text-center mt-1">
                <span
                  className={`text-[10px] font-bold ${
                    utilisation > 90
                      ? "text-red-400"
                      : utilisation > 70
                        ? "text-amber-400"
                        : "text-green-400"
                  }`}
                >
                  {utilisation}%
                </span>
                {divergence > 0 && (
                  <span className="text-[9px] text-gray-400 ml-1">
                    ({divergence} spare)
                  </span>
                )}
              </div>
              <div className="text-center text-[9px] text-gray-400 mt-0.5">
                Arr: {rw.arrivals_queued} · Dep: {rw.departures_queued}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
