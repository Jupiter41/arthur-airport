import { useEffect, useRef, useCallback } from "react";
import type { Flight, KafkaEvent, SimStatus } from "../types";
import { useSimStore } from "../stores/simStore";
import { useFlightStore } from "../stores/flightStore";
import { useWeatherStore } from "../stores/weatherStore";
import { useBaggageStore } from "../stores/baggageStore";
import { useIncidentStore } from "../stores/incidentStore";
import { useGroundVehicleStore } from "../stores/groundVehicleStore";
import { useCostStore } from "../stores/costStore";
import { getAuthToken } from "./auth";
import { useConnectionStore } from "../stores/connectionStore";
import { queryClient } from "../queryClient";
import { simApi } from "./useApi";
import { applyBaggageObservation, applySecurityObservation, applyVehicleObservation, reconcileLiveQueries, resetLiveProjectionGuards } from "./liveProjections";

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
  SimControlChanged: (payload) => {
    if (typeof payload.paused === "boolean") useSimStore.getState().setPaused(payload.paused);
    if (typeof payload.speed_multiplier === "number") useSimStore.getState().setSpeed(payload.speed_multiplier);
    void queryClient.invalidateQueries({ queryKey: ["sim-settings"] });
    void queryClient.invalidateQueries({ queryKey: ["sim-status"] });
  },
  SimClockTick: (payload, sim_time) => {
    const tickFromPayload = payload?.sim_time;
    const nextTick =
      typeof tickFromPayload === "string" ? tickFromPayload : sim_time;
    const dayOfSim =
      typeof payload?.day_of_sim === "number"
        ? (payload.day_of_sim as number)
        : undefined;
    if (nextTick) {
      if (Date.parse(nextTick) < Date.parse(useSimStore.getState().status.sim_time)) resetLiveProjectionGuards();
      useSimStore.getState().updateFromTick(nextTick, dayOfSim);
    }
  },

  FlightStatusChanged: (payload, sim_time) => {
    const { flight_id, new_status, delay_minutes } = payload;
    const store = useFlightStore.getState();
    const existing = store.flights[flight_id as string];
    if (existing) {
      // The owner stamps actual_time at the landed/departed transition, which
      // is this event's sim_time; the 3D timeline starts from it immediately.
      const facts: Partial<Pick<Flight, "actual_time" | "gate_id" | "runway_id">> = {};
      if ((new_status === "landed" || new_status === "departed") && sim_time) facts.actual_time = sim_time;
      if (typeof payload.gate_id === "string" && payload.gate_id) facts.gate_id = payload.gate_id;
      if (typeof payload.runway_id === "string" && payload.runway_id) facts.runway_id = payload.runway_id;
      store.updateFlightStatus(
        flight_id as string,
        new_status as string,
        delay_minutes as number | undefined,
        facts,
      );
    } else {
      // New flight — the board re-fetches (throttled with the reconcile below).
      reconcileLiveQueries("flights");
    }
    store.flashRow(flight_id as string);
    reconcileLiveQueries("flights"); reconcileLiveQueries("gates"); reconcileLiveQueries("runways");
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
    reconcileLiveQueries("gates");
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

  BaggageFlagged: (payload) => {
    useBaggageStore.getState().addFlagged(payload as never);
  },

  // RC9: per-bag BaggageStatusChanged / per-passenger PassengerStatusChanged
  // are no longer delivered by the gateway (no UI consumer: zone occupancy
  // comes from BaggageZoneSnapshot, counts from the batch hints below). The
  // registry must match services/api-gateway/src/wsDeliveryPolicy.json.

  IncidentCreated: (payload, sim_time) => {
    const id = payload.incident_id ?? payload.id;
    if (typeof id !== "string" || typeof payload.type !== "string" || typeof payload.severity !== "string") {
      reconcileLiveQueries("incidents");
      return;
    }
    useIncidentStore.getState().upsertIncident({
      ...payload, id, status: payload.status ?? "active",
      started_at: payload.started_at ?? sim_time,
      location: payload.location ?? "Location unavailable", observed_at: sim_time,
    } as never);
  },

  IncidentStatusChanged: (payload, sim_time) => {
    const { incident_id, new_status } = payload;
    useIncidentStore
      .getState()
      .updateIncidentStatus(
        incident_id as string,
        new_status as "active" | "contained" | "resolved",
        { observed_at: sim_time },
      );
  },

  IncidentCascaded: () => {
    // This fact carries relationship IDs, not a complete Incident record.
    // The separate creation fact/owner read supplies child details.
    reconcileLiveQueries("incidents");
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

  FlightCTOTAssigned: (payload) => {
    const { flight_id, ctot_delay_minutes } = payload;
    useFlightStore
      .getState()
      .updateFlightStatus(
        flight_id as string,
        "boarding",
        ctot_delay_minutes as number,
      );
  },

  MinimumFuelWarning: (payload, sim_time, event) => {
    useIncidentStore.getState().addAlert({
      id: event.event_id,
      sim_time,
      severity: (payload.is_panpan as boolean) ? "critical" : "high",
      message: `Fuel warning: ${payload.flight_number as string} holding ${payload.holding_minutes as number}min`,
      incident_id: "",
    });
  },

  FlightDiverted: (payload) => {
    const { flight_id } = payload;
    useFlightStore
      .getState()
      .updateFlightStatus(flight_id as string, "diverted");
    useFlightStore.getState().flashRow(flight_id as string);
    setTimeout(
      () => useFlightStore.getState().clearFlash(flight_id as string),
      1500,
    );
  },

  GroundVehicleSnapshot: applyVehicleObservation,
  SecurityQueueUpdated: applySecurityObservation,
  BaggageZoneSnapshot: applyBaggageObservation,
  // Batch facts arrive as coalesced, payload-free refetch hints (RC9).
  PassengerStatusBatchChanged: () => { reconcileLiveQueries("passengers"); },
  BaggageStatusBatchChanged: () => {
    reconcileLiveQueries("baggage", "3d-items"); reconcileLiveQueries("baggage", "detail");
    reconcileLiveQueries("baggage", "summary"); reconcileLiveQueries("baggage", "flagged");
  },
  GroundVehicleDispatched: (payload) => {
    // Dispatch facts contain no coordinates. Preserve the last owner position
    // rather than teleporting the vehicle to (0, 0).
    useGroundVehicleStore.getState().updateVehicleStatus(payload.vehicle_id as string, "dispatched", payload.gate_id as string);
    reconcileLiveQueries("ground-vehicles");
  },

  GroundVehicleReturned: (payload) => {
    useGroundVehicleStore
      .getState()
      .updateVehicleStatus(payload.vehicle_id as string, "available");
  },

  // Bottlenecks and recommendations are owned by React Query
  // (useBottlenecksQuery / useRecommendationsQuery polling the analysis
  // REST endpoints). No WebSocket-fed duplicate is kept for them.

  AutonomousActionApplied: (payload, sim_time, event) => {
    useIncidentStore.getState().addAlert({
      id: event.event_id,
      sim_time,
      severity: "medium",
      message: `Autonomous: ${payload.description as string}`,
      incident_id: "",
    });
  },

  CostRecorded: (payload) => {
    useCostStore.getState().handleCostEvent(payload);
    reconcileLiveQueries("costs");
  },
};

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const heartbeatTimer = useRef<ReturnType<typeof setTimeout>>();
  const pendingEvents = useRef<KafkaEvent[]>([]);
  const rafHandle = useRef(0);

  const dispatch = useCallback((event: KafkaEvent) => {
    const { event_type, payload, sim_time } = event;
    const handler = eventHandlers[event_type];
    if (handler) {
      handler(payload as Record<string, unknown>, sim_time, event);
    }
  }, []);

  /** Flush all pending events in a single animation frame. */
  const flushPending = useCallback(() => {
    rafHandle.current = 0;
    const batch = pendingEvents.current;
    pendingEvents.current = [];
    for (const event of batch) {
      dispatch(event);
      window.dispatchEvent(
        new MessageEvent("ws-event", { data: JSON.stringify(event) }),
      );
    }
  }, [dispatch]);

  /** Queue an event and schedule a batched flush for the next frame. */
  const enqueue = useCallback(
    (event: KafkaEvent) => {
      pendingEvents.current.push(event);
      if (!rafHandle.current) {
        rafHandle.current = requestAnimationFrame(flushPending);
      }
    },
    [flushPending],
  );

  const resetHeartbeat = useCallback(() => {
    clearTimeout(heartbeatTimer.current);
    heartbeatTimer.current = setTimeout(() => {
      // No heartbeat received — force reconnect
      wsRef.current?.close();
    }, HEARTBEAT_TIMEOUT_MS);
  }, []);

  const scheduleReconnect = useCallback((connectFn: () => void) => {
    const base = Math.min(
      RECONNECT_BASE_MS * 2 ** reconnectAttempt.current,
      RECONNECT_MAX_MS,
    );
    const delay = base * (0.75 + Math.random() * 0.5);
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
          // A paused clock emits no ticks. Load authoritative speed/pause state
          // on each connection instead of keeping the store's initial defaults.
          void simApi.status().then((value) => {
            if (wsRef.current !== ws || ws.readyState !== WebSocket.OPEN) return;
            const status = value as SimStatus & { tick_number?: number };
            useSimStore.getState().setStatus({ ...status,
              tick_count: status.tick_number ?? status.tick_count ?? 0 });
          }).catch(() => { /* The connection indicators report API failures. */ });
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
                "sim",
                "analysis",
                "costs",
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
            enqueue(data as unknown as KafkaEvent);
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
  }, [dispatch, enqueue, resetHeartbeat, scheduleReconnect]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(heartbeatTimer.current);
      cancelAnimationFrame(rafHandle.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
