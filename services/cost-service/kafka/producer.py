"""Kafka producer for cost-service — events to cost.events."""

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import structlog
from confluent_kafka import Producer

logger = structlog.get_logger(__name__)

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
    from _common.infra import wait_for_kafka_broker
    await wait_for_kafka_broker(logger=logger, max_attempts=max_attempts, delay_s=delay_s)


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
        "produced_at": datetime.now(timezone.utc).isoformat(),
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


def emit_carbon_recorded(
    record_id: str,
    source: str,
    co2_kg: float,
    sim_time: str | datetime,
    sim_day: int,
    description: str,
    flight_id: str | None = None,
) -> None:
    """Emit a CarbonRecorded event to cost.events."""
    if _producer is None:
        return
    sim_time_str = sim_time.isoformat() if isinstance(sim_time, datetime) else sim_time
    envelope = {
        "event_id": str(uuid4()),
        "event_type": "CarbonRecorded",
        "schema_version": "1.0",
        "produced_at": datetime.now(timezone.utc).isoformat(),
        "sim_time": sim_time_str,
        "producer": "cost-service",
        "payload": {
            "carbon_record_id": record_id,
            "source": source,
            "co2_kg": co2_kg,
            "flight_id": flight_id,
            "description": description,
            "sim_time": sim_time_str,
            "sim_day": sim_day,
        },
    }
    _producer.produce(
        topic=EVENTS_TOPIC,
        key=(record_id or "").encode("utf-8"),
        value=json.dumps(envelope).encode("utf-8"),
        callback=lambda err, msg: logger.error("kafka produce error", error=str(err)) if err else None,
    )
    _producer.poll(0)
