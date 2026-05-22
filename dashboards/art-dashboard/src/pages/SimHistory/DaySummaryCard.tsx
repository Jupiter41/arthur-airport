import type { DaySummary } from "./types";

export function DaySummaryCard({
  day,
  selected,
  onClick,
}: {
  day: DaySummary;
  selected: boolean;
  onClick: () => void;
}) {
  const sevColor =
    day.max_severity === "critical"
      ? "border-red-500 bg-red-900/20"
      : day.max_severity === "high"
        ? "border-orange-500 bg-orange-900/10"
        : "border-gray-700 bg-gray-800";

  return (
    <div
      className={`border-l-4 ${sevColor} rounded p-3 cursor-pointer transition-all hover:ring-1 hover:ring-white/20 ${selected ? "ring-2 ring-blue-400" : ""}`}
      onClick={onClick}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-bold text-white">
          Day {day.day_number}
        </span>
        <span className="text-xs text-gray-400">{day.sim_date}</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-gray-400">Flights</span>
          <div className="text-white font-bold">{day.flights_total}</div>
        </div>
        <div>
          <span className="text-gray-400">Pax</span>
          <div className="text-white font-bold">
            {day.passengers_total.toLocaleString()}
          </div>
        </div>
        <div>
          <span className="text-gray-400">Incidents</span>
          <div
            className={
              day.incidents_total > 0
                ? "text-amber-400 font-bold"
                : "text-white font-bold"
            }
          >
            {day.incidents_total}
          </div>
        </div>
      </div>
      <div className="mt-1 flex gap-3 text-[10px] text-gray-400">
        <span>Delayed: {day.flights_delayed}</span>
        <span>Cancelled: {day.flights_cancelled}</span>
        <span>Avg delay: {day.avg_delay_minutes}min</span>
      </div>
    </div>
  );
}
