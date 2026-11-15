import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { baggageApi } from "../../hooks/useApi";
import { useSimStore } from "../../stores/simStore";
import { useConnectionStore } from "../../stores/connectionStore";
import { SceneViewport, type CameraPreset } from "./SceneViewport";
import { useSceneData } from "./useSceneData";
import { AtcBoard } from "./AtcBoard";
import { checkpoint, entities, parseSimSeconds, type BagDetail, type Quality, type SceneOptions, type Terminal, type View } from "./model";

const views: Array<{ id: View; title: string; description: string; number: string }> = [
  { id: "airport", title: "Airfield", description: "Aircraft · gates · ground fleet", number: "01" },
  { id: "passengers", title: "Passenger journey", description: "Terminal · queues · security", number: "02" },
  { id: "baggage", title: "Baggage system", description: "Induction · screening · make-up", number: "03" },
  { id: "atc", title: "Air traffic control", description: "Approach · holding · runways", number: "04" },
];
function BaggageInspector({ zoneId }: { zoneId: string }) {
  const [bagId, setBagId] = useState<string | null>(null);
  const items = useQuery({ queryKey: ["baggage", "3d-items", zoneId], queryFn: () => baggageApi.list({ zone: zoneId, limit: "50" }), refetchInterval: 5000 });
  const detail = useQuery({ queryKey: ["baggage", "detail", bagId], queryFn: () => baggageApi.get(bagId!) as Promise<BagDetail>, enabled: !!bagId, refetchInterval: 5000 });
  return <section className="border-t border-panel-border pt-4 space-y-3" aria-label="Recorded baggage items"><h3 className="text-sm">Recorded items in this zone</h3>
    {items.isError && <p role="alert" className="text-xs text-amber-300">Item records unavailable or stale.</p>}
    {items.isLoading && <p className="text-xs text-gray-400">Loading item records…</p>}
    <p className="text-[11px] text-gray-500">Showing {items.data?.items.length ?? "—"} of {items.data?.total ?? "—"}. 3D bags are aggregate representatives.</p>
    <div className="max-h-40 overflow-y-auto space-y-1">{items.data?.items.map(item => <button key={item.id} onClick={() => setBagId(item.id)} aria-pressed={bagId === item.id} className={`block text-left w-full rounded p-2 text-xs ${bagId === item.id ? "bg-sky-400/15 text-sky-200" : "bg-panel-active text-gray-400"}`}>{item.tag || item.id} · {item.status}</button>)}</div>
    {items.data && !items.data.items.length && <p className="text-xs text-gray-400">No item records currently match this zone.</p>}
    {bagId && <div className="space-y-2 text-xs"><p className="font-mono text-cyan-200">{detail.data?.tag || bagId}</p>{detail.isLoading && <p>Loading scan history…</p>}{detail.isError && <p role="alert" className="text-amber-300">Scan history unavailable or stale.</p>}{detail.data && <><p>{detail.data.status} · last scan: {detail.data.last_scan_zone || "Unknown"}</p><ol className="space-y-2">{detail.data.scan_history?.map((scan, i) => <li key={`${scan.at}-${i}`} className="border-l border-cyan-400/40 pl-2"><p>{scan.zone} · {scan.status}</p><time className="text-gray-500">{scan.at}</time></li>)}</ol>{!detail.data.scan_history?.length && <p className="text-gray-500">No scan history recorded. Next destination unknown.</p>}</>}</div>}
  </section>;
}

export default function Airport3DPage({ view: fixedView, embedded = false }: { view?: View; embedded?: boolean } = {}) {
  const [params, setParams] = useSearchParams();
  const rawView = params.get("view"); const view: View = fixedView ?? (rawView === "passengers" || rawView === "baggage" || rawView === "atc" ? rawView : "airport");
  const rawTerminal = params.get("terminal"); const terminal: Terminal = rawTerminal === "B" || rawTerminal === "C" ? rawTerminal : "A";
  const [quality, setQuality] = useState<Quality>("balanced");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState(""); const [preset, setPreset] = useState<CameraPreset>("overview"); const [cameraRevision, setCameraRevision] = useState(0);
  const { data, unavailable, loading, refresh } = useSceneData(view);
  const clock = useSimStore(s => s.status); const connected = useConnectionStore(s => s.wsConnected);
  const options: SceneOptions = useMemo(() => ({ view, terminal, quality }), [view, terminal, quality]);
  const rows = useMemo(() => entities(data, options, parseSimSeconds(clock.sim_time) ?? 0), [data, options, clock.sim_time]);
  const selected = rows.find(e => e.id === selectedId);
  const visibleRows = rows.filter(e => `${e.label} ${e.status}`.toLowerCase().includes(search.toLowerCase()));
  const security = checkpoint(data, terminal);
  const selectView = (next: View) => { setParams({ view: next, terminal }); setSelectedId(null); setSearch(""); setPreset("overview"); setCameraRevision(v => v + 1); };
  const camera = (next: CameraPreset) => { setPreset(next); setCameraRevision(v => v + 1); };
  const needed = view === "airport" ? ["Flights", "Gates", "Runways", "Vehicles"] : view === "atc" ? ["Flights", "Runways", "Runway queue"] : view === "passengers" ? ["Passengers", "Passenger zones"] : ["Baggage"];
  const degraded = unavailable.filter(name => needed.includes(name));
  return <div className="h-full overflow-y-auto p-4 md:p-6 space-y-5 max-w-[1900px] mx-auto">
    <header className="flex flex-wrap justify-between gap-4 items-end"><div><p className="text-[10px] tracking-[0.28em] uppercase text-cyan-300">Arthur International / Live twin state</p><h2 className="text-2xl mt-2">{views.find(v => v.id === view)?.title}</h2><p className="text-sm text-slate-400 mt-2">Live owner observations · no independent 3D simulation</p></div><div className="text-right text-xs font-mono text-slate-400"><p className="text-cyan-100">{clock.tick_count > 0 ? clock.sim_time.replace("T", " ").replace(/\.\d+Z$/, "Z") : "Awaiting source clock"}</p><p className="mt-1">{connected ? "EVENT STREAM CONNECTED" : "EVENT STREAM DISCONNECTED · REST RECONCILIATION"}{clock.paused ? " · SOURCE PAUSED" : ""}</p></div></header>
    {!embedded && <nav aria-label="3D perspectives" className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">{views.map(item => <button key={item.id} onClick={() => selectView(item.id)} aria-pressed={view === item.id} className={`rounded-xl border p-4 text-left flex gap-4 transition-colors ${view === item.id ? "bg-cyan-400/10 border-cyan-300/40" : "border-panel-border bg-panel hover:bg-panel-active"}`}><span className="font-mono text-xs text-cyan-300/60 mt-1">{item.number}</span><span><span className="block text-sm text-slate-100">{item.title}</span><span className="block text-xs mt-1 text-slate-400">{item.description}</span></span></button>)}</nav>}
    {degraded.length > 0 && <p role="alert" className="rounded-xl border border-amber-400/30 bg-amber-400/5 p-3 text-xs text-amber-200">Unavailable or stale: {degraded.join(", ")}. Last successful observations remain visible where available.</p>}
    <div className="flex flex-wrap justify-between gap-3 items-center"><div className="flex flex-wrap gap-2 items-center">
      {view !== "airport" && view !== "atc" && <label className="text-xs text-gray-400">Terminal <select aria-label="Terminal" value={terminal} onChange={e => { const next = new URLSearchParams(params); next.set("terminal", e.target.value); setParams(next); setSelectedId(null); }} className="ml-1 bg-panel rounded-lg p-2 text-gray-200">{["A", "B", "C"].map(t => <option key={t}>{t}</option>)}</select></label>}
      <label className="text-xs text-gray-400">Quality <select aria-label="Rendering quality" value={quality} onChange={e => setQuality(e.target.value as Quality)} className="ml-1 bg-panel rounded-lg p-2 text-gray-200"><option value="low">Low</option><option value="balanced">Balanced</option><option value="high">High</option></select></label>
    </div><div className="flex gap-2">{([["overview", "Overview"], ["top", "Top view"], ...(view === "airport" || view === "atc" ? [["tower", "Tower"] as const] : []), ["close", "Focus selected"]] as const).map(([id, title]) => <button key={id} onClick={() => camera(id)} disabled={id === "close" && (!selected || selected.positionAvailable === false)} className="text-xs rounded-lg bg-panel border border-panel-border px-3 py-2 disabled:opacity-35 hover:text-cyan-200">{title}</button>)}<button onClick={refresh} className="text-xs text-cyan-200 px-2">Refresh</button></div></div>
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] gap-4 items-start">
      <div className="space-y-3 min-w-0"><SceneViewport data={data} options={options} selectedId={selected?.id ?? null} onSelect={setSelectedId} preset={preset} cameraRevision={cameraRevision} />
        <p className="text-[11px] leading-relaxed text-slate-500">{view === "atc" ? "Read-only traffic picture from owner facts: aircraft fly the flight state-machine timeline; corridors are marked in minutes to touchdown on the compressed approach scale; the holding fix is schematic. Sequence, wake separation, ROT block and capacity come from the flight owner's runway queue. No clearances are modelled." : view === "airport" ? "Aircraft follow the flight owner's state-machine timeline in simulation time: approach from ETA−20 min, touchdown at ETA, rollout and taxi over the owner's taxi durations, pushback-to-airborne over its 5-minute departure window. Vehicles travel their owner trip segments between dispatch and arrival times. Approach distance, taxi routes and take-off geometry are schematic; timing, runway, gate and vehicle coordinates are owner facts." : view === "passengers" ? "Live queue counts, wait and open/frozen lanes. Figures represent aggregate counts and advance at the observed rate (a figure joining now reaches the lanes after the reported wait); frozen lanes stop. Individual passenger coordinates are not supplied by the owner." : "Live zone occupancy, throughput and failures. Bags represent aggregate counts and cross each belt in the observed dwell time (items ÷ throughput); offline belts stop. Inspect actual item scans below. Conveyor layout is schematic."} Motion uses simulation time: it pauses with the source and follows its speed.</p>
        {view === "atc" && <AtcBoard data={data} seconds={parseSimSeconds(clock.sim_time) ?? 0} selectedId={selected?.id ?? null} onSelect={setSelectedId} />}
        {view === "passengers" && security && <div className="grid grid-cols-3 gap-3">{[["Queued passengers", security.queue_length], ["Wait / minutes", security.wait_minutes.toFixed(1)], ["Open lanes", security.frozen ? `${security.lanes_open} / frozen` : security.lanes_open]].map(([title, value]) => <div key={title} className="card"><p className="text-[10px] text-gray-400">{title}</p><p className="text-2xl font-mono text-cyan-100 mt-2">{value}</p></div>)}</div>}
      </div>
      <aside className="card space-y-5 xl:max-h-[690px] xl:overflow-y-auto">
        <div><p className="text-[10px] uppercase tracking-[0.2em] text-cyan-300">Live inspector</p><h2 className="text-base mt-2">{selected?.label || "Select an entity"}</h2>{selected ? <><p className="mt-2 text-xs text-amber-200">{selected.status}</p><dl className="mt-4 space-y-3">{selected.facts.map(([key, value]) => <div key={key}><dt className="text-[10px] text-gray-500">{key}</dt><dd className="text-xs mt-1 text-gray-200 break-words">{value}</dd></div>)}</dl><Link to={`${selected.href}?3d=off`} className="inline-block text-xs text-cyan-300 mt-4">Open 2D details →</Link></> : <p className="text-xs mt-2 text-gray-500">Select a model in the scene, or choose an observed entity below.</p>}</div>
        {view === "passengers" && <Link to="/decisions" className="block text-xs text-cyan-300 border border-cyan-300/20 rounded-lg p-3">Review lane recommendations, approvals and owner receipts →</Link>}
        <section className="border-t border-panel-border pt-4"><label className="block text-xs text-gray-400 mb-2" htmlFor="scene-search">Observed entities · {rows.length}</label><input id="scene-search" type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search entities" className="w-full bg-panel-active border border-panel-border rounded-lg p-2 text-xs" />
          <div className="mt-3 max-h-64 overflow-y-auto space-y-1" aria-label="Observed entity list">{visibleRows.map(row => <button key={`${row.kind}-${row.id}`} onClick={() => setSelectedId(row.id)} aria-pressed={selected?.id === row.id} className={`w-full text-left rounded-lg px-2 py-2 text-xs ${selected?.id === row.id ? "bg-cyan-400/15 text-cyan-100" : "hover:bg-panel-active text-gray-400"}`}><span className="block truncate">{row.label}</span><span className="text-[10px] text-gray-500">{row.kind} · {row.status}</span></button>)}</div>
          {!visibleRows.length && <p className="text-xs text-gray-500 mt-3">{loading ? "Loading observations…" : "No matching observations. No traffic is invented."}</p>}
        </section>
        {selected?.kind === "zone" && <BaggageInspector key={selected.id} zoneId={selected.id} />}
      </aside>
    </div>
    <footer className="flex flex-wrap gap-5 text-xs text-slate-400 border-t border-panel-border pt-4"><span className="text-cyan-300/70">Continue investigating</span><Link to="/ground-ops">Ground operations ↗</Link><Link to="/atc">Air traffic control ↗</Link><Link to="/passengers">Passenger flow ↗</Link><Link to="/baggage">Baggage tracker ↗</Link><Link to="/decisions">Decision evidence ↗</Link></footer>
  </div>;
}
