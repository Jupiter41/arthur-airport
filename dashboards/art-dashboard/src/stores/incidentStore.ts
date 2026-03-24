import { create } from "zustand";
import type { Incident, IncidentAlert } from "../types";

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
    set({ incidents: Object.fromEntries(list.map((i) => [i.id, i])) }),

  upsertIncident: (i) =>
    set((s) => ({ incidents: { ...s.incidents, [i.id]: i } })),

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
