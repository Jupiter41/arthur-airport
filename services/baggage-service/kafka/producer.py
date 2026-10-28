"""Kafka producer for baggage-service — baggage events to baggage.events topic."""

import logging
from datetime import datetime

from confluent_kafka import Producer

from _common import kafka_runtime

logger = logging.getLogger(__name__)

_producer: Producer | None = None
_bulk_mode: bool = False  # In BULK mode, suppress per-bag events

PRODUCER_NAME = "baggage-service"
TOPIC = "baggage.events"


def init_kafka_producer() -> None:
    global _producer
    _producer = kafka_runtime.init_producer(PRODUCER_NAME)


def close_kafka_producer() -> None:
    kafka_runtime.close_producer(_producer)


def set_bulk_mode(enabled: bool) -> None:
    """Toggle BULK mode — suppresses per-bag event emission."""
    global _bulk_mode
    _bulk_mode = enabled


def _produce_event(
    event_type: str,
    sim_time: datetime,
    payload: dict,
    key: str | None = None,
) -> None:
    kafka_runtime.produce_event(
        _producer, event_type, sim_time, payload,
        producer_name=PRODUCER_NAME, topic=TOPIC, key=key,
    )


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


def emit_zone_snapshot(payload: dict, sim_time: datetime) -> None:
    """Aggregate facts are never suppressed by per-bag BULK sampling."""
    _produce_event("BaggageZoneSnapshot", sim_time, payload, key="zones")


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
    return kafka_runtime.check_kafka()


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
    await kafka_runtime.wait_for_kafka(max_attempts=max_attempts, delay_s=delay_s)
