import { useState } from "react";
import type { Flight } from "../../types";
import { StatusBadge } from "../../components/StatusBadge";
import { flightsApi } from "../../hooks/useApi";
import { queryClient } from "../../queryClient";
import { formatTime } from "./helpers";

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-400 font-medium">{label}</div>
      <div className="text-gray-100">{value}</div>
    </div>
  );
}

// Mirrors the flight-service REST guards (routers/flights.py): hold is only
// accepted before/at a decision point; release only unwinds a held (delayed)
// flight. We surface the button that the backend will actually accept.
const HOLDABLE_STATUSES = new Set(["scheduled", "boarding", "approach"]);

const HOLD_REASONS = [
  "gate_conflict",
  "crew_readiness",
  "ctot_slot",
  "connecting_pax",
  "equipment_failure",
] as const;

function FlightActions({ flight }: { flight: Flight }) {
  const [reason, setReason] = useState<string>(HOLD_REASONS[0]);
  const [duration, setDuration] = useState<number>(15);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const canHold = HOLDABLE_STATUSES.has(flight.status);
  const canRelease = flight.status === "delayed";

  if (!canHold && !canRelease) return null;

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["flights"] });

  const run = async (fn: () => Promise<unknown>, label: string) => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await fn();
      await refresh();
      setDone(label);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-gray-700 pt-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Operator Actions
      </h3>

      {canHold && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <select
              aria-label="Hold reason"
              className="flex-1 bg-gray-700 text-gray-100 text-sm rounded px-2 py-1 border border-gray-600"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={busy}
            >
              {HOLD_REASONS.map((r) => (
                <option key={r} value={r}>
                  {r.replace(/_/g, " ")}
                </option>
              ))}
            </select>
            <input
              aria-label="Hold duration (minutes)"
              type="number"
              min={1}
              max={240}
              className="w-20 bg-gray-700 text-gray-100 text-sm rounded px-2 py-1 border border-gray-600"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              disabled={busy}
            />
            <span className="self-center text-xs text-gray-400">min</span>
          </div>
          <button
            className="w-full text-sm font-bold px-3 py-2 rounded bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
            disabled={busy || duration < 1}
            onClick={() =>
              run(
                () => flightsApi.hold(flight.id, reason, duration),
                `Held ${flight.flight_number} (${duration} min)`,
              )
            }
          >
            {busy ? "…" : "Hold flight"}
          </button>
        </div>
      )}

      {canRelease && (
        <button
          className="w-full text-sm font-bold px-3 py-2 rounded bg-green-600 text-white hover:bg-green-500 disabled:opacity-50"
          disabled={busy}
          onClick={() =>
            run(
              () => flightsApi.release(flight.id),
              `Released ${flight.flight_number}`,
            )
          }
        >
          {busy ? "…" : "Release hold"}
        </button>
      )}

      {done && <div className="text-xs text-green-400 mt-2">✓ {done}</div>}
      {error && <div className="text-xs text-red-400 mt-2">{error}</div>}
    </div>
  );
}

export function FlightDetailDrawer({
  flight,
  onClose,
}: {
  flight: Flight;
  onClose: () => void;
}) {
  return (
    <div className="fixed right-0 top-0 h-full w-[400px] bg-gray-800 border-l border-gray-700 shadow-2xl z-50 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Flight details">
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <h2 className="text-lg font-bold text-white">{flight.flight_number}</h2>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white text-xl"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Info label="Airline" value={flight.airline_code} />
          <Info label="Aircraft" value={flight.aircraft_type} />
          <Info label="Registration" value={flight.registration} />
          <Info label="Flight Type" value={flight.flight_type ?? "—"} />
          <Info label="Route" value={flight.route_category ?? "—"} />
          <Info label="Direction" value={flight.direction} />
          <Info label="Origin" value={flight.origin_iata} />
          <Info label="Destination" value={flight.destination_iata} />
          <Info label="Gate" value={flight.gate_id ?? "Unassigned"} />
          <Info label="Runway" value={flight.runway_id ?? "—"} />
          <Info label="Terminal" value={flight.terminal} />
          <Info
            label="Delay"
            value={
              flight.delay_minutes > 0 ? `+${flight.delay_minutes} min` : "None"
            }
          />
        </div>

        <div>
          <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Status
          </h3>
          <StatusBadge
            status={flight.status}
            delay={flight.delay_minutes}
            direction={flight.direction}
            className="text-sm"
          />
        </div>

        <div>
          <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            Passengers
          </h3>
          <div className="flex items-center gap-3">
            <div className="w-full bg-gray-700 rounded-full h-3">
              <div
                className="bg-blue-500 h-3 rounded-full transition-all"
                style={{
                  width: `${flight.pax_count > 0 ? Math.round((flight.pax_boarded / flight.pax_count) * 100) : 0}%`,
                }}
              />
            </div>
            <span className="text-sm text-gray-300 whitespace-nowrap">
              {flight.pax_boarded} / {flight.pax_count}
            </span>
          </div>
        </div>

        <div>
          <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
            {flight.direction === "arrival" ? "Baggage Claimed" : "Baggage"}
          </h3>
          <div className="flex items-center gap-3">
            <div className="w-full bg-gray-700 rounded-full h-3">
              <div
                className="bg-teal-500 h-3 rounded-full transition-all"
                style={{
                  width: `${flight.baggage_count > 0 ? Math.round((flight.baggage_loaded / flight.baggage_count) * 100) : 0}%`,
                }}
              />
            </div>
            <span className="text-sm text-gray-300 whitespace-nowrap">
              {flight.baggage_loaded} / {flight.baggage_count}
            </span>
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <h3 className="text-xs text-gray-400 uppercase tracking-wide">
            Schedule
          </h3>
        </div>
        <div className="text-sm space-y-1 text-gray-300">
          <div>
            Scheduled:{" "}
            <span className="font-mono">
              {formatTime(flight.scheduled_time)}
            </span>
          </div>
          {flight.estimated_time &&
            formatTime(flight.estimated_time) !==
              formatTime(flight.scheduled_time) && (
              <div>
                Estimated:{" "}
                <span className="font-mono text-amber-400">
                  {formatTime(flight.estimated_time)}
                </span>
              </div>
            )}
          {flight.actual_time && (
            <div>
              Actual:{" "}
              <span className="font-mono text-green-400">
                {formatTime(flight.actual_time)}
              </span>
            </div>
          )}
          {flight.direction === "departure" &&
            flight.arrival_estimated_time && (
              <div>
                Arrival ETA:{" "}
                <span className="font-mono text-blue-400">
                  {formatTime(flight.arrival_estimated_time)}
                </span>
                {flight.status === "arrived" && (
                  <span className="ml-2 text-green-400 text-xs">✓ Arrived</span>
                )}
              </div>
            )}
          {flight.flight_duration_minutes != null &&
            flight.flight_duration_minutes > 0 && (
              <div>
                Flight duration:{" "}
                <span className="font-mono text-gray-400">
                  {Math.floor(flight.flight_duration_minutes / 60)}h{" "}
                  {flight.flight_duration_minutes % 60}m
                </span>
              </div>
            )}
        </div>

        <FlightActions flight={flight} />
      </div>
    </div>
  );
}
