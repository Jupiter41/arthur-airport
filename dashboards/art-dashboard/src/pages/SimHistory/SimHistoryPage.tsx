import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
} from "recharts";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import type { ExportFormat } from "../../utils/exportData";
import { weatherApi, incidentsApi, simApi, costsApi } from "../../hooks/useApi";

interface DaySummary {
  day_number: number;
  sim_date: string;
  flights_total: number;
  flights_cancelled: number;
  flights_delayed: number;
  avg_delay_minutes: number;
  passengers_total: number;
  incidents_total: number;
  max_severity: string | null;
}

interface HistoryResponse {
  current_day: number;
  days: DaySummary[];
}

interface WeatherHistoryEntry {
  category: string;
  from: string;
  to: string;
  duration_minutes: number;
}

const DAYS_PER_PAGE = 20;

/* ──────── Day Summary Card ──────── */
function DaySummaryCard({
  day,
  selected,
  onClick,
}: {
  day: DaySummary;
  selected: boolean;
  onClick: () => void;
}) {
  const sevColor =
    day.max_severity === "critical"
      ? "border-red-500 bg-red-900/20"
      : day.max_severity === "high"
        ? "border-orange-500 bg-orange-900/10"
        : "border-gray-700 bg-gray-800";

  return (
    <div
      className={`border-l-4 ${sevColor} rounded p-3 cursor-pointer transition-all hover:ring-1 hover:ring-white/20 ${selected ? "ring-2 ring-blue-400" : ""}`}
      onClick={onClick}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-bold text-white">
          Day {day.day_number}
        </span>
        <span className="text-xs text-gray-400">{day.sim_date}</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-gray-400">Flights</span>
          <div className="text-white font-bold">{day.flights_total}</div>
        </div>
        <div>
          <span className="text-gray-400">Pax</span>
          <div className="text-white font-bold">
            {day.passengers_total.toLocaleString()}
          </div>
        </div>
        <div>
          <span className="text-gray-400">Incidents</span>
          <div
            className={
              day.incidents_total > 0
                ? "text-amber-400 font-bold"
                : "text-white font-bold"
            }
          >
            {day.incidents_total}
          </div>
        </div>
      </div>
      <div className="mt-1 flex gap-3 text-[10px] text-gray-400">
        <span>Delayed: {day.flights_delayed}</span>
        <span>Cancelled: {day.flights_cancelled}</span>
        <span>Avg delay: {day.avg_delay_minutes}min</span>
      </div>
    </div>
  );
}

/* ──────── Flight Stats Chart ──────── */
function FlightStatsChart({ days }: { days: DaySummary[] }) {
  if (days.length === 0) return null;

  const data = days.map((d) => ({
    name: `D${d.day_number}`,
    total: d.flights_total,
    delayed: d.flights_delayed,
    cancelled: d.flights_cancelled,
  }));

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Flights by Day
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={{ fill: "#9ca3af", fontSize: 10 }} />
          <YAxis tick={{ fill: "#9ca3af", fontSize: 10 }} width={36} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #4b5563",
              borderRadius: 4,
            }}
            labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: "#9ca3af" }} />
          <Bar
            dataKey="total"
            name="Total"
            fill="#3b82f6"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            dataKey="delayed"
            name="Delayed"
            fill="#f59e0b"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            dataKey="cancelled"
            name="Cancelled"
            fill="#ef4444"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ──────── Delay Trend Chart ──────── */
function DelayTrendChart({ days }: { days: DaySummary[] }) {
  if (days.length < 2) return null;

  const data = days.map((d) => ({
    name: `D${d.day_number}`,
    avg_delay: d.avg_delay_minutes,
    incidents: d.incidents_total,
  }));

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Delay & Incident Trend
      </h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart
          data={data}
          margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={{ fill: "#9ca3af", fontSize: 10 }} />
          <YAxis tick={{ fill: "#9ca3af", fontSize: 10 }} width={36} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #4b5563",
              borderRadius: 4,
            }}
            labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: "#9ca3af" }} />
          <Line
            type="monotone"
            dataKey="avg_delay"
            name="Avg Delay (min)"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
          <Line
            type="monotone"
            dataKey="incidents"
            name="Incidents"
            stroke="#ef4444"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ──────── Timeline Event ──────── */
interface TimelineEvent {
  time: string;
  type: "weather" | "incident" | "flight";
  severity?: string;
  message: string;
}

function TimelinePanel({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-4 text-center text-gray-400 text-sm">
        No events to display. Run the simulation to generate history.
      </div>
    );
  }

  const typeColors: Record<string, string> = {
    weather: "border-blue-500",
    incident: "border-red-500",
    flight: "border-green-500",
  };

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Event Timeline (Current Day)
      </h3>
      <div className="space-y-1 max-h-[400px] overflow-y-auto">
        {events.map((evt, i) => (
          <div
            key={i}
            className={`flex gap-3 text-xs border-l-2 ${typeColors[evt.type] ?? "border-gray-600"} pl-3 py-1`}
          >
            <span className="text-gray-400 font-mono whitespace-nowrap w-12">
              {formatTime(evt.time)}
            </span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                evt.type === "incident"
                  ? "bg-red-900/40 text-red-400"
                  : evt.type === "weather"
                    ? "bg-blue-900/40 text-blue-400"
                    : "bg-green-900/40 text-green-400"
              }`}
            >
              {evt.type.toUpperCase()}
            </span>
            <span className="text-gray-300">{evt.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Day Detail Modal ──────── */
function DayDetailModal({
  day,
  onClose,
}: {
  day: DaySummary;
  onClose: () => void;
}) {
  // Fetch cost data for this day
  const costQuery = useQuery({
    queryKey: ["costs", "pnl", day.day_number],
    queryFn: () => costsApi.pnl(day.day_number),
  });

  // Close on Escape
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
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto" role="dialog" aria-modal="true" aria-label={`Day ${day.day_number} details`}>
        {/* Header */}
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
          {/* KPI grid */}
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
              color={
                day.avg_delay_minutes > 30 ? "text-red-400" : "text-white"
              }
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

          {/* Financials */}
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

          {/* Flight breakdown mini-chart */}
          <div>
            <h4 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
              Flight Breakdown
            </h4>
            <div className="flex gap-2 text-xs">
              <div className="flex-1 bg-blue-900/30 rounded p-2 text-center">
                <div className="text-blue-400 font-bold">
                  {day.flights_total - day.flights_delayed - day.flights_cancelled}
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

function formatEur(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `€${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `€${(v / 1_000).toFixed(1)}K`;
  return `€${v.toFixed(0)}`;
}

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

  // Pagination
  const totalPages = Math.max(1, Math.ceil(days.length / DAYS_PER_PAGE));
  const pagedDays = useMemo(
    () => days.slice(page * DAYS_PER_PAGE, (page + 1) * DAYS_PER_PAGE),
    [days, page],
  );

  // Build timeline events from weather + incidents
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

  const handleDayClick = useCallback(
    (d: DaySummary) => {
      setSelectedDay(d.day_number);
      setModalDay(d);
    },
    [],
  );

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
              No simulation history yet. Run the simulation for at least one
              day to see history.
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
          {/* Pagination controls */}
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

      {/* Day detail modal */}
      {modalDay && (
        <DayDetailModal
          day={modalDay}
          onClose={() => setModalDay(null)}
        />
      )}
    </div>
  );
}

/* ──────── Utils ──────── */
function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${d.getUTCHours().toString().padStart(2, "0")}:${d.getUTCMinutes().toString().padStart(2, "0")}`;
}
