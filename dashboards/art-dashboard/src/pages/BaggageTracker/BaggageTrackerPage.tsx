import { useState, useEffect } from "react";
import { useBaggageStore } from "../../stores/baggageStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { useBaggageTrackerQueries } from "../../hooks/useQueries";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import { ConveyorMap } from "./ConveyorMap";
import { ZoneStatsPanel, FlowSummaryPanel, FlaggedItemsPanel, LoadingProgressPanel } from "./Panels";
import type { ExportFormat } from "../../utils/exportData";
import type { Flight } from "../../types";

/* ──────── Main Page ──────── */
export default function BaggageTrackerPage() {
  const zones = useBaggageStore((s) => s.zones);
  const summary = useBaggageStore((s) => s.summary);
  const flagged = useBaggageStore((s) => s.flagged);
  const setZones = useBaggageStore((s) => s.setZones);
  const setSummary = useBaggageStore((s) => s.setSummary);
  const setFlagged = useBaggageStore((s) => s.setFlagged);
  const [flights, setFlights] = useState<Flight[]>([]);

  const incidents = useIncidentStore((s) => s.incidents);

  useEffect(() => {
    if (zones.length === 0) return;
    const activeFailures = Object.values(incidents).filter(
      (i) => i.type === "system_failure" && i.status !== "resolved",
    );
    const offlineLocations = new Set(activeFailures.map((i) => i.location));

    let changed = false;
    const updated = zones.map((z) => {
      const shouldBeOffline =
        offlineLocations.has(z.zone_id) ||
        [...offlineLocations].some((loc) =>
          z.zone_id.includes(loc.replace("conveyor-", "")),
        );
      if (shouldBeOffline && z.status !== "offline") {
        changed = true;
        return { ...z, status: "offline" as const };
      }
      if (!shouldBeOffline && z.status === "offline") {
        changed = true;
        return { ...z, status: "active" as const };
      }
      return z;
    });
    if (changed) setZones(updated);
  }, [incidents, zones, setZones]);

  const queries = useBaggageTrackerQueries();

  useEffect(() => {
    if (queries.map.data) setZones(queries.map.data);
  }, [queries.map.data, setZones]);

  useEffect(() => {
    if (queries.summary.data) setSummary(queries.summary.data);
  }, [queries.summary.data, setSummary]);

  useEffect(() => {
    if (queries.flagged.data) setFlagged(queries.flagged.data);
  }, [queries.flagged.data, setFlagged]);

  useEffect(() => {
    if (queries.flights.data) setFlights(queries.flights.data);
  }, [queries.flights.data]);

  const isLoading = queries.map.isLoading && zones.length === 0;
  const hasError = queries.map.isError && zones.length === 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
          <span>Loading baggage data…</span>
        </div>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="text-red-400 text-lg">⚠️ Failed to load baggage data</span>
          <span className="text-sm text-gray-500">
            The baggage-service may not be running. Check that the simulation is active.
          </span>
          <button
            onClick={() => queries.map.refetch()}
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
        <h2 className="text-lg font-bold text-white">Baggage Operations</h2>
        <ExportMenu
          onExport={(fmt: ExportFormat) => {
            const rows = zones.map((z) => ({
              zone_id: z.zone_id,
              zone_type: z.zone_type,
              status: z.status,
              items: z.items,
              capacity: z.capacity,
              utilisation_pct: z.utilisation_pct,
              throughput_per_hour: z.throughput_per_hour,
            }));
            exportData(rows, "baggage-zones", fmt);
          }}
        />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <ConveyorMap zones={zones} />
        </div>

        <div className="space-y-4">
          <ZoneStatsPanel zones={zones} />
          <FlowSummaryPanel summary={summary} />
        </div>
      </div>

      <LoadingProgressPanel flights={flights} />
      <FlaggedItemsPanel flagged={flagged} />
    </div>
  );
}
