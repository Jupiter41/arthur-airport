import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { analysisApi } from "../../hooks/useApi";
import { DecisionTimeline, decisionLabel, simTimestamp } from "./DecisionTimeline";

export function DecisionWorkspace({ compact = false, terminal, incidentId }: { compact?: boolean; terminal?: string; incidentId?: string }) {
  const [params, setParams] = useSearchParams();
  const status=params.get("decision_status")??"";
  const search=params.get("q")??"";
  const offset=Math.max(0,Number(params.get("offset"))||0);
  const setOffset=(value:number)=>{const next=new URLSearchParams(params);next.set("offset",String(value));setParams(next,{replace:true});};
  const filter=(key:string,value:string)=>{const next=new URLSearchParams(params);if(value)next.set(key,value);else next.delete(key);next.delete("offset");next.delete("decision");setParams(next,{replace:true});};
  const limit = compact ? 6 : 25;
  const bottleneck = params.get("bottleneck_id");
  const incident = incidentId ?? params.get("incident_id");
  const targetTerminal=terminal??params.get("terminal");
  const list = useQuery({ queryKey: ["analysis", "decisions", offset, limit, status, bottleneck, incident, search, targetTerminal],
    queryFn: () => analysisApi.decisions({ offset: String(offset), limit: String(limit), ...(search ? { q: search } : {}), ...(["A","B","C"].includes(targetTerminal??"") ? { terminal: targetTerminal! } : {}), ...(status ? { status } : {}), ...(bottleneck ? { bottleneck_id: bottleneck } : {}), ...(incident ? { incident_id: incident } : {}) }), refetchInterval: 5000 });
  const selectedId = params.get("decision") ?? list.data?.decisions[0]?.id;
  const selected = useQuery({ queryKey: ["analysis", "decision", selectedId], queryFn: () => analysisApi.decision(selectedId!), enabled: !!selectedId, refetchInterval: 5000 });
  function select(id: string) { const next = new URLSearchParams(params); next.set("decision", id); setParams(next, { replace: true }); }
  const items = list.data?.decisions ?? [];
  return <section className="space-y-3" aria-label="Decision history">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-lg">Decisions & outcomes</h2><p className="text-xs text-gray-400 mt-1">Recorded evidence · simulation timestamps · refreshed every 5 seconds</p></div>
      {compact && <Link className="text-sm text-sky-300" to={`/decisions?${new URLSearchParams({...(targetTerminal ? {terminal:targetTerminal}:{}),...(incident ? {incident_id:incident}:{})})}`}>Explore all decisions →</Link>}
    </div>
    {!compact && <div className="flex flex-wrap gap-3 items-center">
      <input type="text" aria-label="Search all decisions" className="px-3 py-2 text-sm min-w-0 w-full sm:w-80 border" placeholder="Search all history by target, action or ID" value={search} maxLength={200} onChange={e => filter("q",e.target.value)} />
      <select aria-label="Decision status" value={status} className="text-sm p-2" onChange={e => filter("decision_status",e.target.value)}>
        <option value="">All states</option>{["detected", "pending", "approved", "dispatched", "awaiting_measurement", "measured", "failed", "rejected", "resolved"].map(s => <option key={s} value={s}>{decisionLabel(s)}</option>)}
      </select>
      {(bottleneck || incident) && <button className="text-xs text-sky-300" onClick={() => { const next=new URLSearchParams(params);next.delete("bottleneck_id");next.delete("incident_id");next.delete("decision");next.delete("offset");setParams(next); }}>Clear target filter</button>}
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
        {!selectedId && !list.isLoading && <div className="card border-dashed min-h-48 flex flex-col justify-center text-center"><p className="text-gray-300">Select a decision to inspect its execution and outcome.</p><p className="text-sm text-gray-500 mt-2">Explore active incidents or open Help for the teaching lab.</p></div>}
      </div>
    </div>
  </section>;
}
