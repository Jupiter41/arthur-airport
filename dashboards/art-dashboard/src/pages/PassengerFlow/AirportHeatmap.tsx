import { useMemo } from "react";
import { heatColor } from "./helpers";
import type { ZoneDensity } from "../../types";

function ZoneCell({
  zone,
  locked,
  onClick,
}: {
  zone: ZoneDensity;
  locked: boolean;
  onClick: () => void;
}) {
  const bg = heatColor(zone.load_pct, locked);

  return (
    <div
      className="relative rounded-lg p-2.5 cursor-pointer transition-all duration-700 hover:ring-2 hover:ring-white/40 min-h-[60px] shadow-sm"
      style={{ backgroundColor: bg, opacity: locked ? 0.5 : 1 }}
      onClick={onClick}
    >
      <div className="text-[10px] font-bold text-white drop-shadow-sm truncate">
        {zone.zone_id}
      </div>
      <div className="text-sm font-semibold text-white drop-shadow-sm">
        {zone.density} pax
      </div>
      <div className="text-[9px] text-white/70">
        {zone.load_pct}% ·{" "}
        {zone.capacity - zone.density > 0 ? zone.capacity - zone.density : 0}{" "}
        free
      </div>
      {locked && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg">🔒</span>
        </div>
      )}
    </div>
  );
}

export function AirportHeatmap({
  zones,
  lockedZones,
  onSelect,
}: {
  zones: ZoneDensity[];
  lockedZones: Set<string>;
  onSelect: (z: ZoneDensity) => void;
}) {
  const grouped = useMemo(() => {
    const byType: Record<string, ZoneDensity[]> = {};
    for (const z of zones) {
      const key = z.zone_type || z.zone_id.split("-")[0];
      (byType[key] ??= []).push(z);
    }
    return byType;
  }, [zones]);

  const terminals = ["A", "B", "C"];
  const columns = ["check-in", "security", "airside", "gate"];

  return (
    <div className="bg-gray-900 rounded-lg p-4">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-3">
        Airport Heatmap
      </div>
      <div className="grid grid-cols-4 gap-2 mb-2">
        {columns.map((col) => (
          <div
            key={col}
            className="text-xs text-gray-400 text-center uppercase"
          >
            {col}
          </div>
        ))}
      </div>

      {terminals.map((term) => (
        <div key={term} className="grid grid-cols-4 gap-2 mb-2">
          {columns.map((col) => {
            const key = `${col}-${term}`;
            const matching = zones.filter(
              (z) =>
                z.zone_id
                  .toLowerCase()
                  .includes(`${col}-${term.toLowerCase()}`) ||
                z.zone_id
                  .toLowerCase()
                  .includes(`${col.replace("-", "")}-${term.toLowerCase()}`),
            );

            if (col === "gate" && matching.length === 0) {
              const gateZones = zones.filter(
                (z) =>
                  z.zone_id.toLowerCase().startsWith("gate-") &&
                  z.zone_id
                    .toLowerCase()
                    .startsWith(`gate-${term.toLowerCase()}`),
              );
              if (gateZones.length > 0) {
                const totalDensity = gateZones.reduce(
                  (s, z) => s + z.density,
                  0,
                );
                const totalCap = gateZones.reduce((s, z) => s + z.capacity, 0);
                const avgLoad =
                  totalCap > 0
                    ? Math.round((totalDensity / totalCap) * 100)
                    : 0;
                const agg: ZoneDensity = {
                  zone_id: `gates-${term}`,
                  zone_type: "gate",
                  terminal: term,
                  density: totalDensity,
                  capacity: totalCap,
                  load_pct: avgLoad,
                };
                return (
                  <ZoneCell
                    key={key}
                    zone={agg}
                    locked={lockedZones.has(`terminal-${term}`)}
                    onClick={() => onSelect(agg)}
                  />
                );
              }
            }

            if (matching.length > 0) {
              return (
                <ZoneCell
                  key={key}
                  zone={matching[0]}
                  locked={lockedZones.has(matching[0].zone_id)}
                  onClick={() => onSelect(matching[0])}
                />
              );
            }

            const placeholder: ZoneDensity = {
              zone_id: key,
              zone_type: col,
              terminal: term,
              density: 0,
              capacity: 100,
              load_pct: 0,
            };
            return (
              <ZoneCell
                key={key}
                zone={placeholder}
                locked={false}
                onClick={() => onSelect(placeholder)}
              />
            );
          })}
        </div>
      ))}

      <div className="mt-3">
        <div className="text-xs text-gray-400 uppercase mb-1">
          Arrival Carousels
        </div>
        <div className="grid grid-cols-6 gap-2">
          {[1, 2, 3, 4, 5, 6].map((n) => {
            const z = zones.find((z) => z.zone_id === `carousel-${n}`);
            const zone: ZoneDensity = z ?? {
              zone_id: `carousel-${n}`,
              zone_type: "carousel",
              terminal: "",
              density: 0,
              capacity: 200,
              load_pct: 0,
            };
            return (
              <ZoneCell
                key={zone.zone_id}
                zone={zone}
                locked={false}
                onClick={() => onSelect(zone)}
              />
            );
          })}
        </div>
      </div>

      <div className="flex items-center gap-3 mt-3 text-[10px] text-gray-400">
        {[
          { pct: 10, label: "Calm" },
          { pct: 30, label: "Low" },
          { pct: 50, label: "Moderate" },
          { pct: 65, label: "Busy" },
          { pct: 80, label: "High" },
          { pct: 92, label: "Near Cap" },
          { pct: 100, label: "Full" },
        ].map(({ pct, label }) => (
          <div key={pct} className="flex items-center gap-1">
            <div
              className="w-3 h-3 rounded"
              style={{ backgroundColor: heatColor(pct, false) }}
            />
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
