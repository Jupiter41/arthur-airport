"""Kafka producer for sim-orchestrator — SimClockTick + event emission."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

from services.airport_config import load_airport_runtime_config

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "sim-orchestrator"


def init_kafka_producer() -> None:
    """Initialize the Kafka producer."""
    global _producer
    _producer = Producer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "client.id": PRODUCER_NAME,
        "acks": "all",
        "retries": 3,
    })
    logger.info("Kafka producer initialized")


def close_kafka_producer() -> None:
    """Flush and close the Kafka producer."""
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
    """Produce a single event to Kafka with the standard envelope format."""
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

    # P6-1: Inject OpenTelemetry trace context into envelope
    try:
        from _tracing import get_trace_context
        ctx = get_trace_context()
        if ctx.get("trace_id"):
            envelope["trace_id"] = ctx["trace_id"]
            envelope["span_id"] = ctx["span_id"]
    except Exception:
        pass

    value = json.dumps(envelope).encode("utf-8")

    # Under high tick rates (for example 3600x), local producer buffers can
    # fill briefly; poll and retry instead of letting BufferError kill callers.
    for attempt in range(5):
        try:
            _producer.produce(
                topic=topic,
                key=key.encode("utf-8") if key else None,
                value=value,
                callback=_delivery_report,
            )
            _producer.poll(0)
            return
        except BufferError:
            if attempt == 4:
                logger.error("Kafka local buffer full after retries; dropping %s", event_type)
                return
            _producer.poll(0.05)


def emit_clock_tick(
    sim_time: datetime,
    speed_multiplier: int,
    tick_number: int,
    day_of_sim: int,
    step_minutes: int = 1,
    mode: str = "REALTIME",
) -> None:
    """Emit a SimClockTick event to sim.clock."""
    payload = {
        "sim_time": sim_time.isoformat(),
        "real_time": datetime.now(timezone.utc).isoformat(),
        "speed_multiplier": speed_multiplier,
        "tick_number": tick_number,
        "day_of_sim": day_of_sim,
        "step_minutes": step_minutes,
        "mode": mode,
    }
    produce_event(
        topic="sim.clock",
        event_type="SimClockTick",
        sim_time=sim_time,
        payload=payload,
        key="tick",
    )


def emit_flight_schedule_seeded(
    sim_time: datetime,
    sim_day: int,
    flights: list[dict],
) -> None:
    """Emit a FlightScheduleSeeded batch event to flights.schedule."""
    payload = {
        "sim_day": sim_day,
        "sim_date": sim_time.date().isoformat(),
        "total_flights": len(flights),
        "flight_ids": [f["id"] for f in flights],
    }
    produce_event(
        topic="flights.schedule",
        event_type="FlightScheduleSeeded",
        sim_time=sim_time,
        payload=payload,
    )


def emit_inject_incident(
    sim_time: datetime,
    incident_type: str,
    severity: str,
    location: str,
    trigger: str = "probabilistic",
    description: str | None = None,
) -> None:
    """Emit an InjectIncident command to incidents.inject."""
    payload = {
        "type": incident_type,
        "severity": severity,
        "location": location,
        "trigger": trigger,
        "requested_by": PRODUCER_NAME,
        "at": sim_time.isoformat(),
    }
    if description:
        payload["description"] = description
    produce_event(
        topic="incidents.inject",
        event_type="InjectIncident",
        sim_time=sim_time,
        payload=payload,
    )


def emit_weather_state_changed(
    sim_time: datetime,
    category: str,
) -> None:
    """Emit initial WeatherStateChanged event."""
    _cavok = load_airport_runtime_config().operations.weather_capacity["CAVOK"]
    payload = {
        "weather_id": str(uuid4()),
        "previous_category": None,
        "new_category": category,
        "visibility_m": 15000,
        "wind_direction": 90,
        "wind_speed_kt": 5,
        "wind_gust_kt": 0,
        "ceiling_ft": None,
        "temperature_c": 18.0,
        "phenomena": [],
        "runway_impact": "none",
        "recommended_arrival_rate": _cavok.arrival,
        "recommended_departure_rate": _cavok.departure,
        "at": sim_time.isoformat(),
    }
    produce_event(
        topic="weather.events",
        event_type="WeatherStateChanged",
        sim_time=sim_time,
        payload=payload,
    )


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5) -> None:
    """Wait for Kafka to become available with exponential backoff."""
    for attempt in range(1, max_attempts + 1):
        try:
            admin = AdminClient({
                "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
            })
            loop = asyncio.get_event_loop()
            meta = await loop.run_in_executor(
                None, lambda: admin.list_topics(timeout=5)
            )
            if meta is not None:
                logger.info("Kafka is ready")
                return
        except Exception as e:
            wait = delay_s * min(attempt, 6)
            logger.warning(
                "Kafka not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, max_attempts, e, wait,
            )
            await asyncio.sleep(wait)
    raise RuntimeError(f"Kafka not reachable after {max_attempts} attempts")


async def check_kafka() -> bool:
    """Health check: verify Kafka connectivity."""
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
