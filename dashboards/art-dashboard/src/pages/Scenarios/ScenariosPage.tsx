import { useState, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { scenariosApi, simApi } from "../../hooks/useApi";
import { StatusBadge } from "../../components/StatusBadge";

/* ──────── Types ──────── */

interface ScenarioSummary {
  name: string;
  description: string;
  duration_sim_minutes: number;
  event_count: number;
  outcome_count: number;
  is_base?: boolean;
}

interface ScenarioEvent {
  at_sim_offset_minutes: number;
  type: string;
  severity: string;
  location: string;
  trigger: string;
  description?: string;
}

interface ExpectedOutcome {
  metric: string;
  condition: string;
  within_sim_minutes: number;
}

interface SeedOverrides {
  weather?: string;
  daily_flights?: number;
  load_factor?: number;
}

interface ScenarioDefinition {
  name: string;
  description: string;
  sim_speed: number;
  start_time: string;
  duration_sim_minutes: number;
  seed_overrides?: SeedOverrides;
  events: ScenarioEvent[];
  expected_outcomes: ExpectedOutcome[];
  is_base?: boolean;
}

type ScenarioPayload = Omit<ScenarioDefinition, "is_base">;
type EditorMode = "create" | "edit" | "fork";

const EMPTY_SCENARIO: ScenarioPayload = {
  name: "",
  description: "",
  sim_speed: 600,
  start_time: "2024-06-15T07:30:00",
  duration_sim_minutes: 120,
  seed_overrides: {
    weather: "CAVOK",
    daily_flights: 420,
    load_factor: 0.85,
  },
  events: [
    {
      at_sim_offset_minutes: 30,
      type: "runway_incursion",
      severity: "high",
      location: "runway-09L",
      trigger: "manual",
      description: "",
    },
  ],
  expected_outcomes: [
    {
      metric: "flights_delayed_current",
      condition: ">= 5",
      within_sim_minutes: 60,
    },
  ],
};

interface MetricSnapshot {
  sim_time: string;
  offset_minutes: number;
  flights_delayed_current: number;
  holding_stack_depth: number;
  cascade_depth_max: number;
  avg_delay_minutes: number;
  missed_connections: number;
  security_queue_max: number;
  incident_count_active: number;
  flights_cancelled: number;
  total_delay_minutes: number;
  pax_disrupted: number;
}

interface OutcomeResult {
  metric: string;
  condition: string;
  expected: string;
  actual: number;
  passed: boolean;
  evaluated_at_offset_minutes: number;
}

interface ScenarioRunResult {
  run_id: string;
  scenario_name: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  sim_start_time: string;
  sim_end_time: string;
  duration_sim_minutes: number;
  events_injected: number;
  metric_snapshots: MetricSnapshot[];
  outcome_results: OutcomeResult[];
  summary: string;
  pass_rate?: number;
}

interface ActiveScenario {
  active: boolean;
  run_id?: string;
  scenario_name?: string;
  status?: string;
  events_injected?: number;
  snapshots_collected?: number;
  latest_metrics?: MetricSnapshot;
  sim_time?: string;
}

/* ──────── Severity → color helpers ──────── */

const SEVERITY_COLOR: Record<string, string> = {
  critical: "text-red-400",
  high: "text-orange-400",
  medium: "text-amber-400",
  low: "text-gray-400",
};

const TYPE_EMOJI: Record<string, string> = {
  runway_incursion: "🛬",
  baggage_fire: "🔥",
  security_breach: "🚨",
  system_failure: "⚙️",
  severe_weather: "🌧️",
};

/* ──────── Scenario Card ──────── */

function ScenarioCard({
  scenario,
  selected,
  onSelect,
}: {
  scenario: ScenarioSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      className={`border border-gray-700 rounded-lg p-4 cursor-pointer transition-all hover:ring-1 hover:ring-blue-400/50
        ${selected ? "ring-2 ring-blue-400 bg-gray-800/80" : "bg-gray-800/40 hover:bg-gray-800/60"}`}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <span>{scenario.name}</span>
          {scenario.is_base ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-900/60 text-indigo-200 border border-indigo-700">
              BASE
            </span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-200 border border-emerald-700">
              CUSTOM
            </span>
          )}
        </h3>
        <span className="text-xs text-gray-400">{scenario.duration_sim_minutes}m</span>
      </div>
      <p className="text-xs text-gray-400 line-clamp-2 mb-3">
        {scenario.description}
      </p>
      <div className="flex gap-3 text-xs text-gray-400">
        <span>⚡ {scenario.event_count} events</span>
        <span>📊 {scenario.outcome_count} checks</span>
      </div>
    </div>
  );
}

/* ──────── Event Timeline ──────── */

function EventTimeline({ events }: { events: ScenarioEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="text-xs text-gray-400 italic">
        No events (stress test)
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {events.map((e, i) => (
        <div key={i} className="flex items-start gap-3 group">
          <div className="flex flex-col items-center">
            <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center text-sm">
              {TYPE_EMOJI[e.type] ?? "❓"}
            </div>
            {i < events.length - 1 && (
              <div className="w-0.5 h-6 bg-gray-700 mt-1" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-blue-300">
                T+{e.at_sim_offset_minutes}m
              </span>
              <span
                className={`text-xs font-medium ${SEVERITY_COLOR[e.severity]}`}
              >
                {e.severity}
              </span>
            </div>
            <div className="text-sm text-white">
              {e.type.replace(/_/g, " ")}
            </div>
            <div className="text-xs text-gray-400">
              📍 {e.location}
              {e.description && <span className="ml-1">— {e.description}</span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ──────── Expected Outcomes ──────── */

function OutcomesTable({
  outcomes,
  results,
}: {
  outcomes: ExpectedOutcome[];
  results?: OutcomeResult[];
}) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-400 border-b border-gray-700">
          <th className="text-left py-1.5 font-medium">Metric</th>
          <th className="text-left py-1.5 font-medium">Condition</th>
          <th className="text-left py-1.5 font-medium">Within</th>
          {results && <th className="text-left py-1.5 font-medium">Actual</th>}
          {results && (
            <th className="text-center py-1.5 font-medium">Result</th>
          )}
        </tr>
      </thead>
      <tbody>
        {outcomes.map((o, i) => {
          const r = results?.[i];
          return (
            <tr key={i} className="border-b border-gray-800">
              <td className="py-1.5 text-gray-300 font-mono">{o.metric}</td>
              <td className="py-1.5 text-gray-300">{o.condition}</td>
              <td className="py-1.5 text-gray-400">{o.within_sim_minutes}m</td>
              {r && (
                <td className="py-1.5 text-white font-mono">
                  {typeof r.actual === "number"
                    ? r.actual.toFixed(1)
                    : r.actual}
                </td>
              )}
              {r && (
                <td className="py-1.5 text-center">
                  {r.passed ? (
                    <span className="text-green-400">✅</span>
                  ) : (
                    <span className="text-red-400">❌</span>
                  )}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ──────── Live Metrics Chart ──────── */

function MetricsChart({ snapshots }: { snapshots: MetricSnapshot[] }) {
  if (snapshots.length < 2) {
    return (
      <div className="text-xs text-gray-400 italic py-4 text-center">
        Collecting metrics…
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={snapshots}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis
          dataKey="offset_minutes"
          tick={{ fontSize: 10, fill: "#9CA3AF" }}
          label={{
            value: "Sim minutes",
            position: "bottom",
            fontSize: 10,
            fill: "#6B7280",
          }}
        />
        <YAxis tick={{ fontSize: 10, fill: "#9CA3AF" }} />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1F2937",
            border: "1px solid #374151",
            borderRadius: 8,
            fontSize: 11,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Line
          type="monotone"
          dataKey="flights_delayed_current"
          stroke="#F59E0B"
          strokeWidth={2}
          dot={false}
          name="Flights delayed"
        />
        <Line
          type="monotone"
          dataKey="holding_stack_depth"
          stroke="#EF4444"
          strokeWidth={2}
          dot={false}
          name="Holding stack"
        />
        <Line
          type="monotone"
          dataKey="incident_count_active"
          stroke="#8B5CF6"
          strokeWidth={1.5}
          dot={false}
          name="Active incidents"
        />
        <Line
          type="monotone"
          dataKey="avg_delay_minutes"
          stroke="#3B82F6"
          strokeWidth={1.5}
          dot={false}
          name="Avg delay (min)"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ──────── Past Result Card ──────── */

function ResultCard({
  result,
  selected,
  onSelect,
}: {
  result: ScenarioRunResult;
  selected: boolean;
  onSelect: () => void;
}) {
  const statusColor =
    result.status === "completed"
      ? "text-green-400"
      : result.status === "failed"
        ? "text-red-400"
        : result.status === "stopped"
          ? "text-yellow-400"
          : "text-blue-400";

  const passRate = result.pass_rate ?? 0;
  const passColor =
    passRate >= 80
      ? "text-green-400"
      : passRate >= 50
        ? "text-yellow-400"
        : "text-red-400";

  return (
    <div
      className={`border border-gray-700 rounded p-3 cursor-pointer transition-all hover:ring-1 hover:ring-white/20
        ${selected ? "ring-2 ring-blue-400 bg-gray-800" : "bg-gray-800/40"}`}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-bold text-white">
          {result.scenario_name}
        </span>
        <span className={`text-xs font-mono ${statusColor}`}>
          {result.status}
        </span>
      </div>
      <div className="flex gap-3 text-xs text-gray-400">
        <span>🆔 {result.run_id}</span>
        <span>⏱ {result.duration_sim_minutes}m</span>
        <span>⚡ {result.events_injected} events</span>
        {result.outcome_results && (
          <span className={passColor}>
            {
              result.outcome_results.filter((o: OutcomeResult) => o.passed)
                .length
            }
            /{result.outcome_results.length} passed
          </span>
        )}
      </div>
      {result.summary && (
        <p className="text-xs text-gray-400 mt-1 line-clamp-1">
          {result.summary}
        </p>
      )}
    </div>
  );
}

/* ──────── Main Page ──────── */

export default function ScenariosPage() {
  const queryClient = useQueryClient();
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<string | null>(null);
  const [runSpeed, setRunSpeed] = useState<number>(600);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editorMode, setEditorMode] = useState<EditorMode | null>(null);
  const [editorSourceName, setEditorSourceName] = useState<string | null>(null);
  const [editorJson, setEditorJson] = useState<string>("");
  const [editorBusy, setEditorBusy] = useState(false);
  const [editorError, setEditorError] = useState<string | null>(null);

  // ── Queries ──

  const { data: scenarioList } = useQuery({
    queryKey: ["scenarios"],
    queryFn: () => scenariosApi.list(),
    refetchInterval: 30000,
  });

  const { data: scenarioDef } = useQuery({
    queryKey: ["scenario-def", selectedScenario],
    queryFn: () => scenariosApi.get(selectedScenario!),
    enabled: !!selectedScenario,
  });

  const { data: activeScenario } = useQuery({
    queryKey: ["scenario-active"],
    queryFn: () => scenariosApi.active(),
    refetchInterval: 2000,
  });

  const { data: resultsList } = useQuery({
    queryKey: ["scenario-results"],
    queryFn: () => scenariosApi.results(),
    refetchInterval: 10000,
  });

  const { data: resultDetail } = useQuery({
    queryKey: ["scenario-result", selectedResult],
    queryFn: () => scenariosApi.result(selectedResult!),
    enabled: !!selectedResult,
  });

  const scenarios =
    (scenarioList as { scenarios: ScenarioSummary[] })?.scenarios ?? [];
  const active = activeScenario as ActiveScenario | undefined;
  const definition = scenarioDef as ScenarioDefinition | undefined;
  const results =
    (resultsList as { results: ScenarioRunResult[] })?.results ?? [];
  const detail = resultDetail as ScenarioRunResult | undefined;

  const isActive = active?.active ?? false;

  const openEditor = useCallback(
    (mode: EditorMode, source?: ScenarioDefinition) => {
      setSelectedResult(null);
      setEditorMode(mode);
      setEditorSourceName(source?.name ?? null);
      setEditorError(null);
      const payload: ScenarioPayload = {
        ...(source
          ? {
              name: source.name,
              description: source.description,
              sim_speed: source.sim_speed,
              start_time: source.start_time,
              duration_sim_minutes: source.duration_sim_minutes,
              seed_overrides: source.seed_overrides,
              events: source.events,
              expected_outcomes: source.expected_outcomes,
            }
          : EMPTY_SCENARIO),
      };

      if (mode === "fork" && source) {
        payload.name = `${source.name} (Fork)`;
      }

      setEditorJson(JSON.stringify(payload, null, 2));
    },
    [],
  );

  const closeEditor = useCallback(() => {
    setEditorMode(null);
    setEditorSourceName(null);
    setEditorError(null);
    setEditorJson("");
  }, []);

  // Track when a scenario completes
  useEffect(() => {
    if (active && !active.active && running) {
      setRunning(false);
      queryClient.invalidateQueries({ queryKey: ["scenario-results"] });
    }
  }, [active, running, queryClient]);

  // ── Actions ──

  const handleRun = useCallback(
    async (name: string) => {
      setError(null);
      setRunning(true);
      try {
        await scenariosApi.run(name, runSpeed);
        queryClient.invalidateQueries({ queryKey: ["scenario-active"] });
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to start scenario",
        );
        setRunning(false);
      }
    },
    [runSpeed, queryClient],
  );

  const handleStop = useCallback(async () => {
    setError(null);
    try {
      await scenariosApi.stop();
      setRunning(false);
      queryClient.invalidateQueries({ queryKey: ["scenario-active"] });
      queryClient.invalidateQueries({ queryKey: ["scenario-results"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop scenario");
    }
  }, [queryClient]);

  const handleDeleteScenario = useCallback(async () => {
    if (!definition || definition.is_base) {
      return;
    }
    const ok = window.confirm(
      `Delete custom scenario '${definition.name}'? This removes it permanently.`,
    );
    if (!ok) {
      return;
    }

    setError(null);
    try {
      await scenariosApi.delete(definition.name);
      setSelectedScenario(null);
      queryClient.invalidateQueries({ queryKey: ["scenarios"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete scenario");
    }
  }, [definition, queryClient]);

  const handleSaveEditor = useCallback(async () => {
    if (!editorMode) {
      return;
    }

    setEditorError(null);
    setEditorBusy(true);
    try {
      const parsed = JSON.parse(editorJson) as ScenarioPayload;
      if (!parsed.name || !parsed.description) {
        throw new Error("Scenario must include at least 'name' and 'description'");
      }
      if (!Array.isArray(parsed.events) || !Array.isArray(parsed.expected_outcomes)) {
        throw new Error("'events' and 'expected_outcomes' must be arrays");
      }

      if (editorMode === "edit" && editorSourceName) {
        await scenariosApi.update(editorSourceName, parsed as unknown as Record<string, unknown>);
      } else {
        await scenariosApi.create(parsed as unknown as Record<string, unknown>);
      }

      await queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      setSelectedScenario(parsed.name);
      closeEditor();
    } catch (err) {
      setEditorError(err instanceof Error ? err.message : "Failed to save scenario");
    } finally {
      setEditorBusy(false);
    }
  }, [editorJson, editorMode, editorSourceName, queryClient, closeEditor]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Top: Active scenario banner ── */}
      {isActive && active && (
        <div className="bg-blue-900/40 border-b border-blue-700 px-4 py-3 flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            <span className="text-sm font-bold text-blue-300">
              Running: {active.scenario_name}
            </span>
          </div>
          <div className="flex gap-4 text-xs text-gray-400">
            <span>🆔 {active.run_id}</span>
            <span>⚡ {active.events_injected} injected</span>
            <span>📊 {active.snapshots_collected} snapshots</span>
            {active.latest_metrics && (
              <>
                <span className="text-yellow-400">
                  ✈️ {active.latest_metrics.flights_delayed_current} delayed
                </span>
                <span className="text-red-400">
                  📡 {active.latest_metrics.holding_stack_depth} holding
                </span>
              </>
            )}
          </div>
          <div className="ml-auto">
            <button
              className="text-xs bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded transition-colors"
              onClick={handleStop}
            >
              ⏹ Stop Scenario
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-900/40 border-b border-red-700 px-4 py-2 text-sm text-red-300">
          ⚠ {error}
          <button
            className="ml-2 text-red-400 hover:text-red-200 underline"
            onClick={() => setError(null)}
          >
            dismiss
          </button>
        </div>
      )}

      {/* ── Main content ── */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left panel: scenario list + results list */}
        <div className="w-80 border-r border-gray-700 flex flex-col overflow-hidden">
          {/* Scenario library */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs font-bold text-gray-400 uppercase tracking-wider">
                Scenario Library ({scenarios.length})
              </h2>
              <button
                className="text-[11px] px-2 py-1 rounded bg-emerald-700/80 hover:bg-emerald-600 text-white"
                onClick={() => openEditor("create")}
              >
                + New
              </button>
            </div>
            {scenarios.map((s) => (
              <ScenarioCard
                key={s.name}
                scenario={s}
                selected={selectedScenario === s.name}
                onSelect={() => {
                  setSelectedScenario(s.name);
                  setSelectedResult(null);
                }}
              />
            ))}
            {scenarios.length === 0 && (
              <div className="text-xs text-gray-400 italic py-4 text-center">
                No scenarios loaded. Check sim-orchestrator
                scenarios/definitions/
              </div>
            )}
          </div>

          {/* Past results */}
          <div className="border-t border-gray-700 max-h-[40%] overflow-y-auto p-3 space-y-2">
            <h2 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">
              Past Results ({results.length})
            </h2>
            {results.map((r) => (
              <ResultCard
                key={r.run_id}
                result={r}
                selected={selectedResult === r.run_id}
                onSelect={() => {
                  setSelectedResult(r.run_id);
                  setSelectedScenario(null);
                }}
              />
            ))}
            {results.length === 0 && (
              <div className="text-xs text-gray-400 italic py-2 text-center">
                No runs yet
              </div>
            )}
          </div>
        </div>

        {/* Right panel: detail view */}
        <div className="flex-1 overflow-y-auto p-4">
          {/* Viewing a scenario definition */}
          {selectedScenario && definition && !editorMode && (
            <div className="space-y-6">
              <div className="flex items-start justify-between">
                <div>
                  <h1 className="text-xl font-bold text-white flex items-center gap-2">
                    {definition.name}
                    {definition.is_base ? (
                      <span className="text-[11px] px-2 py-0.5 rounded bg-indigo-900/60 text-indigo-200 border border-indigo-700">
                        Base scenario (immutable)
                      </span>
                    ) : (
                      <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-900/50 text-emerald-200 border border-emerald-700">
                        Custom scenario
                      </span>
                    )}
                  </h1>
                  <p className="text-sm text-gray-400 mt-1 max-w-2xl">
                    {definition.description}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    className="text-sm bg-gray-700 hover:bg-gray-600 text-white px-3 py-2 rounded font-medium transition-colors"
                    onClick={() => openEditor("fork", definition)}
                  >
                    Fork
                  </button>
                  {!definition.is_base && (
                    <button
                      className="text-sm bg-amber-700 hover:bg-amber-600 text-white px-3 py-2 rounded font-medium transition-colors"
                      onClick={() => openEditor("edit", definition)}
                    >
                      Edit
                    </button>
                  )}
                  {!definition.is_base && (
                    <button
                      className="text-sm bg-red-700 hover:bg-red-600 text-white px-3 py-2 rounded font-medium transition-colors"
                      onClick={handleDeleteScenario}
                    >
                      Delete
                    </button>
                  )}
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-gray-400">Speed:</label>
                    <select
                      className="text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white"
                      value={runSpeed}
                      onChange={(e) => setRunSpeed(Number(e.target.value))}
                    >
                      <option value={60}>60×</option>
                      <option value={600}>600×</option>
                      <option value={3600}>3600×</option>
                    </select>
                  </div>
                  <button
                    className="text-sm bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    onClick={() => handleRun(definition.name)}
                    disabled={isActive || running}
                  >
                    {running ? "Starting…" : "▶ Run Scenario"}
                  </button>
                </div>
              </div>

              {/* Scenario params */}
              <div className="grid grid-cols-4 gap-3">
                <div className="bg-gray-800 rounded p-3">
                  <div className="text-xs text-gray-400">Duration</div>
                  <div className="text-lg font-bold text-white">
                    {definition.duration_sim_minutes}m
                  </div>
                </div>
                <div className="bg-gray-800 rounded p-3">
                  <div className="text-xs text-gray-400">Speed</div>
                  <div className="text-lg font-bold text-white">
                    {definition.sim_speed}×
                  </div>
                </div>
                <div className="bg-gray-800 rounded p-3">
                  <div className="text-xs text-gray-400">Start Time</div>
                  <div className="text-lg font-bold text-white">
                    {definition.start_time.split("T")[1]?.replace(/Z$/, "") ??
                      definition.start_time}
                  </div>
                </div>
                <div className="bg-gray-800 rounded p-3">
                  <div className="text-xs text-gray-400">Seed Overrides</div>
                  <div className="text-xs text-white mt-1">
                    {definition.seed_overrides ? (
                      <div className="space-y-0.5">
                        {definition.seed_overrides.weather && (
                          <div>🌤 {definition.seed_overrides.weather}</div>
                        )}
                        {definition.seed_overrides.daily_flights && (
                          <div>
                            ✈ {definition.seed_overrides.daily_flights} flights
                          </div>
                        )}
                        {definition.seed_overrides.load_factor && (
                          <div>
                            👥{" "}
                            {(
                              definition.seed_overrides.load_factor * 100
                            ).toFixed(0)}
                            % load
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-gray-400">Default</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Event timeline & outcomes side by side */}
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <h3 className="text-sm font-bold text-gray-300 mb-3">
                    📅 Event Timeline
                  </h3>
                  <EventTimeline events={definition.events} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-gray-300 mb-3">
                    📊 Expected Outcomes
                  </h3>
                  <OutcomesTable outcomes={definition.expected_outcomes} />
                </div>
              </div>

              {/* Live metrics if this scenario is active */}
              {isActive &&
                active?.scenario_name === definition.name &&
                active.latest_metrics && (
                  <div>
                    <h3 className="text-sm font-bold text-gray-300 mb-3">
                      📈 Live Metrics
                    </h3>
                    <div className="grid grid-cols-4 gap-3 mb-4">
                      <div className="bg-gray-800 rounded p-3 text-center">
                        <div className="text-2xl font-bold text-yellow-400">
                          {active.latest_metrics.flights_delayed_current}
                        </div>
                        <div className="text-xs text-gray-400">
                          Flights delayed
                        </div>
                      </div>
                      <div className="bg-gray-800 rounded p-3 text-center">
                        <div className="text-2xl font-bold text-red-400">
                          {active.latest_metrics.holding_stack_depth}
                        </div>
                        <div className="text-xs text-gray-400">
                          Holding stack
                        </div>
                      </div>
                      <div className="bg-gray-800 rounded p-3 text-center">
                        <div className="text-2xl font-bold text-blue-400">
                          {active.latest_metrics.avg_delay_minutes.toFixed(1)}
                        </div>
                        <div className="text-xs text-gray-400">
                          Avg delay (min)
                        </div>
                      </div>
                      <div className="bg-gray-800 rounded p-3 text-center">
                        <div className="text-2xl font-bold text-purple-400">
                          {active.latest_metrics.incident_count_active}
                        </div>
                        <div className="text-xs text-gray-400">
                          Active incidents
                        </div>
                      </div>
                    </div>
                  </div>
                )}
            </div>
          )}

          {/* Scenario editor */}
          {editorMode && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h1 className="text-xl font-bold text-white">
                  {editorMode === "create" && "Create Custom Scenario"}
                  {editorMode === "edit" && "Edit Custom Scenario"}
                  {editorMode === "fork" && "Fork Scenario"}
                </h1>
                <div className="flex gap-2">
                  <button
                    className="text-sm bg-gray-700 hover:bg-gray-600 text-white px-3 py-2 rounded"
                    onClick={closeEditor}
                    disabled={editorBusy}
                  >
                    Cancel
                  </button>
                  <button
                    className="text-sm bg-green-700 hover:bg-green-600 text-white px-3 py-2 rounded"
                    onClick={handleSaveEditor}
                    disabled={editorBusy}
                  >
                    {editorBusy ? "Saving..." : "Save"}
                  </button>
                </div>
              </div>

              <p className="text-sm text-gray-400">
                Edit the JSON definition directly. Base scenarios cannot be edited in place; fork to create a custom variant.
              </p>

              {editorMode === "edit" && editorSourceName && (
                <p className="text-xs text-gray-400">Editing: {editorSourceName}</p>
              )}

              {editorError && (
                <div className="bg-red-900/30 border border-red-700 text-red-200 text-sm rounded p-3">
                  {editorError}
                </div>
              )}

              <textarea
                className="w-full h-[65vh] bg-gray-900 border border-gray-700 rounded p-3 text-xs text-gray-100 font-mono leading-5"
                value={editorJson}
                onChange={(e) => setEditorJson(e.target.value)}
                spellCheck={false}
              />
            </div>
          )}

          {/* Viewing a past result detail */}
          {selectedResult && detail && !editorMode && (
            <div className="space-y-6">
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-xl font-bold text-white">
                    {detail.scenario_name}
                  </h1>
                  <StatusBadge status={detail.status} />
                </div>
                <p className="text-sm text-gray-400 mt-1">
                  Run ID: {detail.run_id} · Duration:{" "}
                  {detail.duration_sim_minutes}m · Events injected:{" "}
                  {detail.events_injected}
                </p>
                {detail.summary && (
                  <p className="text-sm text-gray-300 mt-2 bg-gray-800 rounded p-3">
                    {detail.summary}
                  </p>
                )}
              </div>

              {/* Metrics chart */}
              {detail.metric_snapshots &&
                detail.metric_snapshots.length > 0 && (
                  <div>
                    <h3 className="text-sm font-bold text-gray-300 mb-3">
                      📈 Metric Timeline
                    </h3>
                    <div className="bg-gray-800 rounded p-4">
                      <MetricsChart snapshots={detail.metric_snapshots} />
                    </div>
                  </div>
                )}

              {/* Outcome results */}
              {detail.outcome_results && detail.outcome_results.length > 0 && (
                <div>
                  <h3 className="text-sm font-bold text-gray-300 mb-3">
                    📊 Outcome Evaluation
                    {detail.pass_rate != null && (
                      <span className="ml-2 text-xs font-normal text-gray-400">
                        ({detail.pass_rate.toFixed(0)}% pass rate)
                      </span>
                    )}
                  </h3>
                  <div className="bg-gray-800 rounded p-4">
                    <OutcomesTable
                      outcomes={detail.outcome_results.map(
                        (o: OutcomeResult) => ({
                          metric: o.metric,
                          condition: o.condition,
                          within_sim_minutes: o.evaluated_at_offset_minutes,
                        }),
                      )}
                      results={detail.outcome_results}
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Empty state */}
          {!selectedScenario && !selectedResult && !editorMode && (
            <div className="flex items-center justify-center h-full text-gray-400">
              <div className="text-center">
                <div className="text-4xl mb-3">🧪</div>
                <div className="text-sm font-medium">
                  Select a scenario to inspect
                </div>
                <div className="text-xs text-gray-600 mt-1">
                  Or run one to see live simulation metrics
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
