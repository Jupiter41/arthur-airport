import { useState, useEffect, useCallback } from "react";
import { analysisApi, costsApi, incidentsApi } from "../hooks/useApi";

interface RecommendationItem {
  id: string;
  action_type: string;
  description: string;
  confidence_score: number;
  applied: boolean;
  expected_impact?: string;
}

const DEMO_PRESETS = [
  {
    label: "Runway Incursion",
    type: "runway_incursion",
    severity: "critical",
    location: "runway-09L",
    toast: "Runway incursion injected — monitoring autonomous response…",
  },
  {
    label: "Security Breach",
    type: "security_breach",
    severity: "high",
    location: "terminal-B",
    toast: "Security breach injected — monitoring autonomous response…",
  },
  {
    label: "System Failure",
    type: "system_failure",
    severity: "medium",
    location: "conveyor-C2",
    toast: "System failure injected — monitoring autonomous response…",
  },
] as const;

export function AutonomousPanel() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(
    null,
  );
  const [log, setLog] = useState<unknown[]>([]);
  const [diagnostics, setDiagnostics] = useState<{
    bottlenecks: number;
    recommendations: number;
    analysisAvailable: boolean;
  } | null>(null);
  const [recsList, setRecsList] = useState<RecommendationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [showInject, setShowInject] = useState(false);
  const [injecting, setInjecting] = useState(false);

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
    // Query both analysis-service and cost-service for maximum coverage
    let bnCount = 0;
    let recsCount = 0;
    let analysisAvailable = false;
    try {
      const [bn, recs] = await Promise.all([
        analysisApi.bottlenecks(),
        analysisApi.recommendations(),
      ]);
      const bnArr = (bn as { bottlenecks?: unknown[] })?.bottlenecks ?? [];
      const recsArr =
        (recs as { recommendations?: unknown[] })?.recommendations ?? [];
      bnCount = bnArr.length;
      recsCount = recsArr.length;
      analysisAvailable = true;
      // Store recommendations for display
      setRecsList(
        (recsArr as RecommendationItem[]).map((r) => ({
          id: r.id ?? "",
          action_type: r.action_type ?? "",
          description: r.description ?? "",
          confidence_score: r.confidence_score ?? 0,
          applied: r.applied ?? false,
          expected_impact: r.expected_impact,
        })),
      );
    } catch {
      /* analysis-service may be unavailable */
    }
    // Also query cost-service recommendations (always available)
    try {
      const costRecs = await costsApi.recommendations();
      const costRecsArr = Array.isArray(costRecs)
        ? costRecs
        : ((costRecs as Record<string, unknown>)?.recommendations as unknown[]) ?? [];
      if (costRecsArr.length > recsCount) {
        recsCount = costRecsArr.length;
      }
    } catch {
      /* cost-service may be unavailable */
    }
    setDiagnostics({
      bottlenecks: bnCount,
      recommendations: recsCount,
      analysisAvailable,
    });
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

  const injectDemoIncident = useCallback(
    async (preset: (typeof DEMO_PRESETS)[number]) => {
      setInjecting(true);
      try {
        await incidentsApi.inject({
          type: preset.type,
          severity: preset.severity,
          location: preset.location,
        });
        setFeedback(preset.toast);
        setShowInject(false);
        // Auto-refresh after 3 seconds to allow detection pipeline to react
        setTimeout(() => {
          refresh();
        }, 3000);
      } catch {
        setFeedback("Failed to inject incident — is the incident service running?");
      } finally {
        setInjecting(false);
      }
    },
    [refresh],
  );

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

      {/* Demo incident injection */}
      <div className="mb-3">
        <button
          onClick={() => setShowInject(!showInject)}
          className="text-xs px-3 py-1.5 rounded bg-red-900/40 text-red-300 hover:bg-red-900/60 border border-red-700/30 transition-colors"
        >
          {showInject ? "Cancel" : "⚡ Inject demo incident"}
        </button>
        {showInject && (
          <div className="mt-2 space-y-1">
            {DEMO_PRESETS.map((preset) => (
              <button
                key={preset.type}
                onClick={() => injectDemoIncident(preset)}
                disabled={injecting}
                className="w-full text-left text-xs px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors flex items-center justify-between disabled:opacity-50"
              >
                <span>{preset.label}</span>
                <span
                  className={`text-[10px] ${
                    preset.severity === "critical"
                      ? "text-red-400"
                      : preset.severity === "high"
                        ? "text-orange-400"
                        : "text-yellow-400"
                  }`}
                >
                  {preset.severity}
                </span>
              </button>
            ))}
          </div>
        )}
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
          </div>
        )}
      </div>

      {/* Active bottlenecks & recommendations — always visible when not off */}
      {currentMode !== "off" && diagnostics && (
        <div className="mt-3">
          <div className="text-[10px] text-gray-400 space-y-0.5 mb-2">
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
            {!diagnostics.analysisAvailable && (
              <div className="text-amber-500/70 mt-1 text-[10px]">
                ⚠ Analysis service not reachable — showing cost-based
                recommendations only.
              </div>
            )}
          </div>
          {/* Show pending (un-applied) recommendations */}
          {recsList.filter((r) => !r.applied).length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] text-blue-400 uppercase tracking-wide">
                Pending Recommendations
              </div>
              {recsList
                .filter((r) => !r.applied)
                .slice(0, 3)
                .map((rec) => (
                  <div
                    key={rec.id}
                    className="text-[11px] bg-blue-900/20 border border-blue-700/30 rounded px-2 py-1.5"
                  >
                    <div className="text-blue-200 truncate">
                      {rec.description}
                    </div>
                    <div className="text-[10px] text-blue-400/60 mt-0.5 flex justify-between">
                      <span>
                        Confidence: {Math.round(rec.confidence_score * 100)}%
                      </span>
                      {rec.expected_impact && (
                        <span className="text-gray-500 truncate ml-2">
                          {rec.expected_impact}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          )}
          {/* Applied recommendations (cooldown) */}
          {recsList.filter((r) => r.applied).length > 0 && (
            <div className="space-y-1 mt-2">
              <div className="text-[10px] text-green-400/70 uppercase tracking-wide">
                Applied (in cooldown)
              </div>
              {recsList
                .filter((r) => r.applied)
                .slice(0, 2)
                .map((rec) => (
                  <div
                    key={rec.id}
                    className="text-[11px] bg-green-900/10 border border-green-700/20 rounded px-2 py-1 text-green-300/60 truncate"
                  >
                    ✓ {rec.description}
                  </div>
                ))}
            </div>
          )}
          {diagnostics.bottlenecks === 0 && recsList.length === 0 && (
            <div className="text-gray-500 text-[10px] italic">
              Inject an incident or increase traffic to trigger bottlenecks.
            </div>
          )}
        </div>
      )}
      </div>
    );
}
