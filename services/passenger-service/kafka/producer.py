"""Kafka producer for passenger-service — events to passengers.events topic."""

import json
import logging
import os
import random
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = logging.getLogger(__name__)

_producer: Producer | None = None

# During bulk tick processing, only a fraction of individual passenger events
# are produced to Kafka to avoid overwhelming the bus.  Dashboard uses REST
# APIs for authoritative counts; these events are observability / real-time hints.
_tick_batch_mode: bool = False
_TICK_EMIT_SAMPLE_RATE = 0.02  # emit ~2% of per-passenger events during tick
_bulk_mode: bool = False  # In BULK mode, suppress ALL per-passenger events

PRODUCER_NAME = "passenger-service"
TOPIC = "passengers.events"


def init_kafka_producer() -> None:
    global _producer
    _producer = Producer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "client.id": PRODUCER_NAME,
        "acks": "all",
        "retries": 3,
    })
    logger.info("Kafka producer initialized")


def close_kafka_producer() -> None:
    if _producer:
        _producer.flush(timeout=10)
        logger.info("Kafka producer flushed and closed")


def set_tick_batch_mode(enabled: bool) -> None:
    """Toggle tick batch mode to throttle per-passenger event emission."""
    global _tick_batch_mode
    _tick_batch_mode = enabled


def set_bulk_mode(enabled: bool) -> None:
    """Toggle BULK mode — suppresses ALL per-entity event emission."""
    global _bulk_mode
    _bulk_mode = enabled


def _delivery_report(err, msg):
    if err:
        logger.error("Kafka delivery failed: %s", err)


def _produce_event(
    event_type: str,
    sim_time: datetime,
    payload: dict,
    key: str | None = None,
) -> None:
    if _producer is None:
        raise RuntimeError("Kafka producer not initialized")

    envelope = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": "1.0",
        "produced_at": datetime.now(timezone.utc).isoformat(),
        "sim_time": sim_time.isoformat(),
        "producer": PRODUCER_NAME,
        "payload": payload,
    }

    # P6-1: Inject OpenTelemetry trace context into envelope
    try:
        from _tracing import get_trace_context
        ctx = get_trace_context()
        if ctx.get("trace_id"):
            envelope["trace_id"] = ctx["trace_id"]
            envelope["span_id"] = ctx["span_id"]
    except Exception:
        pass

    _producer.produce(
        topic=TOPIC,
        key=key.encode("utf-8") if key else None,
        value=json.dumps(envelope).encode("utf-8"),
        callback=_delivery_report,
    )
    _producer.poll(0)


async def emit_passenger_status_changed(
    passenger_id: str,
    name: str,
    previous_status: str,
    new_status: str,
    location_zone: str,
    sim_time: datetime,
    flight_id: str | None = None,
    flight_number: str | None = None,
) -> dict:
    """Emit PassengerStatusChanged event.

    In tick batch mode, only a fraction of events are actually produced
    to keep Kafka throughput manageable.
    """
    payload = {
        "passenger_id": passenger_id,
        "name": name,
        "flight_id": flight_id,
        "flight_number": flight_number,
        "previous_status": previous_status,
        "new_status": new_status,
        "location_zone": location_zone,
        "at": sim_time.isoformat(),
    }
    if _bulk_mode:
        return payload  # BULK mode — suppress all per-passenger events
    if _tick_batch_mode and random.random() > _TICK_EMIT_SAMPLE_RATE:
        return payload  # skip production
    _produce_event("PassengerStatusChanged", sim_time, payload, key=passenger_id)
    return payload


async def emit_passenger_alert(
    alert_type: str,
    message: str,
    sim_time: datetime,
    passenger_id: str | None = None,
    flight_id: str | None = None,
    urgency: str = "info",
) -> dict:
    """Emit PassengerAlert event."""
    payload = {
        "type": alert_type,
        "message": message,
        "passenger_id": passenger_id,
        "flight_id": flight_id,
        "urgency": urgency,
        "at": sim_time.isoformat(),
    }
    _produce_event("PassengerAlert", sim_time, payload, key=passenger_id)
    return payload


async def emit_congestion_detected(
    terminal: str,
    wait_minutes: float,
    queue_depth: int,
    sim_time: datetime,
) -> dict:
    """Emit SecurityCongestionDetected event."""
    payload = {
        "terminal": terminal,
        "wait_minutes": round(wait_minutes, 1),
        "queue_depth": queue_depth,
        "at": sim_time.isoformat(),
    }
    _produce_event("SecurityCongestionDetected", sim_time, payload, key=terminal)
    logger.warning(
        "SecurityCongestionDetected: terminal=%s wait=%.1fmin queue=%d",
        terminal, wait_minutes, queue_depth,
    )
    return payload


async def check_kafka() -> bool:
    try:
        admin = AdminClient({
            "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092")
        })
        meta = admin.list_topics(timeout=3)
        return meta is not None
    except Exception:
        return False


def emit_bulk_state_snapshot(
    sim_time: datetime,
    summary: dict,
) -> None:
    """Emit a BulkStateSnapshot event (used in BULK mode instead of per-entity events)."""
    payload = {
        "service": PRODUCER_NAME,
        "sim_time": sim_time.isoformat(),
        "summary": summary,
    }
    _produce_event("BulkStateSnapshot", sim_time, payload)


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5) -> None:
    import asyncio
    for attempt in range(1, max_attempts + 1):
        ok = await check_kafka()
        if ok:
            return
        wait = delay_s * min(attempt, 6)
        logger.warning(
            "Kafka not ready (attempt %d/%d) — retrying in %.0fs",
            attempt, max_attempts, wait,
        )
        await asyncio.sleep(wait)
    raise RuntimeError(f"Kafka not reachable after {max_attempts} attempts")
