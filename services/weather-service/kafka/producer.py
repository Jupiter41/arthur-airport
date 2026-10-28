"""Kafka producer for weather-service — WeatherStateChanged + METARIssued."""

import logging
from datetime import datetime

from confluent_kafka import Producer

from _common import kafka_runtime

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "weather-service"


def init_kafka_producer() -> None:
    global _producer
    _producer = kafka_runtime.init_producer(PRODUCER_NAME)


def close_kafka_producer() -> None:
    kafka_runtime.close_producer(_producer)


def produce_event(
    topic: str,
    event_type: str,
    sim_time: datetime,
    payload: dict,
    key: str | None = None,
) -> None:
    kafka_runtime.produce_event(
        _producer, event_type, sim_time, payload,
        producer_name=PRODUCER_NAME, topic=topic, key=key,
    )


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
    return kafka_runtime.check_kafka()


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5) -> None:
    await kafka_runtime.wait_for_kafka(max_attempts=max_attempts, delay_s=delay_s)
