import type { NetworkStatus } from "../../hooks/useApi";

/* ──────── Network Panel ──────── */
export function NetworkPanel({
  data,
  onFlyToAirport,
}: {
  data: NetworkStatus;
  onFlyToAirport: (lat: number, lon: number) => void;
}) {
  const statusColor = (level: string) => {
    switch (level) {
      case "red":
        return "text-red-400";
      case "amber":
        return "text-amber-400";
      default:
        return "text-green-400";
    }
  };

  const statusBg = (level: string) => {
    switch (level) {
      case "red":
        return "bg-red-900/30 border-red-700/50";
      case "amber":
        return "bg-amber-900/30 border-amber-700/50";
      default:
        return "bg-slate-800/50 border-slate-700/50";
    }
  };

  return (
    <aside className="absolute bottom-16 left-3 w-80 rounded border border-emerald-700/50 bg-slate-950/96 text-xs shadow-lg backdrop-blur-sm p-3 max-h-80 overflow-y-auto">
      <h2 className="text-sm font-semibold text-emerald-300 mb-2">
        🌐 {data.name}
      </h2>

      {/* Airport status cards */}
      <div className="space-y-1.5">
        {data.airports.map((airport) => (
          <div
            key={airport.icao}
            className={`rounded border p-2 cursor-pointer hover:brightness-125 transition-all ${statusBg(airport.disruption_level)}`}
            onClick={() => onFlyToAirport(airport.lat, airport.lon)}
            title={`Click to fly to ${airport.iata}`}
          >
            <div className="flex items-center justify-between">
              <div>
                <span className="font-bold text-slate-100">{airport.iata}</span>
                <span className="text-slate-400 ml-1.5">{airport.name}</span>
              </div>
              <span
                className={`font-bold uppercase text-[10px] ${statusColor(airport.disruption_level)}`}
              >
                {airport.disruption_level}
              </span>
            </div>
            <div className="flex items-center gap-3 mt-1 text-slate-400">
              <span>Delay: {airport.current_delay_minutes} min</span>
              {airport.gdp_active && (
                <span className="text-red-400 font-bold">GDP ACTIVE</span>
              )}
              {airport.recovery_eta_minutes > 0 && (
                <span>
                  Recovery: ~{Math.ceil(airport.recovery_eta_minutes)} min
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Active GDPs */}
      {data.active_gdps.length > 0 && (
        <div className="mt-3 pt-2 border-t border-slate-700">
          <h3 className="text-[10px] uppercase tracking-wide text-red-400 font-bold mb-1">
            Active Ground Delay Programs
          </h3>
          {data.active_gdps.map((gdp) => (
            <div key={gdp.airport_icao} className="text-slate-300 mb-1">
              <span className="font-bold">{gdp.airport_icao}</span>:{" "}
              {gdp.reason}
              <br />
              <span className="text-slate-400">
                Departure rate: {Math.round(gdp.departure_rate_pct * 100)}% —
                Feeders: {gdp.affected_feeder_airports.join(", ")}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Recent propagations */}
      {data.recent_propagations.length > 0 && (
        <div className="mt-3 pt-2 border-t border-slate-700">
          <h3 className="text-[10px] uppercase tracking-wide text-emerald-400 font-bold mb-1">
            Recent Delay Propagations
          </h3>
          {data.recent_propagations
            .slice(-5)
            .reverse()
            .map((p, i) => (
              <div key={i} className="text-slate-400 mb-0.5">
                {p.flight_number}: {p.source_icao} → {p.target_icao} (
                {p.propagated_delay_minutes} min)
              </div>
            ))}
        </div>
      )}
    </aside>
  );
}
