import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { simApi } from "../../hooks/useApi";
import { SnapshotExport } from "../../components/SnapshotExport";
import { SimControls } from "../../components/SimControls";
import { useAccess } from "../../hooks/auth";
import { NumberInput, Section } from "./FormControls";
import { HourlyWeightsEditor } from "./HourlyWeightsEditor";
import { AutonomousSection } from "./AutonomousSection";
import { EffectiveSettings } from "./EffectiveSettings";
import type { SettingsResponse } from "./types";

type ManifestRequest = Pick<SettingsResponse, "daily_flights" | "hourly_weights">;

export default function SettingsPage() {
  const client = useQueryClient();
  const publicDeployment = import.meta.env.VITE_PUBLIC_DEPLOYMENT === "true";
  const access = useAccess();
  const canChange = access.role !== "viewer" && (!publicDeployment || access.controlling);
  const [controlReady, setControlReady] = useState(false);
  const [local, setLocal] = useState<ManifestRequest | null>(null);
  const [dirty, setDirty] = useState(false);
  const { data: settings, isError, isLoading } = useQuery<SettingsResponse>({
    queryKey: ["sim-settings"],
    queryFn: () => simApi.settings() as Promise<SettingsResponse>,
    refetchInterval: 3000,
  });

  // Refresh on acquiring control without replacing unsaved edits on every poll.
  useEffect(() => {
    let active = true;
    setControlReady(false);
    if (!canChange) return;
    void simApi.settings().then(value => {
      if (!active) return;
      const response = value as SettingsResponse;
      client.setQueryData(["sim-settings"], response);
      setLocal({ daily_flights: response.daily_flights, hourly_weights: response.hourly_weights });
      setDirty(false);
      setControlReady(true);
    }).catch(() => { if (active) setControlReady(false); });
    return () => { active = false; };
  }, [canChange, client]);

  useEffect(() => {
    if (settings && !dirty) setLocal({ daily_flights: settings.daily_flights, hourly_weights: settings.hourly_weights });
  }, [settings, dirty]);

  const mutation = useMutation({
    mutationFn: (body: Partial<ManifestRequest>) => simApi.updateSettings(body),
    onSuccess: () => {
      setDirty(false);
      void client.invalidateQueries({ queryKey: ["sim-settings"] });
    },
  });

  return <div className="page-container space-y-4">
    <header>
      <p className="section-label">Shared airport</p>
      <h1>Simulation controls</h1>
      <p className="text-gray-400 mt-2">Changes affect the shared simulation. Operator access and control are required where enabled.</p>
    </header>
    <section className="card"><SimControls /></section>
    <SnapshotExport />
    {isError && <p role="alert">Settings refresh failed. Last observations may be stale. <button className="btn-secondary"
      onClick={() => void client.invalidateQueries({ queryKey: ["sim-settings"] })}>Retry</button></p>}
    {isLoading && <p>Loading settings…</p>}
    <EffectiveSettings effective={isError ? undefined : settings?.effective}
      canChange={canChange && controlReady && !publicDeployment && !isError} />
    {settings && local && <>
      <Section title="Future manifest requests" icon="📈">
        <p>Saved requests take effect when a new daily manifest is generated. Existing flights and passengers keep their manifest values.</p>
        <fieldset disabled={!canChange || !controlReady || mutation.isPending || isError} className="space-y-3">
          <NumberInput label="Daily flights" value={local.daily_flights} min={50} max={publicDeployment ? 100 : 5000}
            onChange={daily_flights => { setLocal({ ...local, daily_flights }); setDirty(true); mutation.reset(); }} />
          <fieldset disabled={publicDeployment}>
            <HourlyWeightsEditor weights={local.hourly_weights}
              onChange={hourly_weights => { setLocal({ ...local, hourly_weights }); setDirty(true); mutation.reset(); }} />
          </fieldset>
          <div className="flex gap-2">
            <button className="btn-secondary" disabled={!dirty} onClick={() => { setDirty(false); mutation.reset(); }}>Discard edits</button>
            <button className="btn-primary" disabled={!dirty} onClick={() => mutation.mutate(publicDeployment
              ? { daily_flights: local.daily_flights } : local)}>
              {mutation.isPending ? "Saving request…" : "Save manifest request"}
            </button>
          </div>
        </fieldset>
        {mutation.isSuccess && <p role="status">Request saved for future manifests. Current owner settings are shown above.</p>}
        {mutation.isError && <p role="alert">Request unconfirmed: {(mutation.error as Error).message}</p>}
      </Section>
      <details className="card">
        <summary>Other saved preferences and application status</summary>
        <p className="text-gray-400 my-3">Configuration/restart values require changes in the owning service. Stored-only preferences have no runtime consumer. Lane preferences require an explicit owner command above.</p>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
          {Object.entries(settings.requested ?? {}).filter(([key]) => !["daily_flights", "hourly_weights"].includes(key)).map(([key, value]) =>
            <div key={key}><dt className="text-gray-400">{key} · {settings.application[key]?.replace(/_/g, " ") ?? "application unknown"}</dt>
              <dd>{JSON.stringify(value)}</dd></div>)}
        </dl>
      </details>
      {!publicDeployment && <fieldset disabled={!canChange || !controlReady}><AutonomousSection /></fieldset>}
    </>}
  </div>;
}
