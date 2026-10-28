"""Kafka producer for sim-orchestrator — SimClockTick + event emission."""

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Producer, BufferError

from _common import kafka_runtime
from services.airport_config import load_airport_runtime_config

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "sim-orchestrator"


def init_kafka_producer() -> None:
    global _producer
    _producer = kafka_runtime.init_producer(PRODUCER_NAME)


def close_kafka_producer() -> None:
    kafka_runtime.close_producer(_producer)


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
        from _common._tracing import get_trace_context
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
    await kafka_runtime.wait_for_kafka(max_attempts=max_attempts, delay_s=delay_s)


async def check_kafka() -> bool:
    return kafka_runtime.check_kafka()
