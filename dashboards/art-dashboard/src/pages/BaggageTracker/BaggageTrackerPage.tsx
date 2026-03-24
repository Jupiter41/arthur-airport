import { useState, useEffect } from "react";
import { useBaggageStore } from "../../stores/baggageStore";
import { useIncidentStore } from "../../stores/incidentStore";
import { baggageApi, flightsApi } from "../../hooks/useApi";
import type {
  BaggageZone,
  BaggageFlowSummary,
  FlaggedBaggage,
  Flight,
} from "../../types";

/* ──────── SVG Conveyor Map ──────── */
const ZONE_LAYOUT: {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
}[] = [
  // Induction
  { id: "induction-A", x: 20, y: 20, w: 100, h: 50, label: "Induction A" },
  { id: "induction-B", x: 140, y: 20, w: 100, h: 50, label: "Induction B" },
  { id: "induction-C", x: 260, y: 20, w: 100, h: 50, label: "Induction C" },
  // Screening
  { id: "screening-1", x: 20, y: 100, w: 80, h: 40, label: "Screen 1" },
  { id: "screening-2", x: 110, y: 100, w: 80, h: 40, label: "Screen 2" },
  { id: "screening-3", x: 200, y: 100, w: 80, h: 40, label: "Screen 3" },
  { id: "screening-4", x: 290, y: 100, w: 80, h: 40, label: "Screen 4" },
  { id: "screening-5", x: 380, y: 100, w: 80, h: 40, label: "Screen 5" },
  { id: "screening-6", x: 470, y: 100, w: 80, h: 40, label: "Screen 6" },
  // Sorting matrix
  {
    id: "sorting-matrix",
    x: 160,
    y: 170,
    w: 260,
    h: 50,
    label: "Sorting Matrix",
  },
  // Make-up
  { id: "make-up-A", x: 20, y: 250, w: 100, h: 40, label: "Make-up A" },
  { id: "make-up-B", x: 200, y: 250, w: 100, h: 40, label: "Make-up B" },
  { id: "make-up-C", x: 380, y: 250, w: 100, h: 40, label: "Make-up C" },
  // Arrival belts
  { id: "arrival-belt-1", x: 20, y: 320, w: 80, h: 35, label: "Belt 1" },
  { id: "arrival-belt-2", x: 110, y: 320, w: 80, h: 35, label: "Belt 2" },
  { id: "arrival-belt-3", x: 200, y: 320, w: 80, h: 35, label: "Belt 3" },
  { id: "arrival-belt-4", x: 290, y: 320, w: 80, h: 35, label: "Belt 4" },
  { id: "arrival-belt-5", x: 380, y: 320, w: 80, h: 35, label: "Belt 5" },
  { id: "arrival-belt-6", x: 470, y: 320, w: 80, h: 35, label: "Belt 6" },
];

const ARROWS: [string, string][] = [
  ["induction-A", "screening-1"],
  ["induction-B", "screening-3"],
  ["induction-C", "screening-5"],
  ["screening-3", "sorting-matrix"],
  ["sorting-matrix", "make-up-A"],
  ["sorting-matrix", "make-up-B"],
  ["sorting-matrix", "make-up-C"],
];

function zoneColor(util: number, status: string): string {
  if (status === "offline") return "#6b7280"; // gray
  if (util <= 60) return "#22c55e"; // green
  if (util <= 80) return "#f59e0b"; // amber
  return "#ef4444"; // red
}

function toLayoutZoneId(zoneId: string): string {
  const screening = /^screening-unit-(\d+)$/i.exec(zoneId);
  if (screening) {
    return `screening-${screening[1]}`;
  }

  const makeup = /^make-up-([ABC])-\d+$/i.exec(zoneId);
  if (makeup) {
    return `make-up-${makeup[1].toUpperCase()}`;
  }

  return zoneId;
}

function normalizeZoneStatus(status: string): "active" | "offline" | "idle" {
  const normalized = status.toLowerCase();
  if (normalized === "offline") return "offline";
  if (normalized === "active" || normalized === "normal" || normalized === "degraded") {
    return "active";
  }
  return "idle";
}

function aggregateForLayout(zones: BaggageZone[]): Record<string, BaggageZone> {
  const map: Record<string, BaggageZone> = {};

  for (const zone of zones) {
    const layoutId = toLayoutZoneId(zone.zone_id);
    const existing = map[layoutId];
    const status = normalizeZoneStatus(zone.status);

    if (!existing) {
      map[layoutId] = {
        ...zone,
        zone_id: layoutId,
        status,
      };
      continue;
    }

    existing.items += zone.items;
    existing.capacity += zone.capacity;
    existing.throughput_per_hour += zone.throughput_per_hour;
    existing.status =
      existing.status === "offline" || status === "offline"
        ? "offline"
        : existing.status === "active" || status === "active"
          ? "active"
          : "idle";
    existing.utilisation_pct =
      existing.capacity > 0
        ? Math.round((existing.items / existing.capacity) * 100)
        : Math.max(existing.utilisation_pct, zone.utilisation_pct);
  }

  return map;
}

function ConveyorMap({ zones }: { zones: BaggageZone[] }) {
  const zoneMap = aggregateForLayout(zones);

  function getCenter(id: string) {
    const z = ZONE_LAYOUT.find((l) => l.id === id);
    if (!z) return { cx: 0, cy: 0 };
    return { cx: z.x + z.w / 2, cy: z.y + z.h / 2 };
  }

  return (
    <svg viewBox="0 0 580 380" className="w-full h-auto bg-gray-900 rounded-lg">
      {/* Arrows */}
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

      {/* Zones */}
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

/* ──────── Zone Stats Panel ──────── */
function ZoneStatsPanel({ zones }: { zones: BaggageZone[] }) {
  const sorted = [...zones].sort(
    (a, b) => b.utilisation_pct - a.utilisation_pct,
  );

  return (
    <div className="space-y-2">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">
        Zone Stats
      </h3>
      {sorted.slice(0, 8).map((z) => (
        <div key={z.zone_id} className="flex items-center gap-2">
          <span className="text-xs text-gray-300 w-28 truncate">
            {z.zone_id}
          </span>
          <div className="flex-1 bg-gray-700 rounded-full h-2">
            <div
              className="h-2 rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(z.utilisation_pct, 100)}%`,
                backgroundColor: zoneColor(z.utilisation_pct, z.status),
              }}
            />
          </div>
          <span className="text-xs text-gray-400 w-10 text-right">
            {z.utilisation_pct}%
          </span>
          {z.status === "offline" && (
            <span className="text-xs text-red-400 font-bold">⚠</span>
          )}
        </div>
      ))}
    </div>
  );
}

/* ──────── Flow Summary ──────── */
function FlowSummaryPanel({ summary }: { summary: BaggageFlowSummary | null }) {
  if (!summary) return null;

  const loadedCount =
    summary.loaded_count ??
    (summary.by_status?.loaded as number | undefined) ??
    0;
  const flaggedCount =
    summary.flagged_count ??
    (summary.by_status?.flagged as number | undefined) ??
    0;

  return (
    <div className="space-y-2">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide">
        Flow Summary
      </h3>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="bg-gray-800 rounded p-2">
          <div className="text-xs text-gray-500">In System</div>
          <div className="font-bold text-white">
            {(summary.total_in_system ?? 0).toLocaleString()}
          </div>
        </div>
        <div className="bg-gray-800 rounded p-2">
          <div className="text-xs text-gray-500">Loaded</div>
          <div className="font-bold text-teal-400">
            {loadedCount.toLocaleString()}
          </div>
        </div>
        <div className="bg-gray-800 rounded p-2">
          <div className="text-xs text-gray-500">Flagged</div>
          <div className="font-bold text-amber-400">{flaggedCount}</div>
        </div>
      </div>
      {summary.by_status && (
        <div className="text-xs text-gray-400 space-y-1">
          {Object.entries(summary.by_status).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span>{k}</span>
              <span className="text-gray-300">{v as number}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ──────── Flagged Items Panel ──────── */
function FlaggedItemsPanel({ flagged }: { flagged: FlaggedBaggage[] }) {
  if (flagged.length === 0) return null;

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Flagged Items ({flagged.length})
      </h3>
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {flagged.map((item) => (
          <div
            key={item.id}
            className={`flex items-center justify-between text-sm p-2 rounded ${
              item.dg_class === 3
                ? "bg-red-900/40 border border-red-700"
                : "bg-gray-700"
            }`}
          >
            <div>
              <span className="font-mono text-white">{item.tag}</span>
              <span className="ml-2 text-xs text-gray-400">
                {item.flag_reason}
                {item.dg_class != null && ` · DG Class ${item.dg_class}`}
              </span>
            </div>
            <div className="text-xs text-gray-400">
              <span>{item.flight_number}</span>
              <span className="ml-2 text-amber-400 font-bold">
                {item.review_status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────── Loading Progress Panel ──────── */
function LoadingProgressPanel({ flights }: { flights: Flight[] }) {
  const departures = flights
    .filter(
      (f) =>
        f.direction === "departure" &&
        ["boarding", "scheduled"].includes(f.status),
    )
    .sort((a, b) =>
      (a.estimated_time ?? a.scheduled_time).localeCompare(
        b.estimated_time ?? b.scheduled_time,
      ),
    )
    .slice(0, 10);

  if (departures.length === 0) return null;

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Flight Baggage Loading
      </h3>
      <div className="space-y-2">
        {departures.map((f) => {
          const pct =
            f.baggage_count > 0
              ? Math.round((f.baggage_loaded / f.baggage_count) * 100)
              : 0;
          return (
            <div key={f.id} className="flex items-center gap-3">
              <span className="text-sm font-bold text-white w-16">
                {f.flight_number}
              </span>
              <span className="text-xs text-gray-400 w-8">
                {f.gate_id ?? "—"}
              </span>
              <div className="flex-1 bg-gray-700 rounded-full h-2">
                <div
                  className="bg-teal-500 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs text-gray-400 w-20 text-right">
                {f.baggage_loaded}/{f.baggage_count} {pct}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ──────── Main Page ──────── */
export default function BaggageTrackerPage() {
  const zones = useBaggageStore((s) => s.zones);
  const summary = useBaggageStore((s) => s.summary);
  const flagged = useBaggageStore((s) => s.flagged);
  const setZones = useBaggageStore((s) => s.setZones);
  const setSummary = useBaggageStore((s) => s.setSummary);
  const setFlagged = useBaggageStore((s) => s.setFlagged);
  const [flights, setFlights] = useState<Flight[]>([]);

  // Listen for incident-driven zone offline changes
  const incidents = useIncidentStore((s) => s.incidents);

  // Mark zones offline based on active system_failure incidents
  useEffect(() => {
    if (zones.length === 0) return;
    const activeFailures = Object.values(incidents).filter(
      (i) => i.type === "system_failure" && i.status !== "resolved",
    );
    const offlineLocations = new Set(activeFailures.map((i) => i.location));

    let changed = false;
    const updated = zones.map((z) => {
      const shouldBeOffline =
        offlineLocations.has(z.zone_id) ||
        [...offlineLocations].some((loc) =>
          z.zone_id.includes(loc.replace("conveyor-", "")),
        );
      if (shouldBeOffline && z.status !== "offline") {
        changed = true;
        return { ...z, status: "offline" as const };
      }
      if (!shouldBeOffline && z.status === "offline") {
        changed = true;
        return { ...z, status: "active" as const };
      }
      return z;
    });
    if (changed) setZones(updated);
  }, [incidents, zones, setZones]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [mapData, summaryData, flaggedData, flightsData] =
          await Promise.all([
            baggageApi.map(),
            baggageApi.summary(),
            baggageApi.flagged(),
            flightsApi.list({ direction: "departure", limit: "100" }),
          ]);
        if (cancelled) {
          return;
        }
        const md = mapData as { zones?: BaggageZone[] };
        setZones(
          md.zones ??
            (Array.isArray(mapData) ? (mapData as BaggageZone[]) : []),
        );
        const sd = summaryData as Record<string, unknown>;
        setSummary({
          total_in_system: (sd.total_in_system as number) ?? 0,
          by_status: (sd.by_status as Record<string, number>) ?? {},
          flagged_count:
            (sd.flagged_count as number) ??
            (sd.flagged_active as number) ??
            0,
          loaded_count:
            (sd.loaded_count as number) ??
            ((sd.by_status as Record<string, number> | undefined)?.loaded ?? 0),
        });
        const fd = flaggedData as { flagged?: FlaggedBaggage[] };
        setFlagged(
          fd.flagged ??
            (Array.isArray(flaggedData)
              ? (flaggedData as FlaggedBaggage[])
              : []),
        );
        const fl = flightsData as { flights?: Flight[] };
        setFlights(fl.flights ?? []);
      } catch {
        // Keep existing state and retry on next interval tick.
      }
    };

    void load();
    const interval = setInterval(() => {
      void load();
    }, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setZones, setSummary, setFlagged]);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <h2 className="text-lg font-bold text-white">Baggage Operations</h2>

      <div className="grid grid-cols-3 gap-4">
        {/* Conveyor map */}
        <div className="col-span-2">
          <ConveyorMap zones={zones} />
        </div>

        {/* Right sidebar */}
        <div className="space-y-4">
          <ZoneStatsPanel zones={zones} />
          <FlowSummaryPanel summary={summary} />
        </div>
      </div>

      <LoadingProgressPanel flights={flights} />
      <FlaggedItemsPanel flagged={flagged} />
    </div>
  );
}
