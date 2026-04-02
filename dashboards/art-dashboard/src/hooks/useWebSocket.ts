import { useEffect, useRef, useCallback } from "react";
import type { KafkaEvent } from "../types";
import { useSimStore } from "../stores/simStore";
import { useFlightStore } from "../stores/flightStore";
import { useWeatherStore } from "../stores/weatherStore";
import { useBaggageStore } from "../stores/baggageStore";
import { useIncidentStore } from "../stores/incidentStore";
import { usePassengerStore } from "../stores/passengerStore";
import { getAuthToken } from "./auth";
import { useConnectionStore } from "../stores/connectionStore";

const RAW_WS_URL = (import.meta.env.VITE_WS_URL as string | undefined)
  ?.trim()
  .replace(/\/+$/, "");

const WS_URL =
  RAW_WS_URL ??
  (window.location.protocol === "https:" ? "wss://" : "ws://") +
    window.location.host +
    "/ws";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const HEARTBEAT_TIMEOUT_MS = 20000;

/* ──────── Event handler registry ──────── */
type EventHandler = (
  payload: Record<string, unknown>,
  sim_time: string,
  event: KafkaEvent,
) => void;

export const eventHandlers: Record<string, EventHandler> = {
  SimClockTick: (payload, sim_time) => {
    const tickFromPayload = payload?.sim_time;
    const nextTick =
      typeof tickFromPayload === "string" ? tickFromPayload : sim_time;
    if (nextTick) {
      useSimStore.getState().updateFromTick(nextTick);
    }
  },

  FlightStatusChanged: (payload) => {
    const { flight_id, new_status, delay_minutes } = payload;
    useFlightStore
      .getState()
      .updateFlightStatus(
        flight_id as string,
        new_status as string,
        delay_minutes as number | undefined,
      );
    useFlightStore.getState().flashRow(flight_id as string);
    setTimeout(
      () => useFlightStore.getState().clearFlash(flight_id as string),
      1500,
    );
  },

  FlightGateAssigned: (payload) => {
    const { flight_id, gate_id } = payload;
    useFlightStore
      .getState()
      .updateFlightGate(flight_id as string, gate_id as string);
  },

  FlightCancelled: (payload) => {
    const { flight_id } = payload;
    useFlightStore.getState().cancelFlight(flight_id as string);
    useFlightStore.getState().flashRow(flight_id as string);
    setTimeout(
      () => useFlightStore.getState().clearFlash(flight_id as string),
      1500,
    );
  },

  WeatherStateChanged: (payload) => {
    useWeatherStore.getState().updateFromEvent(payload);
  },

  BaggageStatusChanged: (payload) => {
    const { zone_id, items } = payload;
    if (zone_id && items !== undefined) {
      useBaggageStore
        .getState()
        .updateZone(zone_id as string, { items: items as number });
    }
  },

  BaggageFlagged: (payload) => {
    useBaggageStore.getState().addFlagged(payload as never);
  },

  PassengerStatusChanged: (payload) => {
    const { zone_id, density, load_pct } = payload;
    if (zone_id) {
      usePassengerStore
        .getState()
        .updateZoneDensity(
          zone_id as string,
          (density as number) ?? 0,
          (load_pct as number) ?? 0,
        );
    }
  },

  IncidentCreated: (payload) => {
    useIncidentStore.getState().upsertIncident(payload as never);
  },

  IncidentStatusChanged: (payload) => {
    const { incident_id, new_status } = payload;
    useIncidentStore
      .getState()
      .updateIncidentStatus(
        incident_id as string,
        new_status as "active" | "contained" | "resolved",
      );
  },

  IncidentCascaded: (payload) => {
    const { parent_id } = payload;
    useIncidentStore
      .getState()
      .addCascade(parent_id as string, payload as never);
  },

  IncidentAlert: (payload, sim_time, event) => {
    useIncidentStore.getState().addAlert({
      id: event.event_id,
      sim_time,
      severity: (payload.severity as never) ?? "medium",
      message: (payload.message as string) ?? "",
      incident_id: (payload.incident_id as string) ?? "",
    });
  },
};

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const heartbeatTimer = useRef<ReturnType<typeof setTimeout>>();

  const dispatch = useCallback((event: KafkaEvent) => {
    const { event_type, payload, sim_time } = event;
    const handler = eventHandlers[event_type];
    if (handler) {
      handler(payload as Record<string, unknown>, sim_time, event);
    }
  }, []);

  const resetHeartbeat = useCallback(() => {
    clearTimeout(heartbeatTimer.current);
    heartbeatTimer.current = setTimeout(() => {
      // No heartbeat received — force reconnect
      wsRef.current?.close();
    }, HEARTBEAT_TIMEOUT_MS);
  }, []);

  const scheduleReconnect = useCallback((connectFn: () => void) => {
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** reconnectAttempt.current,
      RECONNECT_MAX_MS,
    );
    reconnectAttempt.current += 1;
    setTimeout(connectFn, delay);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (wsRef.current?.readyState === WebSocket.CONNECTING) return;

    void getAuthToken()
      .then((token) => {
        const sep = WS_URL.includes("?") ? "&" : "?";
        const ws = new WebSocket(
          `${WS_URL}${sep}token=${encodeURIComponent(token)}`,
        );

        wsRef.current = ws;

        ws.onopen = () => {
          reconnectAttempt.current = 0;
          useConnectionStore.getState().setWsConnected(true, null);
          // Subscribe to all topics
          ws.send(
            JSON.stringify({
              action: "subscribe",
              topics: [
                "flights",
                "passengers",
                "baggage",
                "weather",
                "incidents",
                "alerts",
              ],
            }),
          );
          resetHeartbeat();
        };

        ws.onmessage = (ev) => {
          let data: Record<string, unknown>;
          try {
            data = JSON.parse(ev.data as string);
          } catch {
            return;
          }
          useConnectionStore.getState().markWsMessage();

          // Ping/pong heartbeat
          if (data.type === "ping") {
            ws.send(JSON.stringify({ type: "pong" }));
            resetHeartbeat();
            // Also update sim time from ping
            if (data.sim_time) {
              useSimStore.getState().updateFromTick(data.sim_time as string);
            }
            return;
          }

          // Snapshot on connect
          if (data.type === "snapshot") {
            if (data.sim_time) {
              useSimStore.getState().updateFromTick(data.sim_time as string);
            }
            // Process bootstrap state for faster reconnect
            const bootstrap = data.bootstrap as
              | Record<string, Record<string, unknown>>
              | undefined;
            if (bootstrap) {
              for (const event of Object.values(bootstrap)) {
                if (event.event_type) {
                  dispatch(event as unknown as KafkaEvent);
                }
              }
            }
            return;
          }

          // Regular event envelope
          if (data.event_type) {
            dispatch(data as unknown as KafkaEvent);
            // Dispatch a custom DOM event for the Kafka inspector
            window.dispatchEvent(
              new MessageEvent("ws-event", { data: ev.data }),
            );
          }
        };

        ws.onclose = () => {
          clearTimeout(heartbeatTimer.current);
          useConnectionStore
            .getState()
            .setWsConnected(false, "WebSocket connection closed");
          scheduleReconnect(connect);
        };

        ws.onerror = () => {
          useConnectionStore
            .getState()
            .setWsConnected(false, "WebSocket error");
          ws.close();
        };
      })
      .catch(() => {
        useConnectionStore
          .getState()
          .setWsConnected(false, "WebSocket auth failed");
        scheduleReconnect(connect);
      });
  }, [dispatch, resetHeartbeat, scheduleReconnect]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(heartbeatTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
