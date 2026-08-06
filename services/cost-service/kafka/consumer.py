"""Kafka consumer for cost-service — subscribes to domain events and triggers cost calculations."""

import asyncio
import json
import os

import structlog
from confluent_kafka import Consumer

from _common.consumer_health import ConsumerHealthTracker
from _common.idempotency import IdempotencyTracker

logger = structlog.get_logger(__name__)

TOPICS = [
    "sim.clock",
    "flights.events",
    "incidents.events",
    "baggage.events",
    "passengers.events",
]

_consumer: Consumer | None = None
_running: bool = False
_rates: dict = {}
_carbon_factors: dict = {}
_consumer_health = ConsumerHealthTracker()
# Deduplicate by envelope event_id — Kafka delivers at-least-once, so a
# redelivered event must not re-run cost/revenue mutations (double-counting).
_idempotency = IdempotencyTracker()


def reset_idempotency() -> None:
    """Test helper — clear the seen-event-id set."""
    _idempotency.clear()


def set_rates(rates: dict) -> None:
    global _rates
    _rates = rates


def set_carbon_factors(factors: dict) -> None:
    global _carbon_factors
    _carbon_factors = factors


def make_consumer() -> Consumer:
    brokers = os.getenv("KAFKA_BROKERS", "kafka:9092")
    return Consumer({
        "bootstrap.servers": brokers,
        "group.id": "cost-service",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })


async def process_envelope(envelope: dict) -> bool:
    """Dispatch one decoded event envelope to the cost/carbon handlers.

    Idempotent by envelope ``event_id``: a redelivered event (Kafka is
    at-least-once) is dropped *before* any state mutation, so cost and revenue
    running totals are never double-counted on redelivery.

    Returns ``True`` if the event was dispatched, ``False`` if it was skipped
    as a duplicate. Unhandled event types still count as dispatched (``True``).
    """
    from services.cost_engine import (
        on_clock_tick,
        on_flight_cancelled,
        on_flight_status_changed,
        on_incident_created,
        on_incident_resolved,
    )
    from services import carbon_tracker

    event_id = envelope.get("event_id", "")
    if _idempotency.is_duplicate(event_id):
        logger.debug(
            "duplicate event skipped",
            event_id=event_id,
            event_type=envelope.get("event_type"),
        )
        return False

    event_type = envelope.get("event_type", "")
    sim_time = envelope.get("sim_time", "")
    payload = envelope.get("payload", {})
    sim_day = payload.get("day_of_sim", 1)

    match event_type:
        case "SimClockTick":
            sim_day = payload.get("day_of_sim", 1)
            await on_clock_tick(payload, sim_time, sim_day, _rates)
            if _carbon_factors:
                await carbon_tracker.on_clock_tick(payload, sim_time, sim_day, _carbon_factors, _rates)
        case "FlightStatusChanged":
            await on_flight_status_changed(payload, sim_time, sim_day, _rates)
            # Carbon: emit flight + APU + ground vehicle on departed
            new_status = payload.get("new_status") or payload.get("status")
            if new_status == "departed" and _carbon_factors:
                from db.neo4j import get_flight_info as _get_fi
                flight = await _get_fi(payload.get("flight_id"))
                if flight and flight.get("direction", "departure") == "departure":
                    await carbon_tracker.on_flight_departed(flight, sim_time, sim_day, _carbon_factors)
        case "FlightCancelled":
            await on_flight_cancelled(payload, sim_time, sim_day, _rates)
        case "IncidentCreated":
            await on_incident_created(payload, sim_time, sim_day, _rates)
        case "IncidentStatusChanged":
            await on_incident_resolved(payload, sim_time, sim_day, _rates)
        case _:
            pass
    return True


async def run_consumer() -> None:
    global _consumer, _running

    _consumer = make_consumer()
    _consumer.subscribe(TOPICS)
    _running = True
    logger.info("kafka consumer started", topics=TOPICS, group="cost-service")

    loop = asyncio.get_event_loop()
    msg_count = 0

    while _running:
        msg = await loop.run_in_executor(None, lambda: _consumer.poll(1.0))
        if msg is None:
            continue
        if msg.error():
            logger.warning("kafka consumer error", error=str(msg.error()))
            continue

        msg_count += 1
        if msg_count <= 3 or msg_count % 100 == 0:
            logger.info("kafka message received", count=msg_count, topic=msg.topic())

        try:
            envelope = json.loads(msg.value().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("bad message", error=str(exc))
            continue

        _consumer_health.mark_message()

        try:
            await process_envelope(envelope)
        except Exception:
            logger.exception("error processing event", event_type=envelope.get("event_type", ""))


def stop_consumer() -> None:
    global _running, _consumer
    _running = False
    if _consumer:
        _consumer.close()
        _consumer = None


def is_consumer_running() -> bool:
    return _running


def get_consumer_health() -> dict:
    return _consumer_health.status()
