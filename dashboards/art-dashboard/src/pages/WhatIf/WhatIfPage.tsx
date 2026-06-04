import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { planningApi } from "../../hooks/useApi";
import { KpiCard } from "../../components/KpiCard";
import { LoadingState, ErrorState } from "../../components/LoadingState";

type Scenario = {
  scenario_id: string;
  name?: string;
  status?: string;
  parent_scenario_id?: string | null;
};

type Replay = {
  scenario_id: string;
  status: string;
  label?: string;
  created_at?: string;
  results?: {
    avg_delay_minutes_mean?: number;
    missed_connections_mean?: number;
    eu261_eur_mean?: number;
  };
};

const ACTIONS = ["gdp_start", "gdp_end", "open_security_lanes", "gate_swap"];

export default function WhatIfPage() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [action, setAction] = useState("open_security_lanes");
  const [simMinute, setSimMinute] = useState(120);
  const [durationMin, setDurationMin] = useState(60);
  const [lanes, setLanes] = useState(2);

  const scenarios = useQuery({
    queryKey: ["planning", "scenarios", "list", "whatif"],
    queryFn: () => planningApi.listScenarios({ limit: 20 }),
    refetchInterval: 20_000,
  });

  const list = (scenarios.data?.scenarios ?? []) as Scenario[];
  const parents = list.filter((s) => !s.parent_scenario_id);
  const parentId = selected ?? parents[0]?.scenario_id ?? null;

  const replays = useQuery({
    queryKey: ["planning", "replays", parentId],
    queryFn: () => planningApi.listReplays(parentId!),
    refetchInterval: 10_000,
    enabled: !!parentId,
  });
  const causal = useQuery({
    queryKey: ["planning", "causal", parentId],
    queryFn: () => planningApi.causalGraph(parentId!),
    refetchInterval: 15_000,
    enabled: !!parentId,
  });

  const replay = useMutation({
    mutationFn: () => {
      const params: Record<string, unknown> = {};
      if (action === "open_security_lanes") params.lanes = lanes;
      if (action === "gate_swap") params.count = lanes;
      return planningApi.replayScenario(parentId!, {
        interventions: [
          {
            action,
            sim_minute: simMinute,
            duration_minutes: durationMin,
            params,
          },
        ],
        label: `${action} @T+${simMinute}`,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planning", "replays", parentId] });
    },
  });

  const counterfactual = useMutation({
    mutationFn: () => {
      const params: Record<string, unknown> = {};
      if (action === "open_security_lanes") params.lanes = lanes;
      if (action === "gate_swap") params.count = lanes;
      return planningApi.counterfactualReport(parentId!, {
        intervention: {
          action,
          sim_minute: simMinute,
          duration_minutes: durationMin,
          params,
        },
        shifts_minutes: [-60, -30, 0, 30, 60],
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planning", "replays", parentId] });
    },
  });

  if (scenarios.isLoading) return <LoadingState message="Loading scenarios…" />;
  if (scenarios.isError)
    return (
      <ErrorState
        message="Failed to load scenarios"
        detail="planning-service may be offline."
        onRetry={() => scenarios.refetch()}
      />
    );

  const replayList = (replays.data?.replays ?? []) as Replay[];
  const kpiNodes = (causal.data?.nodes ?? []).filter((n) => n.kind === "kpi");

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div>
        <h1 className="text-xl font-bold text-white">🔮 What-If Replay</h1>
        <p className="text-xs text-gray-400 mt-0.5">
          Counterfactual delay analysis · clone a scenario, apply an
          intervention, compare KPIs.
        </p>
      </div>

      <div className="bg-surface-card border border-panel-border rounded-xl p-4">
        <h2 className="text-sm font-semibold text-white mb-3">
          Parent scenario
        </h2>
        {parents.length === 0 ? (
          <p className="text-xs text-gray-500">
            No completed scenarios. Create one in the Planning page first.
          </p>
        ) : (
          <select
            value={parentId ?? ""}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full bg-slate-800 border border-panel-border rounded px-2 py-1.5 text-xs text-white"
          >
            {parents.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {(s.name ?? s.scenario_id).slice(0, 60)} — {s.status ?? "?"}
              </option>
            ))}
          </select>
        )}
      </div>

      {parentId && (
        <>
          <div className="bg-surface-card border border-panel-border rounded-xl p-4">
            <h2 className="text-sm font-semibold text-white mb-3">
              Intervention
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
              <label className="text-gray-300">
                Action
                <select
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                  className="w-full mt-1 bg-slate-800 border border-panel-border rounded px-2 py-1 text-white"
                >
                  {ACTIONS.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-gray-300">
                Sim minute (T+)
                <input
                  type="number"
                  value={simMinute}
                  onChange={(e) => setSimMinute(Number(e.target.value))}
                  className="w-full mt-1 bg-slate-800 border border-panel-border rounded px-2 py-1 text-white"
                />
              </label>
              <label className="text-gray-300">
                Duration (min)
                <input
                  type="number"
                  value={durationMin}
                  onChange={(e) => setDurationMin(Number(e.target.value))}
                  className="w-full mt-1 bg-slate-800 border border-panel-border rounded px-2 py-1 text-white"
                />
              </label>
              <label className="text-gray-300">
                Lanes / gates
                <input
                  type="number"
                  value={lanes}
                  onChange={(e) => setLanes(Number(e.target.value))}
                  className="w-full mt-1 bg-slate-800 border border-panel-border rounded px-2 py-1 text-white"
                  disabled={
                    action !== "open_security_lanes" && action !== "gate_swap"
                  }
                />
              </label>
              <div className="flex items-end gap-2">
                <button
                  onClick={() => replay.mutate()}
                  disabled={replay.isPending}
                  className="flex-1 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white px-3 py-1.5 rounded"
                >
                  {replay.isPending ? "Spawning…" : "Replay"}
                </button>
                <button
                  onClick={() => counterfactual.mutate()}
                  disabled={counterfactual.isPending}
                  className="flex-1 bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-white px-3 py-1.5 rounded"
                  title="Spawn 5 children at shifts [-60,-30,0,+30,+60]"
                >
                  Report
                </button>
              </div>
            </div>
            {(replay.error || counterfactual.error) && (
              <p className="text-xs text-rose-400 mt-2">
                {String(replay.error ?? counterfactual.error)}
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {kpiNodes.length === 0 ? (
              <div className="col-span-3 text-xs text-gray-500">
                No baseline KPIs yet. Run the parent scenario first.
              </div>
            ) : (
              kpiNodes.map((n) => {
                const d = (n.data ?? {}) as {
                  mean?: number;
                  unit?: string;
                };
                return (
                  <KpiCard
                    key={n.id}
                    label={n.label}
                    value={`${(d.mean ?? 0).toFixed(2)} ${d.unit ?? ""}`}
                    sub="baseline (parent)"
                  />
                );
              })
            )}
          </div>

          <div className="bg-surface-card border border-panel-border rounded-xl p-4">
            <h2 className="text-sm font-semibold text-white mb-3">
              Replays ({replayList.length})
            </h2>
            {replayList.length === 0 ? (
              <p className="text-xs text-gray-500">
                No replays yet — submit one above.
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-gray-400 border-b border-panel-border">
                  <tr>
                    <th className="text-left py-2">Label</th>
                    <th className="text-left">Status</th>
                    <th className="text-right">Avg delay (min)</th>
                    <th className="text-right">Missed conn.</th>
                    <th className="text-right">EU261 (€)</th>
                    <th className="text-left pl-3">ID</th>
                  </tr>
                </thead>
                <tbody className="text-gray-200">
                  {replayList.map((r) => (
                    <tr
                      key={r.scenario_id}
                      className="border-b border-panel-border/50"
                    >
                      <td className="py-2">{r.label ?? "—"}</td>
                      <td>
                        <span
                          className={
                            r.status === "completed"
                              ? "text-emerald-300"
                              : r.status === "failed"
                                ? "text-rose-400"
                                : "text-amber-300"
                          }
                        >
                          {r.status}
                        </span>
                      </td>
                      <td className="text-right font-mono">
                        {r.results?.avg_delay_minutes_mean?.toFixed(2) ?? "—"}
                      </td>
                      <td className="text-right font-mono">
                        {r.results?.missed_connections_mean?.toFixed(1) ?? "—"}
                      </td>
                      <td className="text-right font-mono">
                        {r.results?.eu261_eur_mean?.toFixed(0) ?? "—"}
                      </td>
                      <td className="pl-3 font-mono text-gray-500 text-[10px]">
                        {r.scenario_id.slice(0, 8)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
