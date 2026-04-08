import { useState, useCallback } from "react";
import { analysisApi } from "../../hooks/useApi";

interface KPIProjection {
  action_index: number;
  delay_minutes_total: number;
  missed_connections: number;
  avg_queue_depth: number;
  cascade_depth: number;
  gate_utilisation_pct: number;
  baggage_throughput_pct: number;
  confidence: number;
}

interface WhatIfResult {
  baseline: KPIProjection;
  projections: KPIProjection[];
  sim_time_at_request: string;
  horizon_minutes: number;
}

const ACTION_OPTIONS = [
  { value: "open_security_lane", label: "Open security lane" },
  { value: "early_gate_call", label: "Early gate call" },
  { value: "redirect_checkin", label: "Redirect check-in" },
  { value: "reassign_gate", label: "Reassign gate" },
  { value: "delay_taxi", label: "Delay taxi" },
  { value: "hold_connecting_flight", label: "Hold connecting flight" },
  { value: "fast_track_passengers", label: "Fast-track passengers" },
  { value: "rebook_passengers", label: "Rebook passengers" },
  { value: "ground_delay_program", label: "Ground delay program" },
  { value: "redistribute_vehicles", label: "Redistribute vehicles" },
  { value: "redirect_baggage", label: "Redirect baggage" },
  { value: "expedite_loading", label: "Expedite loading" },
];

function KPIBar({
  label,
  baseline,
  projected,
  unit,
  lowerIsBetter,
}: {
  label: string;
  baseline: number;
  projected: number;
  unit: string;
  lowerIsBetter: boolean;
}) {
  const delta = projected - baseline;
  const improved = lowerIsBetter ? delta < 0 : delta > 0;
  const color = improved ? "text-green-400" : delta === 0 ? "text-gray-400" : "text-red-400";
  const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : "→";

  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-gray-400">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">{baseline.toFixed(1)}{unit}</span>
        <span className="text-xs text-gray-600">→</span>
        <span className={`text-xs font-bold ${color}`}>
          {projected.toFixed(1)}{unit} {arrow}
        </span>
      </div>
    </div>
  );
}

export default function WhatIfPanel() {
  const [actions, setActions] = useState([
    { action_type: "open_security_lane", description: "", parameters: {} },
  ]);
  const [horizon, setHorizon] = useState(60);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const addAction = useCallback(() => {
    if (actions.length >= 3) return;
    setActions([...actions, { action_type: "open_security_lane", description: "", parameters: {} }]);
  }, [actions]);

  const removeAction = useCallback(
    (index: number) => {
      if (actions.length <= 1) return;
      setActions(actions.filter((_, i) => i !== index));
    },
    [actions],
  );

  const runWhatIf = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await analysisApi.whatIf({
        actions: actions.map((a) => ({
          action_type: a.action_type,
          description: a.description,
          parameters: a.parameters,
        })),
        horizon_minutes: horizon,
      });
      setResult(data as WhatIfResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : "What-if analysis failed");
    } finally {
      setLoading(false);
    }
  }, [actions, horizon]);

  return (
    <div className="bg-gray-800 rounded p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-white">What-If Analysis</h3>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-400">Horizon:</label>
          <select
            className="bg-gray-700 text-white text-xs rounded px-2 py-1"
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
          >
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>60 min</option>
            <option value={90}>90 min</option>
            <option value={120}>120 min</option>
          </select>
        </div>
      </div>

      {/* Action inputs */}
      {actions.map((action, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="text-xs text-gray-400 w-4">{i + 1}.</span>
          <select
            className="bg-gray-700 text-white text-xs rounded px-2 py-1 flex-1"
            value={action.action_type}
            onChange={(e) => {
              const updated = [...actions];
              updated[i] = { ...updated[i], action_type: e.target.value };
              setActions(updated);
            }}
          >
            {ACTION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {actions.length > 1 && (
            <button
              className="text-xs text-red-400 hover:text-red-300"
              onClick={() => removeAction(i)}
            >
              ✕
            </button>
          )}
        </div>
      ))}

      <div className="flex items-center gap-2">
        {actions.length < 3 && (
          <button
            className="text-xs text-blue-400 hover:text-blue-300"
            onClick={addAction}
          >
            + Add action
          </button>
        )}
        <div className="flex-1" />
        <button
          className="text-xs font-bold px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
          disabled={loading}
          onClick={runWhatIf}
        >
          {loading ? "Running..." : "Run Projection"}
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2">
          {error}
        </div>
      )}

      {/* P2-3-4: Multi-action comparison table */}
      {result && (
        <div className="space-y-3">
          <div className="text-xs text-gray-400">
            Projection at {new Date(result.sim_time_at_request).toLocaleTimeString()} +{result.horizon_minutes} min
          </div>

          <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${result.projections.length + 1}, 1fr)` }}>
            {/* Baseline column */}
            <div className="bg-gray-900/50 rounded p-3">
              <div className="text-xs font-bold text-gray-400 mb-2">Baseline</div>
              <KPIBar label="Delay" baseline={result.baseline.delay_minutes_total} projected={result.baseline.delay_minutes_total} unit=" min" lowerIsBetter />
              <KPIBar label="Missed conn." baseline={result.baseline.missed_connections} projected={result.baseline.missed_connections} unit="" lowerIsBetter />
              <KPIBar label="Avg queue" baseline={result.baseline.avg_queue_depth} projected={result.baseline.avg_queue_depth} unit="" lowerIsBetter />
              <KPIBar label="Gate util." baseline={result.baseline.gate_utilisation_pct} projected={result.baseline.gate_utilisation_pct} unit="%" lowerIsBetter={false} />
              <div className="mt-2 flex items-center gap-1">
                <div className="w-12 h-1 bg-gray-700 rounded-full overflow-hidden">
                  <div className="h-full bg-gray-500 rounded-full" style={{ width: `${result.baseline.confidence * 100}%` }} />
                </div>
                <span className="text-[10px] text-gray-400">{(result.baseline.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>

            {/* Projection columns */}
            {result.projections.map((proj, i) => (
              <div key={i} className="bg-gray-900/50 rounded p-3 ring-1 ring-blue-500/30">
                <div className="text-xs font-bold text-blue-400 mb-2">
                  Action {i + 1}: {ACTION_OPTIONS.find((o) => o.value === actions[i]?.action_type)?.label ?? "Unknown"}
                </div>
                <KPIBar label="Delay" baseline={result.baseline.delay_minutes_total} projected={proj.delay_minutes_total} unit=" min" lowerIsBetter />
                <KPIBar label="Missed conn." baseline={result.baseline.missed_connections} projected={proj.missed_connections} unit="" lowerIsBetter />
                <KPIBar label="Avg queue" baseline={result.baseline.avg_queue_depth} projected={proj.avg_queue_depth} unit="" lowerIsBetter />
                <KPIBar label="Gate util." baseline={result.baseline.gate_utilisation_pct} projected={proj.gate_utilisation_pct} unit="%" lowerIsBetter={false} />
                <div className="mt-2 flex items-center gap-1">
                  <div className="w-12 h-1 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${proj.confidence >= 0.7 ? "bg-green-500" : "bg-amber-500"}`}
                      style={{ width: `${proj.confidence * 100}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-gray-400">{(proj.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
