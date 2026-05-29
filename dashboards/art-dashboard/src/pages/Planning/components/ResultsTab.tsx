import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { planningApi } from "../../../hooks/useApi";
import { formatEur } from "../../../utils/formatCurrency";
import type {
  KpiDist,
  DeltaEntry,
  ScenarioSummary,
  InfraChange,
} from "../types";
import { KPI_META } from "../types";
import { ScenarioSelector, Tooltip, formatDuration } from "./shared";

/* ─── Results Comparison Tab ──────────────────────────────── */

export default function ResultsTab() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: scenarios } = useQuery({
    queryKey: ["planning-scenarios"],
    queryFn: () =>
      planningApi.listScenarios({ status: "completed", limit: 50 }),
    refetchInterval: 10_000,
  });

  const {
    data: results,
    isLoading: resultsLoading,
    error: resultsError,
  } = useQuery({
    queryKey: ["planning-results", selectedId],
    queryFn: () =>
      selectedId ? planningApi.getScenarioResults(selectedId) : null,
    enabled: !!selectedId,
    retry: 1,
  });

  const scenarioList = (scenarios?.scenarios ?? []) as ScenarioSummary[];
  const r = results as Record<string, unknown> | undefined;
  const kpis = r?.kpis as Record<string, KpiDist> | undefined;
  const baselineKpis = r?.baseline_kpis as Record<string, KpiDist> | undefined;
  const delta = r?.delta_vs_baseline as Record<string, DeltaEntry> | undefined;
  const infraChanges = (r?.infrastructure_changes ?? []) as InfraChange[];
  const duration = r?.run_duration_seconds as number | undefined;

  // Auto-select first completed scenario; reset if deleted
  useEffect(() => {
    if (scenarioList.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !scenarioList.find((s) => s.id === selectedId)) {
      setSelectedId(scenarioList[0].id);
    }
  }, [selectedId, scenarioList]);

  return (
    <div className="space-y-5">
      {/* Methodology */}
      <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-3">
        <p className="text-xs text-slate-400 leading-relaxed">
          <strong className="text-slate-300">How results are computed:</strong>{" "}
          Each scenario simulates the same dates and random seeds for both the{" "}
          <em>baseline</em> (current KART config) and the{" "}
          <em>modified scenario</em>. The delta shows what changes if you
          implement the scenario. With Monte Carlo runs &gt; 1, KPIs show the
          statistical distribution (P5–P95 = 90% confidence band).
        </p>
      </div>

      {scenarioList.length === 0 ? (
        <div className="text-center text-slate-500 py-12">
          No completed scenarios. Create one in the Builder tab.
        </div>
      ) : (
        <>
          <ScenarioSelector
            scenarios={scenarioList}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />

          {resultsLoading && (
            <div className="text-sm text-slate-400 animate-pulse py-4">
              Loading results…
            </div>
          )}

          {resultsError && (
            <div className="bg-red-900/20 border border-red-800 rounded-lg p-3 text-sm text-red-300">
              Failed to load results. The scenario may need to be re-run.
            </div>
          )}

          {kpis && delta && (
            <>
              {/* Infrastructure changes */}
              {infraChanges.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {infraChanges.map((c, i) => (
                    <div
                      key={i}
                      className="bg-slate-800/60 rounded-lg border border-slate-700 px-3 py-2 text-xs"
                    >
                      <span className="text-slate-400">{c.parameter}: </span>
                      <span className="text-slate-500">{c.baseline}</span>
                      <span className="text-slate-600 mx-1">→</span>
                      <span className="text-white font-medium">
                        {c.scenario}
                      </span>
                      <span
                        className={`ml-1 ${c.change > 0 ? "text-cyan-400" : "text-amber-400"}`}
                      >
                        ({c.change > 0 ? "+" : ""}
                        {c.change})
                      </span>
                    </div>
                  ))}
                  {duration != null && (
                    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 px-3 py-2 text-xs text-slate-500">
                      Computed in {formatDuration(duration)}
                    </div>
                  )}
                </div>
              )}

              {/* KPI comparison table */}
              <KpiComparisonTable
                kpis={kpis}
                baselineKpis={baselineKpis}
                delta={delta}
              />
            </>
          )}
        </>
      )}

      {/* Multi-year projection */}
      {scenarioList.length > 0 && (
        <MultiYearProjection scenarioList={scenarioList} />
      )}
    </div>
  );
}

/* ─── KPI Comparison Table ────────────────────────────────── */

function KpiComparisonTable({
  kpis,
  baselineKpis,
  delta,
}: {
  kpis: Record<string, KpiDist>;
  baselineKpis?: Record<string, KpiDist>;
  delta: Record<string, DeltaEntry>;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-700 text-slate-400">
            <th className="text-left py-2 px-3 font-medium">KPI</th>
            <th className="text-right py-2 px-3 font-medium">Baseline</th>
            <th className="text-right py-2 px-3 font-medium">Scenario</th>
            <th className="text-right py-2 px-3 font-medium">Change</th>
            <th className="text-right py-2 px-3 font-medium">90% Conf.</th>
            <th className="text-center py-2 px-3 font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(kpis).map(([key, dist]) => {
            const meta = KPI_META[key];
            if (!meta) return null;
            const d = delta[key];
            const b = baselineKpis?.[key];
            if (!d) return null;

            const isImproved = meta.lowerIsBetter
              ? d.pct_change < -2
              : d.pct_change > 2;
            const isDegraded = meta.lowerIsBetter
              ? d.pct_change > 2
              : d.pct_change < -2;
            const isNeutral = Math.abs(d.pct_change) <= 2;

            const changeColor = isImproved
              ? "text-emerald-400"
              : isDegraded
                ? "text-red-400"
                : "text-slate-400";
            const verdictIcon = isImproved ? "✓" : isDegraded ? "✗" : "—";
            const verdictColor = isImproved
              ? "text-emerald-400"
              : isDegraded
                ? "text-red-400"
                : "text-slate-500";

            return (
              <tr
                key={key}
                className="border-b border-slate-800 hover:bg-slate-800/30 transition-colors"
              >
                <td className="py-2 px-3">
                  <span className="text-white font-medium">{meta.label}</span>
                  <Tooltip text={meta.description} />
                </td>
                <td className="text-right py-2 px-3 text-slate-400">
                  {b ? meta.format(b.mean) : "—"}
                </td>
                <td className="text-right py-2 px-3 text-white font-medium">
                  {meta.format(dist.mean)}
                </td>
                <td
                  className={`text-right py-2 px-3 font-medium ${changeColor}`}
                >
                  {d.pct_change > 0 ? "+" : ""}
                  {d.pct_change.toFixed(1)}%
                </td>
                <td className="text-right py-2 px-3 text-slate-500">
                  {meta.format(dist.p5)} – {meta.format(dist.p95)}
                </td>
                <td className={`text-center py-2 px-3 text-lg ${verdictColor}`}>
                  {verdictIcon}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="flex items-center gap-4 text-[10px] text-slate-500 mt-2 px-3">
        <span>
          <span className="text-emerald-400">✓</span> Improvement (&gt;2%)
        </span>
        <span>
          <span className="text-red-400">✗</span> Degradation (&gt;2%)
        </span>
        <span>
          <span className="text-slate-400">—</span> Negligible (±2%)
        </span>
        <span className="ml-auto">Hover KPI name for description</span>
      </div>
    </div>
  );
}

/* ─── Multi-Year Projection ───────────────────────────────── */

const CHART_COLORS = [
  "bg-cyan-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-purple-500",
  "bg-rose-500",
];

function MultiYearProjection({
  scenarioList,
}: {
  scenarioList: ScenarioSummary[];
}) {
  const [kpiKey, setKpiKey] = useState("avg_delay_minutes");
  const [growthRate, setGrowthRate] = useState(3.4);
  const [yearsAhead, setYearsAhead] = useState(10);

  const ids = useMemo(() => scenarioList.map((s) => s.id), [scenarioList]);

  const { data: projectionData } = useQuery({
    queryKey: ["planning-multiyear", ids, yearsAhead, growthRate],
    queryFn: () =>
      planningApi.compareMultiyear({
        scenario_ids: ids,
        years_ahead: yearsAhead,
        growth_rate_pct: growthRate,
      }),
    enabled: ids.length > 0,
    staleTime: 30_000,
  });

  const scenarios = projectionData?.scenarios ?? [];
  const meta = KPI_META[kpiKey];

  if (scenarios.length === 0) return null;

  // Compute scale
  const allValues = scenarios.flatMap((s) =>
    s.yearly_kpis.map((yk) => yk.kpis[kpiKey] ?? 0),
  );
  const maxVal = Math.max(...allValues, 1);

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-semibold text-white">
          Multi-Year KPI Projection
        </h4>
        <div className="flex items-center gap-3">
          <select
            value={kpiKey}
            onChange={(e) => setKpiKey(e.target.value)}
            className="bg-slate-700 rounded px-2 py-1 text-xs text-white border border-slate-600"
          >
            {Object.entries(KPI_META).map(([key, m]) => (
              <option key={key} value={key}>
                {m.label}
              </option>
            ))}
          </select>
          <div className="flex items-center gap-1">
            <span className="text-xs text-slate-400">Growth:</span>
            <input
              type="number"
              min={-5}
              max={10}
              step={0.5}
              value={growthRate}
              onChange={(e) => setGrowthRate(Number(e.target.value))}
              className="w-14 bg-slate-700 rounded px-2 py-1 text-xs text-white border border-slate-600"
            />
            <span className="text-xs text-slate-400">%</span>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-3">
        {scenarios.map((s, i) => (
          <div
            key={s.scenario_id}
            className="flex items-center gap-1.5 text-xs"
          >
            <div
              className={`w-3 h-3 rounded ${CHART_COLORS[i % CHART_COLORS.length]}`}
            />
            <span className="text-slate-300">{s.scenario_name}</span>
          </div>
        ))}
      </div>

      {/* Bar chart */}
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {Array.from({ length: yearsAhead + 1 }, (_, yr) => (
          <div key={yr} className="flex items-center gap-2 text-xs">
            <span className="w-8 text-slate-500 text-right">Y{yr}</span>
            <div className="flex-1 flex gap-1">
              {scenarios.map((s, i) => {
                const val = s.yearly_kpis[yr]?.kpis[kpiKey] ?? 0;
                const pct = (val / maxVal) * 100;
                return (
                  <div
                    key={s.scenario_id}
                    className={`${CHART_COLORS[i % CHART_COLORS.length]} rounded h-4 transition-all`}
                    style={{ width: `${Math.max(1, pct / scenarios.length)}%` }}
                    title={`${s.scenario_name}: ${meta ? meta.format(val) : val.toFixed(2)}`}
                  />
                );
              })}
            </div>
            <span className="w-20 text-slate-500 text-right">
              {meta
                ? meta.format(scenarios[0]?.yearly_kpis[yr]?.kpis[kpiKey] ?? 0)
                : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
