import { useState } from "react";
import { StatusBadge } from "../../components/StatusBadge";
import { analysisApi } from "../../hooks/useApi";
import { queryClient } from "../../queryClient";
import type {
  AnalysisBottleneck,
  AnalysisRecommendation,
} from "../../stores/analysisStore";
import { SEVERITY_RING, ACTION_ICON } from "./constants";

export function RecommendationFeed({
  bottlenecks,
  recommendations,
}: {
  bottlenecks: AnalysisBottleneck[];
  recommendations: AnalysisRecommendation[];
}) {
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (bottlenecks.length === 0 && recommendations.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-4 text-center text-gray-400 text-sm">
        No active bottlenecks or recommendations
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">
        Bottlenecks &amp; Recommendations
      </h3>

      {error && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded px-2 py-1">
          {error}
        </div>
      )}

      {bottlenecks.map((bn) => (
        <div
          key={bn.id}
          className={`border-l-4 ${
            bn.severity === "critical"
              ? "border-red-500 bg-red-900/20"
              : "border-amber-500 bg-amber-900/20"
          } rounded p-3`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-white uppercase">
              {bn.type.replace(/_/g, " ")}
            </span>
            <StatusBadge status={bn.severity} />
          </div>
          <div className="text-sm text-gray-300 mt-1">{bn.root_cause}</div>
          <div className="text-xs text-gray-400 mt-1">
            {bn.affected_entity_count} affected · ~
            {bn.estimated_duration_minutes} min
          </div>
        </div>
      ))}

      {recommendations.map((rec) => (
        <div
          key={rec.id}
          className={`ring-1 ${
            SEVERITY_RING[
              bottlenecks.find((b) => b.id === rec.bottleneck_id)?.severity ??
                "warning"
            ] ?? "ring-gray-600"
          } bg-gray-800 rounded p-3`}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm text-white font-medium">
              {ACTION_ICON[rec.action_type] ?? "💡"} {rec.description}
            </span>
            <span className="text-xs text-gray-400">#{rec.priority_rank}</span>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-gray-400">
            <div>
              <span className="text-gray-400">Impact:</span>{" "}
              {rec.expected_impact}
            </div>
            <div>
              <span className="text-gray-400">Cost:</span> {rec.cost}
            </div>
          </div>
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-2">
              <div className="w-20 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    rec.confidence_score >= 0.8
                      ? "bg-green-500"
                      : rec.confidence_score >= 0.6
                        ? "bg-amber-500"
                        : "bg-red-500"
                  }`}
                  style={{ width: `${rec.confidence_score * 100}%` }}
                />
              </div>
              <span className="text-xs text-gray-400">
                {(rec.confidence_score * 100).toFixed(0)}% conf.
              </span>
            </div>
            {!rec.applied && (
              <button
                className="text-xs font-bold px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
                disabled={applying === rec.id}
                onClick={async () => {
                  setApplying(rec.id);
                  setError(null);
                  try {
                    // Real server-side apply: records the operator action and
                    // emits an AutonomousActionApplied event (no longer a
                    // discarded what-if projection).
                    await analysisApi.applyRecommendation(rec.id);
                    await queryClient.invalidateQueries({
                      queryKey: ["analysis", "recommendations"],
                    });
                  } catch (err) {
                    setError(
                      err instanceof Error ? err.message : "Apply failed",
                    );
                  } finally {
                    setApplying(null);
                  }
                }}
              >
                {applying === rec.id ? "..." : "Apply"}
              </button>
            )}
            {rec.applied && (
              <span className="text-xs text-green-400">✓ Applied</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
