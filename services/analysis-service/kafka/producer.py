"""Kafka producer for analysis-service — events to analysis.events."""

import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "analysis-service"
EVENTS_TOPIC = "analysis.events"


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


async def check_kafka() -> bool:
    try:
        admin = AdminClient({
            "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        })
        metadata = admin.list_topics(timeout=5)
        return metadata is not None
    except Exception:
        return False


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5) -> None:
    import asyncio
    for attempt in range(1, max_attempts + 1):
        try:
            admin = AdminClient({
                "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
            })
            metadata = admin.list_topics(timeout=5)
            if metadata:
                logger.info("Kafka broker reachable")
                return
        except Exception as e:
            wait = delay_s * min(attempt, 6)
            logger.warning(
                "Kafka not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, max_attempts, e, wait,
            )
            await asyncio.sleep(wait)
    raise RuntimeError(f"Kafka not reachable after {max_attempts} attempts")


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
        topic=EVENTS_TOPIC,
        key=key.encode("utf-8") if key else None,
        value=json.dumps(envelope).encode("utf-8"),
        callback=_delivery_report,
    )
    _producer.poll(0)


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


def emit_autonomous_action(action: dict, sim_time: datetime) -> None:
    """Emit AutonomousActionApplied event."""
    _produce_event(
        "AutonomousActionApplied",
        sim_time,
        action,
        key=action.get("id", ""),
    )
