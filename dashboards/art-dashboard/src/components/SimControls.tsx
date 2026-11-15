import { useState, useRef } from "react";
import { useSimStore } from "../stores/simStore";
import { simApi } from "../hooks/useApi";
import { useAccess } from "../hooks/auth";
import { Dialog } from "./Dialog";

export function SimControls() {
  const resetTrigger = useRef<HTMLButtonElement>(null);
  const access = useAccess();
  const publicDeployment = import.meta.env.VITE_PUBLIC_DEPLOYMENT === "true";
  const canChange =
    access.role !== "viewer" && (!publicDeployment || access.controlling);
  const { paused, speed_multiplier } = useSimStore((s) => s.status);
  const [busy, setBusy] = useState(false),
    [reset, setReset] = useState(false),
    [error, setError] = useState("");
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation action failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 items-center">
        <label className="text-sm">
          Simulation speed{" "}
          <select
            aria-label="Simulation speed"
            value={speed_multiplier}
            disabled={busy || !canChange}
            onChange={(e) => {
              const speed = Number(e.target.value);
              void run(async () => {
                await simApi.speed(speed);
                useSimStore.getState().setSpeed(speed);
              });
            }}
          >
            {[1, 10, 60, 600, 3600]
              .filter((s) => !publicDeployment || s <= 10)
              .map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
          </select>
        </label>
        <button
          className="btn-secondary"
          disabled={busy || !canChange}
          onClick={() =>
            void run(async () => {
              if (paused) await simApi.resume();
              else await simApi.pause();
              useSimStore.getState().setPaused(!paused);
            })
          }
        >
          {paused ? "Resume simulation" : "Pause simulation"}
        </button>
        <button
          className="btn-danger"
          disabled={busy || !canChange || publicDeployment}
          ref={resetTrigger}
          onClick={() => setReset(true)}
        >
          Reset shared airport
        </button>
      </div>
      {!canChange && (
        <p className="text-sm text-gray-400">
          Sign in as an operator and acquire control where enabled to change
          simulation settings.
        </p>
      )}
      {error && (
        <p role="alert" className="text-red-400">
          {error}
        </p>
      )}
      {reset && (
        <Dialog
          title="Reset shared airport?"
          returnFocus={resetTrigger.current}
          onClose={() => {
            if (!busy) setReset(false);
          }}
        >
          <p className="text-sm mb-4">
            This restarts the shared airport simulation and replaces its current
            operational state. Other viewers and operators will see the reset.
            Export any observations you need before continuing.
          </p>
          <button
            className="btn-danger"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await simApi.reset();
                window.location.reload();
              })
            }
          >
            {busy ? "Resetting…" : "Reset simulation"}
          </button>
          {error && <p role="alert">{error}</p>}
        </Dialog>
      )}
    </div>
  );
}
