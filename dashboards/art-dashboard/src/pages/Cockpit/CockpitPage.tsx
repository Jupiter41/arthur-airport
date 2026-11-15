import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { flightsApi, incidentsApi, passengersApi, baggageApi } from "../../hooks/useApi";
import { useFlightStore } from "../../stores/flightStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { useConnectionStore } from "../../stores/connectionStore";
import type { Flight, Gate, Runway, Incident, PassengerFlowSummary, BaggageZone } from "../../types";
import { DecisionWorkspace } from "../Decisions/DecisionWorkspace";
import { TeachingRunbook } from "../Decisions/TeachingRunbook";
import { ApprovalQueue } from "../IncidentConsole/ApprovalQueue";

export default function CockpitPage() {
  const flights = useFlightStore(s => s.flights);
  const gates = useFlightStore(s => s.gates);
  const runways = useFlightStore(s => s.runways);
  const incidents = useIncidentStore(s => s.incidents);
  const wsConnected = useConnectionStore(s => s.wsConnected);
  // REST reconciles the live stores; components do not read a parallel copy.
  const flightLoad = useQuery({ queryKey: ["flights", "cockpit"], queryFn: async () => (await flightsApi.list({ limit: "500" })).flights as Flight[], refetchInterval: 30_000 });
  const gateLoad = useQuery({ queryKey: ["gates"], queryFn: async () => (await flightsApi.gates()).gates as Gate[], refetchInterval: 30_000 });
  const runwayLoad = useQuery({ queryKey: ["runways"], queryFn: async () => (await flightsApi.runways()).runways as Runway[], refetchInterval: 15_000 });
  const incidentLoad = useQuery({ queryKey: ["incidents", "active"], queryFn: async () => (await incidentsApi.list({ status: "active,contained" })).incidents as Incident[], refetchInterval: 30_000 });
  const passenger = useQuery({ queryKey: ["passengers", "summary"], queryFn: () => passengersApi.summary() as Promise<PassengerFlowSummary>, refetchInterval: 5000 });
  const baggage = useQuery({ queryKey: ["baggage", "map"], queryFn: async () => ((await baggageApi.map()) as { zones: BaggageZone[] }).zones, refetchInterval: 5000 });
  useEffect(() => { if (flightLoad.data) useFlightStore.getState().setFlights(flightLoad.data); }, [flightLoad.data]);
  useEffect(() => { if (gateLoad.data) useFlightStore.getState().setGates(gateLoad.data); }, [gateLoad.data]);
  useEffect(() => { if (runwayLoad.data) useFlightStore.getState().setRunways(runwayLoad.data); }, [runwayLoad.data]);
  useEffect(() => { if (incidentLoad.data) useIncidentStore.getState().setIncidents(incidentLoad.data); }, [incidentLoad.data]);
  const activeFlights = Object.values(flights).filter(f => !["completed", "cancelled", "diverted"].includes(f.status));
  const activeIncidents = Object.values(incidents).filter(i => i.status !== "resolved");
  const security = passenger.data?.security;
  const waits = security ? Object.values(security).map(s => s.wait_minutes) : [];
  const degraded = [flightLoad.isError && "Flights", gateLoad.isError && "Gates", runwayLoad.isError && "Runways", incidentLoad.isError && "Incidents", passenger.isError && "Passengers", baggage.isError && "Baggage"].filter(Boolean);
  const metric = (ready: boolean, value: number) => ready ? String(value) : "—";
  const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  return <div className="h-full overflow-y-auto p-4 md:p-6 space-y-6 max-w-[1600px] mx-auto">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="text-xs uppercase tracking-[0.22em] text-sky-300">Arthur International · KART</p><h1 className="text-3xl mt-2">Airport operations</h1><p className="text-sm text-gray-400 mt-2">See the signal. Understand the decision. Verify the outcome.</p></div>
      <div className={`text-xs rounded-full border px-3 py-2 ${wsConnected ? "border-emerald-400/30 text-emerald-300" : "border-amber-400/30 text-amber-300"}`}>{wsConnected ? "Live event stream connected" : "Event stream disconnected · REST reconciliation continues"}</div>
    </header>
    {degraded.length > 0 && <p role="alert" className="border border-amber-400/30 bg-amber-400/5 rounded-xl p-3 text-sm text-amber-200">Unavailable or stale observations: {degraded.join(", ")}. Showing the last successful observations where available.</p>}
    <div className="grid grid-cols-2 xl:grid-cols-4 gap-3" aria-label="Airport indicators">
      {[["Active flights", metric(!!flightLoad.data, activeFlights.length), "Current flight state"], ["Delayed flights", metric(!!flightLoad.data, activeFlights.filter(f => f.delay_minutes > 15).length), "More than 15 min"], ["Peak security wait", waits.length ? `${Math.max(...waits).toFixed(1)} min` : "—", "Observed terminal wait"], ["Active incidents", metric(!!incidentLoad.data, activeIncidents.length), "Includes contained incidents"]].map(([label, value, note]) => <div key={label} className="card"><p className="text-xs text-gray-400">{label}</p><p className="font-mono text-3xl mt-2 text-gray-100">{value}</p><p className="text-[11px] text-gray-500 mt-2">{note}</p></div>)}
    </div>
    <div className="grid xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)] gap-4 items-start">
      <section className="card space-y-5" aria-label="Airport operational map">
        <div className="flex justify-between"><h2 className="text-base">Airfield &amp; terminal pulse</h2><Link to="/ground-ops" className="text-xs text-sky-300">Ground operations →</Link></div>
        <div className="space-y-2">{runways.map(r => <div key={r.runway_id} className="flex gap-3 items-center"><span className="text-[10px] font-mono w-20 text-gray-400">{r.runway_id}</span><div className="flex-1 bg-panel-active rounded border border-panel-border border-dashed h-8 flex items-center justify-center"><span className={`text-xs ${r.status === "closed" ? "text-rose-300" : "text-gray-300"}`}>{r.status} · {r.current_rate ?? "—"}/{r.capacity_per_hour ?? "—"} ops/h</span></div></div>)}{!runways.length && <p className="text-xs text-gray-500">Runway observations unavailable.</p>}</div>
        <div className="border-t border-dashed border-panel-border" />
        <div className="grid sm:grid-cols-3 gap-3">{["A", "B", "C"].map(terminal => {
          const terminalGates = gates.filter(g => (g.terminal || g.gate_id?.[0] || "").replace(/^T-|^Terminal /, "") === terminal);
          const sec = security?.[`terminal_${terminal.toLowerCase()}`] ?? security?.[terminal] ?? security?.[`Terminal ${terminal}`];
          return <div key={terminal} className="bg-panel-active/70 rounded-xl p-3 border border-panel-border/60">
            <div className="flex justify-between items-center"><h3 className="text-sm">Terminal {terminal}</h3><Link to="/passengers" className="text-xs text-sky-300">Flow ↗</Link></div>
            <p className={`text-xs mt-3 ${sec && sec.wait_minutes >= 20 ? "text-amber-300" : "text-gray-400"}`}>{sec ? `${sec.wait_minutes.toFixed(1)} min · ${sec.queue_length} queued · ${sec.lanes_open} lanes` : "Security unavailable"}</p>
            <div className="flex gap-1 flex-wrap mt-3">{terminalGates.map(g => {
              const occupied = !!g.flight_id || activeFlights.some(f => f.gate_id === g.gate_id);
              const unavailable = ["closed", "maintenance", "offline"].includes(g.status);
              return <span key={g.gate_id} title={`${g.gate_id}: ${unavailable ? g.status : occupied ? "occupied" : "available"}`} className={`h-3 w-3 rounded-sm ${unavailable ? "bg-rose-400/70" : occupied ? "bg-sky-400/70" : "bg-gray-600"}`} />;
            })}</div><p className="text-[10px] text-gray-500 mt-2">{terminalGates.length ? `${terminalGates.length} gates observed` : "Gate observations unavailable"}</p>
          </div>;
        })}</div>
        <p className="text-[10px] text-gray-500">Schematic · gates: blue occupied / gray available / red unavailable</p>
        <div className="flex gap-2 items-center overflow-x-auto pb-1"><Link to="/baggage" className="text-xs text-orange-300 shrink-0">Conveyor zones →</Link>{baggage.data?.map(zone => <span key={zone.zone_id} className={`text-[10px] px-2 py-1 border rounded whitespace-nowrap ${zone.utilisation_pct > 90 ? "border-amber-400/40 text-amber-200" : "border-panel-border text-gray-400"}`}>{zone.zone_id} · {zone.items} bags · {zone.utilisation_pct.toFixed(0)}%</span>)}{!baggage.data?.length && <span className="text-xs text-gray-500">No conveyor observations available</span>}</div>
      </section>
      <aside className="space-y-4">
        <section className="card space-y-3"><div className="flex justify-between"><h2 className="text-sm">Active incidents</h2><Link to="/incidents" className="text-xs text-sky-300">Console →</Link></div>
          {activeIncidents.sort((a, b) => (severityOrder[a.severity] ?? 4) - (severityOrder[b.severity] ?? 4)).slice(0, 5).map(i => <Link key={i.id} to={`/decisions?incident_id=${encodeURIComponent(i.id)}`} className="block text-sm border-l-2 border-rose-400 pl-3 py-1 hover:bg-panel"><p>{i.description || i.type.replace(/_/g, " ")}</p><p className="text-[10px] text-gray-500 mt-1">{i.location} · {i.severity} · trace decisions →</p></Link>)}
          {!activeIncidents.length && <p className="text-xs text-gray-500">{incidentLoad.data ? "No active incidents in the latest observation." : "Incident observations unavailable."}</p>}
        </section>
        <section className="card"><ApprovalQueue pendingOnly /></section>
      </aside>
    </div>
    <Link to="/ground-ops" className="card block border-cyan-300/20 hover:bg-panel-active"><p className="text-xs uppercase tracking-widest text-cyan-300">Live operations →</p><p className="text-sm text-gray-400 mt-2">Ground operations, passengers and baggage each offer 3D on/off. 3D is on by default.</p></Link>
    <DecisionWorkspace compact />
    <TeachingRunbook />
  </div>;
}
