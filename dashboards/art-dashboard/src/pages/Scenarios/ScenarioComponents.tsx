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
import { StatusBadge } from "../../components/StatusBadge";
import type {
  ScenarioSummary,
  ScenarioEvent,
  ExpectedOutcome,
  OutcomeResult,
  MetricSnapshot,
  ScenarioRunResult,
} from "./types";
import { SEVERITY_COLOR, TYPE_EMOJI } from "./types";

/* ──────── Scenario Card ──────── */

export function ScenarioCard({
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
        <span className="text-xs text-gray-400">
          {scenario.duration_sim_minutes}m
        </span>
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

export function EventTimeline({ events }: { events: ScenarioEvent[] }) {
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

/* ──────── Expected Outcomes Table ──────── */

export function OutcomesTable({
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

export function MetricsChart({ snapshots }: { snapshots: MetricSnapshot[] }) {
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

export function ResultCard({
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
