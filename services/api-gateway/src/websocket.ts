import { WebSocketServer, WebSocket } from "ws";
import { IncomingMessage, Server } from "http";
import { verifyTokenFromRequest } from "./auth";
import { Request } from "express";
import client from "prom-client";

// Prometheus metrics
const wsConnectionsGauge = new client.Gauge({
  name: "gateway_ws_connections_active",
  help: "Active WebSocket connections",
});

const wsEventsForwarded = new client.Counter({
  name: "gateway_ws_events_forwarded_total",
  help: "Events forwarded to WebSocket clients",
  labelNames: ["topic"],
});

interface WsClient {
  ws: WebSocket;
  subscriptions: Set<string>;
  alive: boolean;
}

const VALID_TOPICS = new Set([
  "flights",
  "passengers",
  "baggage",
  "weather",
  "incidents",
  "alerts",
  "sim",
]);

const clients = new Set<WsClient>();
let currentSimTime: string | null = null;

export function setCurrentSimTime(simTime: string): void {
  currentSimTime = simTime;
}

export function getCurrentSimTime(): string | null {
  return currentSimTime;
}

export function fanOut(topicKey: string, event: object): void {
  const payload = JSON.stringify(event);

  for (const client of clients) {
    if (
      client.subscriptions.has(topicKey) &&
      client.ws.readyState === WebSocket.OPEN
    ) {
      client.ws.send(payload);
      wsEventsForwarded.inc({ topic: topicKey });
    }
  }
}

export function setupWebSocket(server: Server): void {
  const wss = new WebSocketServer({
    server,
    path: "/ws",
    verifyClient: (
      info: { req: IncomingMessage },
      callback: (result: boolean, code?: number, message?: string) => void,
    ) => {
      const valid = verifyTokenFromRequest(info.req as unknown as Request);
      if (!valid) {
        callback(false, 401, "Unauthorized");
      } else {
        callback(true);
      }
    },
  });

  wss.on("connection", (ws: WebSocket, _req: IncomingMessage) => {
    const client: WsClient = {
      ws,
      subscriptions: new Set(),
      alive: true,
    };
    clients.add(client);
    wsConnectionsGauge.set(clients.size);

    // Send initial snapshot
    ws.send(
      JSON.stringify({
        type: "snapshot",
        sim_time: currentSimTime,
      }),
    );

    ws.on("message", (raw: Buffer) => {
      try {
        const msg = JSON.parse(raw.toString());

        if (msg.action === "subscribe" && Array.isArray(msg.topics)) {
          for (const t of msg.topics) {
            if (typeof t === "string" && VALID_TOPICS.has(t)) {
              client.subscriptions.add(t);
            }
          }
          ws.send(
            JSON.stringify({
              type: "subscribed",
              topics: Array.from(client.subscriptions),
            }),
          );
        }

        if (msg.action === "unsubscribe" && Array.isArray(msg.topics)) {
          for (const t of msg.topics) {
            client.subscriptions.delete(t);
          }
          ws.send(
            JSON.stringify({
              type: "subscribed",
              topics: Array.from(client.subscriptions),
            }),
          );
        }

        if (msg.type === "pong") {
          client.alive = true;
        }
      } catch {
        // Ignore malformed frames
      }
    });

    ws.on("pong", () => {
      client.alive = true;
    });

    ws.on("close", () => {
      clients.delete(client);
      wsConnectionsGauge.set(clients.size);
    });

    ws.on("error", () => {
      clients.delete(client);
      wsConnectionsGauge.set(clients.size);
    });
  });

  // Heartbeat every 15 real seconds
  const heartbeatMs = parseInt(
    process.env.WS_HEARTBEAT_INTERVAL_MS ?? "15000",
    10,
  );

  const heartbeatInterval = setInterval(() => {
    for (const client of clients) {
      if (!client.alive) {
        client.ws.terminate();
        clients.delete(client);
        wsConnectionsGauge.set(clients.size);
        continue;
      }

      client.alive = false;
      if (client.ws.readyState === WebSocket.OPEN) {
        // Send application-level ping
        client.ws.send(
          JSON.stringify({ type: "ping", sim_time: currentSimTime }),
        );
        // Also send WebSocket protocol-level ping
        client.ws.ping();
      }
    }
  }, heartbeatMs);

  // Clean up on server close
  wss.on("close", () => {
    clearInterval(heartbeatInterval);
  });
}
