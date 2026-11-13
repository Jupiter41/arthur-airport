import { useState, useMemo } from "react";
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

  const [selectedZone, setSelectedZone] = useState<ZoneDensity | null>(null);

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
  const zones = queries.heatmap.data ?? [];
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

      <KPIBar summary={summary} zones={zones} />

      <SecurityQueueChart summary={summary} />

      <AirportHeatmap
        zones={zones}
        lockedZones={lockedZones}
        onSelect={setSelectedZone}
      />

      <div className="grid grid-cols-2 gap-4">
        <ConnectionRiskList connections={connectionsAtRisk} />
        <ZoneDetailPanel zone={selectedZone} />
      </div>
    </div>
  );
}
