import { lazy, Suspense, type ReactNode } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import type { View } from "../pages/Airport3D/model";
import { SchematicMap } from "./SchematicMap";

const SpatialView = lazy(() => import("../pages/Airport3D/Airport3DPage"));
const paths: Record<View, string> = {
  airport: "/ground-ops",
  passengers: "/passengers",
  baggage: "/baggage",
  atc: "/atc",
};
export function OperationalView({
  view,
  title,
  children,
}: {
  view: View;
  title: string;
  children: ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const raw = params.get("mode");
  const mode =
    raw === "map" || raw === "3d"
      ? raw
      : params.get("3d") === "on" && raw !== "board"
        ? "3d"
        : "board";
  const family =
    view === "airport" || view === "atc"
      ? [
          ["/ground-ops", "Ground operations"],
          ["/atc", "Air traffic control"],
        ]
      : [
          ["/passengers", "Passengers"],
          ["/baggage", "Baggage"],
          ["/accessibility", "Special assistance"],
        ];
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    next.set(key, value);
    if (key === "mode") next.delete("3d");
    if (key === "terminal") {
      next.delete("entity");
      next.delete("decision");
      next.delete("offset");
    }
    setParams(next);
  }
  return (
    <div className="space-y-4">
      <header className="px-4 md:px-6 pt-5 space-y-4">
        <div className="flex flex-wrap justify-between gap-3 items-center">
          <div>
            <p className="section-label">
              {view === "airport" || view === "atc" ? "Airfield" : "Terminal"}
            </p>
            <h1>{title}</h1>
          </div>
          {view !== "airport" && view !== "atc" && (
            <label className="text-sm">
              Terminal{" "}
              <select
                aria-label="Terminal scope"
                value={params.get("terminal") ?? "all"}
                onChange={(e) => change("terminal", e.target.value)}
              >
                <option value="all">All terminals</option>
                {["A", "B", "C"].map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        <nav aria-label="Operational area" className="flex flex-wrap gap-2">
          {family.map(([path, label]) => (
            <Link
              key={path}
              className="text-sm px-3 py-2 rounded-md bg-panel text-gray-300"
              to={`${path}?terminal=${encodeURIComponent(params.get("terminal") ?? "all")}`}
            >
              {label}
            </Link>
          ))}
        </nav>
        <div
          className="flex border-b border-panel-border"
          aria-label="Representation"
        >
          {(["board", "map", "3d"] as const).map((value) => (
            <button
              key={value}
              className="view-tab"
              aria-pressed={mode === value}
              onClick={() => change("mode", value)}
            >
              {value === "3d" ? "3D" : value === "map" ? "Map" : "Board"}
            </button>
          ))}
        </div>
      </header>
      {mode === "map" && <SchematicMap view={view} />}
      {mode === "3d" &&
      (view === "passengers" || view === "baggage") &&
      !["A", "B", "C"].includes(params.get("terminal") ?? "") ? (
        <p className="card mx-6">
          Choose a terminal above to open its 3D view. All-terminal records
          remain available below.
        </p>
      ) : (
        mode === "3d" && (
          <Suspense fallback={<p className="p-6">Loading spatial view…</p>}>
            <SpatialView view={view} embedded />
          </Suspense>
        )
      )}
      {mode !== "board" && (
        <p className="px-6 text-sm text-gray-400">
          Operational records and actions · same terminal scope
        </p>
      )}
      <div>{children}</div>
    </div>
  );
}
export function LegacySpatialRedirect() {
  const [params] = useSearchParams();
  const selected = params.get("view");
  const view: View =
    selected === "passengers" || selected === "baggage" || selected === "atc"
      ? selected
      : "airport";
  const next = new URLSearchParams(params);
  next.delete("view");
  next.set("3d", "on");
  return <Navigate replace to={`${paths[view]}?${next}`} />;
}
