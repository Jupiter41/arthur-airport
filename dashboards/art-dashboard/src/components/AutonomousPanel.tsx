import { useState, useEffect, useCallback } from "react";
import { analysisApi } from "../hooks/useApi";

export function AutonomousPanel() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(
    null,
  );
  const [log, setLog] = useState<unknown[]>([]);
  const [diagnostics, setDiagnostics] = useState<{
    bottlenecks: number;
    recommendations: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        analysisApi.autonomousSettings(),
        analysisApi.autonomousLog(10),
      ]);
      // API returns { autonomous: { mode, ... } } — unwrap to get inner settings
      const resp = s as Record<string, unknown>;
      setSettings((resp.autonomous as Record<string, unknown>) ?? resp);
      setLog((l as { actions: unknown[] }).actions ?? []);
    } catch {
      /* ignore */
    }
    // Fetch diagnostics — bottleneck and recommendation counts
    try {
      const [bn, recs] = await Promise.all([
        analysisApi.bottlenecks(),
        analysisApi.recommendations(),
      ]);
      const bnArr = (bn as { bottlenecks?: unknown[] })?.bottlenecks ?? [];
      const recsArr =
        (recs as { recommendations?: unknown[] })?.recommendations ?? [];
      setDiagnostics({
        bottlenecks: bnArr.length,
        recommendations: recsArr.length,
      });
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  const toggleMode = useCallback(
    async (mode: string) => {
      setLoading(true);
      setFeedback(null);
      try {
        const result = (await analysisApi.updateAutonomous({ mode })) as Record<
          string,
          unknown
        >;
        await refresh();
        // Show contextual feedback
        const auto = (result.autonomous ?? result) as Record<string, unknown>;
        const enabled = auto.enabled as boolean;
        if (mode === "off") {
          setFeedback("Autonomous mode disabled.");
        } else if (mode === "rl_agent") {
          setFeedback(
            enabled
              ? "RL Agent mode active. Actions will be selected when the RL model is loaded and bottlenecks are detected."
              : "RL Agent mode set but no trained model is loaded. Train a model first.",
          );
        } else {
          setFeedback(
            `${mode === "rule_based" ? "Rule-based" : "Threshold"} mode active. Recommendations will be auto-applied when bottlenecks are detected (every ${(auto.check_interval_sim_minutes as number) ?? 5} sim-minutes).`,
          );
        }
      } finally {
        setLoading(false);
      }
    },
    [refresh],
  );

  // Clear feedback after 8 seconds
  useEffect(() => {
    if (!feedback) return;
    const timer = setTimeout(() => setFeedback(null), 8000);
    return () => clearTimeout(timer);
  }, [feedback]);

  const currentMode = (settings?.mode as string) ?? "off";

  const modeDescriptions: Record<string, string> = {
    off: "No automatic decisions",
    rule_based: "Deterministic rules apply all qualifying recommendations",
    threshold: "Applies top recommendation only if confidence > threshold",
    rl_agent: "PPO-trained neural network selects optimal actions",
  };

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-bold text-white mb-2">
        Autonomous Operations
      </h3>
      <p className="text-[10px] text-gray-500 mb-3">
        {modeDescriptions[currentMode] ?? ""}
      </p>

      <div className="flex gap-2 mb-4">
        {(
          [
            { value: "off", label: "Off" },
            { value: "rule_based", label: "Rule-Based" },
            { value: "threshold", label: "Threshold" },
            { value: "rl_agent", label: "RL Agent" },
          ] as const
        ).map(({ value, label }) => (
          <button
            key={value}
            onClick={() => toggleMode(value)}
            disabled={loading}
            className={`text-xs px-3 py-1.5 rounded transition-colors ${
              currentMode === value
                ? "bg-blue-600 text-white"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {settings && (
        <div className="text-xs text-gray-400 space-y-1 mb-3">
          <div className="flex justify-between">
            <span>Confidence threshold</span>
            <span className="text-white">
              {((settings.confidence_threshold as number) ?? 0.8) * 100}%
            </span>
          </div>
          <div className="flex justify-between">
            <span>Interval</span>
            <span className="text-white">
              {(settings.interval_minutes as number) ??
                (settings.check_interval_sim_minutes as number) ??
                5}{" "}
              min
            </span>
          </div>
        </div>
      )}

      {/* Contextual feedback */}
      {feedback && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-blue-900/30 border border-blue-700/40 text-xs text-blue-300">
          {feedback}
        </div>
      )}

      {/* Recent actions — always visible for selected agent */}
      <div>
        <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          Recent Actions
          {currentMode !== "off" && (
            <span className="ml-2 text-gray-500 normal-case">
              ({currentMode.replace("_", " ")})
            </span>
          )}
        </div>
        {log.length > 0 ? (
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {(log as Record<string, unknown>[]).slice(0, 5).map((action, i) => (
              <div
                key={i}
                className="text-xs bg-gray-700 rounded px-2 py-1 flex justify-between"
              >
                <span className="text-gray-300 truncate">
                  {(action.description as string) ||
                    (action.action_type as string) ||
                    "Action"}
                </span>
                <span className="text-gray-400 ml-2 whitespace-nowrap">
                  {action.applied_at || action.sim_time
                    ? new Date(
                        (action.applied_at ?? action.sim_time) as string,
                      ).toLocaleTimeString()
                    : ""}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-gray-500 bg-gray-700/50 rounded px-3 py-2">
            {currentMode === "off"
              ? "Enable an autonomous mode to start collecting actions."
              : "No autonomous actions taken yet. Actions will appear here when the agent detects bottlenecks and applies recommendations."}
            {currentMode !== "off" && diagnostics && (
              <div className="mt-2 text-[10px] text-gray-400 space-y-0.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={
                      diagnostics.bottlenecks > 0
                        ? "text-amber-400"
                        : "text-gray-500"
                    }
                  >
                    ●
                  </span>
                  Active bottlenecks: {diagnostics.bottlenecks}
                  {diagnostics.bottlenecks === 0 &&
                    " — airport operating smoothly"}
                </div>
                <div className="flex items-center gap-1.5">
                  <span
                    className={
                      diagnostics.recommendations > 0
                        ? "text-blue-400"
                        : "text-gray-500"
                    }
                  >
                    ●
                  </span>
                  Active recommendations: {diagnostics.recommendations}
                  {diagnostics.recommendations === 0 &&
                    " — no actions to apply"}
                </div>
                {diagnostics.bottlenecks === 0 && (
                  <div className="text-gray-500 mt-1 italic">
                    Inject an incident or increase traffic to trigger
                    bottlenecks.
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
