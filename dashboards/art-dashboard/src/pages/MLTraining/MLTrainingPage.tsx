import { useState, useEffect, useCallback } from "react";
import { analysisApi } from "../../hooks/useApi";
import { AutonomousPanel } from "../../components/AutonomousPanel";

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

/* ──────── Training Environment Config ──────── */
interface TrainingConfig {
  rl_model_path: string;
  rl_model_exists: boolean;
  rl_model_loaded: boolean;
  models_dir: string;
  models_dir_exists: boolean;
  model_files: string[];
  env: Record<string, string>;
}

function EnvironmentConfigPanel() {
  const [config, setConfig] = useState<TrainingConfig | null>(null);

  useEffect(() => {
    analysisApi
      .trainingConfig()
      .then((c) => setConfig(c as TrainingConfig))
      .catch(() => {});
    const interval = setInterval(() => {
      analysisApi
        .trainingConfig()
        .then((c) => setConfig(c as TrainingConfig))
        .catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  if (!config) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-bold text-white mb-3">
          Environment & Models
        </h3>
        <div className="text-xs text-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-bold text-white mb-4">
        Environment & Models
      </h3>

      {/* RL Model Status */}
      <div className="mb-4">
        <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          RL Agent
        </div>
        <div className="bg-gray-900 rounded p-3 space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Model path</span>
            <span className="text-white font-mono text-[10px] truncate ml-2 max-w-[200px]">
              {config.rl_model_path}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">File exists</span>
            <span
              className={
                config.rl_model_exists ? "text-green-400" : "text-red-400"
              }
            >
              {config.rl_model_exists ? "Yes" : "No"}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Loaded in memory</span>
            <span
              className={
                config.rl_model_loaded ? "text-green-400" : "text-amber-400"
              }
            >
              {config.rl_model_loaded ? "Active" : "Not loaded"}
            </span>
          </div>
          {!config.rl_model_exists && (
            <div className="text-[10px] text-amber-400 mt-1">
              Train an RL model to enable the RL Agent autonomous mode.
            </div>
          )}
          {!config.rl_model_exists && (
            <div className="text-[10px] text-gray-500 mt-1">
              The RL model is considered trained when{" "}
              <span className="font-mono text-gray-400">best_model.zip</span>{" "}
              and <span className="font-mono text-gray-400">rl_policy.zip</span>{" "}
              files are created in the models directory.
            </div>
          )}
          {config.rl_model_exists && !config.rl_model_loaded && (
            <div className="text-[10px] text-blue-400 mt-1">
              Model is on disk. It will be loaded on next service restart or
              when RL Agent mode is activated.
            </div>
          )}
        </div>
      </div>

      {/* Model Files */}
      {config.model_files.length > 0 && (
        <div className="mb-4">
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Models directory
          </div>
          <div className="bg-gray-900 rounded p-2 space-y-1">
            {config.model_files.map((f) => (
              <div
                key={f}
                className="text-[10px] text-gray-300 font-mono flex items-center gap-1.5"
              >
                <span className="text-green-400">●</span>
                {f}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Environment Variables */}
      <div>
        <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          Environment Variables
        </div>
        <div className="space-y-1">
          {Object.entries(config.env).map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs">
              <span className="text-gray-400 font-mono text-[10px]">{k}</span>
              <span
                className={`font-mono text-[10px] ${v === "(not set)" ? "text-gray-600" : "text-white"}`}
              >
                {v}
              </span>
            </div>
          ))}
        </div>
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
        <EnvironmentConfigPanel />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <LLMConfigPanel />
      </div>

      <TrainingHistory runs={status?.history ?? []} />
    </div>
  );
}
