import { zoneColor } from "./constants";
import type { BaggageZone, BaggageFlowSummary, FlaggedBaggage, Flight } from "../../types";

export function ZoneStatsPanel({ zones }: { zones: BaggageZone[] }) {
  const sorted = [...zones].sort(
    (a, b) => b.utilisation_pct - a.utilisation_pct,
  );

  return (
    <div className="space-y-2">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">
        Zone Stats
      </h3>
      {sorted.slice(0, 8).map((z) => (
        <div key={z.zone_id} className="flex items-center gap-2">
          <span className="text-xs text-gray-300 w-28 truncate">
            {z.zone_id}
          </span>
          <div className="flex-1 bg-gray-700 rounded-full h-2">
            <div
              className="h-2 rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(z.utilisation_pct, 100)}%`,
                backgroundColor: zoneColor(z.utilisation_pct, z.status),
              }}
            />
          </div>
          <span className="text-xs text-gray-400 w-10 text-right">
            {z.utilisation_pct}%
          </span>
          {z.status === "offline" && (
            <span className="text-xs text-red-400 font-bold">⚠</span>
          )}
        </div>
      ))}
    </div>
  );
}

export function FlowSummaryPanel({ summary }: { summary: BaggageFlowSummary | null }) {
  if (!summary) return null;

  const loadedCount =
    summary.loaded_count ??
    (summary.by_status?.loaded as number | undefined) ??
    0;
  const flaggedCount =
    summary.flagged_count ??
    (summary.by_status?.flagged as number | undefined) ??
    0;

  return (
    <div className="space-y-2">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">
        Flow Summary
      </h3>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="bg-gray-800 rounded p-2">
          <div className="text-xs text-gray-400">In System</div>
          <div className="font-bold text-white">
            {(summary.total_in_system ?? 0).toLocaleString()}
          </div>
        </div>
        <div className="bg-gray-800 rounded p-2">
          <div className="text-xs text-gray-400">Loaded</div>
          <div className="font-bold text-teal-400">
            {loadedCount.toLocaleString()}
          </div>
        </div>
        <div className="bg-gray-800 rounded p-2">
          <div className="text-xs text-gray-400">Flagged</div>
          <div className="font-bold text-amber-400">{flaggedCount}</div>
        </div>
      </div>
      {summary.by_status && (
        <div className="text-xs text-gray-400 space-y-1">
          {Object.entries(summary.by_status).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span>{k}</span>
              <span className="text-gray-300">{v as number}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function FlaggedItemsPanel({ flagged }: { flagged: FlaggedBaggage[] }) {
  if (flagged.length === 0) return null;

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Flagged Items ({flagged.length})
      </h3>
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {flagged.map((item) => (
          <div
            key={item.id}
            className={`flex items-center justify-between text-sm p-2 rounded ${
              item.dg_class === 3
                ? "bg-red-900/40 border border-red-700"
                : "bg-gray-700"
            }`}
          >
            <div>
              <span className="font-mono text-white">{item.tag}</span>
              <span className="ml-2 text-xs text-gray-400">
                {item.flag_reason}
                {item.dg_class != null && ` · DG Class ${item.dg_class}`}
              </span>
            </div>
            <div className="text-xs text-gray-400">
              <span>{item.flight_number}</span>
              <span className="ml-2 text-amber-400 font-bold">
                {item.review_status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function LoadingProgressPanel({ flights }: { flights: Flight[] }) {
  const departures = flights
    .filter(
      (f) =>
        f.direction === "departure" &&
        ["boarding", "scheduled"].includes(f.status),
    )
    .sort((a, b) =>
      (a.estimated_time ?? a.scheduled_time).localeCompare(
        b.estimated_time ?? b.scheduled_time,
      ),
    )
    .slice(0, 10);

  if (departures.length === 0) return null;

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Flight Baggage Loading
      </h3>
      <div className="space-y-2">
        {departures.map((f) => {
          const pct =
            f.baggage_count > 0
              ? Math.round((f.baggage_loaded / f.baggage_count) * 100)
              : 0;
          return (
            <div key={f.id} className="flex items-center gap-3">
              <span className="text-sm font-bold text-white w-16">
                {f.flight_number}
              </span>
              <span className="text-xs text-gray-400 w-8">
                {f.gate_id ?? "—"}
              </span>
              <div className="flex-1 bg-gray-700 rounded-full h-2">
                <div
                  className="bg-teal-500 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs text-gray-400 w-20 text-right">
                {f.baggage_loaded}/{f.baggage_count} {pct}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
