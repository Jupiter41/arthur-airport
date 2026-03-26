"""Kafka producer for flight-service — flight events to flights.events topic."""

import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "flight-service"
TOPIC = "flights.events"


def init_kafka_producer() -> None:
    """Create the confluent-kafka Producer with delivery guarantees."""
    global _producer
    _producer = Producer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "client.id": PRODUCER_NAME,
        "acks": "all",
        "retries": 3,
    })
    logger.info("Kafka producer initialized")


def close_kafka_producer() -> None:
    """Flush pending messages and shut down the producer."""
    if _producer:
        _producer.flush(timeout=10)
        logger.info("Kafka producer flushed and closed")


def _delivery_report(err, msg):
    if err:
        logger.error("Kafka delivery failed: %s", err)


def _produce_event(
    event_type: str,
    sim_time: datetime,
    payload: dict,
    key: str | None = None,
) -> None:
    """Build a standard event envelope and produce it to the flights.events topic.

    Args:
        event_type: Event name (e.g. ``FlightStatusChanged``).
        sim_time: Current simulation time for the envelope.
        payload: Domain-specific event data.
        key: Optional Kafka message key (typically flight_id) for partition affinity.
    """
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


def emit_flight_status_changed(
    flight_id: str,
    flight_number: str,
    previous_status: str,
    new_status: str,
    sim_time: datetime,
    gate_id: str | None = None,
    runway_id: str | None = None,
    delay_minutes: int = 0,
    reason: str | None = None,
) -> None:
    """Emit FlightStatusChanged event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "previous_status": previous_status,
        "new_status": new_status,
        "gate_id": gate_id,
        "runway_id": runway_id,
        "delay_minutes": delay_minutes,
        "reason": reason,
    }
    _produce_event("FlightStatusChanged", sim_time, payload, key=flight_id)
    logger.info(
        "Emitted FlightStatusChanged: %s %s -> %s",
        flight_number, previous_status, new_status,
    )


def emit_flight_gate_assigned(
    flight_id: str,
    flight_number: str,
    gate_id: str,
    sim_time: datetime,
    reason: str = "initial_assignment",
) -> None:
    """Emit FlightGateAssigned event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "gate_id": gate_id,
        "reason": reason,
    }
    _produce_event("FlightGateAssigned", sim_time, payload, key=flight_id)
    logger.info("Emitted FlightGateAssigned: %s -> gate %s", flight_number, gate_id)


def emit_flight_runway_assigned(
    flight_id: str,
    flight_number: str,
    runway_id: str,
    operation: str,
    sim_time: datetime,
) -> None:
    """Emit FlightRunwayAssigned event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "runway_id": runway_id,
        "operation": operation,
    }
    _produce_event("FlightRunwayAssigned", sim_time, payload, key=flight_id)
    logger.info(
        "Emitted FlightRunwayAssigned: %s -> runway %s (%s)",
        flight_number, runway_id, operation,
    )


def emit_flight_cancelled(
    flight_id: str,
    flight_number: str,
    sim_time: datetime,
    reason: str = "delay_exceeded_180min",
) -> None:
    """Emit FlightCancelled event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "reason": reason,
    }
    _produce_event("FlightCancelled", sim_time, payload, key=flight_id)
    logger.info("Emitted FlightCancelled: %s reason=%s", flight_number, reason)


def emit_turnaround_task_changed(
    flight_id: str,
    aircraft_registration: str,
    task_name: str,
    new_status: str,
    sim_time: datetime,
    duration_min: int = 0,
) -> None:
    """Emit turnaround.task.started or turnaround.task.completed event."""
    event_type = (
        "TurnaroundTaskStarted" if new_status == "in_progress"
        else "TurnaroundTaskCompleted"
    )
    payload = {
        "flight_id": flight_id,
        "aircraft_registration": aircraft_registration,
        "task_name": task_name,
        "status": new_status,
        "duration_min": duration_min,
    }
    _produce_event(event_type, sim_time, payload, key=flight_id)


async def check_kafka() -> bool:
    try:
        admin = AdminClient({
            "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092")
        })
        meta = admin.list_topics(timeout=3)
        return meta is not None
    except Exception:
        return False


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
