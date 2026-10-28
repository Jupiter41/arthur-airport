"""Kafka producer for passenger-service — events to passengers.events topic."""

import logging
import random
from datetime import datetime

from confluent_kafka import Producer

from _common import kafka_runtime

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
    _producer = kafka_runtime.init_producer(PRODUCER_NAME)


def close_kafka_producer() -> None:
    kafka_runtime.close_producer(_producer)


def set_tick_batch_mode(enabled: bool) -> None:
    """Toggle tick batch mode to throttle per-passenger event emission."""
    global _tick_batch_mode
    _tick_batch_mode = enabled


def set_bulk_mode(enabled: bool) -> None:
    """Toggle BULK mode — suppresses ALL per-entity event emission."""
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


def emit_security_queue_updated(
    terminal: str, queue_depth: int, lanes_open: int,
    wait_minutes: float, sim_time: datetime,
) -> None:
    """An authoritative aggregate; never sample individual queue snapshots."""
    _produce_event("SecurityQueueUpdated", sim_time, {
        "terminal": terminal, "queue_depth": queue_depth,
        "lanes_open": lanes_open, "wait_minutes": round(wait_minutes, 1),
        "at": sim_time.isoformat(),
    }, key=terminal)


# ── 1C — Accessibility events ────────────────────────────────────────────


async def emit_wheelchair_dispatched(
    *,
    assignment_id: str,
    passenger_id: str,
    terminal: str,
    flight_id: str | None,
    wait_minutes: float,
    sim_time: datetime,
) -> dict:
    """Emit WheelchairDispatched event."""
    payload = {
        "assignment_id": assignment_id,
        "passenger_id": passenger_id,
        "terminal": terminal,
        "flight_id": flight_id,
        "wait_minutes": round(wait_minutes, 2),
        "at": sim_time.isoformat(),
    }
    _produce_event("WheelchairDispatched", sim_time, payload, key=passenger_id)
    return payload


async def emit_wheelchair_returned(
    *,
    assignment_id: str,
    passenger_id: str,
    terminal: str,
    sla_met: bool,
    sim_time: datetime,
) -> dict:
    """Emit WheelchairReturned event."""
    payload = {
        "assignment_id": assignment_id,
        "passenger_id": passenger_id,
        "terminal": terminal,
        "sla_met": bool(sla_met),
        "at": sim_time.isoformat(),
    }
    _produce_event("WheelchairReturned", sim_time, payload, key=passenger_id)
    return payload


async def check_kafka() -> bool:
    return kafka_runtime.check_kafka()


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
    await kafka_runtime.wait_for_kafka(max_attempts=max_attempts, delay_s=delay_s)
