import type { ZoneDensity, PassengerFlowSummary } from "../../types";

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

export function KPIBar({
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
      {summary.security &&
        Object.entries(summary.security).map(([term, data]) => (
          <div
            key={term}
            className="bg-gray-800 rounded px-3 py-2 min-w-[120px]"
          >
            <div className="text-xs text-gray-400">Security {term}</div>
            <div className="font-bold text-white">{data.queue_length} pax</div>
            <div className="flex items-center gap-2 mt-0.5">
              {data.frozen ? (
                <div className="text-xs font-semibold text-red-400 animate-pulse">
                  🔒 FROZEN
                </div>
              ) : (
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
              )}
            </div>
            <div className="text-[10px] text-gray-400">
              {data.frozen
                ? "Security breach — lanes closed"
                : `${data.lanes_open} lanes open`}
            </div>
          </div>
        ))}
    </div>
  );
}
