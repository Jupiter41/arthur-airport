import { useState } from "react";
import { incidentsApi } from "../../hooks/useApi";
import { queryClient } from "../../queryClient";
import type { Incident } from "../../types";

/**
 * Operator actions for the selected incident. Wires the existing
 * `incidentsApi.contain/resolve` REST endpoints (previously unwired) to real
 * buttons. Contain is offered while the incident is still active; resolve while
 * it is active or contained. The incident-service enforces the real guards; we
 * surface the transitions an operator can reach.
 */
export function IncidentActions({ incident }: { incident: Incident }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const canContain = incident.status === "active";
  const canResolve = incident.status === "active" || incident.status === "contained";

  if (!canContain && !canResolve) return null;

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["incidents"] });

  const run = async (fn: () => Promise<unknown>, label: string) => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await fn();
      await refresh();
      setDone(label);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-gray-800 rounded p-3 space-y-2">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">
        Operator Actions — {incident.title}
      </h3>
      <div className="flex gap-2">
        {canContain && (
          <button
            className="flex-1 text-sm font-bold px-3 py-2 rounded bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
            disabled={busy}
            onClick={() =>
              run(() => incidentsApi.contain(incident.id), "Contained")
            }
          >
            {busy ? "…" : "Contain"}
          </button>
        )}
        {canResolve && (
          <button
            className="flex-1 text-sm font-bold px-3 py-2 rounded bg-green-600 text-white hover:bg-green-500 disabled:opacity-50"
            disabled={busy}
            onClick={() =>
              run(() => incidentsApi.resolve(incident.id), "Resolved")
            }
          >
            {busy ? "…" : "Resolve"}
          </button>
        )}
      </div>
      {done && <div className="text-xs text-green-400">✓ {done}</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}
    </div>
  );
}
