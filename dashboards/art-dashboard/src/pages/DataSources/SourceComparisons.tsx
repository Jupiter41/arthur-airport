import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { dataSourcesApi } from "../../hooks/useApi";

/* ──────── Capacity Mismatch Warning (tooltip) ──────── */

export function CapacityMismatchWarning({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const [showTooltip, setShowTooltip] = useState(false);
  const warning = details.capacity_warning as string | undefined;
  const ratio = details.capacity_ratio as number | undefined;

  if (!warning) return null;

  return (
    <div className="mt-3 relative">
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-900/20 border border-amber-700/30 cursor-help"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <span className="text-amber-400 text-sm">⚠️</span>
        <span className="text-[10px] text-amber-300">
          Capacity mismatch detected
          {ratio ? ` (${Math.round(ratio * 100)}% utilization)` : ""}
        </span>
      </div>
      {showTooltip && (
        <div className="absolute bottom-full left-0 mb-2 z-50 w-72 p-3 rounded-lg bg-slate-800 border border-slate-600 shadow-xl text-xs text-slate-300">
          <p className="font-medium text-amber-300 mb-1">
            BTS Data / Airport Capacity Mismatch
          </p>
          <p className="text-slate-400 leading-relaxed">{warning}</p>
          <p className="text-slate-500 mt-2 text-[10px]">
            Tip: You can adjust the schedule offset in the sim-orchestrator
            settings or scale the BTS data to match the airport&apos;s
            gate/runway capacity.
          </p>
        </div>
      )}
    </div>
  );
}

/* ──────── Inline Passenger Comparison ──────── */

export function PassengerComparisonInline() {
  const [show, setShow] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["passenger-compare"],
    queryFn: () =>
      dataSourcesApi.passengerCompare() as Promise<Record<string, unknown>>,
    refetchInterval: show ? 15_000 : false,
    enabled: show,
  });

  const simulated = data?.simulated as Record<string, unknown> | undefined;
  const bts = data?.bts_historical as Record<string, unknown> | undefined;
  const deltas = data?.deltas as Record<string, unknown> | undefined;

  return (
    <div className="mt-3">
      <button
        onClick={() => setShow(!show)}
        className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors"
      >
        {show ? "▾ Hide comparison" : "▸ Source comparison"}
      </button>
      {show && (
        <div className="mt-2 p-3 rounded-lg bg-slate-900/50 border border-slate-700/30 space-y-2">
          {isLoading && (
            <div className="text-[10px] text-slate-500">Loading…</div>
          )}
          {data && (
            <>
              <div className="grid grid-cols-2 gap-2 text-[10px]">
                <div>
                  <span className="text-blue-400 font-medium">Simulated: </span>
                  <span className="text-slate-200 font-mono">
                    {(
                      (simulated?.total_passengers as number) ?? 0
                    ).toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-amber-400 font-medium">BTS: </span>
                  <span className="text-slate-200 font-mono">
                    {bts
                      ? ((bts.total_passengers as number) ?? 0).toLocaleString()
                      : "N/A"}
                  </span>
                </div>
              </div>
              {deltas && (
                <div
                  className={`text-[10px] font-medium ${
                    Math.abs(Number(deltas.pct_difference) || 0) > 10
                      ? "text-amber-400"
                      : "text-emerald-400"
                  }`}
                >
                  Δ {(Number(deltas.total_passengers) || 0) > 0 ? "+" : ""}
                  {(Number(deltas.total_passengers) || 0).toLocaleString()} (
                  {(Number(deltas.pct_difference) || 0) > 0 ? "+" : ""}
                  {Number(deltas.pct_difference) || 0}%)
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ──────── Inline Incident Comparison ──────── */

export function IncidentComparisonInline() {
  const [show, setShow] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["incident-compare"],
    queryFn: () =>
      dataSourcesApi.incidentCompare() as Promise<Record<string, unknown>>,
    enabled: show,
  });

  const activeSource = data?.active_source as string | undefined;
  const deltas = data?.deltas as
    | Record<
        string,
        { simulated: number; asrs_historical: number; ratio: number | null }
      >
    | undefined;

  return (
    <div className="mt-3">
      <button
        onClick={() => setShow(!show)}
        className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors"
      >
        {show ? "▾ Hide comparison" : "▸ Source comparison"}
      </button>
      {show && (
        <div className="mt-2 p-3 rounded-lg bg-slate-900/50 border border-slate-700/30 space-y-2">
          {isLoading && (
            <div className="text-[10px] text-slate-500">Loading…</div>
          )}
          {data && (
            <>
              <div className="text-[10px] text-slate-400 mb-1">
                Preset: <span className="text-slate-200">{activeSource}</span>
              </div>
              {deltas && Object.keys(deltas).length > 0 && (
                <div className="space-y-1">
                  {Object.entries(deltas).map(([type, d]) => (
                    <div
                      key={type}
                      className="flex items-center justify-between text-[10px]"
                    >
                      <span className="text-slate-400">
                        {type.replace(/_/g, " ")}
                      </span>
                      <span
                        className={`font-mono ${
                          d.ratio !== null && d.ratio > 1.5
                            ? "text-red-400"
                            : d.ratio !== null && d.ratio < 0.5
                              ? "text-amber-400"
                              : "text-emerald-400"
                        }`}
                      >
                        {d.ratio !== null ? `×${d.ratio}` : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
