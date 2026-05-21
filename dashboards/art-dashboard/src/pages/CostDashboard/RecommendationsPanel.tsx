import { formatEur } from "../../utils/formatCurrency";
import type { FinancialRecommendation } from "../../types";

export function RecommendationsPanel({
  recs,
}: {
  recs: FinancialRecommendation[];
}) {
  if (recs.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-4">
        No active recommendations
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {recs.map((rec, i) => (
        <div
          key={i}
          className="bg-surface border border-panel-border rounded-lg p-3"
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-semibold text-accent">
              {rec.action.replace(/_/g, " ").toUpperCase()}
            </span>
            <span
              className={`text-xs px-2 py-0.5 rounded-full ${
                rec.confidence >= 0.7
                  ? "bg-green-900/50 text-green-300"
                  : "bg-amber-900/50 text-amber-300"
              }`}
            >
              {Math.round(rec.confidence * 100)}% confidence
            </span>
          </div>
          <p className="text-xs text-gray-400 mb-2">{rec.description}</p>
          <div className="flex gap-4 text-xs">
            <span className="text-red-400">
              Cost: {formatEur(rec.cost_eur)}
            </span>
            <span className="text-green-400">
              Saving: {formatEur(rec.saving_eur)}
            </span>
            <span className="font-bold text-white">
              Net: {formatEur(rec.net_benefit_eur)}
            </span>
            <span className="text-gray-500">
              Payback: {rec.payback_sim_minutes}min
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
