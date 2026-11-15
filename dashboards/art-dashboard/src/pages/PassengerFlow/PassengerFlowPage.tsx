import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { normalizeTerminal } from "../Airport3D/model";
import { DecisionWorkspace } from "../Decisions/DecisionWorkspace";
import { useIncidentStore } from "../../stores/incidentStore";
import { usePassengerFlowQueries } from "../../hooks/useQueries";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import { AirportHeatmap } from "./AirportHeatmap";
import { SecurityQueueChart } from "./SecurityQueueChart";
import { KPIBar } from "./KPIBar";
import { ConnectionRiskList } from "./ConnectionRiskList";
import { ZoneDetailPanel } from "./ZoneDetailPanel";
import type { ExportFormat } from "../../utils/exportData";
import type { ZoneDensity } from "../../types";

/* ──────── Main Page ──────── */
export default function PassengerFlowPage() {
  const incidents = useIncidentStore((s) => s.incidents);

  const [params, setParams] = useSearchParams();
  const terminal = params.get("terminal") ?? "all";
  const setSelectedZone = (zone: ZoneDensity) => { const next = new URLSearchParams(params); next.set("entity",zone.zone_id); setParams(next, { replace: true }); };

  const lockedZones = useMemo(() => {
    const set = new Set<string>();
    for (const inc of Object.values(incidents)) {
      if (inc.type === "security_breach" && inc.status !== "resolved") {
        set.add(inc.location);
      }
    }
    return set;
  }, [incidents]);

  // Passenger flow is REST-polled (no live WebSocket stream mutates it), so
  // React Query is the single source of truth — read query data directly.
  const queries = usePassengerFlowQueries();
  const zones = (queries.heatmap.data ?? []).filter(z => terminal === "all" || normalizeTerminal(z.terminal) === terminal);
  const selectedZone = zones.find(z => z.zone_id === params.get("entity")) ?? null;
  const summary = queries.summary.data ?? null;
  const connectionsAtRisk = queries.atRisk.data ?? [];

  const isLoading = queries.heatmap.isLoading && zones.length === 0;
  const hasError = queries.heatmap.isError && zones.length === 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
          <span>Loading passenger data…</span>
        </div>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="text-red-400 text-lg">⚠️ Failed to load passenger data</span>
          <span className="text-sm text-gray-500">
            The passenger-service may not be running. Check that the simulation is active.
          </span>
          <button
            onClick={() => queries.heatmap.refetch()}
            className="mt-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">Passenger Flow</h2>
        <ExportMenu
          onExport={(fmt: ExportFormat) => {
            const rows = zones.map((z) => ({
              zone_id: z.zone_id,
              zone_type: z.zone_type,
              terminal: z.terminal,
              density: z.density,
              capacity: z.capacity,
              load_pct: z.load_pct,
            }));
            exportData(rows, "passenger-flow", fmt);
          }}
        />
      </div>

      <p className="text-xs text-gray-400">Airport-wide totals below; zone records use the selected terminal scope.</p>
      <KPIBar summary={summary} zones={queries.heatmap.data ?? []} />
      <section className="grid md:grid-cols-3 gap-3" aria-label="Terminal security comparison">{Object.entries(summary?.security ?? {}).filter(([t]) => terminal === "all" || normalizeTerminal(t) === terminal).map(([t,sec]) => <Link key={t} to={`/passengers?terminal=${normalizeTerminal(t)}&mode=board`} className="card"><h3>Terminal {normalizeTerminal(t)}</h3><p className={`text-2xl tabular-nums mt-2 ${sec.wait_minutes >= 20 ? "text-amber-300" : ""}`}>{sec.wait_minutes.toFixed(1)} min</p><p className="text-sm text-gray-400 mt-2">{sec.queue_length} queued · {sec.lanes_open} lanes{sec.frozen ? " · Frozen" : ""}</p></Link>)}</section>

      <SecurityQueueChart summary={summary ? {...summary, security:Object.fromEntries(Object.entries(summary.security??{}).filter(([key])=>terminal === "all"||normalizeTerminal(key)===terminal))} : null} />

      <AirportHeatmap
        zones={zones}
        lockedZones={lockedZones}
        onSelect={setSelectedZone}
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <ConnectionRiskList connections={connectionsAtRisk} />
        <ZoneDetailPanel zone={selectedZone} />
      </div>
      <DecisionWorkspace compact terminal={terminal === "all" ? undefined : terminal} />
    </div>
  );
}
