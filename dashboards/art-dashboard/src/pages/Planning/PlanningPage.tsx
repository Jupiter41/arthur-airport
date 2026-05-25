import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { planningApi } from "../../hooks/useApi";
import { formatEur } from "../../utils/formatCurrency";

/* ─── Types ───────────────────────────────────────────────── */

type Tab = "builder" | "results" | "investment" | "audit";

interface KpiDist {
  mean: number;
  std: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

interface DeltaEntry {
  baseline_mean: number;
  scenario_mean: number;
  absolute_change: number;
  pct_change: number;
}

interface ScenarioSummary {
  id: string;
  name: string;
  status: string;
  horizon: string;
  monte_carlo_runs: number;
  created_at: string;
  completed_at?: string;
}

interface InfraChange {
  parameter: string;
  baseline: number;
  scenario: number;
  change: number;
}

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: "builder", label: "Scenario Builder", icon: "🏗️" },
  { key: "results", label: "Results", icon: "📊" },
  { key: "investment", label: "Investment", icon: "💰" },
  { key: "audit", label: "Decision Audit", icon: "📋" },
];

/* ─── KPI metadata for human-readable names and guidance ──── */

const KPI_META: Record<
  string,
  {
    label: string;
    unit: string;
    description: string;
    lowerIsBetter: boolean;
    format: (v: number) => string;
  }
> = {
  avg_delay_minutes: {
    label: "Avg Delay",
    unit: "min",
    description:
      "Average departure delay per flight. Eurocontrol defines >15 min as 'delayed'. Lower is better.",
    lowerIsBetter: true,
    format: (v) => `${v.toFixed(1)} min`,
  },
  on_time_rate: {
    label: "On-Time Rate",
    unit: "%",
    description:
      "Fraction of flights departing within 15 minutes of schedule. Industry benchmark: 80%+. Higher is better.",
    lowerIsBetter: false,
    format: (v) => `${(v * 100).toFixed(1)}%`,
  },
  missed_connections: {
    label: "Missed Connections",
    unit: "/day",
    description:
      "Passengers who miss connecting flights due to delays. Each costs ~€285 in rebooking. Lower is better.",
    lowerIsBetter: true,
    format: (v) => v.toFixed(1),
  },
  gate_utilisation_pct: {
    label: "Gate Utilisation",
    unit: "%",
    description:
      "Percentage of gate-hours used vs available. 70-85% is optimal; above 90% causes conflicts. Moderate is better.",
    lowerIsBetter: false,
    format: (v) => `${v.toFixed(1)}%`,
  },
  runway_utilisation_pct: {
    label: "Runway Utilisation",
    unit: "%",
    description:
      "Peak-hour runway throughput vs theoretical max. Above 85% causes queuing delays. Moderate is better.",
    lowerIsBetter: false,
    format: (v) => `${v.toFixed(1)}%`,
  },
  eu261_liability_eur: {
    label: "EU261 Liability",
    unit: "€/day",
    description:
      "Daily compensation liability under EU Regulation 261/2004. €250-600 per qualifying passenger. Lower is better.",
    lowerIsBetter: true,
    format: (v) => formatEur(v),
  },
  total_cost_eur: {
    label: "Total Cost",
    unit: "€/day",
    description:
      "Total daily operating cost including delay costs, EU261, landing fees, and gate fees. Lower is better.",
    lowerIsBetter: true,
    format: (v) => formatEur(v),
  },
  total_revenue_eur: {
    label: "Total Revenue",
    unit: "€/day",
    description:
      "Total daily revenue from passenger fees, landing fees, and gate fees. Higher is better.",
    lowerIsBetter: false,
    format: (v) => formatEur(v),
  },
  gate_conflicts: {
    label: "Gate Conflicts",
    unit: "/day",
    description:
      "Flights that couldn't find an available gate at boarding time, causing delays. Lower is better.",
    lowerIsBetter: true,
    format: (v) => v.toFixed(1),
  },
  security_wait_max_minutes: {
    label: "Max Security Wait",
    unit: "min",
    description:
      "Longest security queue wait across all terminals. EU benchmark: <20 min. Lower is better.",
    lowerIsBetter: true,
    format: (v) => `${v.toFixed(1)} min`,
  },
};

/* ─── Main Page ───────────────────────────────────────────── */

export default function PlanningPage() {
  const [activeTab, setActiveTab] = useState<Tab>("builder");

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-slate-700 bg-slate-900/50 px-4">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? "border-cyan-400 text-cyan-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === "builder" && <ScenarioBuilder />}
        {activeTab === "results" && <ResultsComparison />}
        {activeTab === "investment" && <InvestmentDashboard />}
        {activeTab === "audit" && <AuditTrail />}
      </div>
    </div>
  );
}

/* ─── Tab 1: Scenario Builder ─────────────────────────────── */

type TemplateType = "custom" | "add_gate" | "add_runway" | "new_route" | "security_lanes";

const TEMPLATE_INFO: Record<
  TemplateType,
  { label: string; icon: string; description: string }
> = {
  custom: {
    label: "Custom Scenario",
    icon: "⚙️",
    description: "Build a scenario from scratch with full control over all parameters.",
  },
  add_gate: {
    label: "Add Gates",
    icon: "🚪",
    description:
      "Evaluate adding contact gates to a terminal. Auto-sets capex (€8M/gate) and opex (€120K/yr/gate).",
  },
  add_runway: {
    label: "Add Runway",
    icon: "🛫",
    description:
      "Evaluate adding a new runway. Auto-sets capex (€800M) and opex (€12M/yr). 30-year horizon.",
  },
  new_route: {
    label: "New Route",
    icon: "🌍",
    description:
      "Evaluate launching a new route. No infrastructure capex — pure demand-side analysis.",
  },
  security_lanes: {
    label: "Security Lanes",
    icon: "🔒",
    description:
      "Evaluate adding/removing security screening lanes. Auto-calculates staffing cost.",
  },
};

function ScenarioBuilder() {
  const qc = useQueryClient();
  const [templateType, setTemplateType] = useState<TemplateType>("custom");
  const [lastEstimate, setLastEstimate] = useState<string | null>(null);

  // Template-specific fields
  const [gateTerminal, setGateTerminal] = useState("B");
  const [gateCount, setGateCount] = useState(1);
  const [runwayId, setRunwayId] = useState("09C");
  const [runwayIls, setRunwayIls] = useState(true);
  const [runwayLength, setRunwayLength] = useState(3000);
  const [routeDest, setRouteDest] = useState("LHR");
  const [routeFlights, setRouteFlights] = useState(2);
  const [routeAircraft, setRouteAircraft] = useState("A320");
  const [secLanes, setSecLanes] = useState<Record<string, number>>({ A: 0, B: 1, C: 0 });

  // Custom form fields
  const [form, setForm] = useState({
    name: "",
    description: "",
    horizon: "day",
    monte_carlo_runs: 1,
    demand_source: "simulation",
    capex_eur: 0,
    opex_delta_eur: 0,
    years_horizon: 25,
    discount_rate: 0.07,
  });

  // Time estimation query — updates when horizon/MC runs change
  const estimateHorizon = templateType === "custom" ? form.horizon : 
    templateType === "add_gate" ? "month" :
    templateType === "add_runway" ? "year" :
    templateType === "new_route" ? "month" : "week";
  const estimateMC = templateType === "custom" ? form.monte_carlo_runs :
    templateType === "add_runway" ? 100 : 200;

  const { data: timeEstimate } = useQuery({
    queryKey: ["planning-estimate", estimateHorizon, estimateMC],
    queryFn: () => planningApi.estimateDuration(estimateHorizon, estimateMC),
    staleTime: 30_000,
  });

  const { data: scenarios, isLoading } = useQuery({
    queryKey: ["planning-scenarios"],
    queryFn: () => planningApi.listScenarios({ limit: 50 }),
    refetchInterval: 5000,
  });

  const createCustomMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => planningApi.createScenario(body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["planning-scenarios"] });
      if (data?.estimated_duration_human) {
        setLastEstimate(data.estimated_duration_human);
      }
    },
  });

  const createTemplateMutation = useMutation({
    mutationFn: (args: { template: string; body: Record<string, unknown> }) =>
      planningApi.createFromTemplate(args.template, args.body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["planning-scenarios"] });
      const d = data as Record<string, unknown> | undefined;
      if (d?.estimated_duration_human) {
        setLastEstimate(d.estimated_duration_human as string);
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => planningApi.deleteScenario(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["planning-scenarios"] }),
  });

  const handleCustomSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    createCustomMutation.mutate(form);
  };

  const handleTemplateSubmit = () => {
    switch (templateType) {
      case "add_gate":
        createTemplateMutation.mutate({
          template: "add_gate",
          body: { terminal: gateTerminal, additional_gates: gateCount },
        });
        break;
      case "add_runway":
        createTemplateMutation.mutate({
          template: "add_runway",
          body: { runway_id: runwayId, ils_capable: runwayIls, length_m: runwayLength },
        });
        break;
      case "new_route":
        createTemplateMutation.mutate({
          template: "new_route",
          body: { destination_iata: routeDest, daily_flights: routeFlights, aircraft_type: routeAircraft },
        });
        break;
      case "security_lanes": {
        const nonZero = Object.fromEntries(
          Object.entries(secLanes).filter(([, v]) => v !== 0),
        );
        if (Object.keys(nonZero).length === 0) return;
        createTemplateMutation.mutate({
          template: "security_lanes",
          body: { lanes_delta: nonZero },
        });
        break;
      }
    }
  };

  const isPending = createCustomMutation.isPending || createTemplateMutation.isPending;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
      {/* Builder panel — 3 cols */}
      <div className="lg:col-span-3 space-y-4">
        {/* Template selector */}
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
          <h3 className="text-base font-semibold text-white mb-1">
            What do you want to evaluate?
          </h3>
          <p className="text-xs text-slate-400 mb-4">
            Choose a scenario template. Each pre-fills realistic cost parameters from industry benchmarks (Eurocontrol Standard Inputs, ICAO guidelines).
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            {(Object.keys(TEMPLATE_INFO) as TemplateType[]).map((key) => {
              const t = TEMPLATE_INFO[key];
              return (
                <button
                  key={key}
                  onClick={() => setTemplateType(key)}
                  className={`text-left rounded-lg p-3 text-xs border transition-colors ${
                    templateType === key
                      ? "bg-cyan-600/20 border-cyan-500 text-cyan-300"
                      : "bg-slate-700/50 border-slate-600 text-slate-300 hover:bg-slate-600/50"
                  }`}
                >
                  <div className="text-lg mb-1">{t.icon}</div>
                  <div className="font-medium text-white text-xs">{t.label}</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Template-specific form */}
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
          <h4 className="text-sm font-medium text-white mb-1">
            {TEMPLATE_INFO[templateType].icon} {TEMPLATE_INFO[templateType].label}
          </h4>
          <p className="text-xs text-slate-400 mb-4">
            {TEMPLATE_INFO[templateType].description}
          </p>

          {templateType === "custom" && (
            <form onSubmit={handleCustomSubmit} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs text-slate-400 mb-1">Scenario Name</label>
                  <input
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600 focus:border-cyan-400 outline-none"
                    placeholder="e.g. Add gate B15 + security lane"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs text-slate-400 mb-1">Description</label>
                  <textarea
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    rows={2}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600 focus:border-cyan-400 outline-none"
                    placeholder="Describe what infrastructure changes this scenario models..."
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Time Horizon
                    <Tooltip text="day = 1 day, week = 7 days, month = 30 days. Longer horizons give more robust statistics but take longer to compute." />
                  </label>
                  <select
                    value={form.horizon}
                    onChange={(e) => setForm({ ...form, horizon: e.target.value })}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  >
                    <option value="day">1 Day</option>
                    <option value="week">1 Week (7 days)</option>
                    <option value="month">1 Month (30 days)</option>
                    <option value="year">1 Year (sampled)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Monte Carlo Runs
                    <Tooltip text="Number of independent simulation runs with different random seeds. More runs = tighter confidence bands. 1 = deterministic. Recommended: 50-200 for investment decisions." />
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={form.monte_carlo_runs}
                    onChange={(e) =>
                      setForm({ ...form, monte_carlo_runs: parseInt(e.target.value) || 1 })
                    }
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Capex (€)
                    <Tooltip text="One-time capital expenditure for the infrastructure change. E.g. €8M per gate, €800M per runway." />
                  </label>
                  <input
                    type="number"
                    min={0}
                    value={form.capex_eur}
                    onChange={(e) =>
                      setForm({ ...form, capex_eur: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Annual Opex Delta (€)
                    <Tooltip text="Additional annual operating cost vs. today. E.g. €120K/yr per gate (maintenance), €204K/yr per security lane (staffing)." />
                  </label>
                  <input
                    type="number"
                    value={form.opex_delta_eur}
                    onChange={(e) =>
                      setForm({ ...form, opex_delta_eur: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Investment Horizon (years)
                    <Tooltip text="How many years to project for NPV calculation. Typical: 20-30 years for infrastructure." />
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={form.years_horizon}
                    onChange={(e) =>
                      setForm({ ...form, years_horizon: parseInt(e.target.value) || 25 })
                    }
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Discount Rate
                    <Tooltip text="Weighted average cost of capital (WACC). Typical airport: 6-8%. Higher = more conservative." />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={0.3}
                    step={0.01}
                    value={form.discount_rate}
                    onChange={(e) =>
                      setForm({ ...form, discount_rate: parseFloat(e.target.value) || 0.07 })
                    }
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
              </div>
              {/* Time estimation */}
              {timeEstimate && (
                <TimeEstimateBar estimate={timeEstimate} />
              )}
              <button
                type="submit"
                disabled={isPending || !form.name.trim()}
                className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-600 disabled:text-slate-400 text-white font-medium py-2 rounded transition-colors"
              >
                {isPending ? "Running…" : "Create & Run Scenario"}
              </button>
            </form>
          )}

          {templateType === "add_gate" && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Terminal</label>
                  <select
                    value={gateTerminal}
                    onChange={(e) => setGateTerminal(e.target.value)}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  >
                    <option value="A">Terminal A (14 gates)</option>
                    <option value="B">Terminal B (14 gates)</option>
                    <option value="C">Terminal C (14 gates)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Gates to Add</label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={gateCount}
                    onChange={(e) => setGateCount(parseInt(e.target.value) || 1)}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
              </div>
              <CostPreview
                items={[
                  { label: "Capex", value: formatEur(gateCount * 8_000_000), note: `${gateCount} gate(s) × €8M` },
                  { label: "Annual Opex", value: formatEur(gateCount * 120_000), note: `${gateCount} gate(s) × €120K/yr` },
                  { label: "Horizon", value: "25 years" },
                  { label: "Monte Carlo", value: "200 runs" },
                ]}
              />
              {timeEstimate && <TimeEstimateBar estimate={timeEstimate} />}
              <button
                onClick={handleTemplateSubmit}
                disabled={isPending}
                className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-600 text-white font-medium py-2 rounded transition-colors"
              >
                {isPending ? "Running…" : `Add ${gateCount} Gate(s) to Terminal ${gateTerminal}`}
              </button>
            </div>
          )}

          {templateType === "add_runway" && (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Runway ID</label>
                  <input
                    value={runwayId}
                    onChange={(e) => setRunwayId(e.target.value)}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    placeholder="e.g. 09C"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">ILS Capable</label>
                  <select
                    value={runwayIls ? "yes" : "no"}
                    onChange={(e) => setRunwayIls(e.target.value === "yes")}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  >
                    <option value="yes">Yes (all-weather ops)</option>
                    <option value="no">No (visual only)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Length (m)</label>
                  <input
                    type="number"
                    min={1500}
                    max={5000}
                    value={runwayLength}
                    onChange={(e) => setRunwayLength(parseInt(e.target.value) || 3000)}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
              </div>
              <CostPreview
                items={[
                  { label: "Capex", value: "€800M", note: "Scaled from major airport runway projects" },
                  { label: "Annual Opex", value: "€12M/yr", note: "Maintenance, ATC, lighting, de-icing" },
                  { label: "Horizon", value: "30 years" },
                  { label: "Monte Carlo", value: "100 runs" },
                ]}
              />
              {timeEstimate && <TimeEstimateBar estimate={timeEstimate} />}
              <button
                onClick={handleTemplateSubmit}
                disabled={isPending}
                className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-600 text-white font-medium py-2 rounded transition-colors"
              >
                {isPending ? "Running…" : `Add Runway ${runwayId}`}
              </button>
            </div>
          )}

          {templateType === "new_route" && (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Destination IATA</label>
                  <input
                    value={routeDest}
                    onChange={(e) => setRouteDest(e.target.value.toUpperCase())}
                    maxLength={4}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    placeholder="e.g. LHR"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Daily Flights</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={routeFlights}
                    onChange={(e) => setRouteFlights(parseInt(e.target.value) || 1)}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Aircraft Type</label>
                  <select
                    value={routeAircraft}
                    onChange={(e) => setRouteAircraft(e.target.value)}
                    className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                  >
                    <option value="A320">A320 (180 pax)</option>
                    <option value="A321">A321 (220 pax)</option>
                    <option value="B738">B738 (189 pax)</option>
                    <option value="B77W">B77W (396 pax)</option>
                    <option value="A333">A333 (300 pax)</option>
                    <option value="E195">E195 (120 pax)</option>
                  </select>
                </div>
              </div>
              <CostPreview
                items={[
                  { label: "Capex", value: "€0", note: "No infrastructure change" },
                  { label: "Analysis", value: "Demand-side impact on existing operations" },
                  { label: "Horizon", value: "5 years" },
                  { label: "Monte Carlo", value: "100 runs" },
                ]}
              />
              {timeEstimate && <TimeEstimateBar estimate={timeEstimate} />}
              <button
                onClick={handleTemplateSubmit}
                disabled={isPending || routeDest.length < 3}
                className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-600 text-white font-medium py-2 rounded transition-colors"
              >
                {isPending ? "Running…" : `Launch Route ART → ${routeDest}`}
              </button>
            </div>
          )}

          {templateType === "security_lanes" && (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                {["A", "B", "C"].map((t) => (
                  <div key={t}>
                    <label className="block text-xs text-slate-400 mb-1">
                      Terminal {t} ({t === "B" ? "3" : "4"} lanes)
                    </label>
                    <select
                      value={secLanes[t] ?? 0}
                      onChange={(e) =>
                        setSecLanes({ ...secLanes, [t]: parseInt(e.target.value) })
                      }
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    >
                      <option value={-1}>Remove 1 lane</option>
                      <option value={0}>No change</option>
                      <option value={1}>+1 lane</option>
                      <option value={2}>+2 lanes</option>
                    </select>
                  </div>
                ))}
              </div>
              {(() => {
                const added = Object.values(secLanes).filter((v) => v > 0).reduce((a, b) => a + b, 0);
                const staffCost = added * 365 * 16 * 35;
                return (
                  <CostPreview
                    items={[
                      { label: "Capex", value: "€0", note: "Existing infrastructure" },
                      { label: "Annual Staffing", value: formatEur(staffCost), note: `${added} lane(s) × 16h/day × €35/h × 365 days` },
                      { label: "Horizon", value: "3 years" },
                      { label: "Monte Carlo", value: "200 runs" },
                    ]}
                  />
                );
              })()}
              {timeEstimate && <TimeEstimateBar estimate={timeEstimate} />}
              <button
                onClick={handleTemplateSubmit}
                disabled={isPending || Object.values(secLanes).every((v) => v === 0)}
                className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-600 text-white font-medium py-2 rounded transition-colors"
              >
                {isPending ? "Running…" : "Adjust Security Lanes"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Scenario list — 2 cols */}
      <div className="lg:col-span-2 bg-slate-800/50 rounded-xl border border-slate-700 p-5">
        <h3 className="text-base font-semibold text-white mb-1">
          Scenarios
          {scenarios && (
            <span className="text-slate-400 text-sm font-normal ml-2">
              ({scenarios.total})
            </span>
          )}
        </h3>
        <p className="text-xs text-slate-400 mb-3">
          Each scenario runs a baseline comparison automatically. View results in the Results tab once completed.
        </p>
        {lastEstimate && (
          <div className="mb-3 bg-cyan-900/30 border border-cyan-700/50 rounded-lg px-3 py-2 text-xs text-cyan-300 flex items-center gap-2">
            <span>⏱</span>
            <span>Estimated completion: {lastEstimate}</span>
            <button onClick={() => setLastEstimate(null)} className="ml-auto text-cyan-400 hover:text-cyan-200">✕</button>
          </div>
        )}
        {isLoading && <div className="text-slate-400 text-sm">Loading…</div>}
        <div className="space-y-2 max-h-[60vh] overflow-y-auto">
          {((scenarios?.scenarios as ScenarioSummary[]) ?? []).map((s) => (
            <ScenarioListItem key={s.id} scenario={s} onDelete={(id) => deleteMutation.mutate(id)} />
          ))}
          {((scenarios?.scenarios as ScenarioSummary[]) ?? []).length === 0 && !isLoading && (
            <div className="text-slate-500 text-sm text-center py-6">
              No scenarios yet. Create one using the form on the left.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Tab 2: Results Comparison ───────────────────────────── */

function ResultsComparison() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: scenarios } = useQuery({
    queryKey: ["planning-scenarios"],
    queryFn: () => planningApi.listScenarios({ status: "completed", limit: 50 }),
    refetchInterval: 10_000,
  });

  const { data: results, isLoading: resultsLoading, error: resultsError } = useQuery({
    queryKey: ["planning-results", selectedId],
    queryFn: () => (selectedId ? planningApi.getScenarioResults(selectedId) : null),
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

  // Auto-select the first completed scenario
  useEffect(() => {
    if (!selectedId && scenarioList.length > 0) {
      setSelectedId(scenarioList[0].id);
    }
  }, [selectedId, scenarioList]);

  return (
    <div className="space-y-6">
      {/* Methodology banner */}
      <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-4">
        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
          How Results Are Computed
        </h4>
        <p className="text-xs text-slate-400 leading-relaxed">
          Each scenario runs the same simulation dates and random seeds for <strong className="text-slate-300">both the baseline (current KART config)</strong> and <strong className="text-slate-300">the modified scenario</strong>.
          The delta shows what changes if you implement the scenario. With Monte Carlo runs {">"} 1, KPIs show the statistical distribution (P5 = pessimistic, P50 = median, P95 = optimistic).
          The 90% confidence band is P5–P95.
        </p>
      </div>

      {/* Scenario selector */}
      <div className="flex gap-2 flex-wrap">
        {scenarioList.map((s) => (
          <button
            key={s.id}
            onClick={() => setSelectedId(s.id)}
            className={`px-3 py-1.5 rounded text-sm border transition-colors ${
              selectedId === s.id
                ? "bg-cyan-600/30 border-cyan-500 text-cyan-300"
                : "bg-slate-700/50 border-slate-600 text-slate-300 hover:bg-slate-600/50"
            }`}
          >
            {s.name}
          </button>
        ))}
        {scenarioList.length === 0 && (
          <div className="text-slate-400 text-sm">
            No completed scenarios. Create and run one from the Scenario Builder tab.
          </div>
        )}
      </div>

      {/* Infrastructure changes */}
      {resultsLoading && selectedId && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-8 text-center">
          <div className="text-cyan-400 text-sm animate-pulse">Loading results…</div>
        </div>
      )}
      {resultsError && selectedId && (
        <div className="bg-slate-800/50 rounded-xl border border-red-700/50 p-5">
          <p className="text-red-400 text-sm">Failed to load results for this scenario.</p>
          <p className="text-slate-500 text-xs mt-1">
            The scenario may still be completing or an error occurred. Try refreshing.
          </p>
        </div>
      )}
      {infraChanges.length > 0 && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
          <h3 className="text-sm font-semibold text-white mb-3">
            Infrastructure Changes vs. Baseline
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {infraChanges.map((c, i) => (
              <div key={i} className="bg-slate-700/50 rounded-lg p-3 border border-slate-600">
                <div className="text-xs text-slate-400">{c.parameter}</div>
                <div className="text-sm text-white mt-1">
                  {c.baseline} → {c.scenario}{" "}
                  <span className={c.change > 0 ? "text-cyan-400" : "text-amber-400"}>
                    ({c.change > 0 ? "+" : ""}{c.change})
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* KPI comparison table */}
      {kpis && delta && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white">
              KPI Comparison — Baseline vs. Scenario
            </h3>
            {duration != null && (
              <span className="text-xs text-slate-500">
                Computed in {duration.toFixed(1)}s
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs uppercase border-b border-slate-700">
                  <th className="text-left py-2 px-3">KPI</th>
                  <th className="text-right py-2 px-3">Baseline</th>
                  <th className="text-right py-2 px-3">Scenario (mean)</th>
                  <th className="text-right py-2 px-3">Change</th>
                  <th className="text-right py-2 px-3">90% Conf. Band</th>
                  <th className="text-center py-2 px-3">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(kpis).map(([name, dist]) => {
                  const meta = KPI_META[name];
                  if (!meta) return null;
                  const d = delta[name];
                  const b = baselineKpis?.[name];
                  const improved = meta.lowerIsBetter
                    ? (d?.absolute_change ?? 0) < 0
                    : (d?.absolute_change ?? 0) > 0;
                  const neutral = Math.abs(d?.pct_change ?? 0) < 2;

                  return (
                    <tr
                      key={name}
                      className="border-b border-slate-700/50 hover:bg-slate-700/20 group"
                    >
                      <td className="py-2.5 px-3">
                        <div className="text-slate-200 font-medium">{meta.label}</div>
                        <div className="text-[10px] text-slate-500 hidden group-hover:block mt-0.5 max-w-xs">
                          {meta.description}
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-right text-slate-400 font-mono text-xs">
                        {b ? meta.format(b.mean) : "—"}
                      </td>
                      <td className="py-2.5 px-3 text-right text-white font-mono text-xs">
                        {meta.format(dist.mean)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-xs">
                        {d ? (
                          <span
                            className={
                              neutral
                                ? "text-slate-400"
                                : improved
                                  ? "text-emerald-400"
                                  : "text-red-400"
                            }
                          >
                            {d.pct_change > 0 ? "+" : ""}{d.pct_change.toFixed(1)}%
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-right text-slate-400 font-mono text-xs">
                        {meta.format(dist.p5)} – {meta.format(dist.p95)}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        {neutral ? (
                          <span className="inline-block w-5 h-5 rounded-full bg-slate-600 text-slate-300 text-xs leading-5">
                            —
                          </span>
                        ) : improved ? (
                          <span className="inline-block w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 text-xs leading-5">
                            ✓
                          </span>
                        ) : (
                          <span className="inline-block w-5 h-5 rounded-full bg-red-500/20 text-red-400 text-xs leading-5">
                            ✗
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-4 mt-4 text-[10px] text-slate-500">
            <span>
              <span className="inline-block w-3 h-3 rounded-full bg-emerald-500/20 mr-1 align-middle" />
              Improvement
            </span>
            <span>
              <span className="inline-block w-3 h-3 rounded-full bg-red-500/20 mr-1 align-middle" />
              Degradation
            </span>
            <span>
              <span className="inline-block w-3 h-3 rounded-full bg-slate-600 mr-1 align-middle" />
              Negligible ({"<"}2%)
            </span>
            <span>Hover a row for the full KPI definition.</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Tab 3: Investment Dashboard ─────────────────────────── */

function InvestmentDashboard() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: scenarios } = useQuery({
    queryKey: ["planning-scenarios"],
    queryFn: () => planningApi.listScenarios({ status: "completed", limit: 50 }),
    refetchInterval: 10_000,
  });

  const { data: fullResults, isLoading: investLoading } = useQuery({
    queryKey: ["planning-results-invest", selectedId],
    queryFn: () => (selectedId ? planningApi.getScenarioResults(selectedId) : null),
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
  const benefitBreakdown = r?.annual_benefit_breakdown as Record<string, number> | undefined;
  const cashFlows = financials?.cumulative_cash_flows as number[] | undefined;

  // Auto-select the first completed scenario
  useEffect(() => {
    if (!selectedId && scenarioList.length > 0) {
      setSelectedId(scenarioList[0].id);
    }
  }, [selectedId, scenarioList]);

  const hasFinancials = !!(financials && Object.keys(financials).length > 0);

  // Find payback year index for cash flow chart
  const paybackIdx = useMemo(() => {
    if (!cashFlows) return -1;
    return cashFlows.findIndex((v) => v >= 0);
  }, [cashFlows]);

  return (
    <div className="space-y-6">
      {/* Methodology */}
      <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-4">
        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
          Investment Analysis Methodology
        </h4>
        <p className="text-xs text-slate-400 leading-relaxed">
          The investment model uses <strong className="text-slate-300">Discounted Cash Flow (DCF)</strong> analysis.
          Annual benefit = cost savings (EU261 avoided + delay costs avoided + missed connections saved) projected from the simulation delta × 365 days.
          Cash flows are discounted at the WACC rate. <strong className="text-slate-300">NPV {">"} 0</strong> means the investment creates value.{" "}
          <strong className="text-slate-300">IRR {">"} WACC</strong> means the project returns more than its cost of capital.
          Cost parameters use <strong className="text-slate-300">Eurocontrol Standard Inputs 2024</strong> (delay: €102/min, rebooking: €285/pax).
        </p>
      </div>

      {/* Scenario selector */}
      <div className="flex gap-2 flex-wrap">
        {scenarioList.map((s) => (
          <button
            key={s.id}
            onClick={() => setSelectedId(s.id)}
            className={`px-3 py-1.5 rounded text-sm border ${
              selectedId === s.id
                ? "bg-emerald-600/30 border-emerald-500 text-emerald-300"
                : "bg-slate-700/50 border-slate-600 text-slate-300 hover:bg-slate-600/50"
            }`}
          >
            {String(s.name)}
          </button>
        ))}
      </div>

      {investLoading && selectedId && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-8 text-center">
          <div className="text-cyan-400 text-sm animate-pulse">Loading investment analysis…</div>
        </div>
      )}

      {hasFinancials ? (
        <>
          {/* Headline metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              label="Net Present Value"
              value={formatEur(financials.npv_eur as number)}
              sublabel={`Over ${financials.years_horizon} years at ${((financials.discount_rate as number) * 100).toFixed(0)}% WACC`}
              color={(financials.npv_eur as number) > 0 ? "text-emerald-400" : "text-red-400"}
            />
            <MetricCard
              label="Internal Rate of Return"
              value={`${((financials.irr_pct as number) ?? 0).toFixed(1)}%`}
              sublabel={`vs. ${((financials.discount_rate as number) * 100).toFixed(0)}% WACC — ${(financials.irr_pct as number) > (financials.discount_rate as number) * 100 ? "exceeds" : "below"} hurdle`}
              color={(financials.irr_pct as number) > (financials.discount_rate as number) * 100 ? "text-emerald-400" : "text-amber-400"}
            />
            <MetricCard
              label="Payback Period"
              value={`${((financials.payback_years as number) ?? Infinity).toFixed(1)} yrs`}
              sublabel={
                (financials.payback_years as number) < (financials.years_horizon as number)
                  ? "Investment recovered within horizon"
                  : "Does not pay back within horizon"
              }
              color={(financials.payback_years as number) < 15 ? "text-cyan-400" : "text-amber-400"}
            />
            <MetricCard
              label="Recommendation"
              value={String(financials.recommendation ?? "—")}
              sublabel={
                financials.recommendation === "invest"
                  ? "NPV positive and IRR exceeds WACC"
                  : financials.recommendation === "marginal"
                    ? "NPV near zero — sensitive to assumptions"
                    : "Negative NPV — cost exceeds benefit"
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
            {/* Annual cash flow details */}
            <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
              <h3 className="text-sm font-semibold text-white mb-3">Annual Cash Flow</h3>
              <div className="space-y-3">
                <CashFlowRow label="Capex (Year 0)" value={financials.capex_eur as number} negative />
                <CashFlowRow label="Annual Benefit" value={financials.annual_benefit_eur as number} />
                <CashFlowRow label="Annual Opex Delta" value={financials.annual_opex_eur as number} negative />
                <div className="border-t border-slate-600 pt-2">
                  <CashFlowRow
                    label="Net Annual Cash Flow"
                    value={financials.net_annual_eur as number}
                    bold
                  />
                </div>
              </div>
            </div>

            {/* Benefit breakdown */}
            {benefitBreakdown && Object.keys(benefitBreakdown).length > 0 && (
              <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
                <h3 className="text-sm font-semibold text-white mb-3">
                  Where Do Benefits Come From?
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
                        className={`flex items-center justify-between text-xs ${isTotal ? "border-t border-slate-600 pt-2 font-bold" : ""}`}
                      >
                        <span className={isTotal ? "text-white" : "text-slate-400"}>
                          {label}
                        </span>
                        <span className={isTotal ? "text-emerald-400" : "text-slate-300"}>
                          {formatEur(val)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Cumulative cash flow chart (ASCII bar chart) */}
          {cashFlows && cashFlows.length > 0 && (
            <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
              <h3 className="text-sm font-semibold text-white mb-3">
                Cumulative Cash Flow Over Time
              </h3>
              <div className="space-y-1">
                {cashFlows.map((val, yr) => {
                  const maxAbs = Math.max(...cashFlows.map((v) => Math.abs(v)), 1);
                  const pct = Math.abs(val) / maxAbs;
                  const isPayback = yr === paybackIdx;
                  return (
                    <div key={yr} className="flex items-center gap-2 text-xs">
                      <span className="w-10 text-right text-slate-500 shrink-0">
                        Y{yr}
                      </span>
                      <div className="flex-1 h-4 relative">
                        <div
                          className={`absolute top-0 h-full rounded-sm transition-all ${
                            val >= 0 ? "bg-emerald-500/40 left-1/2" : "bg-red-500/40 right-1/2"
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
                        } ${isPayback ? "font-bold" : ""}`}
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
      ) : selectedId ? (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-8 text-center">
          <p className="text-slate-400 text-sm">
            No investment analysis available for this scenario.
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Investment analysis requires capex or opex to be set. Use a template (Add Gate, Add Runway, Security Lanes) to auto-fill cost parameters.
          </p>
        </div>
      ) : null}

      {/* Demand growth projections */}
      {growth != null && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
          <h3 className="text-sm font-semibold text-white mb-1">
            Demand Growth Projections (Eurocontrol STATFOR)
          </h3>
          <p className="text-xs text-slate-400 mb-3">
            Long-term traffic growth scenarios from Eurocontrol&apos;s 7-year outlook.
            These growth rates affect future annual benefits in NPV calculations.
          </p>
          <div className="grid grid-cols-3 gap-4">
            {Object.entries(
              (growth as Record<string, unknown>).projections as Record<string, Record<string, unknown>>,
            ).map(([scenario, data]) => (
              <div
                key={scenario}
                className="bg-slate-700/50 rounded-lg p-4 border border-slate-600"
              >
                <div className="text-xs text-slate-400 uppercase">{scenario} scenario</div>
                <div className="text-xl font-bold text-white mt-1">
                  {((data.projected_annual_pax as number) / 1_000_000).toFixed(1)}M pax/yr
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  {Number(data.growth_rate_pct)}% CAGR · ×{Number(data.growth_factor)} in 10 yrs
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Tab 4: Audit Trail ──────────────────────────────────── */

function AuditTrail() {
  const { data: summary } = useQuery({
    queryKey: ["audit-summary"],
    queryFn: () => planningApi.auditSummary(),
    refetchInterval: 10_000,
  });

  const { data: logData } = useQuery({
    queryKey: ["audit-log"],
    queryFn: () => planningApi.auditLog({ limit: 50 }),
    refetchInterval: 10_000,
  });

  const auditSummary = summary as Record<string, unknown> | undefined;
  const entries = (logData?.entries ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-6">
      {/* Methodology */}
      <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-4">
        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
          Decision Audit Trail
        </h4>
        <p className="text-xs text-slate-400 leading-relaxed">
          Every autonomous recommendation is logged with its predicted cost saving.
          30 simulated minutes after application, the actual outcome is measured.
          This feedback loop calibrates model accuracy over time.
        </p>
      </div>

      {/* Summary cards */}
      {auditSummary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard
            label="Total Recommendations"
            value={String(auditSummary.total_recommendations ?? 0)}
            color="text-white"
          />
          <MetricCard
            label="Applied by Operator"
            value={`${auditSummary.applied_count ?? 0} (${auditSummary.applied_pct ?? 0}%)`}
            color="text-cyan-400"
          />
          <MetricCard
            label="Predicted Saving"
            value={formatEur((auditSummary.total_predicted_saving_eur as number) ?? 0)}
            color="text-emerald-400"
          />
          <MetricCard
            label="Actual Saving"
            value={formatEur((auditSummary.total_actual_saving_eur as number) ?? 0)}
            sublabel={
              (auditSummary.measured_count as number) > 0
                ? `Accuracy: ${auditSummary.prediction_accuracy_pct}%`
                : "No measurements yet"
            }
            color="text-amber-400"
          />
        </div>
      )}

      {/* Accuracy bar */}
      {auditSummary && (auditSummary.measured_count as number) > 0 && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Prediction Accuracy</span>
            <span className="text-white font-medium">
              {auditSummary.prediction_accuracy_pct as number}%
            </span>
          </div>
          <div className="w-full bg-slate-700 rounded-full h-2 mt-2">
            <div
              className="bg-cyan-400 h-2 rounded-full transition-all"
              style={{ width: `${Math.min(100, auditSummary.prediction_accuracy_pct as number)}%` }}
            />
          </div>
        </div>
      )}

      {/* Audit log table */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-5">
        <h3 className="text-sm font-semibold text-white mb-3">
          Recommendation History
          <span className="text-slate-400 text-sm font-normal ml-2">
            ({logData?.total ?? 0})
          </span>
        </h3>
        {entries.length === 0 ? (
          <div className="text-slate-400 text-sm text-center py-8">
            No recommendations logged yet. Recommendations appear as the autonomous system makes decisions during simulation.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs uppercase border-b border-slate-700">
                  <th className="text-left py-2 px-2">Time</th>
                  <th className="text-left py-2 px-2">Action</th>
                  <th className="text-left py-2 px-2">Description</th>
                  <th className="text-right py-2 px-2">Predicted</th>
                  <th className="text-right py-2 px-2">Actual</th>
                  <th className="text-center py-2 px-2">Applied</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr
                    key={e.id as string}
                    className="border-b border-slate-700/50 hover:bg-slate-700/30"
                  >
                    <td className="py-2 px-2 text-slate-400 text-xs whitespace-nowrap">
                      {String(e.sim_time || (e.created_at as string)?.slice(0, 19) || "")}
                    </td>
                    <td className="py-2 px-2">
                      <span className="bg-slate-600 text-slate-200 px-1.5 py-0.5 rounded text-xs">
                        {String((e.action_type as string) ?? "").replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-slate-300 max-w-xs truncate">
                      {String(e.recommendation_text)}
                    </td>
                    <td className="py-2 px-2 text-right text-emerald-400 font-mono">
                      {formatEur((e.predicted_saving_eur as number) ?? 0)}
                    </td>
                    <td className="py-2 px-2 text-right font-mono">
                      {e.actual_saving_eur != null ? (
                        <span className={(e.actual_saving_eur as number) >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {formatEur(e.actual_saving_eur as number)}
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-center">
                      {e.was_applied ? (
                        <span className="text-emerald-400">✓</span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Shared components ───────────────────────────────────── */

function ScenarioListItem({ scenario: s, onDelete }: { scenario: ScenarioSummary; onDelete: (id: string) => void }) {
  // Poll status for running scenarios
  const { data: statusData } = useQuery({
    queryKey: ["planning-status", s.id],
    queryFn: () => planningApi.getScenarioStatus(s.id),
    enabled: s.status === "running" || s.status === "pending",
    refetchInterval: 3000,
  });

  const status = statusData as Record<string, unknown> | undefined;
  const progressPct = (status?.progress_pct as number) ?? 0;
  const runsCompleted = (status?.runs_completed as number) ?? 0;
  const runsTotal = (status?.runs_total as number) ?? s.monte_carlo_runs * 2;
  const estimatedRemaining = status?.estimated_remaining_seconds as number | undefined;
  const isRunning = s.status === "running";

  return (
    <div className="bg-slate-700/50 rounded-lg p-3 border border-slate-600">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-white truncate">
            {s.name || "Unnamed"}
          </div>
          <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
            <span>{s.horizon}</span>
            <span>·</span>
            <span>{s.monte_carlo_runs} MC runs</span>
            <span>·</span>
            <StatusBadge status={s.status} />
          </div>
        </div>
        <button
          onClick={() => onDelete(s.id)}
          className="text-red-400 hover:text-red-300 text-xs ml-2 shrink-0"
          title="Delete scenario"
        >
          ✕
        </button>
      </div>
      {/* Progress bar for running scenarios */}
      {isRunning && (
        <div className="mt-2">
          <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
            <span>{runsCompleted}/{runsTotal} runs ({progressPct}%)</span>
            {estimatedRemaining != null && estimatedRemaining > 0 && (
              <span className="text-cyan-400">~{formatDuration(estimatedRemaining)} remaining</span>
            )}
          </div>
          <div className="w-full bg-slate-600 rounded-full h-1.5">
            <div
              className="bg-cyan-400 h-1.5 rounded-full transition-all duration-1000"
              style={{ width: `${Math.min(100, progressPct)}%` }}
            />
          </div>
        </div>
      )}
      {s.status === "failed" && (
        <div className="mt-1 text-[10px] text-red-400">
          Scenario failed — check logs for details
        </div>
      )}
    </div>
  );
}

function TimeEstimateBar({ estimate }: { estimate: { estimated_seconds: number; human_readable: string; confidence: string } }) {
  const confidenceColor = estimate.confidence === "high" ? "text-emerald-400" : estimate.confidence === "medium" ? "text-amber-400" : "text-slate-400";
  return (
    <div className="bg-slate-900/50 rounded-lg px-3 py-2 border border-slate-600/50 flex items-center gap-3 text-xs">
      <span className="text-slate-400">⏱ Estimated run time:</span>
      <span className="text-white font-medium">{estimate.human_readable}</span>
      <span className={`${confidenceColor}`}>
        ({estimate.confidence} confidence)
      </span>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 1) return "< 1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(1)} min`;
  const hours = minutes / 60;
  return `${hours.toFixed(1)} hr`;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-amber-500/20 text-amber-400",
    running: "bg-cyan-500/20 text-cyan-400",
    completed: "bg-emerald-500/20 text-emerald-400",
    failed: "bg-red-500/20 text-red-400",
  };
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-xs ${colors[status] ?? "bg-slate-600 text-slate-300"}`}
    >
      {status}
    </span>
  );
}

function MetricCard({
  label,
  value,
  sublabel,
  color,
}: {
  label: string;
  value: string;
  sublabel?: string;
  color: string;
}) {
  return (
    <div className="bg-slate-700/50 rounded-lg p-4 border border-slate-600">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`text-xl font-bold mt-1 ${color}`}>{value}</div>
      {sublabel && (
        <div className="text-[10px] text-slate-500 mt-1">{sublabel}</div>
      )}
    </div>
  );
}

function CostPreview({
  items,
}: {
  items: { label: string; value: string; note?: string }[];
}) {
  return (
    <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-600/50">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2 font-medium">
        Auto-configured Parameters
      </div>
      <div className="grid grid-cols-2 gap-2">
        {items.map((item, i) => (
          <div key={i} className="text-xs">
            <span className="text-slate-400">{item.label}: </span>
            <span className="text-white font-medium">{item.value}</span>
            {item.note && (
              <div className="text-[10px] text-slate-500 mt-0.5">{item.note}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function CashFlowRow({
  label,
  value,
  negative,
  bold,
}: {
  label: string;
  value: number;
  negative?: boolean;
  bold?: boolean;
}) {
  const display = negative ? -Math.abs(value) : value;
  const color = display >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <div className={`flex items-center justify-between text-xs ${bold ? "font-bold" : ""}`}>
      <span className={bold ? "text-white" : "text-slate-400"}>{label}</span>
      <span className={`font-mono ${bold ? color : color}`}>
        {display >= 0 ? "+" : ""}{formatEur(display)}
      </span>
    </div>
  );
}

function Tooltip({ text }: { text: string }) {
  return (
    <span className="ml-1 inline-block cursor-help relative group">
      <span className="text-slate-500 text-[10px]">ⓘ</span>
      <span className="hidden group-hover:block absolute z-10 bottom-full left-0 w-56 bg-slate-900 border border-slate-600 rounded p-2 text-[10px] text-slate-300 shadow-lg mb-1 leading-relaxed">
        {text}
      </span>
    </span>
  );
}
