import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import { formatEur } from "../../utils/formatCurrency";
import { costsApi } from "../../hooks/useApi";
import type { ExportFormat } from "../../utils/exportData";
import type { DaySummary } from "./types";

function KpiMini({
  label,
  value,
  color = "text-white",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-gray-800 rounded p-2 text-center">
      <div className={`text-sm font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-gray-400">{label}</div>
    </div>
  );
}

export function DayDetailModal({
  day,
  onClose,
}: {
  day: DaySummary;
  onClose: () => void;
}) {
  const costQuery = useQuery({
    queryKey: ["costs", "pnl", day.day_number],
    queryFn: () => costsApi.pnl(day.day_number),
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const pnl = costQuery.data as Record<string, unknown> | undefined;
  const totalCost = Number(pnl?.total_cost_eur ?? 0);
  const totalRevenue = Number(pnl?.total_revenue_eur ?? 0);
  const netPnl = Number(pnl?.net_eur ?? 0);

  const onTimeRate =
    day.flights_total > 0
      ? Math.round(
          ((day.flights_total - day.flights_delayed - day.flights_cancelled) /
            day.flights_total) *
            100,
        )
      : 0;

  const handleExportDay = (fmt: ExportFormat) => {
    const report = {
      day_number: day.day_number,
      sim_date: day.sim_date,
      flights: {
        total: day.flights_total,
        delayed: day.flights_delayed,
        cancelled: day.flights_cancelled,
        on_time_pct: onTimeRate,
        avg_delay_minutes: day.avg_delay_minutes,
      },
      passengers: { total: day.passengers_total },
      incidents: {
        total: day.incidents_total,
        max_severity: day.max_severity,
      },
      financials: {
        total_cost_eur: totalCost,
        total_revenue_eur: totalRevenue,
        net_eur: netPnl,
      },
    };
    exportData([report], `day-${day.day_number}-report`, fmt);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label={`Day ${day.day_number} details`}
      >
        <div className="sticky top-0 bg-gray-900 border-b border-gray-700 px-5 py-3 flex items-center justify-between">
          <h3 className="text-base font-bold text-white">
            Day {day.day_number} — {day.sim_date}
          </h3>
          <div className="flex items-center gap-2">
            <ExportMenu onExport={handleExportDay} />
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white text-xl leading-none px-1"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </div>

        <div className="p-5 space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <KpiMini label="Total Flights" value={String(day.flights_total)} />
            <KpiMini
              label="On-Time Rate"
              value={`${onTimeRate}%`}
              color={onTimeRate >= 80 ? "text-green-400" : "text-amber-400"}
            />
            <KpiMini
              label="Passengers"
              value={day.passengers_total.toLocaleString()}
            />
            <KpiMini
              label="Avg Delay"
              value={`${day.avg_delay_minutes} min`}
              color={day.avg_delay_minutes > 30 ? "text-red-400" : "text-white"}
            />
            <KpiMini
              label="Incidents"
              value={String(day.incidents_total)}
              color={day.incidents_total > 3 ? "text-red-400" : "text-white"}
            />
            <KpiMini
              label="Max Severity"
              value={day.max_severity ?? "—"}
              color={
                day.max_severity === "critical"
                  ? "text-red-400"
                  : day.max_severity === "high"
                    ? "text-orange-400"
                    : "text-white"
              }
            />
          </div>

          <div>
            <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
              Financials
            </h4>
            {costQuery.isLoading ? (
              <div className="text-xs text-gray-500">Loading cost data…</div>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                <KpiMini
                  label="Total Cost"
                  value={formatEur(totalCost)}
                  color="text-red-400"
                />
                <KpiMini
                  label="Revenue"
                  value={formatEur(totalRevenue)}
                  color="text-green-400"
                />
                <KpiMini
                  label="Net P&L"
                  value={formatEur(netPnl)}
                  color={netPnl >= 0 ? "text-green-400" : "text-red-400"}
                />
              </div>
            )}
          </div>

          <div>
            <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
              Flight Breakdown
            </h4>
            <div className="flex gap-2 text-xs">
              <div className="flex-1 bg-blue-900/30 rounded p-2 text-center">
                <div className="text-blue-400 font-bold">
                  {day.flights_total -
                    day.flights_delayed -
                    day.flights_cancelled}
                </div>
                <div className="text-gray-400">On Time</div>
              </div>
              <div className="flex-1 bg-amber-900/30 rounded p-2 text-center">
                <div className="text-amber-400 font-bold">
                  {day.flights_delayed}
                </div>
                <div className="text-gray-400">Delayed</div>
              </div>
              <div className="flex-1 bg-red-900/30 rounded p-2 text-center">
                <div className="text-red-400 font-bold">
                  {day.flights_cancelled}
                </div>
                <div className="text-gray-400">Cancelled</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
