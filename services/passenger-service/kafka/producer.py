"""Kafka producer for passenger-service — events to passengers.events topic."""

import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = logging.getLogger(__name__)

_producer: Producer | None = None

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
    """Emit PassengerStatusChanged event."""
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
