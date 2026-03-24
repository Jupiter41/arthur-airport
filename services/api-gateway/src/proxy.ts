import { createProxyMiddleware, Options } from "http-proxy-middleware";
import { Express } from "express";
import { IncomingMessage, ServerResponse } from "http";

export const UPSTREAM: Record<string, string> = {
  flights: process.env.FLIGHT_SERVICE_URL ?? "http://flight-service:8001",
  passengers:
    process.env.PASSENGER_SERVICE_URL ?? "http://passenger-service:8002",
  baggage: process.env.BAGGAGE_SERVICE_URL ?? "http://baggage-service:8003",
  weather: process.env.WEATHER_SERVICE_URL ?? "http://weather-service:8004",
  incidents: process.env.INCIDENT_SERVICE_URL ?? "http://incident-service:8005",
  sim: process.env.SIM_ORCHESTRATOR_URL ?? "http://sim-orchestrator:8006",
};

export function setupProxy(app: Express): void {
  for (const [key, target] of Object.entries(UPSTREAM)) {
    const prefix = `/api/v1/${key}`;
    const options: Options = {
      target,
      changeOrigin: true,
      // Express strips the mount path from req.url, so we must prepend it back
      pathRewrite: (_path: string) => `${prefix}${_path}`,
      // Follow FastAPI 307 trailing-slash redirects internally
      followRedirects: true,
      on: {
        error: (
          _err: Error,
          _req: IncomingMessage,
          res: ServerResponse | import("net").Socket,
        ) => {
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

    app.use(`/api/v1/${key}`, createProxyMiddleware(options));
  }
}
