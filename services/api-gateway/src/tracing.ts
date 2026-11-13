/**
 * OpenTelemetry tracing setup for the API gateway (P6-1).
 *
 * Must be imported BEFORE any other module to ensure all HTTP/Express
 * handlers are automatically instrumented.
 *
 * Environment variables:
 *   OTEL_EXPORTER_OTLP_ENDPOINT  — e.g. "http://jaeger:4318"
 *   OTEL_SERVICE_NAME             — e.g. "api-gateway"
 *   OTEL_ENABLED                  — set to "false" to disable (default: true)
 */

import type { NodeSDK as SDK } from "@opentelemetry/sdk-node";

const enabled = (process.env.OTEL_ENABLED ?? "true") !== "false";
const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;

let sdk: SDK | undefined;

if (enabled && endpoint) {
  // Avoid loading hundreds of instrumentation modules on the Pi when tracing
  // is disabled. Imports remain before Express when tracing is enabled.
  const { NodeSDK } = require("@opentelemetry/sdk-node") as typeof import("@opentelemetry/sdk-node");
  const { getNodeAutoInstrumentations } = require("@opentelemetry/auto-instrumentations-node") as typeof import("@opentelemetry/auto-instrumentations-node");
  const { OTLPTraceExporter } = require("@opentelemetry/exporter-trace-otlp-http") as typeof import("@opentelemetry/exporter-trace-otlp-http");
  const { resourceFromAttributes } = require("@opentelemetry/resources") as typeof import("@opentelemetry/resources");
  const exporter = new OTLPTraceExporter({
    url: `${endpoint}/v1/traces`,
  });

  sdk = new NodeSDK({
    resource: resourceFromAttributes({
      "service.name": process.env.OTEL_SERVICE_NAME ?? "api-gateway",
    }),
    traceExporter: exporter,
    instrumentations: [
      getNodeAutoInstrumentations({
        "@opentelemetry/instrumentation-fs": { enabled: false },
      }),
    ],
  });

  sdk.start();
  console.log(
    `[otel] Tracing initialised for ${process.env.OTEL_SERVICE_NAME ?? "api-gateway"} → ${endpoint}`,
  );
} else {
  console.log("[otel] Tracing disabled (OTEL_ENABLED=false or no endpoint)");
}

export function shutdownTracing(): Promise<void> {
  if (sdk) return sdk.shutdown();
  return Promise.resolve();
}
