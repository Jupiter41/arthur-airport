import { useSearchParams } from "react-router-dom";
import type { Flight } from "../../types";
import { compare } from "../../hooks/useSort";
import { FlightRow } from "./FlightRow";

export function FIDSPanel({ flights, direction, flashIds, onSelect }: { flights: Flight[]; direction: "departure" | "arrival" | "all"; flashIds: Set<string>; onSelect: (f: Flight) => void }) {
  const [params,setParams] = useSearchParams();
  const prefix = direction === "all" ? "" : `${direction}_`;
  const sort = params.get(`${prefix}sort`) ?? "scheduled_time";
  const descending = params.get(`${prefix}order`) === "desc";
  const rawPage = Number(params.get(`${prefix}page`) ?? 0);
  const page = Math.min(Math.max(0,Number.isFinite(rawPage) ? Math.floor(rawPage) : 0),Math.max(0,Math.ceil(flights.length/50)-1));
  const columns = [["flight_number","Flight"],["flight_type","Type"],["destination_iata","Route"],["gate_id","Gate"],["scheduled_time","Scheduled / estimated · UTC"],["status","Status"],["delay_minutes","Delay"]] as const;
  function update(key: string,value: string) { const next=new URLSearchParams(params); next.set(`${prefix}${key}`,value); setParams(next,{replace:true}); }
  function toggle(key:string) { const next=new URLSearchParams(params); next.set(`${prefix}sort`,key); next.set(`${prefix}order`,sort===key&&!descending ? "desc" : "asc"); setParams(next,{replace:true}); }
  const sorted = [...flights].sort((a,b) => compare(a[sort as keyof Flight],b[sort as keyof Flight],descending?"desc":"asc") || a.id.localeCompare(b.id));
  return <section className="min-w-0 space-y-3" aria-label={`${direction} flight board`}>
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm"><h2>{direction === "all" ? "Flight movements" : direction === "departure" ? "Departures" : "Arrivals"} · {flights.length}</h2><span className="text-gray-400">{flashIds.size ? `${flashIds.size} recently updated · sort preserved` : "Live observations · sort preserved"}</span></div>
    <div className="overflow-auto rounded-md border border-panel-border max-h-[65vh]"><table className="w-full min-w-[760px] text-left text-sm"><thead className="sticky top-0 bg-surface-card z-10"><tr>{columns.map(([key,label]) => <th key={key} aria-sort={sort===key ? descending?"descending":"ascending":"none"} className="px-3 py-2 font-medium text-gray-400"><button className="text-left" onClick={()=>toggle(key)}>{label} {sort===key ? descending?"↓":"↑":""}</button></th>)}</tr></thead><tbody>{sorted.slice(page*50,page*50+50).map(f=><FlightRow key={f.id} flight={f} isFlashing={flashIds.has(f.id)} onClick={()=>onSelect(f)}/>)}{!flights.length&&<tr><td colSpan={7} className="p-8 text-center text-gray-400">No flights match these filters.</td></tr>}</tbody></table></div>
    {flights.length>50&&<div className="flex items-center justify-between"><button className="btn-secondary" disabled={page===0} onClick={()=>update("page",String(page-1))}>Previous</button><span className="text-xs text-gray-400">{page*50+1}–{Math.min((page+1)*50,flights.length)} of {flights.length}</span><button className="btn-secondary" disabled={(page+1)*50>=flights.length} onClick={()=>update("page",String(page+1))}>Next</button></div>}
  </section>;
}
