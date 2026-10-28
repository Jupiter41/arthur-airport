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
from typing import TYPE_CHECKING, Awaitable, Callable
from uuid import uuid4

if TYPE_CHECKING:
    from confluent_kafka import Consumer, Producer

logger = logging.getLogger(__name__)


def init_producer(name: str, brokers: str | None = None) -> Producer:
    """Create a confluent-kafka Producer with the standard delivery guarantees."""
    from confluent_kafka import Producer  # runtime import — not available in tests
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


def check_kafka(brokers: str | None = None) -> bool:
    """Return True if the Kafka broker is reachable via AdminClient."""
    try:
        from confluent_kafka.admin import AdminClient
        admin = AdminClient({"bootstrap.servers": brokers or os.getenv("KAFKA_BROKERS", "kafka:9092")})
        return admin.list_topics(timeout=3) is not None
    except Exception:
        return False


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5, brokers: str | None = None) -> None:
    """Retry until the Kafka broker is reachable or attempts are exhausted."""
    import asyncio
    for attempt in range(1, max_attempts + 1):
        if check_kafka(brokers):
            logger.info("Kafka broker reachable")
            return
        wait = delay_s * min(attempt, 6)
        logger.warning(
            "Kafka not ready (attempt %d/%d) — retrying in %.0fs",
            attempt, max_attempts, wait,
        )
        await asyncio.sleep(wait)
    raise RuntimeError(f"Kafka not reachable after {max_attempts} attempts")


async def run_consumer_loop(
    consumer: Consumer,
    dispatch: Callable[[dict], Awaitable[None]],
    should_run: Callable[[], bool],
    health: object | None = None,
    *,
    batch_size: int = 200,
    timeout: float = 1.0,
) -> None:
    """Poll Kafka, dedup clock ticks, and dispatch each batch.

    Implements the canonical Arthur Airport consumer pattern used by services
    that consume both sim.clock ticks and domain events:

    - Batch-poll ``consumer`` on a thread executor.
    - Keep only the *latest* SimClockTick in each batch (drop stale ticks).
    - Dispatch domain events first, then the single clock tick.
    - Mark ``health`` after each non-empty batch.
    - Close ``consumer`` in the finally block regardless of exit path.

    The caller owns the running flag: set it to False (via ``stop_consumer()``)
    to exit the loop after the current poll cycle.

    Not suitable for consumers that need per-message retry, manual offset commit,
    or a separate command-consumer task (cost-service, analysis-service,
    passenger-service command consumer).
    """
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        while should_run():
            msgs = await loop.run_in_executor(
                None, lambda: consumer.consume(batch_size, timeout=timeout)
            )
            if not msgs:
                continue
            latest_tick: dict | None = None
            others: list[dict] = []
            skipped = 0
            for msg in msgs:
                if msg is None or msg.error():
                    continue
                try:
                    envelope = json.loads(msg.value().decode("utf-8"))
                except Exception:
                    continue
                if envelope.get("event_type") == "SimClockTick":
                    if latest_tick is not None:
                        skipped += 1
                    latest_tick = envelope
                else:
                    others.append(envelope)
            if skipped:
                logger.debug("Skipped %d stale SimClockTick(s)", skipped)
            for envelope in others:
                try:
                    await dispatch(envelope)
                except Exception:
                    logger.error("Consumer dispatch error", exc_info=True)
            if latest_tick is not None:
                try:
                    await dispatch(latest_tick)
                except Exception:
                    logger.error("Consumer dispatch error (SimClockTick)", exc_info=True)
            if health is not None:
                health.mark_message()
    finally:
        consumer.close()
        logger.info("Kafka consumer closed")
