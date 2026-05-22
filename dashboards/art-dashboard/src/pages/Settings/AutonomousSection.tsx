import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { analysisApi } from "../../hooks/useApi";
import { NumberInput } from "./FormControls";
import type { AutonomousMode, AutonomousState } from "./types";

export function AutonomousSection() {
  const queryClient = useQueryClient();

  const { data: autoSettings } = useQuery<AutonomousState>({
    queryKey: ["analysis-autonomous"],
    queryFn: async () => {
      const res = (await analysisApi.autonomousSettings()) as {
        autonomous: AutonomousState;
      };
      return res.autonomous;
    },
    retry: 1,
    refetchInterval: 30_000,
  });

  const { data: autoLog } = useQuery({
    queryKey: ["analysis-autonomous-log"],
    queryFn: async () => {
      const res = await analysisApi.autonomousLog(10);
      return res.actions ?? [];
    },
    retry: 1,
    refetchInterval: 15_000,
  });

  const [localAuto, setLocalAuto] = useState<AutonomousState | null>(null);
  const [autoSaved, setAutoSaved] = useState(false);

  useEffect(() => {
    if (autoSettings && !localAuto) {
      setLocalAuto(autoSettings);
    }
  }, [autoSettings, localAuto]);

  const autoMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      analysisApi.updateAutonomous(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analysis-autonomous"] });
      setAutoSaved(true);
      setTimeout(() => setAutoSaved(false), 2000);
    },
  });

  if (!localAuto) return null;

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">
          🤖 Autonomous Operations
        </h2>
        <div className="flex items-center gap-2">
          {autoSaved && (
            <span className="text-green-400 text-sm animate-pulse">
              ✓ Saved
            </span>
          )}
          <button
            className="px-3 py-1.5 text-sm rounded font-semibold bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40"
            disabled={autoMutation.isPending}
            onClick={() => autoMutation.mutate({ ...localAuto })}
          >
            {autoMutation.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Autonomous Mode
          </label>
          <select
            className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-white"
            value={localAuto.mode ?? (localAuto.enabled ? "threshold" : "off")}
            onChange={(e) => {
              const mode = e.target.value as AutonomousMode;
              setLocalAuto({
                ...localAuto,
                mode,
                enabled: mode !== "off",
              });
            }}
          >
            <option value="off">Off</option>
            <option value="rule_based">Rule-based</option>
            <option value="threshold">Threshold</option>
            <option value="rl_agent">RL Agent (PPO)</option>
          </select>
        </div>
        <NumberInput
          label="Confidence threshold"
          value={localAuto.confidence_threshold}
          onChange={(v) =>
            setLocalAuto({ ...localAuto, confidence_threshold: v })
          }
          min={0.5}
          max={1.0}
          step={0.05}
        />
        <NumberInput
          label="Check interval"
          value={localAuto.check_interval_sim_minutes}
          onChange={(v) =>
            setLocalAuto({ ...localAuto, check_interval_sim_minutes: v })
          }
          min={1}
          max={30}
          unit="min"
        />
      </div>

      {localAuto.enabled && (
        <div className="bg-amber-900/20 border border-amber-600/30 rounded p-3">
          <p className="text-xs text-amber-300">
            ⚠ Autonomous mode ({localAuto.mode ?? "threshold"}) will auto-apply
            recommendations with confidence ≥{" "}
            {(localAuto.confidence_threshold * 100).toFixed(0)}% every{" "}
            {localAuto.check_interval_sim_minutes} sim-minutes.
            {localAuto.mode === "rl_agent" &&
              " RL agent uses a PPO-trained policy — ensure RL_MODEL_PATH is configured."}{" "}
            Flight cancellation, runway closure, and GDP actions always require
            human confirmation.
          </p>
        </div>
      )}

      {autoLog && (autoLog as unknown[]).length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs text-gray-400 uppercase tracking-wide">
            Recent Autonomous Actions
          </h3>
          {(autoLog as Array<Record<string, unknown>>).map((a, i) => (
            <div
              key={(a.id as string) ?? i}
              className="bg-gray-900/50 rounded p-2 flex items-center justify-between"
            >
              <div>
                <span className="text-xs text-white">
                  {a.action_type as string}
                </span>
                <span className="text-xs text-gray-400 ml-2">
                  {a.description as string}
                </span>
              </div>
              <span className="text-xs text-gray-400">
                conf: {((a.confidence_score as number) * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
