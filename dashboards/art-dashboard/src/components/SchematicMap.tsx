import { useSearchParams } from "react-router-dom";
import { useSceneData } from "../pages/Airport3D/useSceneData";
import {
  entities,
  parseSimSeconds,
  type View,
  type Terminal,
  type Point,
} from "../pages/Airport3D/model";
import { useSimStore } from "../stores/simStore";

export function SchematicMap({ view }: { view: View }) {
  const [params, setParams] = useSearchParams();
  const { data, unavailable, loading } = useSceneData(view);
  const time = useSimStore((s) => s.status.sim_time);
  const terminals: Terminal[] = ["A", "B", "C"];
  const scope = params.get("terminal");
  const selectedTerminals = terminals.includes(scope as Terminal)
    ? [scope as Terminal]
    : terminals;
  const all = selectedTerminals.flatMap((terminal, index) =>
    entities(
      data,
      { view, terminal, quality: "low" },
      parseSimSeconds(time) ?? 0,
    ).map((row) => ({
      ...row,
      position: [
        row.position[0] +
          ((view === "passengers" || view === "baggage") &&
          selectedTerminals.length > 1
            ? index * 250
            : 0),
        row.position[1],
        row.position[2],
      ] as Point,
    })),
  );
  const rows = [...new Map(all.map((row) => [row.id, row])).values()];
  const layer = params.get("layer") ?? "all";
  const needed =
    view === "airport"
      ? ["Flights", "Gates", "Runways", "Vehicles"]
      : view === "atc"
        ? ["Flights", "Runways", "Runway queue"]
        : view === "passengers"
          ? ["Passengers", "Passenger zones"]
          : ["Baggage"];
  const degraded = unavailable.filter((name) => needed.includes(name));
  const located = rows.filter(
    (row) =>
      row.positionAvailable !== false &&
      (layer === "all" ||
        row.kind === layer ||
        row.id === params.get("entity")),
  );
  const xs = located.map((r) => r.position[0]),
    ys = located.map((r) => r.position[2]);
  const minX = Math.min(0, ...xs),
    maxX = Math.max(1, ...xs),
    minY = Math.min(0, ...ys),
    maxY = Math.max(1, ...ys);
  const selected = rows.find((r) => r.id === params.get("entity"));
  function select(id: string) {
    const next = new URLSearchParams(params);
    next.set("entity", id);
    setParams(next, { replace: true });
  }
  return (
    <section
      className="mx-4 md:mx-6 card space-y-4"
      aria-label="Airport schematic"
    >
      <div className="flex flex-wrap justify-between gap-3">
        <h2>Operational map</h2>
        {(view === "airport" || view === "atc") && (
          <label className="text-sm">
            Layer{" "}
            <select
              value={layer}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                next.set("layer", e.target.value);
                setParams(next, { replace: true });
              }}
            >
              <option value="all">All entities</option>
              <option value="flight">Aircraft</option>
              <option value="gate">Gates</option>
              <option value="runway">Runways</option>
              <option value="vehicle">Ground fleet</option>
            </select>
          </label>
        )}
        <span className="text-xs text-gray-400">
          Schematic geometry · simulated owner observations
        </span>
      </div>
      {degraded.length > 0 && (
        <p role="status" className="text-amber-300 text-sm">
          Some observations unavailable: {degraded.join(", ")}. Last available
          records may be shown.
        </p>
      )}
      <div className="grid xl:grid-cols-[minmax(0,1fr)_280px] gap-4">
        <svg
          role="img"
          aria-label="Schematic entity positions; use the entity list to select with a keyboard"
          viewBox="0 0 900 420"
          className="w-full min-h-64 bg-panel-active rounded-md"
        >
          <defs>
            <pattern
              id="map-grid"
              width="30"
              height="30"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M30 0H0V30"
                fill="none"
                stroke="currentColor"
                opacity=".08"
              />
            </pattern>
          </defs>
          <rect width="900" height="420" fill="url(#map-grid)" />
          {located.map((row) => {
            const x = 60 + ((row.position[0] - minX) / (maxX - minX)) * 760,
              y = 40 + ((row.position[2] - minY) / (maxY - minY)) * 320;
            return (
              <g
                key={row.id}
                onClick={() => select(row.id)}
                className="cursor-pointer"
              >
                <title>
                  {row.label}: {row.status}
                </title>
                <rect
                  x={x - 7}
                  y={y - 7}
                  width="14"
                  height="14"
                  rx="2"
                  fill={
                    selected?.id === row.id
                      ? "#7dbeff"
                      : /closed|offline|frozen/.test(row.status)
                        ? "#fb7185"
                        : "#8097aa"
                  }
                />
                <text x={x + 11} y={y + 4} fontSize="11" fill="currentColor">
                  {row.label}
                </text>
              </g>
            );
          })}
          {!located.length && (
            <text x="40" y="200" fill="currentColor">
              {loading
                ? "Loading observations…"
                : "No located entities available"}
            </text>
          )}
        </svg>
        <aside className="space-y-3">
          <h3>{selected?.label ?? "Select an entity"}</h3>
          {selected && (
            <>
              <p className="text-sm text-gray-300">{selected.status}</p>
              <dl className="space-y-2">
                {selected.facts.map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs text-gray-400">{label}</dt>
                    <dd className="text-sm break-words">{value}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          <label className="block text-xs text-gray-400" htmlFor="map-entity">
            Observed entities · {rows.length}
          </label>
          <select
            id="map-entity"
            className="w-full"
            value={selected?.id ?? ""}
            onChange={(e) => select(e.target.value)}
          >
            <option value="">Select entity</option>
            {rows.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label} · {row.status}
              </option>
            ))}
          </select>
        </aside>
      </div>
      <p className="text-xs text-gray-400">
        Gray: observed entity · blue: selected · red: closed/offline/frozen.
        Full records and actions follow below.
      </p>
    </section>
  );
}
