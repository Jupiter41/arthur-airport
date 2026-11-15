import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { analysisApi } from "../../hooks/useApi";
import { DecisionTimeline, decisionLabel, simTimestamp } from "./DecisionTimeline";

export function DecisionWorkspace({ compact = false }: { compact?: boolean }) {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = compact ? 6 : 25;
  const bottleneck = params.get("bottleneck_id");
  const incident = params.get("incident_id");
  const list = useQuery({ queryKey: ["analysis", "decisions", offset, limit, status, bottleneck, incident],
    queryFn: () => analysisApi.decisions({ offset: String(offset), limit: String(limit), ...(status ? { status } : {}), ...(bottleneck ? { bottleneck_id: bottleneck } : {}), ...(incident ? { incident_id: incident } : {}) }), refetchInterval: 5000 });
  const selectedId = params.get("decision") ?? list.data?.decisions[0]?.id;
  const selected = useQuery({ queryKey: ["analysis", "decision", selectedId], queryFn: () => analysisApi.decision(selectedId!), enabled: !!selectedId, refetchInterval: 5000 });
  function select(id: string) { const next = new URLSearchParams(params); next.set("decision", id); setParams(next, { replace: true }); }
  const items = list.data?.decisions.filter(item => `${item.description} ${item.id} ${item.bottleneck?.zone ?? ""}`.toLowerCase().includes(search.toLowerCase())) ?? [];
  return <section className="space-y-3" aria-label="Decision history">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-lg">Decisions, from signal to outcome</h2><p className="text-xs text-gray-400 mt-1">Durable evidence · simulation timestamps · refreshed every 5 seconds</p></div>
      {compact && <Link className="text-sm text-sky-300" to="/decisions">Explore all decisions →</Link>}
    </div>
    {!compact && <div className="flex flex-wrap gap-3 items-center">
      <input type="text" aria-label="Search loaded decisions" className="px-3 py-2 text-sm min-w-0 w-full sm:w-80 border" placeholder="Search this page by target or decision" value={search} onChange={e => setSearch(e.target.value)} />
      <select aria-label="Decision status" value={status} className="text-sm p-2" onChange={e => { setStatus(e.target.value); setOffset(0); }}>
        <option value="">All states</option>{["detected", "pending", "approved", "dispatched", "awaiting_measurement", "measured", "failed", "rejected", "resolved"].map(s => <option key={s} value={s}>{decisionLabel(s)}</option>)}
      </select>
      {(bottleneck || incident) && <button className="text-xs text-sky-300" onClick={() => { setParams({}); setOffset(0); }}>Clear target filter</button>}
    </div>}
    {list.isError && <div role="alert" className="rounded-xl border border-rose-400/30 p-3 text-sm text-rose-300">Decision history unavailable. {list.data ? "Showing the last successful response." : "No history can be inferred from this failure."} <button onClick={() => list.refetch()} className="underline">Retry</button></div>}
    <div className="grid gap-4 lg:grid-cols-[minmax(240px,0.8fr)_minmax(0,2fr)] items-start">
      <div className="space-y-2">
        {list.isLoading && <p className="card text-sm text-gray-400">Loading decision history…</p>}
        {items.map(item => <button key={item.id} aria-pressed={item.id === selectedId} onClick={() => select(item.id)} className={`w-full text-left rounded-xl border p-4 transition-colors ${item.id === selectedId ? "border-sky-400/50 bg-sky-400/10" : "border-panel-border/60 bg-surface-card hover:bg-panel"}`}>
          <div className="flex gap-2 items-center justify-between"><span className="text-[10px] uppercase tracking-wider text-gray-400">{item.bottleneck?.zone ?? "Historical target"}</span><span className="text-[10px] text-sky-300">{decisionLabel(item.status)}</span></div>
          <p className="text-sm text-gray-100 mt-2 leading-relaxed">{item.description}</p><time className="block text-[10px] text-gray-500 font-mono mt-3">{simTimestamp(item.updated_at)}</time>
        </button>)}
        {!list.isLoading && !list.isError && !items.length && <p className="card text-sm text-gray-400">{search || status ? "No decisions match this filter." : "No decisions recorded yet. Detection, commands and outcomes will appear here as the simulation runs."}</p>}
        {list.data && list.data.total > limit && <div className="flex justify-between items-center text-xs text-gray-400 pt-2"><button disabled={offset === 0} className="disabled:opacity-30" onClick={() => setOffset(Math.max(0, offset - limit))}>← Previous</button><span>{offset + 1}–{Math.min(offset + limit, list.data.total)} of {list.data.total}</span><button disabled={offset + limit >= list.data.total} className="disabled:opacity-30" onClick={() => setOffset(offset + limit)}>Next →</button></div>}
      </div>
      <div className="min-w-0">
        {selected.isError && <p role="alert" className="card text-rose-300 text-sm">Selected decision unavailable. <button className="underline" onClick={() => selected.refetch()}>Retry</button></p>}
        {selected.isLoading && <p className="card text-gray-400 text-sm">Loading decision evidence…</p>}
        {selected.data && <DecisionTimeline key={selected.data.id} decision={selected.data} onSubmitted={select} />}
        {!selectedId && !list.isLoading && <div className="card border-dashed min-h-48 flex flex-col justify-center text-center"><p className="text-gray-300">The next decision starts with a signal.</p><p className="text-sm text-gray-500 mt-2">Use the teaching runbook below or explore active incidents.</p></div>}
      </div>
    </div>
  </section>;
}
