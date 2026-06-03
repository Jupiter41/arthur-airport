import { useState, useCallback, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { planningApi } from "../../../hooks/useApi";
import { formatEur } from "../../../utils/formatCurrency";
import type { ScenarioSummary } from "../types";
import { CostPreview, ScenarioListItem, TimeEstimateBar } from "./shared";

/* ─── Template types ──────────────────────────────────────── */

type TemplateType =
  | "custom"
  | "add_gate"
  | "add_runway"
  | "new_route"
  | "security_lanes"
  | "add_terminal";

const TEMPLATE_INFO: Record<
  TemplateType,
  { label: string; icon: string; description: string }
> = {
  custom: {
    label: "Custom",
    icon: "⚙️",
    description: "Build from scratch with full control over all parameters.",
  },
  add_gate: {
    label: "Add Gates",
    icon: "🚪",
    description: "Add contact gates to a terminal. Auto-sets capex (€8M/gate).",
  },
  add_runway: {
    label: "Add Runway",
    icon: "🛫",
    description: "Add a new runway. Auto-sets capex (€800M), 30-year horizon.",
  },
  new_route: {
    label: "New Route",
    icon: "🌍",
    description:
      "Launch a new route — pure demand-side analysis, no infra capex.",
  },
  security_lanes: {
    label: "Security Lanes",
    icon: "🔒",
    description: "Add/remove security screening lanes with staffing cost.",
  },
  add_terminal: {
    label: "Add Terminal",
    icon: "🏢",
    description:
      "Build a new terminal with gates, security, and baggage systems.",
  },
};

/* ─── Section wrapper ─────────────────────────────────────── */

function Section({
  title,
  defaultOpen = true,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3 text-left"
      >
        <span className="text-sm font-semibold text-white">{title}</span>
        <span className="text-slate-400 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="px-5 pb-5">{children}</div>}
    </div>
  );
}

/* ─── Main Component ──────────────────────────────────────── */

export default function ScenarioBuilder() {
  const qc = useQueryClient();
  const [templateType, setTemplateType] = useState<TemplateType>("custom");
  const [lastEstimate, setLastEstimate] = useState<string | null>(null);

  // Fetch baseline from backend
  const { data: baseline } = useQuery({
    queryKey: ["planning-baseline"],
    queryFn: () => planningApi.getBaseline(),
    staleTime: 60_000,
  });

  const BASELINE_GATES = useMemo(
    () =>
      ((baseline?.infrastructure as Record<string, unknown>)
        ?.gates_per_terminal as Record<string, number>) ?? {
        A: 14,
        B: 14,
        C: 14,
      },
    [baseline],
  );
  const BASELINE_SECURITY = useMemo(
    () =>
      ((baseline?.infrastructure as Record<string, unknown>)
        ?.security_lanes_per_terminal as Record<string, number>) ?? {
        A: 4,
        B: 3,
        C: 4,
      },
    [baseline],
  );
  const BASELINE_SCREENING =
    ((baseline?.infrastructure as Record<string, unknown>)
      ?.screening_units as number) ?? 6;
  const BASELINE_RUNWAYS =
    (
      (baseline?.infrastructure as Record<string, unknown>)
        ?.runways as unknown[]
    )?.length ?? 2;

  // Template-specific fields
  const [gateTerminal, setGateTerminal] = useState("B");
  const [gateCount, setGateCount] = useState(1);
  const [runwayId, setRunwayId] = useState("09C");
  const [runwayIls, setRunwayIls] = useState(true);
  const [runwayLength, setRunwayLength] = useState(3000);
  const [routeDest, setRouteDest] = useState("LHR");
  const [routeFlights, setRouteFlights] = useState(2);
  const [routeAircraft, setRouteAircraft] = useState("A320");
  const [secLanes, setSecLanes] = useState<Record<string, number>>({
    A: 0,
    B: 1,
    C: 0,
  });

  // Terminal template fields
  const [termLetter, setTermLetter] = useState("D");
  const [termGates, setTermGates] = useState(14);
  const [termSecLanes, setTermSecLanes] = useState(4);
  const [termWBGates, setTermWBGates] = useState(3);
  const [termIntlGates, setTermIntlGates] = useState(7);

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

  // Infrastructure capacity deltas for custom scenarios
  const [infraDeltas, setInfraDeltas] = useState({
    gates: { A: 0, B: 0, C: 0 } as Record<string, number>,
    security_lanes: { A: 0, B: 0, C: 0 } as Record<string, number>,
    screening_units: 0,
    runways: 0,
  });

  const hasInfraChanges =
    Object.values(infraDeltas.gates).some((v) => v !== 0) ||
    Object.values(infraDeltas.security_lanes).some((v) => v !== 0) ||
    infraDeltas.screening_units !== 0 ||
    infraDeltas.runways !== 0;

  const buildInfrastructure = useCallback(() => {
    if (!hasInfraChanges) return undefined;
    const gates_per_terminal: Record<string, number> = {};
    for (const t of Object.keys(BASELINE_GATES)) {
      gates_per_terminal[t] = BASELINE_GATES[t] + (infraDeltas.gates[t] ?? 0);
    }
    const security_lanes_per_terminal: Record<string, number> = {};
    for (const t of Object.keys(BASELINE_SECURITY)) {
      security_lanes_per_terminal[t] =
        BASELINE_SECURITY[t] + (infraDeltas.security_lanes[t] ?? 0);
    }
    const infra: Record<string, unknown> = {
      gates_per_terminal,
      security_lanes_per_terminal,
      screening_units: BASELINE_SCREENING + infraDeltas.screening_units,
    };
    if (infraDeltas.runways !== 0) {
      const runways = [
        { id: "09L", ils: true, length_m: 3500 },
        { id: "09R", ils: false, length_m: 3500 },
      ];
      for (let i = 0; i < infraDeltas.runways; i++) {
        runways.push({ id: `NEW${i + 1}`, ils: true, length_m: 3500 });
      }
      infra.runways = runways;
    }
    return infra;
  }, [
    hasInfraChanges,
    infraDeltas,
    BASELINE_GATES,
    BASELINE_SECURITY,
    BASELINE_SCREENING,
  ]);

  // Auto-calculate CAPEX/OPEX from infrastructure changes
  const infra = buildInfrastructure();
  const { data: costEstimate } = useQuery({
    queryKey: ["planning-cost-estimate", infra],
    queryFn: () => (infra ? planningApi.estimateCost(infra) : null),
    enabled: !!infra && templateType === "custom",
    staleTime: 5000,
  });

  // Time estimation
  const estimateHorizon =
    templateType === "custom"
      ? form.horizon
      : templateType === "add_gate"
        ? "month"
        : templateType === "add_runway" || templateType === "add_terminal"
          ? "year"
          : templateType === "new_route"
            ? "month"
            : "week";
  const estimateMC =
    templateType === "custom"
      ? form.monte_carlo_runs
      : templateType === "add_runway" || templateType === "add_terminal"
        ? 100
        : 200;

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
    mutationFn: (body: Record<string, unknown>) =>
      planningApi.createScenario(body),
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
    const body: Record<string, unknown> = { ...form };
    const builtInfra = buildInfrastructure();
    if (builtInfra) body.infrastructure = builtInfra;
    // Use auto-calculated costs if user hasn't manually set them
    if (costEstimate && form.capex_eur === 0 && form.opex_delta_eur === 0) {
      body.capex_eur = costEstimate.total_capex_eur;
      body.opex_delta_eur = costEstimate.total_annual_opex_eur;
    }
    createCustomMutation.mutate(body);
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
          body: {
            runway_id: runwayId,
            ils_capable: runwayIls,
            length_m: runwayLength,
          },
        });
        break;
      case "new_route":
        createTemplateMutation.mutate({
          template: "new_route",
          body: {
            destination_iata: routeDest,
            daily_flights: routeFlights,
            aircraft_type: routeAircraft,
          },
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
      case "add_terminal":
        createTemplateMutation.mutate({
          template: "add_terminal",
          body: {
            terminal_letter: termLetter,
            gates: termGates,
            security_lanes: termSecLanes,
            wide_body_gates: termWBGates,
            international_gates: termIntlGates,
          },
        });
        break;
    }
  };

  const isPending =
    createCustomMutation.isPending || createTemplateMutation.isPending;

  const scenarioList = (scenarios?.scenarios ?? []) as ScenarioSummary[];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* ── Builder panel (3 cols) ── */}
        <div className="lg:col-span-3 space-y-4">
          {/* Template selector */}
          <Section title="What do you want to evaluate?">
            <p className="text-xs text-slate-400 mb-3">
              Choose a template. Each pre-fills realistic cost parameters from
              Eurocontrol Standard Inputs and ICAO guidelines.
            </p>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {(Object.keys(TEMPLATE_INFO) as TemplateType[]).map((key) => {
                const t = TEMPLATE_INFO[key];
                return (
                  <button
                    key={key}
                    onClick={() => setTemplateType(key)}
                    className={`text-left rounded-lg p-2 text-xs border transition-colors ${
                      templateType === key
                        ? "bg-cyan-600/20 border-cyan-500 text-cyan-300"
                        : "bg-slate-700/50 border-slate-600 text-slate-300 hover:bg-slate-600/50"
                    }`}
                  >
                    <div className="text-lg mb-0.5">{t.icon}</div>
                    <div className="font-medium text-white text-[11px] leading-tight">
                      {t.label}
                    </div>
                  </button>
                );
              })}
            </div>
          </Section>

          {/* Template form */}
          <Section
            title={`${TEMPLATE_INFO[templateType].icon} ${TEMPLATE_INFO[templateType].label}`}
          >
            <p className="text-xs text-slate-400 mb-3">
              {TEMPLATE_INFO[templateType].description}
            </p>

            {templateType === "custom" && (
              <CustomForm
                form={form}
                setForm={setForm}
                infraDeltas={infraDeltas}
                setInfraDeltas={setInfraDeltas}
                hasInfraChanges={hasInfraChanges}
                costEstimate={costEstimate}
                baselineGates={BASELINE_GATES}
                baselineSecurity={BASELINE_SECURITY}
                baselineScreening={BASELINE_SCREENING}
                baselineRunways={BASELINE_RUNWAYS}
                timeEstimate={timeEstimate}
                isPending={isPending}
                onSubmit={handleCustomSubmit}
              />
            )}

            {templateType === "add_gate" && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Terminal
                    </label>
                    <select
                      value={gateTerminal}
                      onChange={(e) => setGateTerminal(e.target.value)}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    >
                      {Object.keys(BASELINE_GATES).map((t) => (
                        <option key={t} value={t}>
                          Terminal {t} ({BASELINE_GATES[t]} gates)
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Gates to add
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={gateCount}
                      onChange={(e) => setGateCount(Number(e.target.value))}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                </div>
                <CostPreview
                  items={[
                    { label: "CAPEX", value: formatEur(gateCount * 8_000_000) },
                    {
                      label: "Annual OPEX",
                      value: formatEur(gateCount * 120_000),
                    },
                    { label: "Horizon", value: "1 month sim / 25yr DCF" },
                    { label: "MC runs", value: "200" },
                  ]}
                />
                <SubmitButton
                  onClick={handleTemplateSubmit}
                  isPending={isPending}
                  timeEstimate={timeEstimate}
                />
              </div>
            )}

            {templateType === "add_runway" && (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Runway ID
                    </label>
                    <input
                      value={runwayId}
                      onChange={(e) => setRunwayId(e.target.value)}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      ILS capable
                    </label>
                    <select
                      value={runwayIls ? "yes" : "no"}
                      onChange={(e) => setRunwayIls(e.target.value === "yes")}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    >
                      <option value="yes">Yes (CAT III)</option>
                      <option value="no">No (visual only)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Length (m)
                    </label>
                    <input
                      type="number"
                      min={1500}
                      max={5000}
                      step={100}
                      value={runwayLength}
                      onChange={(e) => setRunwayLength(Number(e.target.value))}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                </div>
                <CostPreview
                  items={[
                    { label: "CAPEX", value: "€800M" },
                    { label: "Annual OPEX", value: "€12M/yr" },
                    { label: "Horizon", value: "1 year sim / 30yr DCF" },
                    { label: "MC runs", value: "100" },
                  ]}
                />
                <SubmitButton
                  onClick={handleTemplateSubmit}
                  isPending={isPending}
                  timeEstimate={timeEstimate}
                />
              </div>
            )}

            {templateType === "new_route" && (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Destination IATA
                    </label>
                    <input
                      value={routeDest}
                      onChange={(e) =>
                        setRouteDest(e.target.value.toUpperCase())
                      }
                      maxLength={4}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Daily flights
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={routeFlights}
                      onChange={(e) => setRouteFlights(Number(e.target.value))}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Aircraft
                    </label>
                    <select
                      value={routeAircraft}
                      onChange={(e) => setRouteAircraft(e.target.value)}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    >
                      {["A320", "A321", "B738", "B77W", "A333", "E195"].map(
                        (a) => (
                          <option key={a} value={a}>
                            {a}
                          </option>
                        ),
                      )}
                    </select>
                  </div>
                </div>
                <CostPreview
                  items={[
                    { label: "CAPEX", value: "€0 (demand-side only)" },
                    { label: "Horizon", value: "1 month sim / 5yr DCF" },
                    { label: "MC runs", value: "100" },
                  ]}
                />
                <SubmitButton
                  onClick={handleTemplateSubmit}
                  isPending={isPending}
                  timeEstimate={timeEstimate}
                />
              </div>
            )}

            {templateType === "security_lanes" && (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  {Object.keys(BASELINE_SECURITY).map((t) => (
                    <div key={t}>
                      <label className="block text-xs text-slate-400 mb-1">
                        Terminal {t} ({BASELINE_SECURITY[t]} lanes)
                      </label>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() =>
                            setSecLanes((l) => ({
                              ...l,
                              [t]: Math.max(
                                -(BASELINE_SECURITY[t] - 1),
                                (l[t] ?? 0) - 1,
                              ),
                            }))
                          }
                          className="w-8 h-8 rounded bg-slate-700 hover:bg-slate-600 text-white"
                        >
                          −
                        </button>
                        <span
                          className={`w-8 text-center font-mono text-sm ${
                            (secLanes[t] ?? 0) > 0
                              ? "text-cyan-400"
                              : (secLanes[t] ?? 0) < 0
                                ? "text-amber-400"
                                : "text-slate-500"
                          }`}
                        >
                          {(secLanes[t] ?? 0) > 0 ? "+" : ""}
                          {secLanes[t] ?? 0}
                        </span>
                        <button
                          onClick={() =>
                            setSecLanes((l) => ({
                              ...l,
                              [t]: Math.min(10, (l[t] ?? 0) + 1),
                            }))
                          }
                          className="w-8 h-8 rounded bg-slate-700 hover:bg-slate-600 text-white"
                        >
                          +
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                {(() => {
                  const totalDelta = Object.values(secLanes).reduce(
                    (a, b) => a + Math.max(0, b),
                    0,
                  );
                  const annualCost = totalDelta * 365 * 16 * 35;
                  return totalDelta > 0 ? (
                    <CostPreview
                      items={[
                        { label: "CAPEX", value: "€0 (staffing only)" },
                        {
                          label: "Annual staffing",
                          value: formatEur(annualCost),
                        },
                        {
                          label: "Per lane/yr",
                          value: `16h/day × €35/h × 365d`,
                        },
                        { label: "MC runs", value: "200" },
                      ]}
                    />
                  ) : null;
                })()}
                <SubmitButton
                  onClick={handleTemplateSubmit}
                  isPending={isPending}
                  timeEstimate={timeEstimate}
                />
              </div>
            )}

            {templateType === "add_terminal" && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Terminal letter
                    </label>
                    <select
                      value={termLetter}
                      onChange={(e) => setTermLetter(e.target.value)}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    >
                      {["D", "E", "F", "G"].map((l) => (
                        <option key={l} value={l}>
                          Terminal {l}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Gates
                    </label>
                    <input
                      type="number"
                      min={4}
                      max={30}
                      value={termGates}
                      onChange={(e) => setTermGates(Number(e.target.value))}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Security lanes
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={termSecLanes}
                      onChange={(e) => setTermSecLanes(Number(e.target.value))}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Wide-body gates
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={termGates}
                      value={termWBGates}
                      onChange={(e) => setTermWBGates(Number(e.target.value))}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Int'l gates
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={termGates}
                      value={termIntlGates}
                      onChange={(e) => setTermIntlGates(Number(e.target.value))}
                      className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
                    />
                  </div>
                </div>
                <CostPreview
                  items={[
                    {
                      label: "CAPEX",
                      value: formatEur(termGates * 12_000_000),
                    },
                    {
                      label: "Annual OPEX",
                      value: formatEur(
                        termGates * 200_000 + termSecLanes * 365 * 16 * 35,
                      ),
                    },
                    { label: "Horizon", value: "1 year sim / 30yr DCF" },
                    { label: "MC runs", value: "100" },
                  ]}
                />
                <SubmitButton
                  onClick={handleTemplateSubmit}
                  isPending={isPending}
                  timeEstimate={timeEstimate}
                />
              </div>
            )}
          </Section>
        </div>

        {/* ── Scenario list (2 cols) ── */}
        <div className="lg:col-span-2">
          <Section title={`Scenarios (${scenarioList.length})`}>
            {lastEstimate && (
              <div className="bg-cyan-900/20 border border-cyan-800/50 rounded-lg px-3 py-2 text-xs text-cyan-300 mb-3">
                ⏱️ Last created — estimated {lastEstimate}
              </div>
            )}
            {isLoading ? (
              <div className="text-sm text-slate-400 animate-pulse">
                Loading…
              </div>
            ) : scenarioList.length === 0 ? (
              <div className="text-sm text-slate-500 text-center py-6">
                No scenarios yet. Create one to get started.
              </div>
            ) : (
              <div className="space-y-2 max-h-[60vh] overflow-y-auto">
                {scenarioList.map((s) => (
                  <ScenarioListItem
                    key={s.id}
                    scenario={s}
                    onDelete={(id) => deleteMutation.mutate(id)}
                  />
                ))}
              </div>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

/* ─── Custom form sub-component ───────────────────────────── */

function CustomForm({
  form,
  setForm,
  infraDeltas,
  setInfraDeltas,
  hasInfraChanges,
  costEstimate,
  baselineGates,
  baselineSecurity,
  baselineScreening,
  baselineRunways,
  timeEstimate,
  isPending,
  onSubmit,
}: {
  form: {
    name: string;
    description: string;
    horizon: string;
    monte_carlo_runs: number;
    demand_source: string;
    capex_eur: number;
    opex_delta_eur: number;
    years_horizon: number;
    discount_rate: number;
  };
  setForm: (f: typeof form | ((prev: typeof form) => typeof form)) => void;
  infraDeltas: {
    gates: Record<string, number>;
    security_lanes: Record<string, number>;
    screening_units: number;
    runways: number;
  };
  setInfraDeltas: (
    d: typeof infraDeltas | ((prev: typeof infraDeltas) => typeof infraDeltas),
  ) => void;
  hasInfraChanges: boolean;
  costEstimate:
    | {
        breakdown: {
          item: string;
          capex_eur: number;
          annual_opex_eur: number;
        }[];
        total_capex_eur: number;
        total_annual_opex_eur: number;
      }
    | null
    | undefined;
  baselineGates: Record<string, number>;
  baselineSecurity: Record<string, number>;
  baselineScreening: number;
  baselineRunways: number;
  timeEstimate?: {
    estimated_seconds: number;
    human_readable: string;
    confidence: string;
  };
  isPending: boolean;
  onSubmit: (e: React.FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {/* Name & description */}
      <div className="grid grid-cols-1 gap-3">
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Scenario Name
          </label>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600 focus:border-cyan-400 outline-none"
            placeholder="e.g. Add gate B15 + security lane"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Description
          </label>
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={2}
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600 focus:border-cyan-400 outline-none"
            placeholder="Describe what infrastructure changes this scenario models..."
          />
        </div>
      </div>

      {/* Infrastructure changes */}
      <div className="border border-slate-600 rounded-lg p-3 bg-slate-900/40">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-slate-300">
            Infrastructure Changes
          </span>
          {hasInfraChanges && (
            <button
              type="button"
              onClick={() =>
                setInfraDeltas({
                  gates: { A: 0, B: 0, C: 0 },
                  security_lanes: { A: 0, B: 0, C: 0 },
                  screening_units: 0,
                  runways: 0,
                })
              }
              className="text-[10px] text-slate-500 hover:text-slate-300"
            >
              Reset all
            </button>
          )}
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {Object.keys(baselineGates).map((t) => (
            <DeltaControl
              key={`gate-${t}`}
              label={`Gates (Term ${t})`}
              value={infraDeltas.gates[t] ?? 0}
              min={-baselineGates[t]}
              max={10}
              onChange={(v) =>
                setInfraDeltas((d) => ({
                  ...d,
                  gates: { ...d.gates, [t]: v },
                }))
              }
            />
          ))}
          {Object.keys(baselineSecurity).map((t) => (
            <DeltaControl
              key={`sec-${t}`}
              label={`Security (Term ${t})`}
              value={infraDeltas.security_lanes[t] ?? 0}
              min={-(baselineSecurity[t] - 1)}
              max={10}
              onChange={(v) =>
                setInfraDeltas((d) => ({
                  ...d,
                  security_lanes: { ...d.security_lanes, [t]: v },
                }))
              }
            />
          ))}
          <DeltaControl
            label={`Screening units`}
            value={infraDeltas.screening_units}
            min={-(baselineScreening - 1)}
            max={10}
            onChange={(v) =>
              setInfraDeltas((d) => ({
                ...d,
                screening_units: v,
              }))
            }
          />
          <DeltaControl
            label={`Additional runways`}
            value={infraDeltas.runways}
            min={0}
            max={2}
            onChange={(v) =>
              setInfraDeltas((d) => ({
                ...d,
                runways: v,
              }))
            }
          />
        </div>

        {/* Auto-calculated cost estimate */}
        {costEstimate && costEstimate.breakdown.length > 0 && (
          <div className="mt-3 border-t border-slate-700 pt-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">
              Estimated costs (auto-calculated, editable below)
            </div>
            {costEstimate.breakdown.map((item, i) => (
              <div
                key={i}
                className="flex justify-between text-xs text-slate-400 py-0.5"
              >
                <span>{item.item}</span>
                <span>
                  {formatEur(item.capex_eur)} +{" "}
                  {formatEur(item.annual_opex_eur)}
                  /yr
                </span>
              </div>
            ))}
            <div className="flex justify-between text-xs text-cyan-300 font-medium pt-1 border-t border-slate-700 mt-1">
              <span>Total</span>
              <span>
                {formatEur(costEstimate.total_capex_eur)} +{" "}
                {formatEur(costEstimate.total_annual_opex_eur)}/yr
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Simulation & financial parameters */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Simulation horizon
          </label>
          <select
            value={form.horizon}
            onChange={(e) => setForm({ ...form, horizon: e.target.value })}
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
          >
            <option value="day">1 day</option>
            <option value="week">1 week</option>
            <option value="month">1 month</option>
            <option value="year">1 year (sampled)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Monte Carlo runs
          </label>
          <input
            type="number"
            min={1}
            max={500}
            value={form.monte_carlo_runs}
            onChange={(e) =>
              setForm({ ...form, monte_carlo_runs: Number(e.target.value) })
            }
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Investment horizon (yrs)
          </label>
          <input
            type="number"
            min={1}
            max={50}
            value={form.years_horizon}
            onChange={(e) =>
              setForm({ ...form, years_horizon: Number(e.target.value) })
            }
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            CAPEX (€){" "}
            {costEstimate && form.capex_eur === 0 && (
              <span className="text-cyan-400">(auto)</span>
            )}
          </label>
          <input
            type="number"
            min={0}
            step={1000}
            value={
              costEstimate && form.capex_eur === 0
                ? costEstimate.total_capex_eur
                : form.capex_eur
            }
            onChange={(e) =>
              setForm({ ...form, capex_eur: Number(e.target.value) })
            }
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Annual OPEX delta (€){" "}
            {costEstimate && form.opex_delta_eur === 0 && (
              <span className="text-cyan-400">(auto)</span>
            )}
          </label>
          <input
            type="number"
            min={0}
            step={1000}
            value={
              costEstimate && form.opex_delta_eur === 0
                ? costEstimate.total_annual_opex_eur
                : form.opex_delta_eur
            }
            onChange={(e) =>
              setForm({ ...form, opex_delta_eur: Number(e.target.value) })
            }
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Discount rate (WACC)
          </label>
          <input
            type="number"
            min={0}
            max={0.3}
            step={0.01}
            value={form.discount_rate}
            onChange={(e) =>
              setForm({ ...form, discount_rate: Number(e.target.value) })
            }
            className="w-full bg-slate-700 rounded px-3 py-2 text-sm text-white border border-slate-600"
          />
        </div>
      </div>

      <SubmitButton
        onClick={() => {}} // form handles submit
        isPending={isPending}
        timeEstimate={timeEstimate}
        isSubmit
        disabled={!form.name.trim()}
      />
    </form>
  );
}

/* ─── Delta Control ───────────────────────────────────────── */

function DeltaControl({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-400">{label}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onChange(Math.max(min, value - 1))}
          className="w-5 h-5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs flex items-center justify-center"
        >
          −
        </button>
        <span
          className={`w-10 text-center text-xs font-mono ${
            value !== 0
              ? value > 0
                ? "text-cyan-400"
                : "text-amber-400"
              : "text-slate-500"
          }`}
        >
          {value > 0 ? "+" : ""}
          {value}
        </span>
        <button
          type="button"
          onClick={() => onChange(Math.min(max, value + 1))}
          className="w-5 h-5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs flex items-center justify-center"
        >
          +
        </button>
      </div>
    </div>
  );
}

/* ─── Submit Button ───────────────────────────────────────── */

function SubmitButton({
  onClick,
  isPending,
  timeEstimate,
  isSubmit = false,
  disabled = false,
}: {
  onClick: () => void;
  isPending: boolean;
  timeEstimate?: {
    estimated_seconds: number;
    human_readable: string;
    confidence: string;
  };
  isSubmit?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <TimeEstimateBar estimate={timeEstimate} />
      <button
        type={isSubmit ? "submit" : "button"}
        onClick={isSubmit ? undefined : onClick}
        disabled={isPending || disabled}
        className="bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-600 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors"
      >
        {isPending ? "Creating…" : "Create & Run"}
      </button>
    </div>
  );
}
