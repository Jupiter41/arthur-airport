import { useState, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import type { ExportFormat } from "../../utils/exportData";
import { weatherApi, incidentsApi, simApi } from "../../hooks/useApi";
import { DaySummaryCard } from "./DaySummaryCard";
import { FlightStatsChart, DelayTrendChart } from "./Charts";
import { TimelinePanel } from "./TimelinePanel";
import { DayDetailModal } from "./DayDetailModal";
import type {
  DaySummary,
  HistoryResponse,
  WeatherHistoryEntry,
  TimelineEvent,
} from "./types";
import { DAYS_PER_PAGE } from "./types";

/* ──────── Main Page ──────── */
export default function SimHistoryPage() {
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [modalDay, setModalDay] = useState<DaySummary | null>(null);
  const [page, setPage] = useState(0);

  const historyQuery = useQuery<HistoryResponse>({
    queryKey: ["sim-history"],
    queryFn: () => simApi.history() as Promise<HistoryResponse>,
    refetchInterval: 30_000,
  });

  const weatherQuery = useQuery<{ states?: WeatherHistoryEntry[] }>({
    queryKey: ["weather-history"],
    queryFn: () =>
      weatherApi.history(48) as Promise<{ states?: WeatherHistoryEntry[] }>,
    refetchInterval: 30_000,
  });

  const incidentQuery = useQuery({
    queryKey: ["incidents-history"],
    queryFn: () => incidentsApi.list({ limit: "50" }),
    refetchInterval: 30_000,
  });

  const days = historyQuery.data?.days ?? [];

  const totalPages = Math.max(1, Math.ceil(days.length / DAYS_PER_PAGE));
  const pagedDays = useMemo(
    () => days.slice(page * DAYS_PER_PAGE, (page + 1) * DAYS_PER_PAGE),
    [days, page],
  );

  const timelineEvents: TimelineEvent[] = [];

  if (weatherQuery.data?.states) {
    for (const s of weatherQuery.data.states) {
      timelineEvents.push({
        time: s.from,
        type: "weather",
        message: `Weather → ${s.category} (${s.duration_minutes} min)`,
      });
    }
  }

  if (incidentQuery.data?.incidents) {
    for (const inc of incidentQuery.data.incidents as Array<
      Record<string, unknown>
    >) {
      timelineEvents.push({
        time: (inc.started_at as string) ?? "",
        type: "incident",
        severity: inc.severity as string,
        message: `${(inc.type as string)?.replace(/_/g, " ")} — ${inc.location as string} (${(inc.severity as string)?.toUpperCase()})`,
      });
    }
  }

  timelineEvents.sort((a, b) => a.time.localeCompare(b.time));

  const handleExport = (fmt: ExportFormat) => {
    exportData(
      days.map((d) => ({ ...d })),
      "sim-history",
      fmt,
    );
  };

  const handleDayClick = useCallback((d: DaySummary) => {
    setSelectedDay(d.day_number);
    setModalDay(d);
  }, []);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">Simulation History</h2>
        <ExportMenu onExport={handleExport} />
      </div>

      {historyQuery.isLoading && (
        <div className="text-sm text-gray-400">Loading history…</div>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-2 gap-4">
        <FlightStatsChart days={days} />
        <DelayTrendChart days={days} />
      </div>

      {/* Day cards + timeline */}
      <div className="grid grid-cols-3 gap-4">
        <div className="space-y-3">
          <h3 className="text-xs text-gray-400 uppercase tracking-wide">
            Simulation Days ({days.length})
          </h3>
          {days.length === 0 && !historyQuery.isLoading && (
            <div className="text-sm text-gray-400">
              No simulation history yet. Run the simulation for at least one day
              to see history.
            </div>
          )}
          {pagedDays.map((d) => (
            <DaySummaryCard
              key={d.day_number}
              day={d}
              selected={selectedDay === d.day_number}
              onClick={() => handleDayClick(d)}
            />
          ))}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-2">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ← Prev
              </button>
              <span className="text-xs text-gray-400">
                {page + 1} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next →
              </button>
            </div>
          )}
        </div>

        <div className="col-span-2">
          <TimelinePanel events={timelineEvents} />
        </div>
      </div>

      {modalDay && (
        <DayDetailModal day={modalDay} onClose={() => setModalDay(null)} />
      )}
    </div>
  );
}
