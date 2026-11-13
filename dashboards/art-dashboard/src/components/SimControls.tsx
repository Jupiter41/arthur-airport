import { useState, useCallback } from "react";
import { useSimStore } from "../stores/simStore";
import { simApi } from "../hooks/useApi";
import { useAccess } from "../hooks/auth";

const SPEEDS = [1, 10, 60, 600, 3600];

export function SimControls() {
  const access = useAccess();
  const publicDeployment = import.meta.env.VITE_PUBLIC_DEPLOYMENT === "true";
  const canChange = access.role !== "viewer" && (!publicDeployment || access.controlling);
  const { paused, speed_multiplier } = useSimStore((s) => s.status);
  const setPaused = useSimStore((s) => s.setPaused);
  const setSpeed = useSimStore((s) => s.setSpeed);
  const [loading, setLoading] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const handlePauseResume = useCallback(async () => {
    setLoading(true);
    try {
      if (paused) {
        await simApi.resume();
        setPaused(false);
      } else {
        await simApi.pause();
        setPaused(true);
      }
    } finally {
      setLoading(false);
    }
  }, [paused, setPaused]);

  const handleSpeed = useCallback(
    async (speed: number) => {
      setLoading(true);
      try {
        await simApi.speed(speed);
        setSpeed(speed);
      } finally {
        setLoading(false);
      }
    },
    [setSpeed],
  );

  const handleReset = useCallback(async () => {
    if (!confirmReset) {
      setConfirmReset(true);
      setTimeout(() => setConfirmReset(false), 5000);
      return;
    }
    setLoading(true);
    try {
      await simApi.reset();
      window.location.reload();
    } finally {
      setLoading(false);
      setConfirmReset(false);
    }
  }, [confirmReset]);

  return (
    <div className="flex items-center gap-2">
      {/* Speed selector */}
      <select
        className="bg-gray-700 text-white text-xs rounded px-2 py-1 border border-gray-600"
        value={speed_multiplier}
        onChange={(e) => handleSpeed(Number(e.target.value))}
        disabled={loading || !canChange}
      >
        {SPEEDS.filter(s => !publicDeployment || s <= 10).map((s) => (
          <option key={s} value={s}>
            {s}×
          </option>
        ))}
      </select>

      {/* Pause / Resume */}
      <button
        onClick={handlePauseResume}
        disabled={loading || !canChange}
        className={`text-xs font-bold px-2 py-1 rounded ${
          paused
            ? "bg-green-600 hover:bg-green-500 text-white"
            : "bg-amber-600 hover:bg-amber-500 text-white"
        }`}
      >
        {paused ? "▶ Resume" : "⏸ Pause"}
      </button>

      {/* Reset */}
      <button
        onClick={handleReset}
        disabled={loading || !canChange || publicDeployment}
        className={`text-xs font-bold px-2 py-1 rounded ${
          confirmReset
            ? "bg-red-600 hover:bg-red-500 text-white"
            : "bg-gray-600 hover:bg-gray-500 text-white"
        }`}
      >
        {confirmReset ? "Confirm Reset?" : "↺ Reset"}
      </button>
    </div>
  );
}
