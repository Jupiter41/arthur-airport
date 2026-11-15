import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Dialog } from "./Dialog";
import { availableDestinations } from "./navigation";
import { flightsApi, incidentsApi, baggageApi } from "../hooks/useApi";
import type { Flight, Incident } from "../types";

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const [search, setSearch] = useState("");
  const [lookup, setLookup] = useState("");
  const flights = useQuery({ queryKey: ["search", "flights"], queryFn: () => flightsApi.list({ limit: "500" }), staleTime: 30_000 });
  const incidents = useQuery({ queryKey: ["search", "incidents"], queryFn: () => incidentsApi.list({ limit: "100" }), staleTime: 15_000 });
  const bags = useQuery({ queryKey: ["search", "baggage", lookup], queryFn: () => baggageApi.search(lookup), enabled: !!lookup, retry: false });
  const q = search.toLowerCase().trim();
  const bagData = bags.data && typeof bags.data === "object" ? bags.data as Record<string, unknown> : {};
  const bagItems = (Array.isArray(bags.data) ? bags.data : bagData.items ?? bagData.baggage ?? bagData.results ?? []) as Array<{ id: string; tag?: string }>;
  return <Dialog title="Search airport" onClose={onClose}>
    <label className="block text-sm mb-2" htmlFor="airport-search">Pages, flight numbers, gates or incidents</label>
    <input id="airport-search" autoFocus className="w-full" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search or enter a baggage tag" />
    <div className="mt-4 max-h-[50vh] overflow-y-auto space-y-4">
      <section><h3 className="text-xs text-gray-400 mb-2">Pages</h3>{availableDestinations.filter(d => `${d.label} ${d.group}`.toLowerCase().includes(q)).map(d => <Link key={d.path} onClick={onClose} className="search-result" to={d.path}>{d.label}<span className="text-xs text-gray-400">{d.workspace}</span></Link>)}</section>
      {q && <section><h3 className="text-xs text-gray-400 mb-2">Flights · up to 500 observed records</h3>{(flights.data?.flights as Flight[] | undefined)?.filter(f => `${f.flight_number} ${f.gate_id ?? ""} ${f.id}`.toLowerCase().includes(q)).slice(0, 15).map(f => <Link key={f.id} onClick={onClose} className="search-result" to={`/flights?flight=${encodeURIComponent(f.id)}`}>{f.flight_number}<span>{f.gate_id ?? "Unassigned"} · {f.status}</span></Link>)}{flights.isError && <p className="text-amber-300 text-sm">Flight search unavailable.</p>}</section>}
      {q && <section><h3 className="text-xs text-gray-400 mb-2">Incidents · up to 100 observed records</h3>{(incidents.data?.incidents as Incident[] | undefined)?.filter(i => `${i.id} ${i.title} ${i.description} ${i.location}`.toLowerCase().includes(q)).slice(0, 10).map(i => <Link key={i.id} onClick={onClose} className="search-result" to={`/incidents?incident=${encodeURIComponent(i.id)}`}>{i.title || i.type.replace(/_/g, " ")}<span>{i.location}</span></Link>)}{incidents.isError && <p className="text-amber-300 text-sm">Incident search unavailable.</p>}</section>}
      {q && <section className="space-y-2"><Link className="search-result" onClick={onClose} to={`/decisions?q=${encodeURIComponent(search)}`}>Search all decision history →</Link><button className="btn-secondary" onClick={() => setLookup(search)}>Look up baggage tag / PNR</button>{bags.isFetching && <p>Looking up baggage…</p>}{bags.isError && <p role="alert">Baggage lookup unavailable.</p>}{lookup && bags.isSuccess && !bagItems.length && <p>No matching baggage records.</p>}{Array.isArray(bagItems) && bagItems.map(b => <Link key={b.id} onClick={onClose} className="search-result" to={`/baggage?bag=${encodeURIComponent(b.id)}`}>{b.tag ?? b.id}</Link>)}</section>}
    </div>
  </Dialog>;
}

