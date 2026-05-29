import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { planningApi } from "../../../hooks/useApi";
import { formatEur } from "../../../utils/formatCurrency";
import type { ScenarioSummary } from "../types";

/* ─── Status Badge ────────────────────────────────────────── */

export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-slate-600 text-slate-200",
    running: "bg-cyan-600/30 text-cyan-300 animate-pulse",
    completed: "bg-emerald-600/30 text-emerald-300",
    failed: "bg-red-600/30 text-red-300",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${styles[status] ?? styles.pending}`}
    >
      {status}
    </span>
  );
}

/* ─── Metric Card ─────────────────────────────────────────── */

export function MetricCard({
  label,
  value,
  sublabel,
  color = "text-white",
}: {
  label: string;
  value: string;
  sublabel?: string;
  color?: string;
}) {
  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      <div className={`text-xl font-bold ${color}`}>{value}</div>
      {sublabel && (
        <div className="text-xs text-slate-500 mt-1">{sublabel}</div>
      )}
    </div>
  );
}

/* ─── Cost Preview ────────────────────────────────────────── */

export function CostPreview({
  items,
}: {
  items: { label: string; value: string }[];
}) {
  return (
    <div className="bg-slate-900/40 rounded-lg border border-slate-600/50 p-3 mt-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">
        Auto-configured parameters
      </div>
      <div className="grid grid-cols-2 gap-2">
        {items.map((item) => (
          <div key={item.label}>
            <div className="text-[10px] text-slate-500">{item.label}</div>
            <div className="text-xs text-white font-medium">{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Cash Flow Row ───────────────────────────────────────── */

export function CashFlowRow({
  label,
  value,
  bold = false,
}: {
  label: string;
  value: number;
  bold?: boolean;
}) {
  const color =
    value > 0
      ? "text-emerald-400"
      : value < 0
        ? "text-red-400"
        : "text-slate-400";
  return (
    <div
      className={`flex justify-between text-sm ${bold ? "border-t border-slate-600 pt-2 mt-2" : ""}`}
    >
      <span className={`${bold ? "text-white font-medium" : "text-slate-400"}`}>
        {label}
      </span>
      <span className={`font-mono ${color}`}>{formatEur(value)}</span>
    </div>
  );
}

/* ─── Time Estimate Bar ───────────────────────────────────── */

export function TimeEstimateBar({
  estimate,
}: {
  estimate?: {
    estimated_seconds: number;
    human_readable: string;
    confidence: string;
  };
}) {
  if (!estimate) return null;
  const confColor =
    estimate.confidence === "high"
      ? "text-emerald-400"
      : estimate.confidence === "medium"
        ? "text-amber-400"
        : "text-slate-400";
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-900/40 rounded-lg px-3 py-2 border border-slate-700">
      <span>⏱️ Estimated: {estimate.human_readable}</span>
      <span className={confColor}>({estimate.confidence})</span>
    </div>
  );
}

/* ─── Tooltip ─────────────────────────────────────────────── */

export function Tooltip({ text }: { text: string }) {
  return (
    <span className="relative group cursor-help ml-1">
      <span className="text-slate-500 text-[10px]">ⓘ</span>
      <span className="hidden group-hover:block absolute z-50 bg-slate-900 border border-slate-600 rounded-lg p-2 text-xs text-slate-300 w-48 bottom-full left-1/2 -translate-x-1/2 mb-1 shadow-xl">
        {text}
      </span>
    </span>
  );
}

/* ─── Format duration ─────────────────────────────────────── */

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

/* ─── Scenario List Item ──────────────────────────────────── */

export function ScenarioListItem({
  scenario,
  onDelete,
}: {
  scenario: ScenarioSummary;
  onDelete: (id: string) => void;
}) {
  const isRunning =
    scenario.status === "running" || scenario.status === "pending";
  const { data: statusData } = useQuery({
    queryKey: ["planning-status", scenario.id],
    queryFn: () => planningApi.getScenarioStatus(scenario.id),
    enabled: isRunning,
    refetchInterval: isRunning ? 3000 : false,
  });

  const st = statusData as Record<string, unknown> | undefined;
  const progress = (st?.progress_pct as number) ?? 0;
  const runsCompleted = (st?.runs_completed as number) ?? 0;
  const runsTotal = (st?.runs_total as number) ?? 0;
  const remaining = st?.estimated_remaining_seconds as number | undefined;

  return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700 p-3 text-xs">
      <div className="flex items-start justify-between mb-1">
        <div className="font-medium text-white truncate flex-1 mr-2">
          {scenario.name || "Unnamed"}
        </div>
        <StatusBadge status={scenario.status} />
      </div>
      <div className="flex items-center gap-2 text-slate-500 mb-2">
        <span>{scenario.horizon}</span>
        <span>·</span>
        <span>{scenario.monte_carlo_runs} MC</span>
      </div>

      {isRunning && (
        <div className="space-y-1">
          <div className="flex justify-between text-[10px] text-slate-500">
            <span>
              Runs {runsCompleted}/{runsTotal}
            </span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-slate-700 rounded-full h-1.5">
            <div
              className="bg-cyan-500 rounded-full h-1.5 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          {remaining != null && (
            <div className="text-[10px] text-slate-500">
              ~{formatDuration(remaining)} remaining
            </div>
          )}
        </div>
      )}

      {scenario.status === "failed" && (
        <div className="text-red-400 text-[10px] mt-1">Scenario failed</div>
      )}

      <div className="flex justify-end mt-2">
        <button
          onClick={() => onDelete(scenario.id)}
          className="text-slate-500 hover:text-red-400 text-[10px] transition-colors"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

/* ─── Scenario Selector Grid ──────────────────────────────── */

export function ScenarioSelector({
  scenarios,
  selectedId,
  onSelect,
}: {
  scenarios: ScenarioSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(scenarios.length > 6);

  const visible = collapsed ? scenarios.slice(0, 4) : scenarios;

  return (
    <div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {visible.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`text-left rounded-lg p-3 border transition-all ${
              selectedId === s.id
                ? "bg-cyan-600/15 border-cyan-500 shadow-lg shadow-cyan-900/20"
                : "bg-slate-800/60 border-slate-700 hover:border-slate-500"
            }`}
          >
            <div
              className={`text-sm font-semibold truncate ${selectedId === s.id ? "text-cyan-300" : "text-white"}`}
            >
              {s.name || "Unnamed"}
            </div>
            <div className="flex items-center gap-2 mt-1 text-xs text-slate-400">
              <span>{s.horizon}</span>
              <span className="text-slate-600">·</span>
              <span>{s.monte_carlo_runs} MC</span>
              {s.completed_at && (
                <>
                  <span className="text-slate-600">·</span>
                  <span>{new Date(s.completed_at).toLocaleDateString()}</span>
                </>
              )}
            </div>
          </button>
        ))}
      </div>
      {scenarios.length > 4 && (
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-xs text-slate-400 hover:text-slate-200 mt-2"
        >
          {collapsed
            ? `Show all ${scenarios.length} scenarios ▾`
            : "Show fewer ▴"}
        </button>
      )}
    </div>
  );
}
