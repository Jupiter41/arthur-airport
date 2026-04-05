import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { simApi, analysisApi } from "../../hooks/useApi";

/* ──────── Types ──────── */

interface SimSettings {
  daily_flights: number;
  load_factor_mean: number;
  pax_multiplier: number;
  special_event: string | null;
  weather_lock: string | null;
  wind_kt: number;
  gust_enabled: boolean;
  runway_incursion_rate: number;
  baggage_fire_rate: number;
  security_breach_rate: number;
  system_failure_rate: number;
  suppression_window_h: number;
  lanes_a: number;
  lanes_b: number;
  lanes_c: number;
  mct_minutes: number;
  screening_units: number;
  sorting_capacity: number;
  dg_false_positive_rate: number;
}

interface SimStatus {
  running: boolean;
  paused: boolean;
  sim_time: string;
  speed_multiplier: number;
  day_number: number;
}

/* ──────── Small reusable inputs ──────── */

function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  unit,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  unit?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-gray-300">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          className="w-20 bg-gray-700 text-white text-right rounded px-2 py-1 text-sm
                     border border-gray-600 focus:border-blue-400 focus:outline-none"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {unit && <span className="text-xs text-gray-500 w-8">{unit}</span>}
      </div>
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-gray-300">{label}</span>
      <button
        className={`w-10 h-5 rounded-full transition-colors relative ${checked ? "bg-blue-500" : "bg-gray-600"}`}
        onClick={() => onChange(!checked)}
      >
        <span
          className={`block w-4 h-4 rounded-full bg-white absolute top-0.5 transition-transform ${checked ? "translate-x-5" : "translate-x-0.5"}`}
        />
      </button>
    </div>
  );
}

function SelectInput({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-gray-300">{label}</span>
      <select
        className="bg-gray-700 text-white text-sm rounded px-2 py-1 border border-gray-600
                   focus:border-blue-400 focus:outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ──────── Section wrapper ──────── */

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <span>{icon}</span>
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

/* ──────── Speed selector ──────── */

const SPEEDS = [1, 10, 60, 600, 3600];

function SpeedSelector({
  current,
  onChange,
}: {
  current: number;
  onChange: (s: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-gray-300">Speed</span>
      <div className="flex gap-1">
        {SPEEDS.map((s) => (
          <button
            key={s}
            onClick={() => onChange(s)}
            className={`px-2 py-1 text-xs rounded font-mono transition-colors ${
              current === s
                ? "bg-blue-500 text-white"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600"
            }`}
          >
            {s >= 3600 ? `${s / 3600}h` : s >= 60 ? `${s}×` : `${s}×`}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ──────── Main page ──────── */

const WEATHER_OPTIONS = [
  { value: "", label: "FSM (auto)" },
  { value: "CAVOK", label: "CAVOK" },
  { value: "VMC", label: "VMC" },
  { value: "IMC", label: "IMC" },
  { value: "LIFR", label: "LIFR" },
];

export default function SettingsPage() {
  const queryClient = useQueryClient();

  const { data: status } = useQuery<SimStatus>({
    queryKey: ["sim-status"],
    queryFn: () => simApi.status() as Promise<SimStatus>,
    refetchInterval: 3000,
  });

  const { data: serverSettings, isLoading } = useQuery<SimSettings>({
    queryKey: ["sim-settings"],
    queryFn: () => simApi.settings() as Promise<SimSettings>,
  });

  const [local, setLocal] = useState<SimSettings | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  // Sync server → local on first load
  useEffect(() => {
    if (serverSettings && !local) {
      setLocal(serverSettings);
    }
  }, [serverSettings, local]);

  const patch = useCallback(
    <K extends keyof SimSettings>(key: K, value: SimSettings[K]) => {
      setLocal((prev) => (prev ? { ...prev, [key]: value } : prev));
      setDirty(true);
      setSaved(false);
    },
    [],
  );

  const mutation = useMutation({
    mutationFn: (body: Partial<SimSettings>) => simApi.updateSettings(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sim-settings"] });
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const speedMutation = useMutation({
    mutationFn: (speed: number) => simApi.speed(speed),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["sim-status"] }),
  });

  const pauseMutation = useMutation({
    mutationFn: () => (status?.paused ? simApi.resume() : simApi.pause()),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["sim-status"] }),
  });

  const handleApply = () => {
    if (!local) return;
    // Only send changed fields
    const diff: Record<string, unknown> = {};
    if (serverSettings) {
      for (const key of Object.keys(local) as (keyof SimSettings)[]) {
        if (local[key] !== serverSettings[key]) {
          diff[key] = local[key];
        }
      }
    } else {
      Object.assign(diff, local);
    }
    if (Object.keys(diff).length > 0) {
      mutation.mutate(diff as Partial<SimSettings>);
    } else {
      setDirty(false);
    }
  };

  const handleReset = () => {
    if (serverSettings) {
      setLocal(serverSettings);
      setDirty(false);
    }
  };

  if (isLoading || !local) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        Loading settings…
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          ⚙️ Simulation Settings
        </h1>
        <div className="flex items-center gap-2">
          {saved && (
            <span className="text-green-400 text-sm animate-pulse">
              ✓ Saved
            </span>
          )}
          {mutation.isError && (
            <span className="text-red-400 text-sm">
              Error: {(mutation.error as Error).message}
            </span>
          )}
          <button
            onClick={handleReset}
            disabled={!dirty}
            className="px-3 py-1.5 text-sm rounded bg-gray-700 text-gray-300
                       hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Reset
          </button>
          <button
            onClick={handleApply}
            disabled={!dirty || mutation.isPending}
            className="px-4 py-1.5 text-sm rounded font-semibold transition-colors
                       bg-blue-600 text-white hover:bg-blue-500
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? "Applying…" : "Apply"}
          </button>
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {/* ── Time & Speed ── */}
        <Section title="Time & Speed" icon="⏱️">
          <SpeedSelector
            current={status?.speed_multiplier ?? 60}
            onChange={(s) => speedMutation.mutate(s)}
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-gray-300">Day</span>
            <span className="text-sm font-mono text-white">
              {status?.day_number ?? "–"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-gray-300">Sim Time</span>
            <span className="text-sm font-mono text-white">
              {status?.sim_time
                ? new Date(status.sim_time).toLocaleTimeString()
                : "–"}
            </span>
          </div>
          <Toggle
            label="Paused"
            checked={status?.paused ?? false}
            onChange={() => pauseMutation.mutate()}
          />
        </Section>

        {/* ── Demand ── */}
        <Section title="Demand" icon="📈">
          <NumberInput
            label="Daily flights"
            value={local.daily_flights}
            onChange={(v) => patch("daily_flights", v)}
            min={50}
            max={1200}
          />
          <NumberInput
            label="Load factor"
            value={local.load_factor_mean}
            onChange={(v) => patch("load_factor_mean", v)}
            min={0.1}
            max={1.0}
            step={0.05}
          />
          <NumberInput
            label="Pax multiplier"
            value={local.pax_multiplier}
            onChange={(v) => patch("pax_multiplier", v)}
            min={0.1}
            max={5.0}
            step={0.1}
          />
          <SelectInput
            label="Special event"
            value={local.special_event ?? ""}
            options={[
              { value: "", label: "None" },
              { value: "holiday", label: "Holiday rush" },
              { value: "sports", label: "Sports event" },
              { value: "convention", label: "Convention" },
            ]}
            onChange={(v) => patch("special_event", v || null)}
          />
        </Section>

        {/* ── Weather ── */}
        <Section title="Weather" icon="🌤️">
          <SelectInput
            label="Lock to"
            value={local.weather_lock ?? ""}
            options={WEATHER_OPTIONS}
            onChange={(v) => patch("weather_lock", v || null)}
          />
          <NumberInput
            label="Wind"
            value={local.wind_kt}
            onChange={(v) => patch("wind_kt", v)}
            min={0}
            max={100}
            unit="kt"
          />
          <Toggle
            label="Gusts enabled"
            checked={local.gust_enabled}
            onChange={(v) => patch("gust_enabled", v)}
          />
        </Section>

        {/* ── Incidents ── */}
        <Section title="Incidents" icon="🚨">
          <NumberInput
            label="Runway incursion"
            value={local.runway_incursion_rate}
            onChange={(v) => patch("runway_incursion_rate", v)}
            min={0}
            max={1}
            step={0.001}
            unit="/h"
          />
          <NumberInput
            label="Baggage fire"
            value={local.baggage_fire_rate}
            onChange={(v) => patch("baggage_fire_rate", v)}
            min={0}
            max={1}
            step={0.001}
            unit="/h"
          />
          <NumberInput
            label="Security breach"
            value={local.security_breach_rate}
            onChange={(v) => patch("security_breach_rate", v)}
            min={0}
            max={1}
            step={0.001}
            unit="/h"
          />
          <NumberInput
            label="System failure"
            value={local.system_failure_rate}
            onChange={(v) => patch("system_failure_rate", v)}
            min={0}
            max={1}
            step={0.001}
            unit="/h"
          />
          <NumberInput
            label="Suppression window"
            value={local.suppression_window_h}
            onChange={(v) => patch("suppression_window_h", v)}
            min={0.5}
            max={24}
            step={0.5}
            unit="h"
          />
        </Section>

        {/* ── Security ── */}
        <Section title="Security" icon="🔒">
          <NumberInput
            label="Lanes — Terminal A"
            value={local.lanes_a}
            onChange={(v) => patch("lanes_a", v)}
            min={1}
            max={20}
          />
          <NumberInput
            label="Lanes — Terminal B"
            value={local.lanes_b}
            onChange={(v) => patch("lanes_b", v)}
            min={1}
            max={20}
          />
          <NumberInput
            label="Lanes — Terminal C"
            value={local.lanes_c}
            onChange={(v) => patch("lanes_c", v)}
            min={1}
            max={20}
          />
          <NumberInput
            label="MCT"
            value={local.mct_minutes}
            onChange={(v) => patch("mct_minutes", v)}
            min={15}
            max={180}
            unit="min"
          />
        </Section>

        {/* ── Baggage ── */}
        <Section title="Baggage" icon="🧳">
          <NumberInput
            label="Screening units"
            value={local.screening_units}
            onChange={(v) => patch("screening_units", v)}
            min={1}
            max={30}
          />
          <NumberInput
            label="Sorting capacity"
            value={local.sorting_capacity}
            onChange={(v) => patch("sorting_capacity", v)}
            min={100}
            max={10000}
            unit="/h"
          />
          <NumberInput
            label="DG false-pos rate"
            value={local.dg_false_positive_rate}
            onChange={(v) => patch("dg_false_positive_rate", v)}
            min={0}
            max={0.5}
            step={0.001}
          />
        </Section>
      </div>

      {/* ── Autonomous Operations (P2-4-1) ── */}
      <AutonomousSection />
    </div>
  );
}

/* ──────── Autonomous Operations Panel (P2-4-1) ──────── */

interface AutonomousState {
  enabled: boolean;
  confidence_threshold: number;
  check_interval_sim_minutes: number;
  blocked_actions: string[];
}

function AutonomousSection() {
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
        <h2 className="text-lg font-bold text-white">🤖 Autonomous Operations</h2>
        <div className="flex items-center gap-2">
          {autoSaved && (
            <span className="text-green-400 text-sm animate-pulse">✓ Saved</span>
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
        <Toggle
          label="Autonomous Mode"
          checked={localAuto.enabled}
          onChange={(v) => setLocalAuto({ ...localAuto, enabled: v })}
        />
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
            ⚠ Autonomous mode will auto-apply recommendations with confidence ≥{" "}
            {(localAuto.confidence_threshold * 100).toFixed(0)}% every{" "}
            {localAuto.check_interval_sim_minutes} sim-minutes.
            Flight cancellation, runway closure, and GDP actions always
            require human confirmation.
          </p>
        </div>
      )}

      {/* Recent autonomous actions */}
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
                <span className="text-xs text-white">{a.action_type as string}</span>
                <span className="text-xs text-gray-500 ml-2">
                  {a.description as string}
                </span>
              </div>
              <span className="text-xs text-gray-500">
                conf: {((a.confidence_score as number) * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
