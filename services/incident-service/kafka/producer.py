"""Kafka producer for incident-service — events to incidents.events and incidents.alerts."""

import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "incident-service"
EVENTS_TOPIC = "incidents.events"
ALERTS_TOPIC = "incidents.alerts"


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

    # P6-1: Inject OpenTelemetry trace context into envelope
    try:
        from _tracing import get_trace_context
        ctx = get_trace_context()
        if ctx.get("trace_id"):
            envelope["trace_id"] = ctx["trace_id"]
            envelope["span_id"] = ctx["span_id"]
    except Exception:
        pass

    _producer.produce(
        topic=topic,
        key=key.encode("utf-8") if key else None,
        value=json.dumps(envelope).encode("utf-8"),
        callback=_delivery_report,
    )
    _producer.poll(0)


# ── Event emitters ───────────────────────────────────────────


def emit_incident_created(incident: dict, sim_time: datetime) -> None:
    """Emit IncidentCreated event."""
    payload = {
        "incident_id": incident["id"],
        "type": incident["type"],
        "severity": incident["severity"],
        "status": incident["status"],
        "trigger": incident.get("trigger", ""),
        "title": incident.get("title", ""),
        "location": incident.get("location", ""),
        "description": incident.get("description", ""),
        "protocol": incident.get("protocol", ""),
        "ttr_minutes": incident.get("ttr_minutes"),
        "cascade_depth": incident.get("cascade_depth", 0),
    }
    _produce_event(EVENTS_TOPIC, "IncidentCreated", sim_time, payload, key=incident["id"])
    logger.info("Emitted IncidentCreated: %s type=%s", incident["id"][:8], incident["type"])


def emit_incident_status_changed(
    incident: dict,
    new_status: str,
    sim_time: datetime,
    note: str = "",
) -> None:
    """Emit IncidentStatusChanged event."""
    payload = {
        "incident_id": incident["id"],
        "type": incident.get("type", ""),
        "severity": incident.get("severity", ""),
        "previous_status": "active" if new_status == "contained" else incident.get("status", "active"),
        "new_status": new_status,
        "note": note,
        "location": incident.get("location", ""),
    }
    _produce_event(EVENTS_TOPIC, "IncidentStatusChanged", sim_time, payload, key=incident["id"])
    logger.info(
        "Emitted IncidentStatusChanged: %s → %s", incident["id"][:8], new_status
    )


def emit_incident_cascaded(
    parent_id: str, child: dict, sim_time: datetime
) -> None:
    """Emit IncidentCascaded event."""
    payload = {
        "parent_incident_id": parent_id,
        "child_incident_id": child["id"],
        "child_type": child["type"],
        "child_severity": child["severity"],
        "cascade_depth": child.get("cascade_depth", 0),
        "location": child.get("location", ""),
    }
    _produce_event(EVENTS_TOPIC, "IncidentCascaded", sim_time, payload, key=parent_id)
    logger.info(
        "Emitted IncidentCascaded: %s → %s", parent_id[:8], child["type"]
    )


def emit_incident_alert(incident: dict, sim_time: datetime) -> None:
    """Emit IncidentAlert — every new incident + every status change."""
    from services.protocols import build_alert
    alert = build_alert(incident, sim_time)

    _produce_event(ALERTS_TOPIC, "IncidentAlert", sim_time, alert, key=incident["id"])
    logger.debug("Emitted IncidentAlert: %s", incident["id"][:8])


# ── Health check ─────────────────────────────────────────────


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
