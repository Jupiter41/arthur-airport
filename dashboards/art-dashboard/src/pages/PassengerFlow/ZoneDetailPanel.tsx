import type { ZoneDensity } from "../../types";

export function ZoneDetailPanel({ zone }: { zone: ZoneDensity | null }) {
  if (!zone) return null;
  const remaining = Math.max(0, zone.capacity - zone.density);
  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-sm font-bold text-white mb-2">{zone.zone_id}</h3>
      <div className="text-sm space-y-1 text-gray-300">
        <div className="flex justify-between">
          <span>Density</span>
          <span>{zone.density} pax</span>
        </div>
        <div className="flex justify-between">
          <span>Capacity</span>
          <span>{zone.capacity}</span>
        </div>
        <div className="flex justify-between">
          <span>Remaining</span>
          <span className={remaining < 10 ? "text-red-400 font-bold" : ""}>
            {remaining} slots
          </span>
        </div>
        <div className="flex justify-between">
          <span>Load</span>
          <span
            className={
              zone.load_pct > 85
                ? "text-red-400 font-bold"
                : zone.load_pct > 70
                  ? "text-amber-400 font-bold"
                  : ""
            }
          >
            {zone.load_pct}%
          </span>
        </div>
        <div className="w-full bg-gray-700 rounded-full h-2 mt-2">
          <div
            className={`h-2 rounded-full transition-all duration-700 ${
              zone.load_pct > 85
                ? "bg-red-500"
                : zone.load_pct > 70
                  ? "bg-amber-500"
                  : "bg-green-500"
            }`}
            style={{ width: `${Math.min(100, zone.load_pct)}%` }}
          />
        </div>
      </div>
    </div>
  );
}
