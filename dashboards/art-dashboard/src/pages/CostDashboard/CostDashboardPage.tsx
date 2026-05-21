import { useState } from "react";
import { useCostDashboardQueries } from "../../hooks/useQueries";
import { useSimStore } from "../../stores/simStore";
import { formatEur } from "../../utils/formatCurrency";
import { KpiCard } from "../../components/KpiCard";
import { ExportMenu } from "../../components/ExportMenu";
import { exportData } from "../../utils/exportData";
import {
  LoadingState,
  ErrorState,
  EmptyState,
} from "../../components/LoadingState";
import { CostBreakdownChart } from "./CostBreakdownChart";
import { HourlyCurveChart } from "./HourlyCurveChart";
import { IncidentRankingTable } from "./IncidentRankingTable";
import { RecommendationsPanel } from "./RecommendationsPanel";
import { CategoryBarChart } from "./CategoryBarChart";
import { CostRateModal } from "./CostRateEditor";
import { AutonomousModal } from "./AutonomousModal";
import type {
  CostSummary,
  HourlyCostPoint,
  IncidentCostRanking,
  FinancialRecommendation,
} from "../../types";

/* ──────── Main Page ──────── */

export default function CostDashboardPage() {
  const dayNumber = useSimStore((s) => s.status.day_number);
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [showRateModal, setShowRateModal] = useState(false);
  const [showAutonomousModal, setShowAutonomousModal] = useState(false);
  const day = selectedDay ?? dayNumber ?? 1;

  const { summary, pnl, hourly, incidentRanking, recommendations } =
    useCostDashboardQueries(day);

  const costSummary = summary.data as CostSummary | undefined;
  const hourlyData = (hourly.data ?? []) as HourlyCostPoint[];
  const incidentData = (incidentRanking.data ?? []) as IncidentCostRanking[];
  const recsData = (recommendations.data ?? []) as FinancialRecommendation[];

  const isLoading = summary.isLoading || pnl.isLoading || hourly.isLoading;

  const hasError = summary.isError || hourly.isError;

  if (isLoading) {
    return <LoadingState message="Loading cost data…" />;
  }

  if (hasError) {
    return (
      <ErrorState
        message="Failed to load cost data"
        detail="The cost-service may not be running or is still starting up. Check that the simulation is active and generating flight events."
        onRetry={() => {
          summary.refetch();
          hourly.refetch();
        }}
      />
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
          <button
            onClick={() => setShowAutonomousModal(true)}
            className="text-xs bg-purple-700/80 hover:bg-purple-600 text-white px-2.5 py-1.5 rounded transition-colors"
            title="Autonomous Operations & Incident Injection"
          >
            🤖 Autonomous
          </button>
          <button
            onClick={() => setShowRateModal(true)}
            className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-2.5 py-1.5 rounded transition-colors"
            title="Configure cost rates and profiles"
          >
            ⚙️ Rates
          </button>
          <ExportMenu
            onExport={(fmt) => {
              const rows = hourlyData.map((h) => ({
                day,
                hour: h.hour,
                cost_eur: h.cost_eur,
                revenue_eur: h.revenue_eur,
                net_eur: h.net_eur,
              }));
              // Add a summary row
              rows.push({
                day,
                hour: -1,
                cost_eur: totalCost,
                revenue_eur: totalRevenue,
                net_eur: net,
              });
              exportData(rows, `cost-dashboard-day-${day}`, fmt);
            }}
          />
          <label className="text-xs text-gray-400">Day:</label>
          <input
            type="number"
            min={1}
            value={selectedDay ?? dayNumber ?? 1}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (v === dayNumber) setSelectedDay(null);
              else setSelectedDay(Math.max(1, v));
            }}
            className="w-16 bg-surface border border-panel-border rounded px-2 py-1 text-sm text-white"
          />
          {selectedDay !== null && selectedDay !== dayNumber && (
            <button
              onClick={() => setSelectedDay(null)}
              className="text-[10px] text-gray-400 hover:text-white px-1.5 py-0.5 rounded bg-surface border border-panel-border"
              title="Sync with current sim day"
            >
              ↻ Live
            </button>
          )}
        </div>
      </div>

      {/* No data explanation */}
      {noData && (
        <EmptyState
          title="No cost data yet."
          description="Costs are computed from flight events (landings, departures, delays). Run the simulation for a few minutes to generate flights, and cost data will appear automatically."
        />
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

      {/* Cost Rate Modal */}
      {showRateModal && (
        <CostRateModal onClose={() => setShowRateModal(false)} />
      )}

      {/* Autonomous Operations Modal */}
      {showAutonomousModal && (
        <AutonomousModal onClose={() => setShowAutonomousModal(false)} />
      )}
    </div>
  );
}
