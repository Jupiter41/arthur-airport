import type { ADSBFeatureCollection } from "../../types";

export function NearbyFlightsPanel({
  data,
}: {
  data: ADSBFeatureCollection | undefined;
}) {
  if (!data || data.features.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-3">
        <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          📡 Real Flights Nearby
        </h3>
        <div className="text-xs text-gray-400">
          ADS-B disabled or no aircraft detected
        </div>
      </div>
    );
  }

  const sorted = [...data.features].sort(
    (a, b) => a.properties.distance_km - b.properties.distance_km,
  );

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        📡 Real Flights Nearby ({data.metadata.aircraft_count})
      </h3>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {sorted.slice(0, 12).map((f) => {
          const alt =
            f.properties.altitude_m != null
              ? `FL${Math.round(f.properties.altitude_m / 30.48 / 100)}`
              : "—";
          const speed =
            f.properties.velocity_ms != null
              ? `${Math.round(f.properties.velocity_ms * 1.944)}kt`
              : "—";
          return (
            <div
              key={f.properties.icao24}
              className="flex items-center justify-between text-xs bg-gray-700 rounded px-2 py-1"
            >
              <span className="font-mono font-bold text-orange-300 w-20 truncate">
                {f.properties.callsign?.trim() || f.properties.icao24}
              </span>
              <span className="text-gray-400">{alt}</span>
              <span className="text-gray-400">{speed}</span>
              <span className="text-gray-300 font-mono">
                {f.properties.distance_km.toFixed(0)} km
              </span>
            </div>
          );
        })}
      </div>
      {data.metadata.last_update && (
        <div className="mt-2 text-[10px] text-gray-400">
          Updated: {new Date(data.metadata.last_update).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
