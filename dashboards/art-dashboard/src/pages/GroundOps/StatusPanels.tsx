import { StatusBadge } from "../../components/StatusBadge";
import type { Flight, Runway, Incident } from "../../types";

/* ──────── Holding Stack ──────── */
export function HoldingStackPanel({ flights }: { flights: Flight[] }) {
  const holding = flights.filter((f) => f.status === "approach");

  if (holding.length === 0) return null;

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Holding Stack ({holding.length})
      </h3>
      <div className="space-y-1">
        {holding.slice(0, 8).map((f) => (
          <div
            key={f.id}
            className="flex items-center justify-between text-sm bg-gray-700 rounded px-2 py-1"
          >
            <span className="font-bold text-white">{f.flight_number}</span>
            <span className="text-xs text-gray-400">
              {f.delay_minutes > 0 ? `+${f.delay_minutes}min` : "on time"}
            </span>
            <StatusBadge status={f.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Ground Stop Panel ──────── */
export function GroundStopPanel({ incidents }: { incidents: Incident[] }) {
  const groundStop = incidents.some(
    (i) => i.type === "runway_incursion" && i.status !== "resolved",
  );

  return (
    <div
      className={`rounded p-3 ${groundStop ? "bg-red-900/50 border border-red-700" : "bg-gray-800"}`}
    >
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-1">
        Ground Stop
      </h3>
      {groundStop ? (
        <div className="text-sm text-red-400 font-bold animate-pulse">
          ⛔ GROUND STOP — Departures suspended
        </div>
      ) : (
        <div className="text-sm text-green-400">NORMAL — Departures active</div>
      )}
    </div>
  );
}

/* ──────── Runway Queue Panel ──────── */
export function RunwayQueuePanel({
  runways,
  flights,
}: {
  runways: Runway[];
  flights: Flight[];
}) {
  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Runway Queues
      </h3>
      <div className="space-y-2">
        {runways.map((rw) => {
          const queued = flights.filter(
            (f) =>
              f.runway_id === rw.runway_id &&
              ["taxiing", "departed"].includes(f.status),
          );
          return (
            <div key={rw.runway_id} className="text-xs">
              <span className="font-mono font-bold text-white">
                {rw.runway_id}
              </span>
              <span className="text-gray-400 ml-2">
                Arr: {rw.arrivals_queued} · Dep: {rw.departures_queued}
              </span>
              {queued.length > 0 && (
                <span className="text-gray-400 ml-2">
                  {queued.map((f) => f.flight_number).join(" · ")}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
