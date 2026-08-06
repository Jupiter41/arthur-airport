"""Kafka producer for flight-service — flight events to flights.events topic.

Producer lifecycle and the standard event-envelope build/emit are owned by
``_common.kafka_runtime`` (shared across all producing services). This module
keeps only the flight-domain ``emit_*`` helpers and the topic names.
"""

import logging
import os
from datetime import datetime

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

from _common import kafka_runtime

logger = logging.getLogger(__name__)

_producer: Producer | None = None

PRODUCER_NAME = "flight-service"
TOPIC = "flights.events"
GROUND_TOPIC = "ground.events"


def init_kafka_producer() -> None:
    """Create the confluent-kafka Producer with delivery guarantees."""
    global _producer
    _producer = kafka_runtime.init_producer(PRODUCER_NAME)


def close_kafka_producer() -> None:
    """Flush pending messages and shut down the producer."""
    kafka_runtime.close_producer(_producer)


def _produce_event(
    event_type: str,
    sim_time,
    payload: dict,
    key: str | None = None,
    topic: str | None = None,
) -> None:
    """Build a standard event envelope and produce it to the given topic.

    Args:
        event_type: Event name (e.g. ``FlightStatusChanged``).
        sim_time: Current simulation time for the envelope.
        payload: Domain-specific event data.
        key: Optional Kafka message key (typically flight_id) for partition affinity.
        topic: Target topic, defaults to ``flights.events``.
    """
    kafka_runtime.produce_event(
        _producer,
        event_type,
        sim_time,
        payload,
        producer_name=PRODUCER_NAME,
        topic=topic or TOPIC,
        key=key,
    )


def emit_flight_status_changed(
    flight_id: str,
    flight_number: str,
    previous_status: str,
    new_status: str,
    sim_time: datetime,
    gate_id: str | None = None,
    runway_id: str | None = None,
    delay_minutes: int = 0,
    reason: str | None = None,
    direction: str | None = None,
    destination_iata: str | None = None,
) -> None:
    """Emit FlightStatusChanged event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "previous_status": previous_status,
        "new_status": new_status,
        "gate_id": gate_id,
        "runway_id": runway_id,
        "delay_minutes": delay_minutes,
        "reason": reason,
        "direction": direction,
        "destination_iata": destination_iata,
    }
    _produce_event("FlightStatusChanged", sim_time, payload, key=flight_id)
    logger.info(
        "Emitted FlightStatusChanged: %s %s -> %s",
        flight_number, previous_status, new_status,
    )


def emit_flight_gate_assigned(
    flight_id: str,
    flight_number: str,
    gate_id: str,
    sim_time: datetime,
    reason: str = "initial_assignment",
) -> None:
    """Emit FlightGateAssigned event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "gate_id": gate_id,
        "reason": reason,
    }
    _produce_event("FlightGateAssigned", sim_time, payload, key=flight_id)
    logger.info("Emitted FlightGateAssigned: %s -> gate %s", flight_number, gate_id)


def emit_flight_runway_assigned(
    flight_id: str,
    flight_number: str,
    runway_id: str,
    operation: str,
    sim_time: datetime,
) -> None:
    """Emit FlightRunwayAssigned event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "runway_id": runway_id,
        "operation": operation,
    }
    _produce_event("FlightRunwayAssigned", sim_time, payload, key=flight_id)
    logger.info(
        "Emitted FlightRunwayAssigned: %s -> runway %s (%s)",
        flight_number, runway_id, operation,
    )


def emit_flight_cancelled(
    flight_id: str,
    flight_number: str,
    sim_time: datetime,
    reason: str = "delay_exceeded_180min",
) -> None:
    """Emit FlightCancelled event."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "reason": reason,
    }
    _produce_event("FlightCancelled", sim_time, payload, key=flight_id)
    logger.info("Emitted FlightCancelled: %s reason=%s", flight_number, reason)


def emit_turnaround_task_changed(
    flight_id: str,
    aircraft_registration: str,
    task_name: str,
    new_status: str,
    sim_time: datetime,
    duration_min: int = 0,
) -> None:
    """Emit turnaround.task.started or turnaround.task.completed event."""
    event_type = (
        "TurnaroundTaskStarted" if new_status == "in_progress"
        else "TurnaroundTaskCompleted"
    )
    payload = {
        "flight_id": flight_id,
        "aircraft_registration": aircraft_registration,
        "task_name": task_name,
        "status": new_status,
        "duration_min": duration_min,
    }
    _produce_event(event_type, sim_time, payload, key=flight_id)


def emit_flight_ctot_assigned(
    flight_id: str,
    flight_number: str,
    ctot_delay_minutes: int,
    sim_time: datetime,
) -> None:
    """Emit FlightCTOTAssigned event — ATC slot allocation delay."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "ctot_delay_minutes": ctot_delay_minutes,
    }
    _produce_event("FlightCTOTAssigned", sim_time, payload, key=flight_id)
    logger.info(
        "Emitted FlightCTOTAssigned: %s delay=%dmin",
        flight_number, ctot_delay_minutes,
    )


def emit_minimum_fuel_warning(
    flight_id: str,
    flight_number: str,
    holding_minutes: int,
    fuel_remaining_kg: int,
    is_panpan: bool,
    sim_time: datetime,
) -> None:
    """Emit MinimumFuelWarning event — aircraft in holding burning fuel."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "holding_minutes": holding_minutes,
        "fuel_remaining_kg": fuel_remaining_kg,
        "is_panpan": is_panpan,
        "priority_landing": is_panpan,
    }
    _produce_event("MinimumFuelWarning", sim_time, payload, key=flight_id)
    logger.info(
        "Emitted MinimumFuelWarning: %s holding=%dmin panpan=%s",
        flight_number, holding_minutes, is_panpan,
    )


def emit_flight_diverted(
    flight_id: str,
    flight_number: str,
    reason: str,
    sim_time: datetime,
) -> None:
    """Emit FlightDiverted event — flight diverted to alternate airport."""
    payload = {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "reason": reason,
    }
    _produce_event("FlightDiverted", sim_time, payload, key=flight_id)
    logger.info("Emitted FlightDiverted: %s reason=%s", flight_number, reason)


# ---------------------------------------------------------------------------
# Ground vehicle events → ground.events topic
# ---------------------------------------------------------------------------

def emit_ground_vehicle_dispatched(
    vehicle_id: str,
    vehicle_type: str,
    gate_id: str,
    flight_id: str,
    task_name: str,
    transit_minutes: int,
    sim_time: datetime,
) -> None:
    """Emit GroundVehicleDispatched event."""
    payload = {
        "vehicle_id": vehicle_id,
        "vehicle_type": vehicle_type,
        "gate_id": gate_id,
        "flight_id": flight_id,
        "task_name": task_name,
        "transit_minutes": transit_minutes,
    }
    _produce_event("GroundVehicleDispatched", sim_time, payload,
                   key=vehicle_id, topic=GROUND_TOPIC)
    logger.info("Emitted GroundVehicleDispatched: %s → gate %s for %s",
                vehicle_id, gate_id, task_name)


def emit_ground_vehicle_returned(
    vehicle_id: str,
    vehicle_type: str,
    sim_time: datetime,
) -> None:
    """Emit GroundVehicleReturned event."""
    payload = {
        "vehicle_id": vehicle_id,
        "vehicle_type": vehicle_type,
    }
    _produce_event("GroundVehicleReturned", sim_time, payload,
                   key=vehicle_id, topic=GROUND_TOPIC)
    logger.info("Emitted GroundVehicleReturned: %s", vehicle_id)


async def check_kafka() -> bool:
    try:
        admin = AdminClient({
            "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092")
        })
        meta = admin.list_topics(timeout=3)
        return meta is not None
    except Exception:
        return False


def emit_bulk_state_snapshot(
    sim_time: datetime,
    summary: dict,
) -> None:
    """Emit a BulkStateSnapshot event (used in BULK mode instead of per-flight events)."""
    payload = {
        "service": PRODUCER_NAME,
        "sim_time": sim_time.isoformat(),
        "summary": summary,
    }
    _produce_event("BulkStateSnapshot", sim_time, payload)


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
