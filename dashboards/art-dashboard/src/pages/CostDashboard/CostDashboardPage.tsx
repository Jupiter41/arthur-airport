import { useState, useMemo } from "react";
import { useCostDashboardQueries } from "../../hooks/useQueries";
import { useCostStore } from "../../stores/costStore";
import { useSimStore } from "../../stores/simStore";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import type {
  CostSummary,
  HourlyCostPoint,
  IncidentCostRanking,
  FinancialRecommendation,
} from "../../types";

/* ──────── Constants ──────── */

const CATEGORY_COLORS: Record<string, string> = {
  landing_fee: "#3b82f6",
  gate_fee: "#6366f1",
  passenger_fee: "#8b5cf6",
  eu261_compensation: "#ef4444",
  crew_overtime: "#f97316",
  holding_fuel: "#f59e0b",
  ground_handling: "#14b8a6",
  incident_direct: "#dc2626",
  incident_response: "#e11d48",
  staffing: "#64748b",
  retail_revenue: "#22c55e",
  slot_revenue: "#10b981",
};

const CATEGORY_LABELS: Record<string, string> = {
  landing_fee: "Landing Fees",
  gate_fee: "Gate Fees",
  passenger_fee: "Passenger Fees",
  eu261_compensation: "EU261 Compensation",
  crew_overtime: "Crew Overtime",
  holding_fuel: "Holding Fuel",
  ground_handling: "Ground Handling",
  incident_direct: "Incident Direct",
  incident_response: "Incident Response",
  staffing: "Staffing",
  retail_revenue: "Retail Revenue",
  slot_revenue: "Slot Revenue",
};

function formatEur(v: unknown): string {
  const n = Number(v ?? 0);
  if (Number.isNaN(n)) return "€0";
  if (Math.abs(n) >= 1_000_000) return `€${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `€${(n / 1_000).toFixed(1)}K`;
  return `€${n.toFixed(0)}`;
}

/* ──────── KPI Card ──────── */

function KpiCard({
  label,
  value,
  sub,
  color = "text-white",
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="bg-surface-card border border-panel-border rounded-xl p-4">
      <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">
        {label}
      </div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}

/* ──────── Cost Breakdown Donut ──────── */

function CostBreakdownChart({
  byCategory,
}: {
  byCategory: Record<string, number>;
}) {
  const data = useMemo(() => {
    return Object.entries(byCategory)
      .filter(([, v]) => v > 0)
      .map(([cat, val]) => ({
        name: CATEGORY_LABELS[cat] ?? cat,
        value: Math.round(val),
        fill: CATEGORY_COLORS[cat] ?? "#6b7280",
      }))
      .sort((a, b) => b.value - a.value);
  }, [byCategory]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm text-center">
        No cost breakdown yet — costs accumulate as flights land, depart, and are delayed.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          innerRadius="40%"
          outerRadius="75%"
          paddingAngle={2}
          stroke="none"
        >
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.fill} />
          ))}
        </Pie>
        <Tooltip
          formatter={(v: unknown) => formatEur(v)}
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
          }}
          itemStyle={{ color: "#e2e8f0" }}
        />
        <Legend
          wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }}
          iconType="circle"
          iconSize={8}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

/* ──────── Hourly Cost/Revenue Curve ──────── */

function HourlyCurveChart({ hours }: { hours: HourlyCostPoint[] }) {
  if (hours.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm text-center">
        No hourly data yet — hourly costs and revenues appear as the simulation progresses through the day.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={hours}>
        <defs>
          <linearGradient id="colorCost" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="hour"
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          tickFormatter={(h: number) => `${h}:00`}
        />
        <YAxis
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: number) => formatEur(v)}
        />
        <Tooltip
          formatter={(v: unknown) => formatEur(v)}
          labelFormatter={(h) => `${h}:00`}
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
          }}
          itemStyle={{ color: "#e2e8f0" }}
        />
        <Area
          type="monotone"
          dataKey="cost_eur"
          name="Cost"
          stroke="#ef4444"
          fill="url(#colorCost)"
          strokeWidth={2}
        />
        <Area
          type="monotone"
          dataKey="revenue_eur"
          name="Revenue"
          stroke="#22c55e"
          fill="url(#colorRevenue)"
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ──────── Incident Cost Ranking ──────── */

function IncidentRankingTable({
  incidents,
}: {
  incidents: IncidentCostRanking[];
}) {
  if (incidents.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-4">
        No incident costs recorded
      </div>
    );
  }

  return (
    <div className="overflow-auto max-h-full">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-400 text-xs uppercase tracking-wider border-b border-panel-border">
            <th className="text-left py-2 px-2">Type</th>
            <th className="text-right py-2 px-2">Direct</th>
            <th className="text-right py-2 px-2">Response</th>
            <th className="text-right py-2 px-2 font-bold">Total</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((inc) => (
            <tr
              key={inc.incident_id}
              className="border-b border-panel-border/50 hover:bg-panel-hover/30"
            >
              <td className="py-2 px-2 text-gray-300">
                {inc.type.replace(/_/g, " ")}
              </td>
              <td className="py-2 px-2 text-right text-red-400">
                {formatEur(inc.direct_eur)}
              </td>
              <td className="py-2 px-2 text-right text-orange-400">
                {formatEur(inc.response_eur)}
              </td>
              <td className="py-2 px-2 text-right font-bold text-white">
                {formatEur(inc.total_eur)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ──────── Recommendations Panel ──────── */

function RecommendationsPanel({ recs }: { recs: FinancialRecommendation[] }) {
  if (recs.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-4">
        No active recommendations
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {recs.map((rec, i) => (
        <div
          key={i}
          className="bg-surface border border-panel-border rounded-lg p-3"
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-semibold text-accent">
              {rec.action.replace(/_/g, " ").toUpperCase()}
            </span>
            <span
              className={`text-xs px-2 py-0.5 rounded-full ${
                rec.confidence >= 0.7
                  ? "bg-green-900/50 text-green-300"
                  : "bg-amber-900/50 text-amber-300"
              }`}
            >
              {Math.round(rec.confidence * 100)}% confidence
            </span>
          </div>
          <p className="text-xs text-gray-400 mb-2">{rec.description}</p>
          <div className="flex gap-4 text-xs">
            <span className="text-red-400">
              Cost: {formatEur(rec.cost_eur)}
            </span>
            <span className="text-green-400">
              Saving: {formatEur(rec.saving_eur)}
            </span>
            <span className="font-bold text-white">
              Net: {formatEur(rec.net_benefit_eur)}
            </span>
            <span className="text-gray-500">
              Payback: {rec.payback_sim_minutes}min
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ──────── Category Breakdown Bar Chart ──────── */

function CategoryBarChart({
  byCategory,
}: {
  byCategory: Record<string, number>;
}) {
  const data = useMemo(() => {
    return Object.entries(byCategory)
      .filter(([, v]) => v > 0)
      .map(([cat, val]) => ({
        category: CATEGORY_LABELS[cat] ?? cat,
        amount: Math.round(val),
        fill: CATEGORY_COLORS[cat] ?? "#6b7280",
      }))
      .sort((a, b) => b.amount - a.amount);
  }, [byCategory]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        No data
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
        <XAxis
          type="number"
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: number) => formatEur(v)}
        />
        <YAxis
          type="category"
          dataKey="category"
          stroke="#64748b"
          tick={{ fontSize: 10 }}
          width={120}
        />
        <Tooltip
          formatter={(v: unknown) => formatEur(v)}
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
          }}
          itemStyle={{ color: "#e2e8f0" }}
        />
        <Bar dataKey="amount" name="Amount" radius={[0, 4, 4, 0]}>
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ──────── Main Page ──────── */

export default function CostDashboardPage() {
  const dayNumber = useSimStore((s) => s.status.day_number);
  const [selectedDay, setSelectedDay] = useState(1);
  const day = selectedDay || dayNumber || 1;

  const { summary, pnl, hourly, incidentRanking, recommendations } =
    useCostDashboardQueries(day);

  const costSummary = summary.data as CostSummary | undefined;
  const hourlyData = (hourly.data ?? []) as HourlyCostPoint[];
  const incidentData = (incidentRanking.data ?? []) as IncidentCostRanking[];
  const recsData = (recommendations.data ?? []) as FinancialRecommendation[];

  const isLoading =
    summary.isLoading ||
    pnl.isLoading ||
    hourly.isLoading;

  const hasError = summary.isError || hourly.isError;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
          <span>Loading cost data…</span>
        </div>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="text-red-400 text-lg">⚠️ Failed to load cost data</span>
          <span className="text-sm text-gray-500 max-w-md">
            The cost-service may not be running or is still starting up.
            Check that the simulation is active and generating flight events.
          </span>
          <button
            onClick={() => {
              summary.refetch();
              hourly.refetch();
            }}
            className="mt-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const totalCost = costSummary?.total_cost_eur ?? 0;
  const totalRevenue = costSummary?.total_revenue_eur ?? 0;
  const net = costSummary?.net_eur ?? 0;
  const margin = costSummary?.margin_pct ?? 0;
  const eu261 = costSummary?.eu261_exposure_eur ?? 0;
  const byCategory = costSummary?.by_category ?? {};
  const noData = totalCost === 0 && totalRevenue === 0;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">💰 Cost Dashboard</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Financial overview — Day {day}
            {costSummary?.sim_time
              ? ` · ${new Date(costSummary.sim_time).toLocaleTimeString()}`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-400">Day:</label>
          <input
            type="number"
            min={1}
            value={selectedDay}
            onChange={(e) => setSelectedDay(Math.max(1, Number(e.target.value)))}
            className="w-16 bg-surface border border-panel-border rounded px-2 py-1 text-sm text-white"
          />
        </div>
      </div>

      {/* No data explanation */}
      {noData && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg p-3 text-sm text-amber-300 flex items-start gap-2">
          <span className="text-lg">💡</span>
          <div>
            <strong>No cost data yet.</strong> Costs are computed from flight events
            (landings, departures, delays). Run the simulation for a few minutes to
            generate flights, and cost data will appear automatically.
          </div>
        </div>
      )}

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard
          label="Total Cost"
          value={formatEur(totalCost)}
          color="text-red-400"
        />
        <KpiCard
          label="Total Revenue"
          value={formatEur(totalRevenue)}
          color="text-green-400"
        />
        <KpiCard
          label="Net P&L"
          value={formatEur(net)}
          color={net >= 0 ? "text-green-400" : "text-red-400"}
          sub={`Margin: ${margin.toFixed(1)}%`}
        />
        <KpiCard
          label="EU261 Exposure"
          value={formatEur(eu261)}
          color={eu261 > 50_000 ? "text-red-400" : "text-amber-400"}
        />
        <KpiCard
          label="Cost Categories"
          value={String(Object.keys(byCategory).length)}
          sub="active categories"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Hourly Curve */}
        <div className="bg-surface-card border border-panel-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">
            Cost vs Revenue — Hourly
          </h2>
          <div className="h-64">
            <HourlyCurveChart hours={hourlyData} />
          </div>
        </div>

        {/* Cost Breakdown Donut */}
        <div className="bg-surface-card border border-panel-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">
            Cost Breakdown by Category
          </h2>
          <div className="h-64">
            <CostBreakdownChart byCategory={byCategory} />
          </div>
        </div>
      </div>

      {/* Second Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Category Bar Chart */}
        <div className="bg-surface-card border border-panel-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">
            Cost by Category
          </h2>
          <div className="h-72">
            <CategoryBarChart byCategory={byCategory} />
          </div>
        </div>

        {/* Incident Cost Ranking */}
        <div className="bg-surface-card border border-panel-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">
            Top Incidents by Financial Impact
          </h2>
          <div className="h-72">
            <IncidentRankingTable incidents={incidentData} />
          </div>
        </div>
      </div>

      {/* Recommendations */}
      <div className="bg-surface-card border border-panel-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">
          💡 Financial Recommendations
        </h2>
        <RecommendationsPanel recs={recsData} />
      </div>
    </div>
  );
}
