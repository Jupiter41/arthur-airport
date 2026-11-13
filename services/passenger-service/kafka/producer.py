"""Kafka producer for passenger-service — events to passengers.events topic."""

import json
import logging
import random
import time
from datetime import datetime

from confluent_kafka import Producer

from _common import kafka_runtime
from _common.kafka_runtime import build_envelope

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


def tick_emit_decision() -> bool:
    """Whether one per-passenger tick fact should be materialised now (G1-a).

    Honours the same BULK / tick-batch sampling as ``emit_passenger_status_changed``
    so the atomic tick path stages only the fraction of ``PassengerStatusChanged``
    facts that the direct-emit path used to produce. The authoritative domain
    write is always applied in full; the per-passenger event stream stays sampled
    to keep Kafka throughput manageable during fast-forward.
    """
    if _bulk_mode:
        return False
    if _tick_batch_mode and random.random() > _TICK_EMIT_SAMPLE_RATE:
        return False
    return True


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


def build_passenger_status_changed_fact(
    passenger_id: str,
    name: str,
    previous_status: str,
    new_status: str,
    location_zone: str,
    sim_time: datetime,
    flight_id: str | None = None,
    flight_number: str | None = None,
) -> dict:
    """Build a full PassengerStatusChanged envelope for the transactional outbox.

    Identical payload shape to ``emit_passenger_status_changed`` but produces no
    Kafka message — the envelope is persisted in ``PassengerOutbox`` and later
    delivered by ``_common.outbox.run`` via ``publish_confirmed`` (G1).
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
    return build_envelope("PassengerStatusChanged", sim_time, payload, PRODUCER_NAME)


def build_passenger_alert_fact(
    alert_type: str,
    message: str,
    sim_time: datetime,
    passenger_id: str | None = None,
    flight_id: str | None = None,
    urgency: str = "info",
) -> dict:
    """Build a full PassengerAlert envelope for the transactional outbox (G1-c).

    Same payload shape as ``emit_passenger_alert`` but produces no Kafka message —
    the envelope is staged in ``PassengerOutbox`` alongside the domain
    ``PassengerStatusChanged`` fact so that the state change and its alert commit
    (or roll back) together, then deliver via ``_common.outbox.run``.
    """
    payload = {
        "type": alert_type,
        "message": message,
        "passenger_id": passenger_id,
        "flight_id": flight_id,
        "urgency": urgency,
        "at": sim_time.isoformat(),
    }
    return build_envelope("PassengerAlert", sim_time, payload, PRODUCER_NAME)


def build_command_receipt_fact(
    event_type: str,
    sim_time: datetime,
    payload: dict,
) -> dict:
    """Build an owner command-receipt envelope for the outbox (G1-b).

    ``event_type`` is ``CommandExecuted`` or ``CommandRejected``. The receipt
    fact is staged in the same transaction as the command's domain write and
    domain fact, so an owner receipt is never emitted without the state change
    it describes (and vice versa). The envelope gets a fresh ``event_id`` on
    every call; downstream consumers dedup on the stable ``command_id`` carried
    in the payload, so re-emitting on redelivery is safe.
    """
    return build_envelope(event_type, sim_time, dict(payload), PRODUCER_NAME)


def publish_confirmed(document: dict) -> None:
    """Blocking produce of one outbox fact; RAISE unless the broker acks in time.

    Mirrors cost-service's ``publish_confirmed``: the outbox delivery loop calls
    this off-loop (``asyncio.to_thread``) and keeps the row when it raises, so an
    unconfirmed fact is retained rather than silently dropped.
    """
    if _producer is None:
        raise RuntimeError("Passenger event producer unavailable; outbox retained")
    delivered: list = []
    payload = document.get("payload") or {}
    key = payload.get("passenger_id") or payload.get("terminal") or document.get("event_id") or ""
    _producer.produce(
        topic=TOPIC,
        key=key.encode("utf-8") if key else None,
        value=json.dumps(document).encode("utf-8"),
        callback=lambda error, message: delivered.append(error),
    )
    deadline = time.monotonic() + 10
    while not delivered and time.monotonic() < deadline:
        _producer.poll(0.1)
    if not delivered or delivered[0] is not None:
        raise RuntimeError("Passenger broker acknowledgement unavailable; outbox retained")


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
    from _common.events import SecurityQueueUpdatedPayload

    payload = SecurityQueueUpdatedPayload.model_validate({
        "terminal": terminal, "queue_depth": queue_depth,
        "lanes_open": lanes_open, "wait_minutes": round(wait_minutes, 1),
        "at": sim_time.isoformat(),
    }).model_dump(mode="json")
    _produce_event("SecurityQueueUpdated", sim_time, payload, key=terminal)


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
