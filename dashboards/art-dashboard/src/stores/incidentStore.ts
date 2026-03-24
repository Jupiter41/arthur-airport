import { create } from "zustand";
import type { Incident, IncidentAlert } from "../types";

/**
 * Normalize an incident object from the API or Kafka.
 * The API returns `protocol` (singular string) but the frontend
 * Incident type expects `protocols` (string[]). Also ensures all
 * array fields default to [] and numeric fields default to 0.
 */
function normalizeIncident(raw: Record<string, unknown>): Incident {
  const i = raw as Partial<Incident> & Record<string, unknown>;
  // Map `protocol` (string from API) → `protocols` (array for frontend)
  let protocols = i.protocols;
  if (!Array.isArray(protocols)) {
    const proto = (i as Record<string, unknown>).protocol;
    protocols = typeof proto === "string" && proto ? [proto] : [];
  }
  return {
    ...i,
    protocols,
    cascade_depth: i.cascade_depth ?? 0,
    cascade_tree: i.cascade_tree ?? null,
  } as Incident;
}

interface IncidentStoreState {
  incidents: Record<string, Incident>;
  alerts: IncidentAlert[];

  setIncidents: (list: Incident[]) => void;
  upsertIncident: (i: Incident) => void;
  updateIncidentStatus: (
    id: string,
    status: Incident["status"],
    patch?: Partial<Incident>,
  ) => void;
  addCascade: (parentId: string, child: Incident) => void;
  addAlert: (a: IncidentAlert) => void;
  setAlerts: (a: IncidentAlert[]) => void;
}

const MAX_ALERTS = 200;

export const useIncidentStore = create<IncidentStoreState>((set) => ({
  incidents: {},
  alerts: [],

  setIncidents: (list) =>
    set({
      incidents: Object.fromEntries(
        list.map((i) => {
          const n = normalizeIncident(i as unknown as Record<string, unknown>);
          return [n.id, n];
        }),
      ),
    }),

  upsertIncident: (i) =>
    set((s) => {
      const n = normalizeIncident(i as unknown as Record<string, unknown>);
      return { incidents: { ...s.incidents, [n.id]: n } };
    }),

  updateIncidentStatus: (id, status, patch) =>
    set((s) => {
      const existing = s.incidents[id];
      if (!existing) return s;
      return {
        incidents: {
          ...s.incidents,
          [id]: { ...existing, ...patch, status },
        },
      };
    }),

  addCascade: (_parentId, child) =>
    set((s) => ({ incidents: { ...s.incidents, [child.id]: child } })),

  addAlert: (a) =>
    set((s) => ({
      alerts: [a, ...s.alerts].slice(0, MAX_ALERTS),
    })),

  setAlerts: (a) => set({ alerts: a.slice(0, MAX_ALERTS) }),
}));
