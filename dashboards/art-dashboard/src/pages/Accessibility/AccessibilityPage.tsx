import { useQuery } from "@tanstack/react-query";
import { accessibilityApi } from "../../hooks/useApi";
import { KpiCard } from "../../components/KpiCard";
import { LoadingState, ErrorState } from "../../components/LoadingState";

export default function AccessibilityPage() {
  const sla = useQuery({
    queryKey: ["accessibility", "sla"],
    queryFn: () => accessibilityApi.sla(),
    refetchInterval: 15_000,
  });
  const resources = useQuery({
    queryKey: ["accessibility", "resources"],
    queryFn: () => accessibilityApi.resources(),
    refetchInterval: 15_000,
  });
  const staffing = useQuery({
    queryKey: ["accessibility", "staffing"],
    queryFn: () => accessibilityApi.staffing(),
    refetchInterval: 30_000,
  });

  if (sla.isLoading) return <LoadingState message="Loading accessibility…" />;
  if (sla.isError)
    return (
      <ErrorState
        message="Failed to load accessibility data"
        detail="passenger-service may be offline."
        onRetry={() => sla.refetch()}
      />
    );

  const s = sla.data;
  const compliant = s?.compliant ?? false;
  const actual = s?.actual_pct ?? 0;
  const target = s?.target_pct ?? 90;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">
          ♿ Accessibility & Special Assistance
        </h1>
        <p className="text-xs text-gray-400 mt-0.5">
          ECAC Doc 30 SLA · wheelchair pool monitoring
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <KpiCard
          label="SLA actual"
          value={`${actual.toFixed(1)}%`}
          sub={`Target: ${target}%`}
          color={compliant ? "text-emerald-300" : "text-amber-300"}
        />
        <KpiCard
          label="Compliance"
          value={compliant ? "✓ Met" : "✗ Below target"}
          color={compliant ? "text-emerald-400" : "text-rose-400"}
        />
        <KpiCard label="Samples (24h)" value={String(s?.samples ?? 0)} />
        <KpiCard
          label="Mean dispatch wait"
          value={`${(s?.mean_dispatch_wait_minutes ?? 0).toFixed(1)} min`}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-surface-card border border-panel-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-white mb-3">
            SLA by terminal
          </h2>
          <table className="w-full text-xs">
            <thead className="text-gray-400 border-b border-panel-border">
              <tr>
                <th className="text-left py-2">Terminal</th>
                <th className="text-right">Samples</th>
                <th className="text-right">SLA %</th>
                <th className="text-right">Mean wait</th>
              </tr>
            </thead>
            <tbody className="text-gray-200">
              {Object.entries(s?.by_terminal ?? {}).map(([term, stats]) => (
                <tr key={term} className="border-b border-panel-border/50">
                  <td className="py-2 font-mono">{term}</td>
                  <td className="text-right">{stats.samples}</td>
                  <td
                    className={`text-right font-mono ${
                      stats.sla_pct >= target
                        ? "text-emerald-300"
                        : "text-amber-300"
                    }`}
                  >
                    {stats.sla_pct.toFixed(1)}%
                  </td>
                  <td className="text-right font-mono">
                    {stats.mean_wait_minutes.toFixed(1)} min
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-surface-card border border-panel-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-white mb-3">
            Wheelchair pool utilisation
          </h2>
          <table className="w-full text-xs">
            <thead className="text-gray-400 border-b border-panel-border">
              <tr>
                <th className="text-left py-2">Terminal</th>
                <th className="text-right">In use</th>
                <th className="text-right">Available</th>
                <th className="text-right">Queue</th>
                <th className="text-left pl-2">Utilisation</th>
              </tr>
            </thead>
            <tbody className="text-gray-200">
              {(resources.data?.terminals ?? []).map((t) => {
                const pct = t.total > 0 ? (t.in_use / t.total) * 100 : 0;
                return (
                  <tr
                    key={t.terminal}
                    className="border-b border-panel-border/50"
                  >
                    <td className="py-2 font-mono">{t.terminal}</td>
                    <td className="text-right font-mono">
                      {t.in_use}/{t.total}
                    </td>
                    <td className="text-right font-mono">{t.available}</td>
                    <td
                      className={`text-right font-mono ${
                        t.queue_depth > 20
                          ? "text-rose-400"
                          : t.queue_depth > 0
                            ? "text-amber-300"
                            : "text-gray-400"
                      }`}
                    >
                      {t.queue_depth}
                    </td>
                    <td className="pl-2 w-32">
                      <div className="h-2 bg-slate-800 rounded">
                        <div
                          className={`h-2 rounded ${
                            pct >= 95
                              ? "bg-rose-500"
                              : pct >= 75
                                ? "bg-amber-500"
                                : "bg-emerald-500"
                          }`}
                          style={{ width: `${Math.min(100, pct)}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-surface-card border border-panel-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-white mb-1">
          Staffing recommendation
        </h2>
        <p className="text-xs text-gray-500 mb-3">
          {staffing.data?.method ?? ""}
        </p>
        <table className="w-full text-xs">
          <thead className="text-gray-400 border-b border-panel-border">
            <tr>
              <th className="text-left py-2">Terminal</th>
              <th className="text-right">Peak hourly demand</th>
              <th className="text-right">Current pool</th>
              <th className="text-right">Recommended agents</th>
              <th className="text-right">Δ</th>
            </tr>
          </thead>
          <tbody className="text-gray-200">
            {(staffing.data?.terminals ?? []).map((t) => {
              const delta = t.recommended_agents - t.current_pool;
              return (
                <tr
                  key={t.terminal}
                  className="border-b border-panel-border/50"
                >
                  <td className="py-2 font-mono">{t.terminal}</td>
                  <td className="text-right font-mono">
                    {t.peak_hourly_demand}
                  </td>
                  <td className="text-right font-mono">{t.current_pool}</td>
                  <td className="text-right font-mono text-emerald-300">
                    {t.recommended_agents}
                  </td>
                  <td
                    className={`text-right font-mono ${
                      delta > 0 ? "text-rose-300" : "text-emerald-300"
                    }`}
                  >
                    {delta > 0 ? `+${delta}` : delta}
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
