import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { simApi } from "../../hooks/useApi";
import { NumberInput, Toggle, SelectInput, Section } from "./FormControls";
import { HourlyWeightsEditor } from "./HourlyWeightsEditor";
import { SpeedSelector } from "./SpeedSelector";
import { AutonomousSection } from "./AutonomousSection";
import type { SimSettings, SimStatus } from "./types";
import { WEATHER_OPTIONS } from "./types";

/* ──────── Main page ──────── */

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

        {/* ── Schedule Distribution ── */}
        <Section title="Hourly Distribution" icon="📊">
          <HourlyWeightsEditor
            weights={local.hourly_weights ?? {}}
            onChange={(w) => patch("hourly_weights", w)}
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
