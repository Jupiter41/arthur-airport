import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import type { View } from "../pages/Airport3D/model";

const SpatialView = lazy(() => import("../pages/Airport3D/Airport3DPage"));
const paths: Record<View, string> = { airport: "/ground-ops", passengers: "/passengers", baggage: "/baggage", atc: "/atc" };

export function OperationalView({ view, title, children }: { view: View; title: string; children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const enabled = params.get("3d") !== "off";
  return <div className="h-full flex flex-col">
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-panel-border bg-panel/40">
      <h1 className="text-base">{title}</h1>
      <button type="button" role="switch" aria-label="3D view" aria-checked={enabled} onClick={() => {
        const next = new URLSearchParams(params); next.set("3d", enabled ? "off" : "on"); setParams(next, { replace: true });
      }} className="flex items-center gap-3 text-xs text-gray-300">
        <span>{enabled ? "3D on" : "3D off · 2D view"}</span>
        <span aria-hidden="true" className={`w-10 h-6 rounded-full p-1 transition-colors ${enabled ? "bg-cyan-500" : "bg-gray-600"}`}><span className={`block h-4 w-4 bg-white rounded-full transition-transform ${enabled ? "translate-x-4" : ""}`} /></span>
      </button>
    </div>
    <div className="flex-1 min-h-0"><Suspense fallback={<p className="p-6 text-gray-400">Loading operational view…</p>}>{enabled ? <SpatialView view={view} embedded /> : children}</Suspense></div>
  </div>;
}

export function LegacySpatialRedirect() {
  const [params] = useSearchParams();
  const selected = params.get("view");
  const view: View = selected === "passengers" || selected === "baggage" || selected === "atc" ? selected : "airport";
  const next = new URLSearchParams(params); next.delete("view"); next.set("3d", "on");
  return <Navigate replace to={`${paths[view]}?${next}`} />;
}
