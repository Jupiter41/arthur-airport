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

import { NodeSDK } from "@opentelemetry/sdk-node";
import { getNodeAutoInstrumentations } from "@opentelemetry/auto-instrumentations-node";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { Resource } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";

const enabled = (process.env.OTEL_ENABLED ?? "true") !== "false";
const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;

let sdk: NodeSDK | undefined;

if (enabled && endpoint) {
  const exporter = new OTLPTraceExporter({
    url: `${endpoint}/v1/traces`,
  });

  sdk = new NodeSDK({
    resource: new Resource({
      [ATTR_SERVICE_NAME]: process.env.OTEL_SERVICE_NAME ?? "api-gateway",
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
