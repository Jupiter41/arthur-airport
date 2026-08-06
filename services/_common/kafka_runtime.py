"""Shared Kafka producer lifecycle + standard event-envelope emission.

Every producing service copy-pasted the same three things: producer creation
(``acks=all``, retries), a ``_produce_event`` that wraps a domain payload in the
common envelope (``event_id``/``event_type``/``schema_version``/``produced_at``/
``sim_time``/``producer``/``payload`` + injected trace context), and a flush on
shutdown. Only the topic names and the typed ``emit_*`` helpers differ per
service. This module owns the generic parts; a service keeps its ``emit_*``
functions and delegates transport here.

Usage (in a service's ``kafka/producer.py``):

    from _common import kafka_runtime

    _producer = None
    def init_kafka_producer():
        global _producer
        _producer = kafka_runtime.init_producer("flight-service")
    def _produce_event(event_type, sim_time, payload, key=None, topic=None):
        kafka_runtime.produce_event(
            _producer, event_type, sim_time, payload,
            producer_name="flight-service", topic=topic or "flights.events", key=key,
        )
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Producer

logger = logging.getLogger(__name__)


def init_producer(name: str, brokers: str | None = None) -> Producer:
    """Create a confluent-kafka Producer with the standard delivery guarantees."""
    producer = Producer(
        {
            "bootstrap.servers": brokers or os.getenv("KAFKA_BROKERS", "kafka:9092"),
            "client.id": name,
            "acks": "all",
            "retries": 3,
        }
    )
    logger.info("Kafka producer initialized", extra={"producer": name})
    return producer


def close_producer(producer: Producer | None) -> None:
    """Flush pending messages and shut down the producer."""
    if producer is not None:
        producer.flush(timeout=10)
        logger.info("Kafka producer flushed and closed")


def _default_delivery_report(err, msg) -> None:
    if err:
        logger.error("Kafka delivery failed: %s", err)


def build_envelope(
    event_type: str,
    sim_time: datetime,
    payload: dict,
    producer_name: str,
) -> dict:
    """Build the standard event envelope, injecting OTel trace context if present.

    ``produced_at`` is a real wall-clock timestamp (transport metadata); business
    time is carried in ``sim_time`` per the architecture rules.
    """
    envelope = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": "1.0",
        "produced_at": datetime.now(timezone.utc).isoformat(),
        "sim_time": sim_time.isoformat(),
        "producer": producer_name,
        "payload": payload,
    }
    try:
        from _common._tracing import get_trace_context

        ctx = get_trace_context()
        if ctx.get("trace_id"):
            envelope["trace_id"] = ctx["trace_id"]
            envelope["span_id"] = ctx["span_id"]
    except Exception:
        pass
    return envelope


def produce_event(
    producer: Producer | None,
    event_type: str,
    sim_time: datetime,
    payload: dict,
    *,
    producer_name: str,
    topic: str,
    key: str | None = None,
    on_delivery=None,
) -> None:
    """Wrap ``payload`` in the standard envelope and produce it to ``topic``."""
    if producer is None:
        raise RuntimeError("Kafka producer not initialized")

    envelope = build_envelope(event_type, sim_time, payload, producer_name)
    producer.produce(
        topic=topic,
        key=key.encode("utf-8") if key else None,
        value=json.dumps(envelope).encode("utf-8"),
        callback=on_delivery or _default_delivery_report,
    )
    producer.poll(0)
