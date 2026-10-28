"""Kafka producer for analysis-service — events to analysis.events."""

import json
import logging
from datetime import datetime

from confluent_kafka import Producer

from _common import kafka_runtime

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "analysis-service"
EVENTS_TOPIC = "analysis.events"
# A7/A9: command input topic consumed by flight-service (see EVENT_BUS §4.8b).
COMMANDS_TOPIC = "flights.commands"


def init_kafka_producer() -> None:
    global _producer
    _producer = kafka_runtime.init_producer(PRODUCER_NAME)


def close_kafka_producer() -> None:
    kafka_runtime.close_producer(_producer)


async def check_kafka() -> bool:
    return kafka_runtime.check_kafka()


def publish_confirmed(topic: str, key: str, envelope: dict) -> None:
    """Only the committed outbox worker publishes action facts/commands."""
    import time

    if _producer is None:
        raise RuntimeError("Kafka producer not initialized")
    delivered = []
    _producer.produce(topic=topic, key=key.encode(), value=json.dumps(envelope, allow_nan=False).encode(),
                      callback=lambda error, message: delivered.append(error))
    deadline = time.monotonic() + 10
    while not delivered and time.monotonic() < deadline:
        _producer.poll(0.1)
    if not delivered or delivered[0] is not None:
        raise RuntimeError("Action delivery not confirmed; outbox retained")


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5) -> None:
    await kafka_runtime.wait_for_kafka(max_attempts=max_attempts, delay_s=delay_s)


def _produce_event(
    event_type: str,
    sim_time: datetime,
    payload: dict,
    key: str | None = None,
) -> None:
    kafka_runtime.produce_event(
        _producer, event_type, sim_time, payload,
        producer_name=PRODUCER_NAME, topic=EVENTS_TOPIC, key=key,
    )


# ── Event emitters ───────────────────────────────────────────


def emit_bottleneck_detected(bottleneck: dict, sim_time: datetime) -> None:
    """Emit BottleneckDetected event."""
    _produce_event(
        "BottleneckDetected",
        sim_time,
        bottleneck,
        key=bottleneck.get("id", ""),
    )


def emit_bottleneck_resolved(bottleneck_id: str, sim_time: datetime) -> None:
    """Emit BottleneckResolved event."""
    _produce_event(
        "BottleneckResolved",
        sim_time,
        {"bottleneck_id": bottleneck_id},
        key=bottleneck_id,
    )


def emit_recommendation_generated(recommendation: dict, sim_time: datetime) -> None:
    """Emit RecommendationGenerated event."""
    _produce_event(
        "RecommendationGenerated",
        sim_time,
        recommendation,
        key=recommendation.get("id", ""),
    )


def emit_anomaly_detected(anomaly: dict, sim_time: datetime) -> None:
    """Emit AnomalyDetected event (P5-3-1)."""
    _produce_event(
        "AnomalyDetected",
        sim_time,
        anomaly,
        key="anomaly",
    )


def emit_narration_generated(narration: dict, sim_time: datetime) -> None:
    """Emit NarrationGenerated event (P5-2-3)."""
    _produce_event(
        "NarrationGenerated",
        sim_time,
        narration,
        key="narration",
    )
