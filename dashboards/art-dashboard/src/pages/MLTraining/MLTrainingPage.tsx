import { useState, useEffect, useCallback } from "react";
import { analysisApi } from "../../hooks/useApi";

/* ──────── Types ──────── */
interface TrainingRun {
  id: string;
  model_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  progress_pct: number;
  total_timesteps: number;
  current_timesteps: number;
  metrics: Record<string, unknown>;
  error: string | null;
  output_path: string | null;
}

interface ModelFile {
  path: string;
  size_bytes: number;
  modified_at: string;
}

interface TrainingStatus {
  active_run: TrainingRun | null;
  history: TrainingRun[];
  available_models: ModelFile[];
}

/* ──────── Training Control Panel ──────── */
function TrainingControl({
  activeRun,
  onStart,
  onStop,
}: {
  activeRun: TrainingRun | null;
  onStart: (type: string, timesteps: number) => void;
  onStop: () => void;
}) {
  const [modelType, setModelType] = useState("rl");
  const [timesteps, setTimesteps] = useState(50000);
  const isRunning = activeRun?.status === "running";

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-bold text-white mb-4">Start Training</h3>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="text-xs text-gray-400 block mb-1">Model Type</label>
          <select
            className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600 disabled:opacity-50"
            value={modelType}
            onChange={(e) => setModelType(e.target.value)}
            disabled={isRunning}
          >
            <option value="rl">RL Agent (PPO)</option>
            <option value="anomaly">Anomaly Detector</option>
            <option value="forecast">Queue Forecaster</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Timesteps</label>
          <input
            type="number"
            min={1000}
            max={1000000}
            step={1000}
            value={timesteps}
            onChange={(e) => setTimesteps(Number(e.target.value))}
            disabled={isRunning}
            className="w-full bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600 disabled:opacity-50"
          />
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onStart(modelType, timesteps)}
          disabled={isRunning}
          className="flex-1 text-sm font-bold px-4 py-2.5 rounded bg-green-600 text-white hover:bg-green-500 disabled:bg-gray-600 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? "Training in progress..." : "Start Training"}
        </button>
        {isRunning && (
          <button
            onClick={onStop}
            className="text-sm font-bold px-4 py-2.5 rounded bg-red-600 text-white hover:bg-red-500 transition-colors"
          >
            Stop
          </button>
        )}
      </div>

      {/* Active run progress */}
      {activeRun && activeRun.status === "running" && (
        <div className="mt-4 bg-gray-900 rounded p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-400">
              {activeRun.model_type.toUpperCase()} Training
            </span>
            <span className="text-xs text-blue-400 font-mono">
              {activeRun.progress_pct.toFixed(1)}%
            </span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-2.5">
            <div
              className="bg-blue-500 h-2.5 rounded-full transition-all duration-1000 animate-pulse"
              style={{ width: `${Math.min(100, activeRun.progress_pct)}%` }}
            />
          </div>
          <div className="flex items-center justify-between mt-2 text-[10px] text-gray-400">
            <span>
              {activeRun.current_timesteps.toLocaleString()} /{" "}
              {activeRun.total_timesteps.toLocaleString()} steps
            </span>
            <span>
              Started:{" "}
              {activeRun.started_at
                ? new Date(activeRun.started_at).toLocaleTimeString()
                : "—"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ──────── Autonomous Mode Panel ──────── */
function AutonomousPanel() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(
    null,
  );
  const [log, setLog] = useState<unknown[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        analysisApi.autonomousSettings(),
        analysisApi.autonomousLog(10),
      ]);
      setSettings(s as Record<string, unknown>);
      setLog((l as { actions: unknown[] }).actions ?? []);
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
      try {
        await analysisApi.updateAutonomous({ mode });
        await refresh();
      } finally {
        setLoading(false);
      }
    },
    [refresh],
  );

  const currentMode = (settings?.mode as string) ?? "off";

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-bold text-white mb-3">
        Autonomous Operations
      </h3>

      <div className="flex gap-2 mb-4">
        {["off", "rule", "threshold", "rl_agent"].map((mode) => (
          <button
            key={mode}
            onClick={() => toggleMode(mode)}
            disabled={loading}
            className={`text-xs px-3 py-1.5 rounded transition-colors ${
              currentMode === mode
                ? "bg-blue-600 text-white"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600"
            }`}
          >
            {mode === "off"
              ? "Off"
              : mode === "rl_agent"
                ? "RL Agent"
                : mode.charAt(0).toUpperCase() + mode.slice(1)}
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
              {(settings.interval_minutes as number) ?? 5} min
            </span>
          </div>
        </div>
      )}

      {/* Recent actions */}
      {log.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Recent Actions
          </div>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {(log as Record<string, unknown>[]).slice(0, 5).map((action, i) => (
              <div
                key={i}
                className="text-xs bg-gray-700 rounded px-2 py-1 flex justify-between"
              >
                <span className="text-gray-300 truncate">
                  {action.description as string}
                </span>
                <span className="text-gray-400 ml-2 whitespace-nowrap">
                  {action.sim_time
                    ? new Date(action.sim_time as string).toLocaleTimeString()
                    : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ──────── Model Registry ──────── */
function ModelRegistry({ models }: { models: ModelFile[] }) {
  if (models.length === 0) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-bold text-white mb-3">Trained Models</h3>
        <div className="text-xs text-gray-400">
          No trained models found. Start a training run to generate one.
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-bold text-white mb-3">
        Trained Models ({models.length})
      </h3>
      <div className="space-y-2">
        {models.map((m) => (
          <div
            key={m.path}
            className="bg-gray-700 rounded p-2 text-xs flex items-center justify-between"
          >
            <div>
              <span className="text-white font-mono">{m.path}</span>
              <div className="text-gray-400 mt-0.5">
                {(m.size_bytes / 1024).toFixed(1)} KB ·{" "}
                {new Date(m.modified_at).toLocaleString()}
              </div>
            </div>
            <span className="text-green-400 text-[10px]">Ready</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Training History ──────── */
function TrainingHistory({ runs }: { runs: TrainingRun[] }) {
  if (runs.length === 0) return null;

  const STATUS_COLORS: Record<string, string> = {
    completed: "text-green-400",
    running: "text-blue-400",
    failed: "text-red-400",
    stopped: "text-amber-400",
    queued: "text-gray-400",
  };

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-bold text-white mb-3">Training History</h3>
      <div className="space-y-2">
        {runs.map((run) => (
          <div key={run.id} className="bg-gray-700 rounded p-3 text-xs">
            <div className="flex items-center justify-between mb-1">
              <span className="text-white font-bold">
                {run.model_type.toUpperCase()} —{" "}
                {run.total_timesteps.toLocaleString()} steps
              </span>
              <span
                className={`font-bold uppercase ${STATUS_COLORS[run.status] ?? "text-gray-400"}`}
              >
                {run.status}
              </span>
            </div>
            <div className="text-gray-400">
              {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
              {run.completed_at &&
                ` → ${new Date(run.completed_at).toLocaleTimeString()}`}
            </div>
            {run.error && (
              <div className="text-red-400 mt-1 text-[10px] truncate">
                {run.error}
              </div>
            )}
            {run.metrics && Object.keys(run.metrics).length > 0 && (
              <div className="text-gray-400 mt-1">
                {Object.entries(run.metrics).map(([k, v]) => (
                  <span key={k} className="mr-3">
                    {k}: <span className="text-white">{String(v)}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── LLM Config Panel ──────── */
function LLMConfigPanel() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    analysisApi
      .llmConfig()
      .then((c) => setConfig(c as Record<string, unknown>))
      .catch(() => {});
  }, []);

  if (!config) return null;

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-bold text-white mb-3">LLM Configuration</h3>
      <div className="text-xs text-gray-400 space-y-1">
        {Object.entries(config).map(([k, v]) => (
          <div key={k} className="flex justify-between">
            <span>{k}</span>
            <span className="text-white">
              {typeof v === "boolean" ? (v ? "Yes" : "No") : String(v ?? "—")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Main Page ──────── */
export default function MLTrainingPage() {
  const [status, setStatus] = useState<TrainingStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = (await analysisApi.trainingStatus()) as TrainingStatus;
      setStatus(s);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleStart = useCallback(
    async (type: string, timesteps: number) => {
      await analysisApi.trainingStart(type, timesteps);
      await refresh();
    },
    [refresh],
  );

  const handleStop = useCallback(async () => {
    await analysisApi.trainingStop();
    await refresh();
  }, [refresh]);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <h2 className="text-lg font-bold text-white">ML & Agent Training</h2>

      <div className="grid grid-cols-2 gap-4">
        <TrainingControl
          activeRun={status?.active_run ?? null}
          onStart={handleStart}
          onStop={handleStop}
        />
        <AutonomousPanel />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <ModelRegistry models={status?.available_models ?? []} />
        <LLMConfigPanel />
      </div>

      <TrainingHistory runs={status?.history ?? []} />
    </div>
  );
}
