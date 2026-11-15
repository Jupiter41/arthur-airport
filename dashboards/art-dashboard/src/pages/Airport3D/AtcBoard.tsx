import { Link, useSearchParams } from "react-router-dom";
import { useMemo, type ReactNode } from "react";
import { useSimStore } from "../../stores/simStore";
import { atcPicture, clockText, type RunwayQueueEntry } from "./atc";
import {
  buildLayout,
  flightPose,
  holdingOrder,
  parseSimSeconds,
  type SceneData,
} from "./model";
import { useSceneData } from "./useSceneData";
import type { Flight } from "../../types";

const hhmmss = (iso: string | null | undefined) =>
  iso ? iso.replace(/\.\d+/, "").slice(11, 19) : "—";

function Section({
  title,
  count,
  children,
  note,
}: {
  title: string;
  count?: number;
  children: ReactNode;
  note?: string;
}) {
  return (
    <section className="card space-y-2 min-w-0" aria-label={title}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs uppercase tracking-[0.18em] text-cyan-300">
          {title}
        </h3>
        {count !== undefined && (
          <span className="text-[10px] font-mono text-gray-500">{count}</span>
        )}
      </div>
      {children}
      {note && <p className="text-[10px] text-gray-500">{note}</p>}
    </section>
  );
}
const Empty = ({ children }: { children: ReactNode }) => (
  <p className="text-xs text-gray-500">{children}</p>
);

export function AtcBoard({
  data,
  seconds,
  selectedId,
  onSelect,
}: {
  data: SceneData;
  seconds: number;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}) {
  const picture = useMemo(() => {
    const layout = buildLayout(data);
    const holding = holdingOrder(data.flights);
    return atcPicture(data.flights, data.runways, layout, seconds, (f) =>
      flightPose(f, data, seconds, layout, holding),
    );
  }, [data, seconds]);
  const byId = useMemo(
    () => new Map(data.flights.map((f) => [f.id, f])),
    [data.flights],
  );
  const callsign = (flight: Flight | undefined, fallback = "—") => {
    if (!flight)
      return <span className="font-mono text-gray-400">{fallback}</span>;
    return (
      <button
        type="button"
        onClick={() => onSelect?.(flight.id)}
        aria-pressed={selectedId === flight.id}
        className={`font-mono text-left hover:text-cyan-200 ${selectedId === flight.id ? "text-cyan-200 underline" : "text-gray-100"}`}
      >
        {flight.flight_number}
      </button>
    );
  };
  const q = data.runwayQueue;
  const queueRows = (rows: RunwayQueueEntry[]) =>
    rows.length ? (
      <ol className="space-y-1">
        {rows.slice(0, 12).map((row) => (
          <li
            key={row.flight_id}
            className="grid grid-cols-[1.5rem_1fr_auto_auto] gap-2 text-xs items-center"
          >
            <span className="font-mono text-gray-500">{row.position}</span>
            <span className="truncate">
              {callsign(byId.get(row.flight_id), row.flight_id.slice(0, 8))}{" "}
              <span className="text-gray-500">
                {row.aircraft_type} · {row.weight_category}
              </span>
              {row.emergency && (
                <span className="ml-1 text-red-300">EMERG</span>
              )}
            </span>
            <span className="font-mono text-gray-400">
              {hhmmss(row.estimated_time)}
            </span>
            <span
              className="font-mono text-amber-200"
              title="Owner minimum wake separation behind the preceding movement"
            >
              {row.wake_separation_seconds === null
                ? "—"
                : `+${clockText(row.wake_separation_seconds)}`}
            </span>
          </li>
        ))}
      </ol>
    ) : (
      <Empty>Queue empty.</Empty>
    );

  return (
    <div className="space-y-4" data-testid="atc-board">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          [
            "Weather",
            q
              ? `${q.weather_category}${q.ils_required ? " · ILS req." : ""}`
              : "—",
          ],
          ["Arrival rate", q ? `${q.arrival_rate}/h` : "—"],
          ["Departure rate", q ? `${q.departure_rate}/h` : "—"],
          [
            "Movements last 60 min",
            q ? `${q.current_rate} / ${q.capacity_per_hour}` : "—",
          ],
          [
            "Runway occupancy (ROT)",
            q
              ? q.runway_occupied
                ? `Blocked to ${hhmmss(q.runway_free_at)}`
                : "Free"
              : "—",
          ],
        ].map(([title, value]) => (
          <div key={title} className="card">
            <p className="text-[10px] text-gray-400">{title}</p>
            <p className="text-sm font-mono text-cyan-100 mt-1">{value}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2" aria-label="Runway strips">
        {picture.strips.map((strip) => (
          <div
            key={strip.key}
            className={`card border ${strip.occupant ? "border-amber-400/40" : "border-panel-border"}`}
          >
            <div className="flex justify-between items-baseline">
              <p className="font-mono text-sm text-gray-100">
                RWY {strip.ends.map((e) => e.runway_id).join(" / ")}
              </p>
              <p
                className={`text-[10px] uppercase ${strip.occupant ? "text-amber-300" : "text-emerald-300"}`}
              >
                {strip.occupant ? "Occupied" : "Clear"}
              </p>
            </div>
            <p className="text-[11px] text-gray-400 mt-1">
              {strip.ends
                .map(
                  (e) =>
                    `${e.runway_id} ${e.status}${(e as typeof e & { current_use?: string }).current_use ? ` · ${(e as typeof e & { current_use?: string }).current_use}` : ""}`,
                )
                .join(" | ")}
            </p>
            <p className="text-xs mt-2">
              {strip.occupant ? (
                <>
                  {callsign(strip.occupant.flight)}{" "}
                  <span className="text-amber-200">{strip.occupant.phase}</span>
                </>
              ) : (
                <span className="text-gray-500">
                  No aircraft in a runway phase
                </span>
              )}
            </p>
            {strip.shortFinal && (
              <p className="text-xs mt-1">
                Short final: {callsign(strip.shortFinal.flight)}{" "}
                <span className="font-mono text-cyan-200">
                  {clockText(strip.shortFinal.seconds)}
                </span>
              </p>
            )}
            <p className="text-[10px] text-gray-500 mt-2">
              Owner queue depth · arr {strip.ends[0]?.arrivals_queued ?? 0} ·
              dep {strip.ends[0]?.departures_queued ?? 0}
            </p>
          </div>
        ))}
        {!picture.strips.length && <Empty>No runway observations.</Empty>}
      </div>
      <div className="grid gap-3 xl:grid-cols-3 md:grid-cols-2">
        <Section
          title="Final approach sequence"
          count={picture.arrivals.length}
          note="Touchdown at owner ETA. Spacing = difference between consecutive ETAs on the same strip."
        >
          {picture.arrivals.length ? (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] text-gray-500 text-left">
                  <th className="font-normal">Flight</th>
                  <th className="font-normal">RWY</th>
                  <th className="font-normal text-right">To touchdown</th>
                  <th className="font-normal text-right">Spacing</th>
                </tr>
              </thead>
              <tbody>
                {picture.arrivals.map((row) => (
                  <tr key={row.flight.id}>
                    <td>
                      {callsign(row.flight)}{" "}
                      <span className="text-gray-500">
                        {row.flight.aircraft_type}
                      </span>
                    </td>
                    <td className="font-mono text-gray-300">{row.runway}</td>
                    <td className="font-mono text-right text-cyan-100">
                      {clockText(row.secondsToTouchdown)}
                    </td>
                    <td className="font-mono text-right text-gray-400">
                      {row.spacingSeconds === null
                        ? "—"
                        : clockText(row.spacingSeconds)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No arrivals on approach.</Empty>
          )}
        </Section>
        <Section
          title="Holding stack"
          count={picture.holding.length}
          note="Arrivals the owner moved from approach to delayed (runway unavailable). Fix is schematic."
        >
          {picture.holding.length ? (
            <ol className="space-y-1">
              {picture.holding.map((row, i) => (
                <li
                  key={row.flight.id}
                  className="text-xs flex justify-between gap-2"
                >
                  <span>
                    {i + 1}. {callsign(row.flight)}{" "}
                    <span className="text-gray-500">
                      {row.flight.aircraft_type}
                    </span>
                  </span>
                  <span className="text-amber-200">{row.detail}</span>
                </li>
              ))}
            </ol>
          ) : (
            <Empty>No aircraft holding.</Empty>
          )}
        </Section>
        <Section
          title="Owner runway sequence"
          note="Airport-wide queues in owner priority order (emergency, then ETA). A runway is assigned when the owner grants the slot."
        >
          {q ? (
            <div className="grid grid-cols-1 gap-3">
              <div>
                <p className="text-[10px] text-gray-400 mb-1">
                  Arrivals awaiting slot · {q.arrivals.length}
                </p>
                {queueRows(q.arrivals)}
              </div>
              <div>
                <p className="text-[10px] text-gray-400 mb-1">
                  Departures awaiting slot · {q.departures.length}
                </p>
                {queueRows(q.departures)}
              </div>
            </div>
          ) : (
            <Empty>Runway queue unavailable.</Empty>
          )}
        </Section>
        <Section
          title="Ground movements"
          count={picture.groundIn.length + picture.departing.length}
        >
          {picture.groundIn.length + picture.departing.length ? (
            <ul className="space-y-1">
              {[...picture.groundIn, ...picture.departing].map((row) => (
                <li key={row.flight.id} className="text-xs">
                  <div className="flex justify-between gap-2">
                    <span>
                      {callsign(row.flight)}{" "}
                      <span className="text-gray-500">
                        {row.flight.direction === "arrival" ? "IN" : "OUT"} ·{" "}
                        {row.flight.gate_id || "—"}
                      </span>
                    </span>
                    <span className="text-cyan-200">{row.phase}</span>
                  </div>
                  <p className="text-[10px] text-gray-500 truncate">
                    {row.detail}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No aircraft rolling, taxiing or departing.</Empty>
          )}
        </Section>
        <Section
          title="Departures at gate"
          count={picture.boarding.length}
          note="The owner releases a departure at its estimated time once 95 % have boarded (lower thresholds after long delays)."
        >
          {picture.boarding.length ? (
            <ul className="space-y-1">
              {picture.boarding.slice(0, 14).map((row) => (
                <li
                  key={row.flight.id}
                  className="text-xs grid grid-cols-[1fr_auto_auto] gap-2"
                >
                  <span className="truncate">
                    {callsign(row.flight)}{" "}
                    <span className="text-gray-500">
                      {row.flight.gate_id || "—"} · {row.flight.status}
                    </span>
                  </span>
                  <span
                    className={`font-mono ${row.ready ? "text-emerald-300" : "text-gray-400"}`}
                  >
                    {Math.round(row.boardedPct * 100)}%
                    {row.ready ? " READY" : ""}
                  </span>
                  <span className="font-mono text-gray-300">
                    {clockText(row.secondsToOffBlock)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No departures boarding.</Empty>
          )}
        </Section>
        <Section title="Clearances">
          <p className="text-xs text-gray-400">
            The flight owner does not model ATC clearances, radar separation or
            runway crossings, so this view is read-only and issues no
            instructions. Operator holds and releases remain on the flight
            board.
          </p>
        </Section>
      </div>
    </div>
  );
}

/** 2D traffic board for `/atc?3d=off`. */
export default function AtcTrafficPage() {
  const [params, setParams] = useSearchParams();
  const select = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("entity", id);
    setParams(next, { replace: true });
  };
  const { data, unavailable } = useSceneData("atc");
  const clock = useSimStore((s) => s.status);
  const seconds = parseSimSeconds(clock.sim_time) ?? 0;
  const degraded = unavailable.filter((name) =>
    ["Flights", "Runways", "Runway queue"].includes(name),
  );
  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 space-y-4 max-w-[1900px] mx-auto">
      <p className="text-xs font-mono text-slate-400">
        SIM {clock.sim_time.replace("T", " ").replace(/\.\d+Z?$/, "")}
        {clock.paused ? " · PAUSED" : ""}
      </p>
      {degraded.length > 0 && (
        <p
          role="alert"
          className="rounded-xl border border-amber-400/30 bg-amber-400/5 p-3 text-xs text-amber-200"
        >
          Unavailable or stale: {degraded.join(", ")}.
        </p>
      )}
      {params.get("entity") &&
        data.flights.some((f) => f.id === params.get("entity")) && (
          <Link
            className="text-accent"
            to={`/flights?flight=${encodeURIComponent(params.get("entity")!)}`}
          >
            Inspect selected flight →
          </Link>
        )}
      <AtcBoard
        data={data}
        seconds={seconds}
        selectedId={params.get("entity")}
        onSelect={select}
      />
    </div>
  );
}
