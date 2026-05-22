import type { ConnectionAtRisk } from "../../types";

export function ConnectionRiskList({
  connections,
}: {
  connections: ConnectionAtRisk[];
}) {
  if (connections.length === 0) return null;

  const riskColors: Record<string, string> = {
    watch: "bg-gray-600 text-gray-200",
    at_risk: "bg-amber-600 text-white",
    missed: "bg-red-600 text-white",
  };

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Connections at Risk
      </h3>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {connections.map((c) => (
          <div
            key={c.passenger_id}
            className="flex items-center justify-between text-sm bg-gray-700 rounded p-2"
          >
            <div>
              <span className="text-white font-medium">{c.passenger_name}</span>
              <span className="ml-2 text-xs text-gray-400">
                {c.inbound_flight}
                {c.inbound_delay_minutes > 0 &&
                  ` +${c.inbound_delay_minutes}min`}
                {" → "}
                {c.connection_flight}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">
                {c.time_until_departure_min} min
              </span>
              <span
                className={`text-xs font-bold px-2 py-0.5 rounded ${riskColors[c.risk_level] ?? "bg-gray-600"}`}
              >
                {c.risk_level.toUpperCase().replace("_", " ")}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
