"""OpenTelemetry tracing initialisation — shared across all Python services.

Configures a TracerProvider with OTLP exporter and auto-instruments FastAPI.
Import and call ``init_tracing(app)`` in each service's ``main.py`` after
creating the FastAPI app.

Environment variables:
    OTEL_SERVICE_NAME      — logical service name (e.g. "flight-service")
    OTEL_EXPORTER_OTLP_ENDPOINT — OTLP HTTP endpoint (e.g. "http://jaeger:4318")
    OTEL_ENABLED           — set to "false" to disable tracing (default: true)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_tracer_provider = None


def init_tracing(app: "FastAPI", service_name: str | None = None) -> None:
    """Initialise OpenTelemetry tracing and instrument the FastAPI app.

    Safe to call even when tracing is disabled — becomes a no-op.
    """
    global _tracer_provider

    if os.getenv("OTEL_ENABLED", "true").lower() == "false":
        logger.info("OpenTelemetry tracing disabled (OTEL_ENABLED=false)")
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        logger.info("OpenTelemetry tracing disabled (no OTEL_EXPORTER_OTLP_ENDPOINT)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry packages not installed — tracing disabled")
        return

    name = service_name or os.getenv("OTEL_SERVICE_NAME", "unknown-service")

    resource = Resource.create({"service.name": name})
    _tracer_provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(_tracer_provider)

    FastAPIInstrumentor.instrument_app(app)

    logger.info("OpenTelemetry tracing initialised for %s → %s", name, endpoint)


def get_trace_context() -> dict[str, str]:
    """Extract current trace context as a dict for Kafka envelope injection.

    Returns a dict with ``trace_id`` and ``span_id`` keys, or empty strings
    if no active span exists.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return {
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
            }
    except Exception:
        pass
    return {"trace_id": "", "span_id": ""}


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider."""
    global _tracer_provider
    if _tracer_provider:
        _tracer_provider.shutdown()
        _tracer_provider = None
