"""Kafka consumer for cost-service — subscribes to domain events and triggers cost calculations."""

import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime

import structlog
from confluent_kafka import Consumer

from _common.consumer_health import ConsumerHealthTracker
from services import ledger

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
_carbon_factors: dict = {}
_consumer_health = ConsumerHealthTracker()
HANDLED_EVENTS = {"SimClockTick", "FlightStatusChanged", "FlightCancelled",
                  "IncidentCreated", "IncidentStatusChanged"}


def set_carbon_factors(factors: dict) -> None:
    global _carbon_factors
    _carbon_factors = factors


def make_consumer() -> Consumer:
    brokers = os.getenv("KAFKA_BROKERS", "kafka:9092")
    return Consumer({
        "bootstrap.servers": brokers,
        "group.id": "cost-service",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "session.timeout.ms": 10000,
    })


async def process_envelope(envelope: dict) -> bool:
    """Commit all financial effects and input identity together, or none."""
    decoded = ledger.FinancialEnvelope.model_validate(envelope).model_dump(mode="json")
    if decoded["event_type"] not in HANDLED_EVENTS:
        return True
    factors = deepcopy(_carbon_factors)

    async def dispatch(event: dict) -> None:
        batch = ledger.current_batch.get()
        await _dispatch(event, batch.state["rates"], factors)

    return await ledger.process(decoded, dispatch)


async def _dispatch(envelope: dict, rates: dict, factors: dict) -> None:
    from services.cost_engine import (
        on_clock_tick,
        on_flight_cancelled,
        on_flight_status_changed,
        on_incident_created,
        on_incident_resolved,
    )
    from services import carbon_tracker

    event_type = envelope.get("event_type", "")
    sim_time = envelope.get("sim_time", "")
    payload = envelope.get("payload", {})
    batch = ledger.current_batch.get()
    sim_day = payload.get("day_of_sim", batch.state["sim_day"] if batch else 1)
    if "day_of_sim" not in payload and batch and batch.state.get("clock_date"):
        date = datetime.fromisoformat(sim_time).date()
        reference = datetime.fromisoformat(batch.state["clock_date"]).date()
        sim_day += (date - reference).days
    if batch is not None:
        batch.billing_day = sim_day

    match event_type:
        case "SimClockTick":
            await on_clock_tick(payload, sim_time, sim_day, rates)
            if factors:
                await carbon_tracker.on_clock_tick(payload, sim_time, sim_day, factors, rates)
        case "FlightStatusChanged":
            await on_flight_status_changed(payload, sim_time, sim_day, rates)
            # Carbon: emit flight + APU + ground vehicle on departed
            new_status = payload.get("new_status") or payload.get("status")
            if new_status == "departed" and factors:
                from db.neo4j import get_flight_info as _get_fi
                flight = await _get_fi(payload.get("flight_id"))
                if flight and flight.get("direction", "departure") == "departure":
                    await carbon_tracker.on_flight_departed(flight, sim_time, sim_day, factors)
        case "FlightCancelled":
            await on_flight_cancelled(payload, sim_time, sim_day, rates)
        case "IncidentCreated":
            await on_incident_created(payload, sim_time, sim_day, rates)
        case "IncidentStatusChanged":
            await on_incident_resolved(payload, sim_time, sim_day, rates)
        case _:
            pass


async def run_consumer() -> None:
    global _consumer, _running

    _consumer = make_consumer()
    _consumer.subscribe(TOPICS)
    _running = True
    logger.info("kafka consumer started", topics=TOPICS, group="cost-service")

    loop = asyncio.get_event_loop()
    try:
        while _running:
            messages = await loop.run_in_executor(None, lambda: _consumer.consume(500, timeout=0.1))
            if not messages:
                continue
            for msg in messages:
                if not _running:
                    break
                if msg.error():
                    logger.warning("kafka consumer error", error=str(msg.error()))
                    continue
                try:
                    envelope = json.loads(msg.value().decode("utf-8"))
                    if isinstance(envelope, dict) and not envelope.get("event_id"):
                        envelope["event_id"] = f"kafka:{msg.topic()}:{msg.partition()}:{msg.offset()}"
                    ledger.FinancialEnvelope.model_validate(envelope)
                except (ValueError, UnicodeError) as exc:
                    logger.warning("bad financial message", error=str(exc))
                    continue
                while _running:
                    try:
                        await process_envelope(envelope)
                    except Exception:
                        logger.exception("financial transaction failed; retrying", event_id=envelope["event_id"])
                        await asyncio.sleep(1)
                        continue
                    _consumer_health.mark_message()
                    break
            if _running:
                # All fetched positions are safe only after the entire batch.
                await loop.run_in_executor(None, lambda: _consumer.commit(asynchronous=False))
    finally:
        _running = False
        _consumer.close()
        _consumer = None


def stop_consumer() -> None:
    global _running
    _running = False


def is_consumer_running() -> bool:
    return _running


def get_consumer_health() -> dict:
    return _consumer_health.status()
