"""Kafka producer for weather-service — WeatherStateChanged + METARIssued."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "weather-service"


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


def produce_event(
    topic: str,
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

    _producer.produce(
        topic=topic,
        key=key.encode("utf-8") if key else None,
        value=json.dumps(envelope).encode("utf-8"),
        callback=_delivery_report,
    )
    _producer.poll(0)


def emit_weather_state_changed(
    sim_time: datetime,
    weather_id: str,
    previous_category: str | None,
    new_category: str,
    params: dict,
    capacity: dict,
) -> None:
    """Emit WeatherStateChanged event to weather.events."""
    payload = {
        "weather_id": weather_id,
        "previous_category": previous_category,
        "new_category": new_category,
        "visibility_m": params["visibility_m"],
        "wind_direction": params["wind_direction"],
        "wind_speed_kt": params["wind_speed_kt"],
        "wind_gust_kt": params["wind_gust_kt"],
        "ceiling_ft": params["ceiling_ft"],
        "temperature_c": params["temperature_c"],
        "phenomena": params["phenomena"],
        "runway_impact": capacity["runway_impact"],
        "recommended_arrival_rate": capacity["arrival_rate"],
        "recommended_departure_rate": capacity["departure_rate"],
        "at": sim_time.isoformat(),
    }
    produce_event(
        topic="weather.events",
        event_type="WeatherStateChanged",
        sim_time=sim_time,
        payload=payload,
    )
    logger.info("Emitted WeatherStateChanged: %s -> %s", previous_category, new_category)


def emit_metar_issued(sim_time: datetime, metar_raw: str) -> None:
    """Emit METARIssued event to weather.events."""
    payload = {
        "raw": metar_raw,
        "at": sim_time.isoformat(),
    }
    produce_event(
        topic="weather.events",
        event_type="METARIssued",
        sim_time=sim_time,
        payload=payload,
    )
    logger.debug("Emitted METARIssued: %s", metar_raw[:40])


async def check_kafka() -> bool:
    try:
        admin = AdminClient({
            "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        })
        loop = asyncio.get_event_loop()
        meta = await loop.run_in_executor(
            None, lambda: admin.list_topics(timeout=3)
        )
        return meta is not None
    except Exception:
        return False


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5) -> None:
    for attempt in range(1, max_attempts + 1):
        if await check_kafka():
            logger.info("Kafka is ready")
            return
        wait = delay_s * min(attempt, 6)
        logger.warning(
            "Kafka not ready (attempt %d/%d) — retrying in %.0fs",
            attempt, max_attempts, wait,
        )
        await asyncio.sleep(wait)
    raise RuntimeError(f"Kafka not reachable after {max_attempts} attempts")
