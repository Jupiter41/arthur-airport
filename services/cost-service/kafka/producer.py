"""Kafka producer for cost-service — events to cost.events."""

import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from confluent_kafka import Producer

logger = logging.getLogger(__name__)

_producer: Producer | None = None

EVENTS_TOPIC = "cost.events"


def init_kafka_producer() -> None:
    global _producer
    brokers = os.getenv("KAFKA_BROKERS", "kafka:9092")
    _producer = Producer({
        "bootstrap.servers": brokers,
        "client.id": "cost-service",
        "acks": "all",
        "retries": 3,
    })
    logger.info("kafka producer initialised", brokers=brokers)


def close_kafka_producer() -> None:
    global _producer
    if _producer:
        _producer.flush(timeout=10)
        _producer = None


def check_kafka() -> bool:
    return _producer is not None


async def wait_for_kafka(max_attempts: int = 12, delay_s: int = 5) -> None:
    import asyncio
    brokers = os.getenv("KAFKA_BROKERS", "kafka:9092")
    for attempt in range(1, max_attempts + 1):
        try:
            p = Producer({"bootstrap.servers": brokers, "socket.timeout.ms": 5000})
            p.list_topics(timeout=5)
            logger.info("kafka connected", attempt=attempt)
            return
        except Exception as exc:
            logger.warning("kafka not ready", attempt=attempt, error=str(exc))
            if attempt < max_attempts:
                await asyncio.sleep(delay_s)
    raise RuntimeError("kafka not reachable after max attempts")


def emit_cost_recorded(
    cost_record_id: str,
    category: str,
    amount_eur: float,
    is_revenue: bool,
    sim_time: datetime,
    sim_day: int,
    description: str,
    flight_id: str | None = None,
    incident_id: str | None = None,
) -> None:
    if _producer is None:
        return
    envelope = {
        "event_id": str(uuid4()),
        "event_type": "CostRecorded",
        "schema_version": "1.0",
        "produced_at": datetime.utcnow().isoformat(),
        "sim_time": sim_time.isoformat() if isinstance(sim_time, datetime) else sim_time,
        "producer": "cost-service",
        "payload": {
            "cost_record_id": cost_record_id,
            "category": category,
            "amount_eur": amount_eur,
            "is_revenue": is_revenue,
            "flight_id": flight_id,
            "incident_id": incident_id,
            "description": description,
            "sim_time": sim_time.isoformat() if isinstance(sim_time, datetime) else sim_time,
            "sim_day": sim_day,
        },
    }
    _producer.produce(
        topic=EVENTS_TOPIC,
        key=(cost_record_id or "").encode("utf-8"),
        value=json.dumps(envelope).encode("utf-8"),
        callback=lambda err, msg: logger.error("kafka produce error", error=str(err)) if err else None,
    )
    _producer.poll(0)
