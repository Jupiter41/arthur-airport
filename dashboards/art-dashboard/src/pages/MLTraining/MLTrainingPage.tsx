import { useState, useEffect, useCallback } from "react";
import { analysisApi } from "../../hooks/useApi";
import { AutonomousPanel } from "../../components/AutonomousPanel";
import { TrainingControl, ModelRegistry, TrainingHistory } from "./TrainingComponents";
import { LLMConfigPanel, EnvironmentConfigPanel } from "./ConfigPanels";
import type { TrainingStatus } from "./types";

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
