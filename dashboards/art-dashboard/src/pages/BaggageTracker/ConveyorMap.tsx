import { ZONE_LAYOUT, ARROWS, zoneColor, aggregateForLayout } from "./constants";
import type { BaggageZone } from "../../types";

export function ConveyorMap({ zones }: { zones: BaggageZone[] }) {
  const zoneMap = aggregateForLayout(zones);

  function getCenter(id: string) {
    const z = ZONE_LAYOUT.find((l) => l.id === id);
    if (!z) return { cx: 0, cy: 0 };
    return { cx: z.x + z.w / 2, cy: z.y + z.h / 2 };
  }

  return (
    <svg viewBox="0 0 580 380" className="w-full h-auto bg-gray-900 rounded-lg">
      <defs>
        <marker
          id="arrowhead"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" fill="#6b7280" />
        </marker>
      </defs>
      {ARROWS.map(([from, to]) => {
        const a = getCenter(from);
        const b = getCenter(to);
        return (
          <line
            key={`${from}-${to}`}
            x1={a.cx}
            y1={a.cy}
            x2={b.cx}
            y2={b.cy}
            stroke="#4b5563"
            strokeWidth={2}
            markerEnd="url(#arrowhead)"
          />
        );
      })}

      {ZONE_LAYOUT.map((layout) => {
        const zone = zoneMap[layout.id];
        const util = zone?.utilisation_pct ?? 0;
        const status = zone?.status ?? "idle";
        const items = zone?.items ?? 0;
        const fill = zoneColor(util, status);

        return (
          <g key={layout.id}>
            <rect
              x={layout.x}
              y={layout.y}
              width={layout.w}
              height={layout.h}
              rx={4}
              fill={fill}
              opacity={status === "offline" ? 0.4 : 0.7}
              className="transition-all duration-700"
            />
            <text
              x={layout.x + layout.w / 2}
              y={layout.y + layout.h / 2 - 5}
              textAnchor="middle"
              className="fill-white text-[9px] font-bold"
            >
              {layout.label}
            </text>
            <text
              x={layout.x + layout.w / 2}
              y={layout.y + layout.h / 2 + 10}
              textAnchor="middle"
              className="fill-white text-[8px]"
            >
              {items} items
            </text>
            {status === "offline" && (
              <text
                x={layout.x + layout.w / 2}
                y={layout.y + layout.h + 12}
                textAnchor="middle"
                className="fill-red-400 text-[8px] font-bold"
              >
                ⚠ OFFLINE
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
