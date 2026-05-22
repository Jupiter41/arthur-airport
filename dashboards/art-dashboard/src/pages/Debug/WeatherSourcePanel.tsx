import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { weatherApi } from "../../hooks/useApi";

export function WeatherSourcePanel() {
  const [source, setSource] = useState("simulated");
  const [csvPath, setCsvPath] = useState("");
  const [liveIcao, setLiveIcao] = useState("EGLL");
  const [result, setResult] = useState<string | null>(null);

  // Override state
  const [overrides, setOverrides] = useState<Record<string, number | null>>({
    visibility_m: null,
    wind_speed_kt: null,
    ceiling_ft: null,
    temperature_c: null,
  });

  const { data: currentSource } = useQuery({
    queryKey: ["weather-source"],
    queryFn: () => weatherApi.source(),
    refetchInterval: 10000,
  });

  const switchMutation = useMutation({
    mutationFn: () =>
      weatherApi.switchSource(
        source,
        csvPath || undefined,
        liveIcao || undefined,
      ),
    onSuccess: (data) => setResult(JSON.stringify(data, null, 2)),
    onError: (err) => setResult(`Error: ${(err as Error).message}`),
  });

  const overrideMutation = useMutation({
    mutationFn: () => weatherApi.setOverrides(overrides),
    onSuccess: (data) => setResult(JSON.stringify(data, null, 2)),
    onError: (err) => setResult(`Error: ${(err as Error).message}`),
  });

  return (
    <div className="space-y-4">
      {/* Current source */}
      <div className="bg-gray-900 rounded p-3">
        <h4 className="text-xs text-gray-400 font-semibold mb-1">
          Current Source
        </h4>
        <pre className="text-xs text-green-400 font-mono">
          {currentSource
            ? JSON.stringify(currentSource, null, 2)
            : "Loading..."}
        </pre>
      </div>

      {/* Source switcher */}
      <div className="space-y-3">
        <h4 className="text-sm text-gray-400 font-semibold">
          Switch Weather Source
        </h4>
        <div className="flex items-center gap-2">
          <select
            className="bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="simulated">Simulated (FSM)</option>
            <option value="historical">Historical (CSV replay)</option>
            <option value="live">Live (ADDS API)</option>
          </select>
        </div>

        {source === "historical" && (
          <input
            className="w-full bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
            placeholder="CSV path (e.g. /app/data/weather/EGLL_30days.csv)"
            value={csvPath}
            onChange={(e) => setCsvPath(e.target.value)}
          />
        )}

        {source === "live" && (
          <input
            className="w-full bg-gray-700 text-white text-sm rounded px-2 py-1.5 border border-gray-600"
            placeholder="ICAO station (e.g. EGLL, LFPG)"
            value={liveIcao}
            onChange={(e) => setLiveIcao(e.target.value)}
          />
        )}

        <button
          onClick={() => switchMutation.mutate()}
          disabled={switchMutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-semibold
                     hover:bg-blue-500 disabled:opacity-40"
        >
          {switchMutation.isPending ? "Switching..." : "Switch Source"}
        </button>
      </div>

      {/* Parameter overrides */}
      <div className="space-y-3">
        <h4 className="text-sm text-gray-400 font-semibold">
          Parameter Overrides
        </h4>
        <p className="text-xs text-gray-400">
          Lock individual parameters regardless of active source. Leave empty to
          unlock.
        </p>

        {(
          [
            "visibility_m",
            "wind_speed_kt",
            "ceiling_ft",
            "temperature_c",
          ] as const
        ).map((key) => (
          <div key={key} className="flex items-center gap-2">
            <label className="text-xs text-gray-400 w-28 font-mono">
              {key}
            </label>
            <input
              type="number"
              className="w-28 bg-gray-700 text-white text-sm rounded px-2 py-1 border border-gray-600"
              placeholder="unlocked"
              value={overrides[key] ?? ""}
              onChange={(e) =>
                setOverrides((prev) => ({
                  ...prev,
                  [key]: e.target.value === "" ? null : Number(e.target.value),
                }))
              }
            />
          </div>
        ))}

        <button
          onClick={() => overrideMutation.mutate()}
          disabled={overrideMutation.isPending}
          className="px-4 py-2 bg-amber-600 text-white rounded text-sm font-semibold
                     hover:bg-amber-500 disabled:opacity-40"
        >
          {overrideMutation.isPending ? "Applying..." : "Apply Overrides"}
        </button>
      </div>

      {result && (
        <pre className="bg-gray-900 text-green-400 text-xs p-3 rounded overflow-auto max-h-32 font-mono">
          {result}
        </pre>
      )}
    </div>
  );
}
