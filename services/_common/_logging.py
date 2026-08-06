"""Structured logging setup — shared across all Python services.

Configures structlog to emit JSON log lines with trace context, service name,
and standard fields. Replaces ``logging.basicConfig()`` in each service's
``main.py``.

Usage:
    from _common._logging import setup_logging
    setup_logging("flight-service")
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def _add_trace_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict,
) -> dict:
    """Inject OpenTelemetry trace_id and span_id into every log line."""
    try:
        from _common._tracing import get_trace_context

        ctx = get_trace_context()
        if ctx.get("trace_id"):
            event_dict["trace_id"] = ctx["trace_id"]
            event_dict["span_id"] = ctx["span_id"]
    except Exception:
        pass
    return event_dict


def setup_logging(service_name: str) -> None:
    """Configure structlog with JSON output and stdlib integration.

    All existing stdlib loggers are re-routed through structlog's processing
    pipeline, producing consistent JSON output on stdout.
    """
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    # Shared processors for both structlog and stdlib
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _add_trace_context,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Suppress noisy loggers
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    logging.getLogger("neo4j.io").setLevel(logging.WARNING)

    # Bind service name globally
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)

    logger = structlog.get_logger(service_name)
    logger.info("structured logging initialised", log_level=os.getenv("LOG_LEVEL", "INFO"))
