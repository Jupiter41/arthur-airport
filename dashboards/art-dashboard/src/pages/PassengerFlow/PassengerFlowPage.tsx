import { useState, useEffect, useMemo } from "react";
import { usePassengerStore } from "../../stores/passengerStore";
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
  const zones = usePassengerStore((s) => s.zones);
  const summary = usePassengerStore((s) => s.summary);
  const connectionsAtRisk = usePassengerStore((s) => s.connectionsAtRisk);
  const setZones = usePassengerStore((s) => s.setZones);
  const setSummary = usePassengerStore((s) => s.setSummary);
  const setConnectionsAtRisk = usePassengerStore((s) => s.setConnectionsAtRisk);
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

  const queries = usePassengerFlowQueries();

  useEffect(() => {
    if (queries.heatmap.data) setZones(queries.heatmap.data);
  }, [queries.heatmap.data, setZones]);

  useEffect(() => {
    if (queries.summary.data) setSummary(queries.summary.data);
  }, [queries.summary.data, setSummary]);

  useEffect(() => {
    if (queries.atRisk.data) setConnectionsAtRisk(queries.atRisk.data);
  }, [queries.atRisk.data, setConnectionsAtRisk]);

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
