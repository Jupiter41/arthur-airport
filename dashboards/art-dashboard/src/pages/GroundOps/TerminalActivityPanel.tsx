import { useMemo } from "react";
import { StatusBadge } from "../../components/StatusBadge";
import type { Flight, Gate } from "../../types";

export function TerminalActivityPanel({
  terminals,
  gates,
  flights,
}: {
  terminals: string[];
  gates: Gate[];
  flights: Flight[];
}) {
  const flightByGate = useMemo(() => {
    const m: Record<string, Flight> = {};
    for (const f of flights) {
      if (f.gate_id) m[f.gate_id] = f;
    }
    return m;
  }, [flights]);

  return (
    <div className="bg-gray-900 rounded-lg p-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Terminal Activity — Flight / Passenger / Baggage
      </h3>
      <div className="grid grid-cols-3 gap-4">
        {terminals.map((term) => {
          const termGates = gates
            .filter((g) => {
              const raw = g.terminal || g.gate_id.charAt(0);
              return raw.replace(/^T-/, "") === term;
            })
            .filter(
              (g) =>
                g.status === "occupied" ||
                g.status === "boarding" ||
                g.status === "departing",
            );
          return (
            <div key={term} className="bg-gray-800 rounded p-3">
              <div className="text-sm font-bold text-white mb-2">
                Terminal {term}
                <span className="text-xs text-gray-400 ml-2">
                  {termGates.length} active gate
                  {termGates.length !== 1 ? "s" : ""}
                </span>
              </div>
              {termGates.length === 0 ? (
                <div className="text-xs text-gray-400">No active flights</div>
              ) : (
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {termGates.map((g) => {
                    const flight = flightByGate[g.gate_id];
                    if (!flight) return null;
                    const paxPct =
                      flight.pax_count > 0
                        ? Math.round(
                            (flight.pax_boarded / flight.pax_count) * 100,
                          )
                        : 0;
                    const bagPct =
                      flight.baggage_count > 0
                        ? Math.round(
                            (flight.baggage_loaded / flight.baggage_count) *
                              100,
                          )
                        : 0;
                    return (
                      <div
                        key={g.gate_id}
                        className="bg-gray-700 rounded p-2 text-xs"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono font-bold text-white">
                            {g.gate_id}
                          </span>
                          <span className="text-cyan-400 font-semibold">
                            {flight.flight_number}
                          </span>
                          <StatusBadge status={flight.status} />
                        </div>
                        <div className="text-gray-400 text-[10px] mb-1">
                          {flight.direction === "departure" ? "→" : "←"}{" "}
                          {flight.direction === "departure"
                            ? flight.destination_iata
                            : flight.origin_iata}{" "}
                          · {flight.aircraft_type}
                          {flight.delay_minutes > 0 && (
                            <span className="text-amber-400 ml-1">
                              +{flight.delay_minutes}min
                            </span>
                          )}
                        </div>
                        {/* Passengers */}
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-gray-400 w-8">PAX</span>
                          <div className="flex-1 bg-gray-600 rounded-full h-1.5">
                            <div
                              className="bg-green-500 h-1.5 rounded-full transition-all duration-700"
                              style={{ width: `${paxPct}%` }}
                            />
                          </div>
                          <span className="text-gray-400 w-16 text-right">
                            {flight.pax_boarded}/{flight.pax_count}
                          </span>
                        </div>
                        {/* Baggage */}
                        <div className="flex items-center gap-2">
                          <span className="text-gray-400 w-8">BAG</span>
                          <div className="flex-1 bg-gray-600 rounded-full h-1.5">
                            <div
                              className="bg-blue-500 h-1.5 rounded-full transition-all duration-700"
                              style={{ width: `${bagPct}%` }}
                            />
                          </div>
                          <span className="text-gray-400 w-16 text-right">
                            {flight.baggage_loaded}/{flight.baggage_count}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
