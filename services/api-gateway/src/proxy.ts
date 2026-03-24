import { createProxyMiddleware, Options } from "http-proxy-middleware";
import { Express } from "express";
import { IncomingMessage, ServerResponse } from "http";
import client from "prom-client";

type BodyRequest = IncomingMessage & {
  body?: unknown;
};

const upstreamErrors =
  (client.register.getSingleMetric(
    "gateway_upstream_errors_total",
  ) as client.Counter) ??
  new client.Counter({
    name: "gateway_upstream_errors_total",
    help: "Upstream errors by service",
    labelNames: ["service"],
  });

export const UPSTREAM: Record<string, string> = {
  flights: process.env.FLIGHT_SERVICE_URL ?? "http://flight-service:8001",
  passengers:
    process.env.PASSENGER_SERVICE_URL ?? "http://passenger-service:8002",
  baggage: process.env.BAGGAGE_SERVICE_URL ?? "http://baggage-service:8003",
  weather: process.env.WEATHER_SERVICE_URL ?? "http://weather-service:8004",
  incidents: process.env.INCIDENT_SERVICE_URL ?? "http://incident-service:8005",
  sim: process.env.SIM_ORCHESTRATOR_URL ?? "http://sim-orchestrator:8006",
};

type ProxyRoute = {
  service: keyof typeof UPSTREAM;
  mountPath: string;
  upstreamPrefix: string;
};

const PROXY_ROUTES: ProxyRoute[] = [
  // Flight service
  { service: "flights", mountPath: "/api/v1/flights", upstreamPrefix: "/api/v1/flights" },
  { service: "flights", mountPath: "/api/v1/runways", upstreamPrefix: "/api/v1/runways" },
  { service: "flights", mountPath: "/api/v1/gates", upstreamPrefix: "/api/v1/gates" },

  // Weather service
  { service: "weather", mountPath: "/api/v1/weather", upstreamPrefix: "/api/v1/weather" },

  // Incident service
  { service: "incidents", mountPath: "/api/v1/incidents/alerts", upstreamPrefix: "/api/v1/alerts" },
  { service: "incidents", mountPath: "/api/v1/incidents", upstreamPrefix: "/api/v1/incidents" },

  // Simulation orchestrator
  { service: "sim", mountPath: "/api/v1/sim", upstreamPrefix: "/api/v1/sim" },

  // Passenger service. Frontend namespaces these under /passengers/*.
  { service: "passengers", mountPath: "/api/v1/passengers/flow", upstreamPrefix: "/api/v1/flow" },
  {
    service: "passengers",
    mountPath: "/api/v1/passengers/connections",
    upstreamPrefix: "/api/v1/connections",
  },
  { service: "passengers", mountPath: "/api/v1/passengers/alerts", upstreamPrefix: "/api/v1/alerts" },
  { service: "passengers", mountPath: "/api/v1/passengers", upstreamPrefix: "/api/v1/passengers" },

  // Baggage service. Frontend namespaces these under /baggage/*.
  { service: "baggage", mountPath: "/api/v1/baggage/flow", upstreamPrefix: "/api/v1/flow" },
  { service: "baggage", mountPath: "/api/v1/baggage/flagged", upstreamPrefix: "/api/v1/flagged" },
  { service: "baggage", mountPath: "/api/v1/baggage", upstreamPrefix: "/api/v1/baggage" },
];

function joinPath(base: string, suffix: string): string {
  if (!suffix || suffix === "/") {
    return base;
  }
  return `${base.replace(/\/+$/, "")}/${suffix.replace(/^\/+/, "")}`;
}

export function setupProxy(app: Express): void {
  for (const route of PROXY_ROUTES) {
    const target = UPSTREAM[route.service];
    const key = route.service;
    const options: Options = {
      target,
      changeOrigin: true,
      // Express strips mount path from req.url, rebuild with desired upstream prefix.
      pathRewrite: (_path: string) => joinPath(route.upstreamPrefix, _path),
      // Follow FastAPI 307 trailing-slash redirects internally
      followRedirects: true,
      on: {
        proxyReq: (proxyReq, req) => {
          const request = req as BodyRequest;
          const body = request.body;
          if (!body || typeof body !== "object") {
            return;
          }

          const bodyData = JSON.stringify(body);
          proxyReq.setHeader("Content-Type", "application/json");
          proxyReq.setHeader("Content-Length", Buffer.byteLength(bodyData));
          proxyReq.write(bodyData);
        },
        error: (
          _err: Error,
          _req: IncomingMessage,
          res: ServerResponse | import("net").Socket,
        ) => {
          upstreamErrors.inc({ service: key });
          if ("writeHead" in res && !res.headersSent) {
            res.writeHead(502, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                error: `${key} service unavailable`,
                service: key,
              }),
            );
          }
        },
      },
    };

    app.use(route.mountPath, createProxyMiddleware(options));
  }
}
