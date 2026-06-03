import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { planningApi } from "../../../hooks/useApi";
import { formatEur } from "../../../utils/formatCurrency";
import type { ScenarioSummary } from "../types";
import { MetricCard, CashFlowRow, ScenarioSelector } from "./shared";

export default function InvestmentTab() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: scenarios } = useQuery({
    queryKey: ["planning-scenarios"],
    queryFn: () =>
      planningApi.listScenarios({ status: "completed", limit: 50 }),
    refetchInterval: 10_000,
  });

  const { data: fullResults, isLoading: investLoading } = useQuery({
    queryKey: ["planning-results", selectedId],
    queryFn: () =>
      selectedId ? planningApi.getScenarioResults(selectedId) : null,
    enabled: !!selectedId,
    retry: 1,
  });

  const { data: growth } = useQuery({
    queryKey: ["demand-growth"],
    queryFn: () => planningApi.demandGrowth(),
  });

  const scenarioList = (scenarios?.scenarios ?? []) as ScenarioSummary[];
  const r = fullResults as Record<string, unknown> | undefined;
  const financials = r?.financials as Record<string, unknown> | undefined;
  const benefitBreakdown = r?.annual_benefit_breakdown as
    | Record<string, number>
    | undefined;
  const cashFlows = financials?.cumulative_cash_flows as number[] | undefined;

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

  const hasFinancials = !!(financials && Object.keys(financials).length > 0);

  const paybackIdx = useMemo(() => {
    if (!cashFlows) return -1;
    return cashFlows.findIndex((v) => v >= 0);
  }, [cashFlows]);

  return (
    <div className="space-y-5">
      {/* Methodology */}
      <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-3">
        <p className="text-xs text-slate-400 leading-relaxed">
          <strong className="text-slate-300">DCF Investment Analysis:</strong>{" "}
          Annual benefit = simulation cost savings × 365 days. Cash flows
          discounted at WACC.{" "}
          <strong className="text-slate-300">NPV &gt; 0</strong> → investment
          creates value.{" "}
          <strong className="text-slate-300">IRR &gt; WACC</strong> → returns
          exceed cost of capital. Costs from{" "}
          <strong className="text-slate-300">
            Eurocontrol Standard Inputs 2024
          </strong>{" "}
          (€102/min delay, €285/pax rebooking).
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

          {investLoading && selectedId && (
            <div className="text-sm text-slate-400 animate-pulse py-4">
              Loading investment analysis…
            </div>
          )}

          {hasFinancials ? (
            <>
              {/* Headline metrics */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard
                  label="Net Present Value"
                  value={formatEur(financials.npv_eur as number)}
                  sublabel={`Over ${financials.years_horizon}yr at ${((financials.discount_rate as number) * 100).toFixed(0)}% WACC`}
                  color={
                    (financials.npv_eur as number) > 0
                      ? "text-emerald-400"
                      : "text-red-400"
                  }
                />
                <MetricCard
                  label="IRR"
                  value={
                    financials.irr_meaningful === false || financials.irr_pct == null
                      ? "n/a"
                      : `${((financials.irr_pct as number) ?? 0).toFixed(1)}%`
                  }
                  sublabel={
                    financials.irr_meaningful === false || financials.irr_pct == null
                      ? "No real IRR (cashflow has no sign change)"
                      : `${(financials.irr_pct as number) > (financials.discount_rate as number) * 100 ? "Exceeds" : "Below"} ${((financials.discount_rate as number) * 100).toFixed(0)}% WACC`
                  }
                  color={
                    financials.irr_meaningful === false || financials.irr_pct == null
                      ? "text-slate-400"
                      : (financials.irr_pct as number) >
                          (financials.discount_rate as number) * 100
                        ? "text-emerald-400"
                        : "text-amber-400"
                  }
                />
                <MetricCard
                  label="Payback Period"
                  value={`${((financials.payback_years as number) ?? Infinity).toFixed(1)} yrs`}
                  sublabel={
                    (financials.payback_years as number) <
                    (financials.years_horizon as number)
                      ? "Recovered within horizon"
                      : "Not recovered within horizon"
                  }
                  color={
                    (financials.payback_years as number) < 15
                      ? "text-cyan-400"
                      : "text-amber-400"
                  }
                />
                <MetricCard
                  label="Recommendation"
                  value={String(financials.recommendation ?? "—")}
                  sublabel={
                    financials.recommendation === "invest"
                      ? "NPV positive, IRR exceeds WACC"
                      : financials.recommendation === "marginal"
                        ? "NPV near zero — sensitive to assumptions"
                        : "NPV negative — cost exceeds benefit"
                  }
                  color={
                    financials.recommendation === "invest"
                      ? "text-emerald-400"
                      : financials.recommendation === "marginal"
                        ? "text-amber-400"
                        : "text-red-400"
                  }
                />
              </div>

              {/* Cash flow breakdown */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
                  <h3 className="text-sm font-semibold text-white mb-3">
                    Annual Cash Flow
                  </h3>
                  <div className="space-y-2">
                    <CashFlowRow
                      label="Capex (Year 0)"
                      value={-(financials.capex_eur as number)}
                    />
                    <CashFlowRow
                      label="Annual Benefit"
                      value={financials.annual_benefit_eur as number}
                    />
                    <CashFlowRow
                      label="Annual Opex Delta"
                      value={-(financials.annual_opex_eur as number)}
                    />
                    <CashFlowRow
                      label="Net Annual"
                      value={financials.net_annual_eur as number}
                      bold
                    />
                  </div>
                </div>

                {benefitBreakdown &&
                  Object.keys(benefitBreakdown).length > 0 && (
                    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">
                        Benefit Breakdown
                      </h3>
                      <div className="space-y-2">
                        {Object.entries(benefitBreakdown).map(([key, val]) => {
                          const label = key
                            .replace(/_annual$/, "")
                            .replace(/_/g, " ")
                            .replace(/\b\w/g, (c) => c.toUpperCase());
                          const isTotal = key === "total_annual_benefit";
                          return (
                            <div
                              key={key}
                              className={`flex items-center justify-between text-xs ${isTotal ? "border-t border-slate-600 pt-2 mt-1 font-bold" : ""}`}
                            >
                              <span
                                className={
                                  isTotal ? "text-white" : "text-slate-400"
                                }
                              >
                                {label}
                              </span>
                              <span
                                className={`font-mono ${isTotal ? "text-emerald-400" : "text-slate-300"}`}
                              >
                                {formatEur(val)}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
              </div>

              {/* Cumulative cash flow chart */}
              {cashFlows && cashFlows.length > 0 && (
                <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
                  <h3 className="text-sm font-semibold text-white mb-3">
                    Cumulative Cash Flow
                  </h3>
                  <div className="space-y-1">
                    {cashFlows.map((val, yr) => {
                      const maxAbs = Math.max(
                        ...cashFlows.map((v) => Math.abs(v)),
                        1,
                      );
                      const pct = Math.abs(val) / maxAbs;
                      const isPayback = yr === paybackIdx;
                      return (
                        <div
                          key={yr}
                          className="flex items-center gap-2 text-xs"
                        >
                          <span className="w-8 text-right text-slate-500 shrink-0">
                            Y{yr}
                          </span>
                          <div className="flex-1 h-4 relative">
                            <div
                              className={`absolute top-0 h-full rounded-sm ${
                                val >= 0
                                  ? "bg-emerald-500/40 left-1/2"
                                  : "bg-red-500/40 right-1/2"
                              }`}
                              style={{ width: `${pct * 50}%` }}
                            />
                            {isPayback && (
                              <div className="absolute top-0 left-1/2 h-full w-px bg-cyan-400" />
                            )}
                          </div>
                          <span
                            className={`w-20 text-right font-mono shrink-0 ${
                              val >= 0 ? "text-emerald-400" : "text-red-400"
                            }`}
                          >
                            {formatEur(val)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {paybackIdx >= 0 && (
                    <div className="text-xs text-cyan-400 mt-2">
                      ↑ Payback in Year {paybackIdx}
                    </div>
                  )}
                </div>
              )}
            </>
          ) : selectedId && !investLoading ? (
            <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-8 text-center">
              <p className="text-slate-400 text-sm">
                No investment analysis available.
              </p>
              <p className="text-slate-500 text-xs mt-1">
                Set capex or opex when creating the scenario, or use a template.
              </p>
            </div>
          ) : null}
        </>
      )}

      {/* Demand growth */}
      {growth != null && (
        <DemandGrowthPanel growth={growth as Record<string, unknown>} />
      )}
    </div>
  );
}

/* ─── Demand Growth Panel ─────────────────────────────────── */

function DemandGrowthPanel({ growth }: { growth: Record<string, unknown> }) {
  const projections = growth.projections as Record<
    string,
    Record<string, unknown>
  >;
  if (!projections) return null;

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
      <h3 className="text-sm font-semibold text-white mb-1">
        Eurocontrol STATFOR Demand Growth
      </h3>
      <p className="text-xs text-slate-400 mb-3">
        Long-term traffic growth scenarios affecting future NPV calculations.
      </p>
      <div className="grid grid-cols-3 gap-3">
        {Object.entries(projections).map(([scenario, data]) => (
          <div
            key={scenario}
            className="bg-slate-700/50 rounded-lg p-3 border border-slate-600"
          >
            <div className="text-xs text-slate-400 uppercase">{scenario}</div>
            <div className="text-lg font-bold text-white mt-1">
              {((data.projected_annual_pax as number) / 1_000_000).toFixed(1)}M
              pax/yr
            </div>
            <div className="text-xs text-slate-400 mt-0.5">
              {Number(data.growth_rate_pct)}% CAGR · ×
              {Number(data.growth_factor)} in 10yr
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
