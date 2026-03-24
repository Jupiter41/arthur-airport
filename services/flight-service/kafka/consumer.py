"""Kafka consumer for flight-service.

Consumes: SimClockTick, WeatherStateChanged, IncidentCreated, IncidentStatusChanged, FlightScheduleSeeded
On each tick: evaluates all active flights through the FSM, assigns runways, resolves gates.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

from confluent_kafka import Consumer

from db.neo4j import (
    get_active_flights,
    update_flight_status,
    get_boarded_percentage,
    assign_flight_to_runway,
    release_gate,
    get_open_runway,
)
from kafka.producer import (
    emit_flight_status_changed,
    emit_flight_gate_assigned,
    emit_flight_runway_assigned,
    emit_flight_cancelled,
)
from services.state_machine import evaluate_transition, TERMINAL_STATES
from services.runway_queue import RunwayQueue
from services.gate_resolver import ensure_gate_assigned, check_and_resolve_conflict
from services.turnaround import propagate_turnaround_delay

logger = logging.getLogger(__name__)

_consumer: Consumer | None = None
_consumer_running = False

# --- In-memory state ---
_sim_time: datetime | None = None
_runway_queue = RunwayQueue()

# Manual holds: flight_id -> {reason, expected_duration_minutes, held_at}
_held_flights: dict[str, dict] = {}

# Incident-affected entities: set of gate_ids and runway_ids currently impacted
_incident_affected_gates: set[str] = set()
_incident_affected_runways: set[str] = set()

# Idempotency: track processed event IDs
_processed_events: set[str] = set()
_MAX_PROCESSED = 10000

# WebSocket broadcast callback
_ws_broadcast = None


def set_ws_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def get_sim_time() -> datetime | None:
    return _sim_time


def get_runway_queue() -> RunwayQueue:
    return _runway_queue


def get_held_flights() -> dict:
    return _held_flights


def is_consumer_running() -> bool:
    return _consumer_running


def stop_consumer() -> None:
    global _consumer_running
    _consumer_running = False


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "flight-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })


async def run_consumer() -> None:
    """Main consumer loop — runs as background asyncio task."""
    global _consumer, _consumer_running

    _consumer = _make_consumer()
    _consumer.subscribe(["sim.clock", "weather.events", "incidents.events", "flights.schedule"])
    _consumer_running = True

    loop = asyncio.get_event_loop()
    logger.info("Kafka consumer started (topics: sim.clock, weather.events, incidents.events, flights.schedule)")

    try:
        while _consumer_running:
            msg = await loop.run_in_executor(None, _consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Consumer error: %s", msg.error())
                continue
            try:
                envelope = json.loads(msg.value().decode("utf-8"))
                await _dispatch(envelope)
            except Exception as e:
                logger.error("Processing error: %s", e, exc_info=True)
    finally:
        _consumer.close()
        _consumer_running = False
        logger.info("Kafka consumer stopped")


async def _dispatch(envelope: dict) -> None:
    """Route events to handlers based on event_type."""
    global _processed_events

    event_id = envelope.get("event_id", "")
    event_type = envelope.get("event_type")
    payload = envelope.get("payload", {})

    # Idempotency check
    if event_id in _processed_events:
        return
    _processed_events.add(event_id)
    if len(_processed_events) > _MAX_PROCESSED:
        # Trim oldest (approximate — set doesn't preserve order, but prevents unbounded growth)
        excess = len(_processed_events) - _MAX_PROCESSED
        for _ in range(excess):
            _processed_events.pop()

    sim_time_str = envelope.get("sim_time")
    if not sim_time_str:
        return
    try:
        sim_time = datetime.fromisoformat(sim_time_str)
        # Strip timezone to keep all comparisons naive
        sim_time = sim_time.replace(tzinfo=None)
    except (ValueError, TypeError):
        return

    match event_type:
        case "SimClockTick":
            await _on_clock_tick(payload, sim_time)
        case "WeatherStateChanged":
            await _on_weather_changed(payload, sim_time)
        case "IncidentCreated":
            await _on_incident_created(payload, sim_time)
        case "IncidentStatusChanged":
            await _on_incident_status_changed(payload, sim_time)
        case "FlightScheduleSeeded":
            await _on_schedule_seeded(payload, sim_time)
        case _:
            pass


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    """Process a SimClockTick — advance all active flights through the FSM."""
    global _sim_time
    _sim_time = sim_time

    # 1. Get all active flights
    flights = await get_active_flights(sim_time)

    # 2. Assign runway slots from the queue
    runway_assignments = _runway_queue.assign_slots(sim_time)
    for assignment in runway_assignments:
        runway_id = await get_open_runway(ils_required=_runway_queue.ils_required)
        if runway_id:
            await assign_flight_to_runway(
                assignment["flight_id"],
                runway_id,
                assignment["operation"],
                sim_time,
            )
            # Find flight info for event
            for f in flights:
                if f["id"] == assignment["flight_id"]:
                    emit_flight_runway_assigned(
                        flight_id=f["id"],
                        flight_number=f["flight_number"],
                        runway_id=runway_id,
                        operation=assignment["operation"],
                        sim_time=sim_time,
                    )
                    f["runway_id"] = runway_id
                    break

    # 3. Process each flight through the FSM
    for flight in flights:
        await _process_flight(flight, sim_time)


async def _process_flight(flight: dict, sim_time: datetime) -> None:
    """Evaluate and execute FSM transition for a single flight."""
    flight_id = flight["id"]
    current_status = flight["status"]
    direction = flight.get("direction", "departure")

    # Check manual hold
    has_hold = flight_id in _held_flights

    # Check gate availability
    gate_id = flight.get("gate_id")
    gate_available = True
    if gate_id and gate_id in _incident_affected_gates:
        gate_available = False

    # Check runway availability
    runway_available = True
    runway_id = flight.get("runway_id")
    if runway_id and runway_id in _incident_affected_runways:
        runway_available = False
    # Also check if any runway at all is available
    if not runway_id:
        open_rw = await get_open_runway(ils_required=_runway_queue.ils_required)
        runway_available = open_rw is not None

    # Get boarding percentage for departure flights in boarding state
    boarded_pct = 1.0
    if current_status == "boarding" and direction == "departure":
        boarded_pct = await get_boarded_percentage(flight_id)
        # If passenger-service hasn't processed passengers yet, simulate progress
        # based on time elapsed since boarding started
        if boarded_pct < 0.01:
            estimated = flight.get("estimated_time")
            if estimated:
                try:
                    est = datetime.fromisoformat(str(estimated))
                    boarding_start = est - timedelta(minutes=60)
                    elapsed = (sim_time - boarding_start).total_seconds() / 60
                    # Linear boarding assumption: 60 minutes to board all passengers
                    boarded_pct = min(1.0, max(0.0, elapsed / 60.0))
                except (ValueError, TypeError):
                    boarded_pct = 1.0

    # For scheduled departures, ensure gate is assigned before boarding
    if current_status == "scheduled" and direction == "departure":
        estimated = flight.get("estimated_time")
        if estimated:
            try:
                est = datetime.fromisoformat(str(estimated))
                if sim_time >= est - timedelta(minutes=65):
                    new_gate = await ensure_gate_assigned(
                        flight_id, gate_id, None, sim_time
                    )
                    if new_gate and new_gate != gate_id:
                        flight["gate_id"] = new_gate
                        gate_id = new_gate
                        emit_flight_gate_assigned(
                            flight_id=flight_id,
                            flight_number=flight["flight_number"],
                            gate_id=new_gate,
                            sim_time=sim_time,
                        )
            except (ValueError, TypeError):
                pass

    # For arrivals approaching, enqueue for runway (only if not already assigned)
    if current_status == "scheduled" and direction == "arrival" and not flight.get("runway_id"):
        estimated = flight.get("estimated_time", "")
        try:
            est = datetime.fromisoformat(str(estimated))
            if sim_time >= est - timedelta(minutes=35):
                _runway_queue.enqueue_arrival(flight_id, str(estimated))
        except (ValueError, TypeError):
            pass

    # For departures ready to depart, enqueue for runway (only if not already assigned)
    if current_status == "boarding" and direction == "departure" and not flight.get("runway_id"):
        estimated = flight.get("estimated_time", "")
        if boarded_pct >= 0.95:
            _runway_queue.enqueue_departure(flight_id, str(estimated))

    # Evaluate FSM transition
    new_status = evaluate_transition(
        flight=flight,
        sim_time=sim_time,
        runway_available=runway_available,
        gate_available=gate_available,
        boarded_pct=boarded_pct,
        has_hold=has_hold,
    )

    if new_status is None:
        # Check for delay accumulation on boarding flights past departure time
        if current_status == "boarding" and direction == "departure":
            estimated = flight.get("estimated_time")
            if estimated:
                try:
                    est = datetime.fromisoformat(str(estimated))
                    if sim_time > est and boarded_pct < 0.95:
                        delay = int((sim_time - est).total_seconds() / 60)
                        if delay > (flight.get("delay_minutes", 0) or 0):
                            await update_flight_status(
                                flight_id, "boarding", sim_time,
                                delay_minutes=delay,
                                delay_reason="boarding_incomplete",
                            )
                except (ValueError, TypeError):
                    pass
        return

    # Execute the transition
    await _execute_transition(flight, current_status, new_status, sim_time)


async def _execute_transition(
    flight: dict,
    previous_status: str,
    new_status: str,
    sim_time: datetime,
) -> None:
    """Execute a flight state transition — update Neo4j, emit events, handle side effects."""
    flight_id = flight["id"]
    flight_number = flight["flight_number"]
    direction = flight.get("direction", "departure")
    delay_minutes = flight.get("delay_minutes", 0) or 0

    # Prepare update kwargs
    update_kwargs: dict = {}

    # Side effects by transition type
    match new_status:
        case "boarding":
            # Ensure gate is assigned for arrivals coming from approach->delayed->approach
            if direction == "arrival":
                gate_id = flight.get("gate_id")
                if not gate_id:
                    new_gate = await ensure_gate_assigned(flight_id, None, None, sim_time)
                    if new_gate:
                        emit_flight_gate_assigned(
                            flight_id=flight_id,
                            flight_number=flight_number,
                            gate_id=new_gate,
                            sim_time=sim_time,
                        )

        case "departed":
            update_kwargs["actual_time"] = sim_time.isoformat()
            # Release gate
            released = await release_gate(flight_id)
            if released:
                logger.info("Gate %s released by departing flight %s", released, flight_number)

        case "landed":
            update_kwargs["actual_time"] = sim_time.isoformat()
            # Assign gate for arrival
            if direction == "arrival":
                gate_id = flight.get("gate_id")
                new_gate = await ensure_gate_assigned(flight_id, gate_id, None, sim_time)
                if new_gate:
                    emit_flight_gate_assigned(
                        flight_id=flight_id,
                        flight_number=flight_number,
                        gate_id=new_gate,
                        sim_time=sim_time,
                    )

        case "delayed":
            # Check if it's a weather/incident delay
            reason = flight.get("delay_reason", "")
            if flight_id in _held_flights:
                reason = _held_flights[flight_id].get("reason", "manual_hold")
            elif flight.get("runway_id") in _incident_affected_runways:
                reason = "runway_incident"
            elif flight.get("gate_id") in _incident_affected_gates:
                reason = "gate_incident"
            else:
                reason = reason or "operational"
            update_kwargs["delay_reason"] = reason

        case "cancelled":
            update_kwargs["delay_reason"] = "delay_exceeded_180min"
            # Remove from runway queue
            _runway_queue.remove(flight_id)
            # Remove hold
            _held_flights.pop(flight_id, None)
            # Release gate
            await release_gate(flight_id)
            # Emit cancellation event
            emit_flight_cancelled(
                flight_id=flight_id,
                flight_number=flight_number,
                sim_time=sim_time,
                reason="delay_exceeded_180min",
            )

        case "at_gate":
            # Arrival turnaround — propagate delay if applicable
            if direction == "arrival" and delay_minutes > 0:
                reg = flight.get("aircraft_registration", "")
                aircraft_type = flight.get("aircraft_type", "")
                if reg:
                    await propagate_turnaround_delay(
                        flight_id=flight_id,
                        aircraft_registration=reg,
                        aircraft_type=aircraft_type,
                        direction=direction,
                        delay_minutes=delay_minutes,
                        sim_time=sim_time,
                        depth=0,
                        producer_callback=_emit_status_changed_callback,
                    )

    # Update Neo4j
    updated = await update_flight_status(
        flight_id=flight_id,
        new_status=new_status,
        sim_time=sim_time,
        delay_minutes=update_kwargs.get("delay_minutes", delay_minutes),
        delay_reason=update_kwargs.get("delay_reason"),
        estimated_time=update_kwargs.get("estimated_time"),
        actual_time=update_kwargs.get("actual_time"),
    )

    # Emit status change event
    emit_flight_status_changed(
        flight_id=flight_id,
        flight_number=flight_number,
        previous_status=previous_status,
        new_status=new_status,
        sim_time=sim_time,
        gate_id=flight.get("gate_id"),
        runway_id=flight.get("runway_id"),
        delay_minutes=delay_minutes,
    )

    # Broadcast to WebSocket
    if _ws_broadcast:
        try:
            asyncio.create_task(_ws_broadcast({
                "type": "FlightStatusChanged",
                "flight_id": flight_id,
                "flight_number": flight_number,
                "previous_status": previous_status,
                "new_status": new_status,
                "gate_id": flight.get("gate_id"),
                "sim_time": sim_time.isoformat(),
            }))
        except Exception:
            pass

    logger.debug(
        "Flight %s: %s -> %s (delay=%d)",
        flight_number, previous_status, new_status, delay_minutes,
    )


async def _emit_status_changed_callback(
    flight_id: str,
    flight: dict,
    previous_status: str,
    new_status: str,
    sim_time: datetime,
) -> None:
    """Callback for turnaround propagation to emit FlightStatusChanged."""
    emit_flight_status_changed(
        flight_id=flight_id,
        flight_number=flight.get("flight_number", ""),
        previous_status=previous_status,
        new_status=new_status,
        sim_time=sim_time,
        delay_minutes=flight.get("delay_minutes", 0),
        reason="turnaround_delay",
    )


async def _on_weather_changed(payload: dict, sim_time: datetime) -> None:
    """Handle WeatherStateChanged — update runway capacity."""
    global _sim_time
    _sim_time = sim_time

    category = payload.get("new_category", "CAVOK")
    arrival_rate = payload.get("recommended_arrival_rate", 32)
    departure_rate = payload.get("recommended_departure_rate", 32)
    runway_impact = payload.get("runway_impact", "none")

    _runway_queue.update_capacity(arrival_rate, departure_rate, category)

    # If severe weather, close affected runways
    if runway_impact == "closed":
        _incident_affected_runways.update(["09L", "27R", "09R", "27L"])
    elif runway_impact == "single_runway":
        # Only ILS runways remain open — close non-ILS
        _incident_affected_runways.discard("09L")
        _incident_affected_runways.discard("27R")
        _incident_affected_runways.add("09R")
        _incident_affected_runways.add("27L")
    else:
        # Clear weather-related runway closures
        _incident_affected_runways.clear()

    logger.info(
        "Weather updated: %s (arr=%d/hr, dep=%d/hr, impact=%s)",
        category, arrival_rate, departure_rate, runway_impact,
    )


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentCreated — hold flights on affected runway or gate."""
    location = payload.get("location", "")
    severity = payload.get("severity", "low")
    incident_type = payload.get("type", "")

    # Runway incident
    if "runway" in location.lower():
        runway_id = location.replace("runway-", "")
        _incident_affected_runways.add(runway_id)
        logger.info("Incident: runway %s affected (%s)", runway_id, incident_type)

    # Gate incident
    if "gate" in location.lower():
        gate_id = location.replace("gate-", "")
        _incident_affected_gates.add(gate_id)
        logger.info("Incident: gate %s affected (%s)", gate_id, incident_type)


async def _on_incident_status_changed(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentStatusChanged — resume flights if incident resolved."""
    new_status = payload.get("new_status", "")
    location = payload.get("location", "")

    if new_status in ("resolved", "contained"):
        if "runway" in location.lower():
            runway_id = location.replace("runway-", "")
            _incident_affected_runways.discard(runway_id)
            logger.info("Incident resolved: runway %s restored", runway_id)
        if "gate" in location.lower():
            gate_id = location.replace("gate-", "")
            _incident_affected_gates.discard(gate_id)
            logger.info("Incident resolved: gate %s restored", gate_id)


async def _on_schedule_seeded(payload: dict, sim_time: datetime) -> None:
    """Handle FlightScheduleSeeded — log acknowledgment (flights already in Neo4j)."""
    total = payload.get("total_flights", 0)
    sim_day = payload.get("sim_day", 0)
    logger.info("Flight schedule seeded: day=%d, flights=%d", sim_day, total)


# --- Public API for manual hold/release ---

async def hold_flight(flight_id: str, reason: str, duration_min: int, sim_time: datetime) -> dict | None:
    """Place a manual hold on a flight."""
    _held_flights[flight_id] = {
        "reason": reason,
        "expected_duration_minutes": duration_min,
        "held_at": sim_time.isoformat(),
    }
    from db.neo4j import apply_delay
    estimated = None
    from db.neo4j import get_flight_by_id
    flight = await get_flight_by_id(flight_id)
    if flight:
        est = flight.get("estimated_time")
        if est:
            try:
                new_est = datetime.fromisoformat(str(est)) + timedelta(minutes=duration_min)
                estimated = new_est.isoformat()
            except (ValueError, TypeError):
                pass

    updated = await apply_delay(
        flight_id=flight_id,
        delay_minutes=duration_min,
        reason=reason,
        new_estimated_time=estimated or "",
        sim_time=sim_time,
    )

    if updated:
        emit_flight_status_changed(
            flight_id=flight_id,
            flight_number=updated.get("flight_number", ""),
            previous_status=updated.get("status", "boarding"),
            new_status="delayed",
            sim_time=sim_time,
            delay_minutes=duration_min,
            reason=reason,
        )

        # Broadcast to WebSocket
        if _ws_broadcast:
            try:
                asyncio.create_task(_ws_broadcast({
                    "type": "FlightStatusChanged",
                    "flight_id": flight_id,
                    "flight_number": updated.get("flight_number", ""),
                    "previous_status": "boarding",
                    "new_status": "delayed",
                    "sim_time": sim_time.isoformat(),
                }))
            except Exception:
                pass

    return updated


async def release_flight(flight_id: str, sim_time: datetime) -> dict | None:
    """Release a manual hold on a flight."""
    _held_flights.pop(flight_id, None)
    from db.neo4j import get_flight_by_id, update_flight_status
    flight = await get_flight_by_id(flight_id)
    if not flight:
        return None

    direction = flight.get("direction", "departure")
    new_status = "boarding" if direction == "departure" else "approach"

    updated = await update_flight_status(
        flight_id=flight_id,
        new_status=new_status,
        sim_time=sim_time,
    )

    if updated:
        emit_flight_status_changed(
            flight_id=flight_id,
            flight_number=flight.get("flight_number", ""),
            previous_status="delayed",
            new_status=new_status,
            sim_time=sim_time,
        )

    return updated
