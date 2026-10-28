"""Kafka producer for incident-service — events to incidents.events and incidents.alerts."""

import logging
from datetime import datetime

from confluent_kafka import Producer

from _common import kafka_runtime

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "incident-service"
EVENTS_TOPIC = "incidents.events"
ALERTS_TOPIC = "incidents.alerts"


def init_kafka_producer() -> None:
    global _producer
    _producer = kafka_runtime.init_producer(PRODUCER_NAME)


def close_kafka_producer() -> None:
    kafka_runtime.close_producer(_producer)


def _produce_event(
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
    return kafka_runtime.check_kafka()


async def wait_for_kafka(max_attempts: int = 12, delay_s: float = 5) -> None:
    await kafka_runtime.wait_for_kafka(max_attempts=max_attempts, delay_s=delay_s)
