import {
  createProxyMiddleware,
  fixRequestBody,
  Options,
} from "http-proxy-middleware";
import { Express } from "express";
import { IncomingMessage, ServerResponse } from "http";
import client from "prom-client";

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
  analysis: process.env.ANALYSIS_SERVICE_URL ?? "http://analysis-service:8007",
  costs: process.env.COST_SERVICE_URL ?? "http://cost-service:8008",
  planning: process.env.PLANNING_SERVICE_URL ?? "http://planning-service:8009",
};

type ProxyRoute = {
  service: keyof typeof UPSTREAM;
  mountPath: string;
  upstreamPrefix: string;
};

const PROXY_ROUTES: ProxyRoute[] = [
  // Flight service
  {
    service: "flights",
    mountPath: "/api/v1/flights",
    upstreamPrefix: "/api/v1/flights",
  },
  {
    service: "flights",
    mountPath: "/api/v1/runways",
    upstreamPrefix: "/api/v1/runways",
  },
  {
    service: "flights",
    mountPath: "/api/v1/gates",
    upstreamPrefix: "/api/v1/gates",
  },
  {
    service: "flights",
    mountPath: "/api/v1/turnarounds",
    upstreamPrefix: "/api/v1/turnarounds",
  },
  {
    service: "flights",
    mountPath: "/api/v1/ground-vehicles",
    upstreamPrefix: "/api/v1/ground-vehicles",
  },

  // Weather service
  {
    service: "weather",
    mountPath: "/api/v1/weather",
    upstreamPrefix: "/api/v1/weather",
  },

  // Incident service
  {
    service: "incidents",
    mountPath: "/api/v1/incidents/alerts",
    upstreamPrefix: "/api/v1/alerts",
  },
  {
    service: "incidents",
    mountPath: "/api/v1/incidents",
    upstreamPrefix: "/api/v1/incidents",
  },

  // Simulation orchestrator
  {
    service: "sim",
    mountPath: "/api/v1/scenarios",
    upstreamPrefix: "/api/v1/scenarios",
  },
  { service: "sim", mountPath: "/api/v1/sim", upstreamPrefix: "/api/v1/sim" },

  // Network endpoints (sim-orchestrator)
  {
    service: "sim",
    mountPath: "/api/v1/network",
    upstreamPrefix: "/api/v1/network",
  },

  // Debug endpoints (sim-orchestrator)
  {
    service: "sim",
    mountPath: "/api/v1/debug",
    upstreamPrefix: "/api/v1/debug",
  },

  // Passenger service. Frontend namespaces these under /passengers/*.
  {
    service: "passengers",
    mountPath: "/api/v1/passengers/flow",
    upstreamPrefix: "/api/v1/flow",
  },
  {
    service: "passengers",
    mountPath: "/api/v1/passengers/connections",
    upstreamPrefix: "/api/v1/connections",
  },
  {
    service: "passengers",
    mountPath: "/api/v1/passengers/alerts",
    upstreamPrefix: "/api/v1/alerts",
  },
  {
    service: "passengers",
    mountPath: "/api/v1/passengers",
    upstreamPrefix: "/api/v1/passengers",
  },

  // Baggage service. Frontend namespaces these under /baggage/*.
  {
    service: "baggage",
    mountPath: "/api/v1/baggage/flow",
    upstreamPrefix: "/api/v1/flow",
  },
  {
    service: "baggage",
    mountPath: "/api/v1/baggage/flagged",
    upstreamPrefix: "/api/v1/flagged",
  },
  {
    service: "baggage",
    mountPath: "/api/v1/baggage",
    upstreamPrefix: "/api/v1/baggage",
  },

  // Analysis service
  {
    service: "analysis",
    mountPath: "/api/v1/analysis",
    upstreamPrefix: "/api/v1/analysis",
  },

  // Cost service
  {
    service: "costs",
    mountPath: "/api/v1/costs",
    upstreamPrefix: "/api/v1/costs",
  },

  // Planning service
  {
    service: "planning",
    mountPath: "/api/v1/planning",
    upstreamPrefix: "/api/v1/planning",
  },
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
        proxyReq: fixRequestBody,
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
