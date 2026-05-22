import type { BaggageZone } from "../../types";

export const ZONE_LAYOUT: {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
}[] = [
  { id: "induction-A", x: 20, y: 20, w: 100, h: 50, label: "Induction A" },
  { id: "induction-B", x: 140, y: 20, w: 100, h: 50, label: "Induction B" },
  { id: "induction-C", x: 260, y: 20, w: 100, h: 50, label: "Induction C" },
  { id: "screening-unit-1", x: 20, y: 100, w: 80, h: 40, label: "Screen 1" },
  { id: "screening-unit-2", x: 110, y: 100, w: 80, h: 40, label: "Screen 2" },
  { id: "screening-unit-3", x: 200, y: 100, w: 80, h: 40, label: "Screen 3" },
  { id: "screening-unit-4", x: 290, y: 100, w: 80, h: 40, label: "Screen 4" },
  { id: "screening-unit-5", x: 380, y: 100, w: 80, h: 40, label: "Screen 5" },
  { id: "screening-unit-6", x: 470, y: 100, w: 80, h: 40, label: "Screen 6" },
  {
    id: "sorting-matrix",
    x: 160,
    y: 170,
    w: 260,
    h: 50,
    label: "Sorting Matrix",
  },
  { id: "make-up-A", x: 20, y: 250, w: 100, h: 40, label: "Make-up A" },
  { id: "make-up-B", x: 200, y: 250, w: 100, h: 40, label: "Make-up B" },
  { id: "make-up-C", x: 380, y: 250, w: 100, h: 40, label: "Make-up C" },
  { id: "arrival-belt-1", x: 20, y: 320, w: 80, h: 35, label: "Belt 1" },
  { id: "arrival-belt-2", x: 110, y: 320, w: 80, h: 35, label: "Belt 2" },
  { id: "arrival-belt-3", x: 200, y: 320, w: 80, h: 35, label: "Belt 3" },
  { id: "arrival-belt-4", x: 290, y: 320, w: 80, h: 35, label: "Belt 4" },
  { id: "arrival-belt-5", x: 380, y: 320, w: 80, h: 35, label: "Belt 5" },
  { id: "arrival-belt-6", x: 470, y: 320, w: 80, h: 35, label: "Belt 6" },
];

export const ARROWS: [string, string][] = [
  ["induction-A", "screening-unit-1"],
  ["induction-A", "screening-unit-2"],
  ["induction-B", "screening-unit-3"],
  ["induction-B", "screening-unit-4"],
  ["induction-C", "screening-unit-5"],
  ["induction-C", "screening-unit-6"],
  ["screening-unit-1", "sorting-matrix"],
  ["screening-unit-2", "sorting-matrix"],
  ["screening-unit-3", "sorting-matrix"],
  ["screening-unit-4", "sorting-matrix"],
  ["screening-unit-5", "sorting-matrix"],
  ["screening-unit-6", "sorting-matrix"],
  ["sorting-matrix", "make-up-A"],
  ["sorting-matrix", "make-up-B"],
  ["sorting-matrix", "make-up-C"],
  ["make-up-A", "arrival-belt-1"],
  ["make-up-A", "arrival-belt-2"],
  ["make-up-B", "arrival-belt-3"],
  ["make-up-B", "arrival-belt-4"],
  ["make-up-C", "arrival-belt-5"],
  ["make-up-C", "arrival-belt-6"],
];

export function zoneColor(util: number, status: string): string {
  if (status === "offline") return "#6b7280";
  if (util <= 60) return "#22c55e";
  if (util <= 80) return "#f59e0b";
  return "#ef4444";
}

export function toLayoutZoneId(zoneId: string): string {
  const makeup = /^make-up-([ABC])-\d+$/i.exec(zoneId);
  if (makeup) {
    return `make-up-${makeup[1].toUpperCase()}`;
  }
  return zoneId;
}

export function normalizeZoneStatus(status: string): "active" | "offline" | "idle" {
  const normalized = status.toLowerCase();
  if (normalized === "offline") return "offline";
  if (
    normalized === "active" ||
    normalized === "normal" ||
    normalized === "degraded"
  ) {
    return "active";
  }
  return "idle";
}

export function aggregateForLayout(zones: BaggageZone[]): Record<string, BaggageZone> {
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
