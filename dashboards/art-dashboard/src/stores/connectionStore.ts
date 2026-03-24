import { create } from "zustand";

interface ConnectionState {
  apiConnected: boolean | null;
  wsConnected: boolean;
  lastApiError: string | null;
  lastWsError: string | null;
  wsLastMessageAt: string | null;
  setApiConnected: (connected: boolean, error?: string | null) => void;
  setWsConnected: (connected: boolean, error?: string | null) => void;
  markWsMessage: () => void;
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  apiConnected: null,
  wsConnected: false,
  lastApiError: null,
  lastWsError: null,
  wsLastMessageAt: null,
  setApiConnected: (connected, error = null) =>
    set({
      apiConnected: connected,
      lastApiError: connected ? null : (error ?? "API unreachable"),
    }),
  setWsConnected: (connected, error = null) =>
    set({
      wsConnected: connected,
      lastWsError: connected ? null : (error ?? "WebSocket disconnected"),
    }),
  markWsMessage: () =>
    set({
      wsLastMessageAt: new Date().toISOString(),
    }),
}));
