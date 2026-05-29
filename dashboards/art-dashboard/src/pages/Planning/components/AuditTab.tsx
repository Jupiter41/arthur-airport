import { useQuery } from "@tanstack/react-query";
import { planningApi } from "../../../hooks/useApi";
import { formatEur } from "../../../utils/formatCurrency";
import { MetricCard } from "./shared";

export default function AuditTab() {
  const { data: summary } = useQuery({
    queryKey: ["audit-summary"],
    queryFn: () => planningApi.auditSummary(),
    refetchInterval: 10_000,
  });

  const { data: logData } = useQuery({
    queryKey: ["audit-log"],
    queryFn: () => planningApi.auditLog({ limit: 50 }),
    refetchInterval: 10_000,
  });

  const auditSummary = summary as Record<string, unknown> | undefined;
  const entries = (logData?.entries ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-5">
      {/* Methodology */}
      <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-3">
        <p className="text-xs text-slate-400 leading-relaxed">
          <strong className="text-slate-300">Decision Audit Trail:</strong>{" "}
          Every autonomous recommendation is logged with its predicted cost
          saving. 30 sim-minutes after application, the actual outcome is
          measured. This feedback loop calibrates model accuracy over time.
        </p>
      </div>

      {/* Summary cards */}
      {auditSummary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricCard
            label="Total Recommendations"
            value={String(auditSummary.total_recommendations ?? 0)}
            color="text-white"
          />
          <MetricCard
            label="Applied by Operator"
            value={`${auditSummary.applied_count ?? 0} (${auditSummary.applied_pct ?? 0}%)`}
            color="text-cyan-400"
          />
          <MetricCard
            label="Predicted Saving"
            value={formatEur(
              (auditSummary.total_predicted_saving_eur as number) ?? 0,
            )}
            color="text-emerald-400"
          />
          <MetricCard
            label="Actual Saving"
            value={formatEur(
              (auditSummary.total_actual_saving_eur as number) ?? 0,
            )}
            sublabel={
              (auditSummary.measured_count as number) > 0
                ? `Accuracy: ${auditSummary.prediction_accuracy_pct}%`
                : "No measurements yet"
            }
            color="text-amber-400"
          />
        </div>
      )}

      {/* Accuracy bar */}
      {auditSummary && (auditSummary.measured_count as number) > 0 && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Prediction Accuracy</span>
            <span className="text-white font-medium">
              {auditSummary.prediction_accuracy_pct as number}%
            </span>
          </div>
          <div className="w-full bg-slate-700 rounded-full h-2 mt-2">
            <div
              className="bg-cyan-400 h-2 rounded-full transition-all"
              style={{
                width: `${Math.min(100, auditSummary.prediction_accuracy_pct as number)}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* Audit log table */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3">
          Recommendation History
          <span className="text-slate-400 font-normal ml-2">
            ({logData?.total ?? 0})
          </span>
        </h3>
        {entries.length === 0 ? (
          <div className="text-slate-400 text-sm text-center py-8">
            No recommendations logged yet. They appear as the autonomous system
            makes decisions during simulation.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-400 uppercase border-b border-slate-700">
                  <th className="text-left py-2 px-2">Time</th>
                  <th className="text-left py-2 px-2">Action</th>
                  <th className="text-left py-2 px-2">Description</th>
                  <th className="text-right py-2 px-2">Predicted</th>
                  <th className="text-right py-2 px-2">Actual</th>
                  <th className="text-center py-2 px-2">Applied</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr
                    key={e.id as string}
                    className="border-b border-slate-700/50 hover:bg-slate-700/30"
                  >
                    <td className="py-2 px-2 text-slate-400 whitespace-nowrap">
                      {String(
                        e.sim_time ||
                          (e.created_at as string)?.slice(0, 19) ||
                          "",
                      )}
                    </td>
                    <td className="py-2 px-2">
                      <span className="bg-slate-600 text-slate-200 px-1.5 py-0.5 rounded">
                        {String((e.action_type as string) ?? "").replace(
                          /_/g,
                          " ",
                        )}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-slate-300 max-w-xs truncate">
                      {String(e.recommendation_text)}
                    </td>
                    <td className="py-2 px-2 text-right text-emerald-400 font-mono">
                      {formatEur((e.predicted_saving_eur as number) ?? 0)}
                    </td>
                    <td className="py-2 px-2 text-right font-mono">
                      {e.actual_saving_eur != null ? (
                        <span
                          className={
                            (e.actual_saving_eur as number) >= 0
                              ? "text-emerald-400"
                              : "text-red-400"
                          }
                        >
                          {formatEur(e.actual_saving_eur as number)}
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-center">
                      {e.was_applied ? (
                        <span className="text-emerald-400">✓</span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
