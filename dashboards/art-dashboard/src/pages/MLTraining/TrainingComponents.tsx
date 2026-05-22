import { useState } from "react";
import type { TrainingRun, ModelFile } from "./types";

export function TrainingControl({
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

export function ModelRegistry({ models }: { models: ModelFile[] }) {
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

export function TrainingHistory({ runs }: { runs: TrainingRun[] }) {
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
