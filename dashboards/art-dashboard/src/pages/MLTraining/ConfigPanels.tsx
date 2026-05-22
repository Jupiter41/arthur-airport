import { useState, useEffect } from "react";
import { analysisApi } from "../../hooks/useApi";
import type { TrainingConfig } from "./types";

export function LLMConfigPanel() {
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

export function EnvironmentConfigPanel() {
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
