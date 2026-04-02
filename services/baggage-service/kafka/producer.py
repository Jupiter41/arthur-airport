"""Kafka producer for baggage-service — baggage events to baggage.events topic."""

import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = logging.getLogger(__name__)

_producer: Producer | None = None
_bulk_mode: bool = False  # In BULK mode, suppress per-bag events

PRODUCER_NAME = "baggage-service"
TOPIC = "baggage.events"


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


def set_bulk_mode(enabled: bool) -> None:
    """Toggle BULK mode — suppresses per-bag event emission."""
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
        "produced_at": datetime.utcnow().isoformat(),
        "sim_time": sim_time.isoformat(),
        "producer": PRODUCER_NAME,
        "payload": payload,
    }

    _producer.produce(
        topic=TOPIC,
        key=key.encode("utf-8") if key else None,
        value=json.dumps(envelope).encode("utf-8"),
        callback=_delivery_report,
    )
    _producer.poll(0)


async def emit_baggage_status_changed(
    baggage_id: str,
    tag: str,
    previous_status: str,
    new_status: str,
    scan_zone: str,
    sim_time: datetime,
    passenger_id: str | None = None,
    flight_id: str | None = None,
) -> dict:
    """Emit BaggageStatusChanged event. Returns the envelope payload."""
    payload = {
        "baggage_id": baggage_id,
        "tag": tag,
        "passenger_id": passenger_id,
        "flight_id": flight_id,
        "previous_status": previous_status,
        "new_status": new_status,
        "scan_zone": scan_zone,
        "at": sim_time.isoformat(),
    }
    if _bulk_mode:
        return payload  # BULK mode — suppress per-bag events
    _produce_event("BaggageStatusChanged", sim_time, payload, key=tag)
    logger.debug(
        "Emitted BaggageStatusChanged: %s %s -> %s @ %s",
        tag, previous_status, new_status, scan_zone,
    )
    return payload


async def emit_baggage_flagged(
    baggage_id: str,
    tag: str,
    flag_reason: str,
    scan_zone: str,
    sim_time: datetime,
    dg_class: str | None = None,
    passenger_id: str | None = None,
    flight_id: str | None = None,
) -> dict:
    """Emit BaggageFlagged event. Returns the envelope payload."""
    payload = {
        "baggage_id": baggage_id,
        "tag": tag,
        "passenger_id": passenger_id,
        "flight_id": flight_id,
        "flag_reason": flag_reason,
        "dg_class": dg_class,
        "scan_zone": scan_zone,
        "at": sim_time.isoformat(),
    }
    _produce_event("BaggageFlagged", sim_time, payload, key=tag)
    logger.info(
        "Emitted BaggageFlagged: %s reason=%s dg_class=%s @ %s",
        tag, flag_reason, dg_class, scan_zone,
    )
    return payload


async def emit_conveyor_delay(
    zone_id: str,
    terminal: str,
    items: int,
    capacity: int,
    overflow: int,
    estimated_delay_min: float,
    sim_time: datetime,
) -> dict:
    """Emit baggage.conveyor.delay event when a make-up zone is overloaded (GAP-4-6)."""
    payload = {
        "zone_id": zone_id,
        "terminal": terminal,
        "items": items,
        "capacity": capacity,
        "overflow": overflow,
        "estimated_delay_min": estimated_delay_min,
        "at": sim_time.isoformat(),
    }
    _produce_event("ConveyorDelay", sim_time, payload)
    logger.warning(
        "Emitted ConveyorDelay: zone=%s overflow=%d delay=%.1fmin",
        zone_id, overflow, estimated_delay_min,
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
    """Emit a BulkStateSnapshot event (used in BULK mode instead of per-bag events)."""
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
