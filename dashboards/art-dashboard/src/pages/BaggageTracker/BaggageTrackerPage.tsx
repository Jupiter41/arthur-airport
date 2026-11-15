import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { normalizeTerminal } from "../Airport3D/model";
import { BaggageInspector } from "../../components/BaggageInspector";
import { useQuery } from "@tanstack/react-query";
import { baggageApi } from "../../hooks/useApi";
import type { BagDetail } from "../Airport3D/model";
import { useBaggageTrackerQueries } from "../../hooks/useQueries";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import { ConveyorMap } from "./ConveyorMap";
import {
  ZoneStatsPanel,
  FlowSummaryPanel,
  FlaggedItemsPanel,
  LoadingProgressPanel,
} from "./Panels";
import type { ExportFormat } from "../../utils/exportData";
import type { Flight } from "../../types";

/* ──────── Main Page ──────── */
export default function BaggageTrackerPage() {
  const [flaggedOffset, setFlaggedOffset] = useState(0);
  const [params] = useSearchParams();
  const terminal = params.get("terminal") ?? "all";
  const bagId = params.get("bag");
  const bag = useQuery({
    queryKey: ["baggage", "detail", bagId],
    queryFn: () => baggageApi.get(bagId!) as Promise<BagDetail>,
    enabled: !!bagId,
  });

  const queries = useBaggageTrackerQueries(flaggedOffset);
  // Both dimensions read the same owner projection in React Query. Never
  // synthesize conveyor failures/recovery from incidents in the browser.
  const zones = (queries.map.data ?? []).filter(
    (z) =>
      terminal === "all" ||
      z.zone_id.toUpperCase().split(/[-_]/).includes(terminal) ||
      !/[-_][ABC](?:[-_]|$)/i.test(z.zone_id),
  );
  const flights = (queries.flights.data ?? []).filter(
    (f: Flight) =>
      terminal === "all" ||
      normalizeTerminal(f.terminal || f.gate_id?.[0] || "") === terminal,
  );
  const summary = queries.summary.data ?? null;

  const isLoading = queries.map.isLoading && zones.length === 0;
  const hasError = queries.map.isError && zones.length === 0;

  if (isLoading && !bagId) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
          <span>Loading baggage data…</span>
        </div>
      </div>
    );
  }

  if (hasError && !bagId) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="text-red-400 text-lg">
            ⚠️ Failed to load baggage data
          </span>
          <span className="text-sm text-gray-500">
            The baggage-service may not be running. Check that the simulation is
            active.
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

      {hasError && (
        <p role="alert" className="text-amber-300">
          Conveyor observations unavailable. Direct item records remain
          available below.
        </p>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2">
          <ConveyorMap zones={zones} />
        </div>

        <div className="space-y-4">
          <ZoneStatsPanel zones={zones} />
          <FlowSummaryPanel summary={summary} />
        </div>
      </div>

      {params.get("entity") &&
        zones.some((z) => z.zone_id === params.get("entity")) && (
          <div className="card">
            <BaggageInspector zoneId={params.get("entity")!} />
          </div>
        )}
      {bagId && (
        <section className="card space-y-3">
          <h2>Baggage scan history</h2>
          {bag.isLoading && <p>Loading item…</p>}
          {bag.isError && <p role="alert">Item records unavailable.</p>}
          {bag.data && (
            <>
              <p>
                {bag.data.tag ?? bagId} · {bag.data.status}
              </p>
              <ol>
                {bag.data.scan_history?.map((scan, i) => (
                  <li
                    key={i}
                    className="border-l border-panel-border pl-3 py-2"
                  >
                    {scan.zone} · {scan.status}
                    <time className="block text-gray-400 text-xs">
                      {scan.at}
                    </time>
                  </li>
                ))}
              </ol>
              {!bag.data.scan_history?.length && (
                <p>No scan history recorded.</p>
              )}
            </>
          )}
        </section>
      )}
      <p className="text-xs text-gray-400">
        Zone and flight records follow terminal scope. Shared conveyors and
        airport-wide flagged items remain visible.
      </p>
      <LoadingProgressPanel flights={flights} />
      <FlaggedItemsPanel
        flagged={queries.flagged.data?.flagged ?? []}
        total={queries.flagged.data?.total ?? 0}
        offset={flaggedOffset}
        loading={queries.flagged.isFetching}
        error={queries.flagged.isError}
        onPageChange={setFlaggedOffset}
      />
    </div>
  );
}
