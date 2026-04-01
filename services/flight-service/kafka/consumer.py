"""Kafka consumer for flight-service.

Consumes: SimClockTick, WeatherStateChanged, IncidentCreated, IncidentStatusChanged, FlightScheduleSeeded
On each tick: evaluates all active flights through the FSM, assigns runways, resolves gates.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from confluent_kafka import Consumer

from db.neo4j import (
    get_active_flights,
    get_active_incident_locations,
    update_flight_status,
    get_boarded_percentage,
    assign_flight_to_runway,
    release_gate,
    get_open_runway,
    get_paired_flight,
)
from kafka.producer import (
    emit_flight_status_changed,
    emit_flight_gate_assigned,
    emit_flight_runway_assigned,
    emit_flight_cancelled,
    emit_turnaround_task_changed,
    emit_bulk_state_snapshot,
)
from services.state_machine import evaluate_transition
from services.runway_queue import RunwayQueue
from services.gate_resolver import ensure_gate_assigned
from services.turnaround import propagate_turnaround_delay
from services.turnaround_plan import (
    TurnaroundPlan,
    create_turnaround_plan,
    nominal_turnaround_minutes,
)
from services.spatial import taxi_time_from_positions
from metrics import (
    flight_status_transitions_total as m_transitions,
    flights_active as m_active,
    flights_delayed_current as m_delayed,
    flights_cancelled_total as m_cancelled,
    envelope_invalid_total as m_envelope_invalid,
)

logger = logging.getLogger(__name__)


# ── Class-based state holder ────────────────────────────────


class FlightConsumerState:
    """Holds all mutable runtime state for the flight consumer.

    Eliminates module-level globals that caused repeated UnboundLocalError
    bugs (sprints 1, 3, 6) due to Python's `global` scoping rules.
    """

    def __init__(self) -> None:
        self.sim_time: datetime | None = None
        self.last_tick_sim_time: datetime | None = None
        self.runway_queue = RunwayQueue()
        self.held_flights: dict[str, dict] = {}
        self.incident_affected_gates: set[str] = set()
        self.incident_affected_runways: set[str] = set()
        self.processed_events: set[str] = set()
        self.ws_broadcast: Callable[[dict], Awaitable[None]] | None = None
        self.turnaround_plans: dict[str, TurnaroundPlan] = {}  # keyed by aircraft_registration
        # Spatial layout caches (populated from Neo4j on startup)
        self.gate_positions: dict[str, dict] = {}   # gate_id → {position_x, position_y}
        self.runway_positions: dict[str, dict] = {}  # runway_id → {threshold_x, threshold_y}
        # Speed mode tracking (REALTIME / FAST / BULK)
        self.current_mode: str = "REALTIME"
        self.last_mode: str = "REALTIME"
        self.last_sync_sim_time: datetime | None = None

    MAX_PROCESSED = 10000

    def check_idempotency(self, event_id: str) -> bool:
        """Returns True if the event has already been processed (duplicate)."""
        if not event_id:
            return False
        if event_id in self.processed_events:
            return True
        self.processed_events.add(event_id)
        if len(self.processed_events) > self.MAX_PROCESSED:
            excess = len(self.processed_events) - self.MAX_PROCESSED
            for _ in range(excess):
                self.processed_events.pop()
        return False

    async def rebuild_from_neo4j(self) -> None:
        """Rebuild in-memory incident impact sets from Neo4j on startup."""
        try:
            locations = await get_active_incident_locations()
        except Exception as e:
            logger.error("Failed to rebuild incident impacts: %s", e)
            return

        for location in locations:
            if "runway" in location.lower():
                runway_id = location.replace("runway-", "")
                self.incident_affected_runways.add(runway_id)
            if "gate" in location.lower():
                gate_id = location.replace("gate-", "")
                self.incident_affected_gates.add(gate_id)

        logger.info(
            "Rebuilt flight state from Neo4j: %d affected runways, %d affected gates",
            len(self.incident_affected_runways),
            len(self.incident_affected_gates),
        )

        # Load spatial positions for taxi time computation
        await self._load_spatial_positions()

    async def _load_spatial_positions(self) -> None:
        """Load gate and runway positions from Neo4j for taxi time computation."""
        from db.neo4j import get_driver
        try:
            driver = get_driver()
            async with driver.session() as session:
                result = await session.run(
                    "MATCH (g:Gate) WHERE g.position_x IS NOT NULL "
                    "RETURN g.id AS id, g.position_x AS x, g.position_y AS y"
                )
                async for record in result:
                    self.gate_positions[record["id"]] = {
                        "position_x": record["x"],
                        "position_y": record["y"],
                    }

                result = await session.run(
                    "MATCH (r:Runway) WHERE r.threshold_x IS NOT NULL "
                    "RETURN r.id AS id, r.threshold_x AS tx, r.threshold_y AS ty"
                )
                async for record in result:
                    self.runway_positions[record["id"]] = {
                        "threshold_x": record["tx"],
                        "threshold_y": record["ty"],
                    }

            logger.info(
                "Loaded spatial positions: %d gates, %d runways",
                len(self.gate_positions),
                len(self.runway_positions),
            )
        except Exception as e:
            logger.warning("Failed to load spatial positions (using defaults): %s", e)


# Module-level singleton
_state = FlightConsumerState()
_consumer: Consumer | None = None
_consumer_running = False


def set_ws_broadcast(fn):
    _state.ws_broadcast = fn


def get_sim_time() -> datetime | None:
    """Return the latest sim_time seen by the consumer, or None before the first tick."""
    return _state.sim_time


def get_runway_queue() -> RunwayQueue:
    """Return the in-memory runway queue used for slot scheduling."""
    return _state.runway_queue


def get_held_flights() -> dict:
    """Return the dict of manually held flights (flight_id → hold info)."""
    return _state.held_flights


def is_consumer_running() -> bool:
    """Return True if the Kafka consumer loop is actively polling."""
    return _consumer_running


def stop_consumer() -> None:
    """Signal the consumer loop to terminate after the current poll cycle."""
    global _consumer_running
    _consumer_running = False


def _make_consumer() -> Consumer:
    """Create a new confluent-kafka Consumer configured for the flight-svc group."""
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
    _consumer.subscribe(["sim.clock", "weather.events", "incidents.events", "flights.schedule", "baggage.events"])
    _consumer_running = True

    loop = asyncio.get_event_loop()
    logger.info("Kafka consumer started (topics: sim.clock, weather.events, incidents.events, flights.schedule)")

    try:
        while _consumer_running:
            # Batch-consume to allow tick skipping when behind
            msgs = await loop.run_in_executor(None, lambda: _consumer.consume(200, timeout=1.0))
            if not msgs:
                continue

            # Separate clock ticks from other events, keeping order
            latest_tick_envelope = None
            other_envelopes: list[dict] = []
            skipped_ticks = 0

            for msg in msgs:
                if msg is None or msg.error():
                    continue
                try:
                    envelope = json.loads(msg.value().decode("utf-8"))
                except Exception:
                    continue
                if envelope.get("event_type") == "SimClockTick":
                    if latest_tick_envelope is not None:
                        skipped_ticks += 1
                    latest_tick_envelope = envelope
                else:
                    other_envelopes.append(envelope)

            if skipped_ticks > 0:
                logger.debug("Skipped %d stale clock ticks", skipped_ticks)

            # Process non-tick events first (flight status changes, etc.)
            for envelope in other_envelopes:
                try:
                    await _dispatch(envelope)
                except Exception as e:
                    logger.error("Processing error: %s", e, exc_info=True)

            # Process only the latest clock tick
            if latest_tick_envelope is not None:
                try:
                    await _dispatch(latest_tick_envelope)
                except Exception as e:
                    logger.error("Processing error: %s", e, exc_info=True)
    finally:
        _consumer.close()
        _consumer_running = False
        logger.info("Kafka consumer stopped")


def _validate_envelope(envelope: dict) -> tuple[str | None, dict, datetime | None]:
    """Validate event envelope. Returns (event_type, payload, sim_time) or Nones on failure."""
    event_type = envelope.get("event_type")
    if not isinstance(event_type, str):
        m_envelope_invalid.labels(reason="missing_event_type").inc()
        logger.warning("Invalid envelope: missing or non-string event_type")
        return None, {}, None

    sim_time_str = envelope.get("sim_time")
    if not sim_time_str:
        m_envelope_invalid.labels(reason="missing_sim_time").inc()
        logger.warning("Invalid envelope: missing sim_time (event_type=%s)", event_type)
        return None, {}, None

    try:
        sim_time = datetime.fromisoformat(str(sim_time_str)).replace(tzinfo=None)
    except (ValueError, TypeError):
        m_envelope_invalid.labels(reason="invalid_sim_time").inc()
        logger.warning("Invalid envelope: unparseable sim_time=%r", sim_time_str)
        return None, {}, None

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        m_envelope_invalid.labels(reason="invalid_payload").inc()
        logger.warning("Invalid envelope: payload is not a dict (event_type=%s)", event_type)
        return None, {}, None

    return event_type, payload, sim_time


async def _dispatch(envelope: dict) -> None:
    """Route events to handlers based on event_type."""
    event_id = envelope.get("event_id", "")

    # Idempotency check
    if _state.check_idempotency(event_id):
        return

    event_type, payload, sim_time = _validate_envelope(envelope)
    if event_type is None:
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
        case "BaggageFlagged":
            await _on_baggage_flagged(payload, sim_time)
        case _:
            pass


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    """Process a SimClockTick — advance all active flights through the FSM."""
    _state.sim_time = sim_time
    _state.last_tick_sim_time = sim_time

    # Track simulation mode
    _state.last_mode = _state.current_mode
    _state.current_mode = payload.get("mode", "REALTIME")
    is_bulk = _state.current_mode == "BULK"

    # Compute delta for multi-minute ticks
    step_minutes = payload.get("step_minutes", 1)

    # 1. Get all active flights
    flights = await get_active_flights(sim_time)

    # 2. Assign runway slots from the queue
    runway_assignments = _state.runway_queue.assign_slots(sim_time)
    for assignment in runway_assignments:
        runway_id = await get_open_runway(ils_required=_state.runway_queue.ils_required)
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
                    if not is_bulk:
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

    # 3b. Advance all active turnaround plans (delta-aware)
    _advance_turnaround_plans(sim_time, step_minutes)

    # 4. Update Prometheus gauges
    status_counts: dict[str, int] = {}
    delayed_count = 0
    for flight in flights:
        s = flight.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
        if s == "delayed":
            delayed_count += 1
    for s, count in status_counts.items():
        m_active.labels(status=s).set(count)
    m_delayed.set(delayed_count)

    # 5. BULK mode: emit periodic BulkStateSnapshot
    if is_bulk:
        await _maybe_emit_flight_bulk_snapshot(sim_time, status_counts)


BULK_SNAPSHOT_INTERVAL_SIM_MIN = int(os.getenv("BULK_SNAPSHOT_INTERVAL_MIN", "60"))


async def _maybe_emit_flight_bulk_snapshot(
    sim_time: datetime,
    status_counts: dict[str, int],
) -> None:
    """Emit a BulkStateSnapshot summarising flight state (BULK mode only)."""
    force = _state.last_mode == "BULK" and _state.current_mode != "BULK"

    if not force and _state.last_sync_sim_time is not None:
        elapsed = (sim_time - _state.last_sync_sim_time).total_seconds() / 60
        if elapsed < BULK_SNAPSHOT_INTERVAL_SIM_MIN:
            return

    _state.last_sync_sim_time = sim_time

    summary = {
        "by_status": status_counts,
        "active_turnarounds": len(_state.turnaround_plans),
        "held_flights": len(_state.held_flights),
        "affected_runways": list(_state.incident_affected_runways),
        "affected_gates": list(_state.incident_affected_gates),
    }

    emit_bulk_state_snapshot(sim_time, summary)
    logger.info("BulkStateSnapshot emitted (flights): %s", status_counts)


def _advance_turnaround_plans(sim_time: datetime, step_minutes: int = 1) -> None:
    """Advance all active turnaround plans and emit events for changed tasks.

    When step_minutes > 1 (BULK mode), advance the plan multiple times to
    ensure tasks that complete within the step window are properly resolved.
    """
    completed_regs: list[str] = []
    is_bulk = _state.current_mode == "BULK"

    for reg, plan in _state.turnaround_plans.items():
        if step_minutes > 1 and plan.started_at is not None:
            # Advance through intermediate minutes for correct task completion
            for offset in range(step_minutes):
                intermediate = sim_time - timedelta(minutes=step_minutes - 1 - offset)
                changed = plan.advance(intermediate)
                if not is_bulk:
                    for task in changed:
                        emit_turnaround_task_changed(
                            flight_id=plan.arrival_flight_id,
                            aircraft_registration=reg,
                            task_name=task.name,
                            new_status=task.status.value,
                            sim_time=intermediate,
                            duration_min=task.duration_min,
                        )
        else:
            changed = plan.advance(sim_time)
            if not is_bulk:
                for task in changed:
                    emit_turnaround_task_changed(
                        flight_id=plan.arrival_flight_id,
                        aircraft_registration=reg,
                        task_name=task.name,
                        new_status=task.status.value,
                        sim_time=sim_time,
                        duration_min=task.duration_min,
                    )
        if plan.is_complete:
            completed_regs.append(reg)
    # Don't remove completed plans here — they'll be cleaned up when 'arrived' fires


def get_turnaround_plan(aircraft_registration: str) -> TurnaroundPlan | None:
    """Public accessor for turnaround plan state (used by routers)."""
    return _state.turnaround_plans.get(aircraft_registration)


async def _process_flight(flight: dict, sim_time: datetime) -> None:
    """Evaluate and execute FSM transition for a single flight."""
    flight_id = flight["id"]
    current_status = flight["status"]
    direction = flight.get("direction", "departure")

    # Check manual hold
    has_hold = flight_id in _state.held_flights

    # Check gate availability
    gate_id = flight.get("gate_id")
    gate_available = True
    if gate_id and gate_id in _state.incident_affected_gates:
        gate_available = False

    # Check runway availability
    runway_available = True
    runway_id = flight.get("runway_id")
    if runway_id and runway_id in _state.incident_affected_runways:
        runway_available = False
    # Also check if any runway at all is available
    if not runway_id:
        open_rw = await get_open_runway(ils_required=_state.runway_queue.ils_required)
        runway_available = open_rw is not None

    # Get boarding percentage for departure flights in boarding state
    boarded_pct = 1.0
    if current_status == "boarding" and direction == "departure":
        boarded_pct = await get_boarded_percentage(flight_id)
        # Fallback only for true positioning flights with no passengers assigned.
        # For normal flights, do not synthesize boarding progress from elapsed time,
        # otherwise flights can depart with unrealistically low onboard counts.
        if boarded_pct < 0.01:
            pax_count = flight.get("pax_count", 0) or 0
            if pax_count == 0:
                # Positioning flight with no passengers — allow immediate departure.
                boarded_pct = 1.0

    # For scheduled departures, ensure gate is assigned before boarding
    if current_status == "scheduled" and direction == "departure":
        estimated = flight.get("estimated_time")
        if estimated:
            try:
                est = datetime.fromisoformat(str(estimated))
                if sim_time >= est - timedelta(minutes=65):
                    new_gate = await ensure_gate_assigned(
                        flight_id, gate_id, None, sim_time,
                        aircraft_type=flight.get("aircraft_type"),
                        flight_type=flight.get("flight_type"),
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
                _state.runway_queue.enqueue_arrival(flight_id, str(estimated))
        except (ValueError, TypeError):
            pass

    # For departures ready to depart, enqueue for runway (only if not already assigned)
    if current_status == "boarding" and direction == "departure" and not flight.get("runway_id"):
        estimated = flight.get("estimated_time", "")
        if boarded_pct >= 0.95:
            _state.runway_queue.enqueue_departure(flight_id, str(estimated))

    # Compute spatial taxi times from positions
    runway_id = flight.get("runway_id")
    runway_pos = _state.runway_positions.get(runway_id) if runway_id else None
    gate_pos = _state.gate_positions.get(gate_id) if gate_id else None
    taxi_initial, taxi_total = taxi_time_from_positions(runway_pos, gate_pos)

    # Evaluate FSM transition
    new_status = evaluate_transition(
        flight=flight,
        sim_time=sim_time,
        runway_available=runway_available,
        gate_available=gate_available,
        boarded_pct=boarded_pct,
        has_hold=has_hold,
        taxi_initial_min=taxi_initial,
        taxi_total_min=taxi_total,
    )

    # ── Turnaround-aware gating ──
    reg = flight.get("aircraft_registration", "")

    # Gate arrival at_gate → arrived on deplaning completion
    if (new_status == "arrived" and direction == "arrival"
            and reg and reg in _state.turnaround_plans):
        plan = _state.turnaround_plans[reg]
        if not plan.deplaning_done:
            new_status = None  # wait for deplaning to complete

    # Gate departure scheduled → boarding on turnaround readiness
    if (new_status == "boarding" and direction == "departure"
            and reg and reg in _state.turnaround_plans):
        plan = _state.turnaround_plans[reg]
        if not plan.ready_for_boarding:
            new_status = None  # wait for cleaning + deplaning

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
                    new_gate = await ensure_gate_assigned(
                        flight_id, None, None, sim_time,
                        aircraft_type=flight.get("aircraft_type"),
                        flight_type=flight.get("flight_type"),
                    )
                    if new_gate:
                        emit_flight_gate_assigned(
                            flight_id=flight_id,
                            flight_number=flight_number,
                            gate_id=new_gate,
                            sim_time=sim_time,
                        )

        case "departed":
            update_kwargs["actual_time"] = sim_time.isoformat()
            # Compute arrival_estimated_time for departures
            if direction == "departure":
                duration = flight.get("flight_duration_minutes")
                if duration and int(duration) > 0:
                    from datetime import timedelta as td
                    arrival_est = sim_time + td(minutes=int(duration))
                    update_kwargs["arrival_estimated_time"] = arrival_est.isoformat()
            # Release gate
            released = await release_gate(flight_id)
            if released:
                logger.info("Gate %s released by departing flight %s", released, flight_number)

        case "landed":
            update_kwargs["actual_time"] = sim_time.isoformat()
            # Assign gate for arrival
            if direction == "arrival":
                gate_id = flight.get("gate_id")
                new_gate = await ensure_gate_assigned(
                    flight_id, gate_id, None, sim_time,
                    aircraft_type=flight.get("aircraft_type"),
                    flight_type=flight.get("flight_type"),
                )
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
            if flight_id in _state.held_flights:
                reason = _state.held_flights[flight_id].get("reason", "manual_hold")
            elif flight.get("runway_id") in _state.incident_affected_runways:
                reason = "runway_incident"
            elif flight.get("gate_id") in _state.incident_affected_gates:
                reason = "gate_incident"
            else:
                reason = reason or "operational"
            update_kwargs["delay_reason"] = reason

        case "cancelled":
            update_kwargs["delay_reason"] = "delay_exceeded_180min"
            # Remove from runway queue
            _state.runway_queue.remove(flight_id)
            # Remove hold
            _state.held_flights.pop(flight_id, None)
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
            # Arrival turnaround — create task-based turnaround plan
            if direction == "arrival":
                reg = flight.get("aircraft_registration", "")
                aircraft_type = flight.get("aircraft_type", "")
                if reg:
                    paired = await get_paired_flight(reg, "arrival")
                    paired_id = paired["id"] if paired else None
                    plan = create_turnaround_plan(
                        aircraft_registration=reg,
                        arrival_flight_id=flight_id,
                        aircraft_type=aircraft_type,
                        paired_departure_id=paired_id,
                        flight_type=flight.get("flight_type"),
                    )
                    started_tasks = plan.start(sim_time)
                    _state.turnaround_plans[reg] = plan
                    for t in started_tasks:
                        emit_turnaround_task_changed(
                            flight_id=flight_id,
                            aircraft_registration=reg,
                            task_name=t.name,
                            new_status=t.status.value,
                            sim_time=sim_time,
                            duration_min=t.duration_min,
                        )
                    logger.info(
                        "Turnaround plan created for %s (reg=%s, cp=%d min)",
                        flight_number, reg, plan.critical_path_minutes(),
                    )

                    # Propagate delay via critical-path math (replaces flat buffer)
                    if delay_minutes > 0 and paired:
                        buffer = nominal_turnaround_minutes(aircraft_type, flight.get("flight_type"))
                        propagated = max(0, delay_minutes - buffer)
                        if propagated > 0:
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

        case "arrived":
            # Arrival fully completed — release gate and clean up turnaround
            if direction == "arrival":
                released = await release_gate(flight_id)
                if released:
                    logger.info("Gate %s released by arrived flight %s", released, flight_number)
                # Clean up turnaround plan if complete
                reg = flight.get("aircraft_registration", "")
                if reg and reg in _state.turnaround_plans:
                    plan = _state.turnaround_plans[reg]
                    if plan.is_complete:
                        del _state.turnaround_plans[reg]

    # Update Neo4j
    await update_flight_status(
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

    # Update Prometheus counters
    m_transitions.labels(from_status=previous_status, to_status=new_status).inc()
    if new_status == "cancelled":
        reason = update_kwargs.get("delay_reason", "unknown")
        m_cancelled.labels(reason=reason).inc()

    # Immediately update alert-critical gauges at mutation site
    m_active.labels(status=previous_status).dec()
    m_active.labels(status=new_status).inc()

    # Broadcast to WebSocket
    if _state.ws_broadcast:
        try:
            asyncio.create_task(_state.ws_broadcast({
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
    _state.sim_time = sim_time

    category = payload.get("new_category", "CAVOK")
    arrival_rate = payload.get("recommended_arrival_rate", 32)
    departure_rate = payload.get("recommended_departure_rate", 32)
    runway_impact = payload.get("runway_impact", "none")

    _state.runway_queue.update_capacity(arrival_rate, departure_rate, category)

    # If severe weather, close affected runways
    if runway_impact == "closed":
        _state.incident_affected_runways.update(["09L", "27R", "09R", "27L"])
    elif runway_impact == "single_runway":
        # Only ILS runways remain open — close non-ILS
        _state.incident_affected_runways.discard("09L")
        _state.incident_affected_runways.discard("27R")
        _state.incident_affected_runways.add("09R")
        _state.incident_affected_runways.add("27L")
    else:
        # Clear weather-related runway closures
        _state.incident_affected_runways.clear()

    logger.info(
        "Weather updated: %s (arr=%d/hr, dep=%d/hr, impact=%s)",
        category, arrival_rate, departure_rate, runway_impact,
    )


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentCreated — hold flights on affected runway or gate."""
    location = payload.get("location", "")
    incident_type = payload.get("type", "")

    # Runway incident
    if "runway" in location.lower():
        runway_id = location.replace("runway-", "")
        _state.incident_affected_runways.add(runway_id)
        logger.info("Incident: runway %s affected (%s)", runway_id, incident_type)

    # Gate incident
    if "gate" in location.lower():
        gate_id = location.replace("gate-", "")
        _state.incident_affected_gates.add(gate_id)
        logger.info("Incident: gate %s affected (%s)", gate_id, incident_type)


async def _on_incident_status_changed(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentStatusChanged — resume flights if incident resolved."""
    new_status = payload.get("new_status", "")
    location = payload.get("location", "")

    if new_status in ("resolved", "contained"):
        if "runway" in location.lower():
            runway_id = location.replace("runway-", "")
            _state.incident_affected_runways.discard(runway_id)
            logger.info("Incident resolved: runway %s restored", runway_id)
        if "gate" in location.lower():
            gate_id = location.replace("gate-", "")
            _state.incident_affected_gates.discard(gate_id)
            logger.info("Incident resolved: gate %s restored", gate_id)


async def _on_schedule_seeded(payload: dict, sim_time: datetime) -> None:
    """Handle FlightScheduleSeeded — log acknowledgment (flights already in Neo4j)."""
    total = payload.get("total_flights", 0)
    sim_day = payload.get("sim_day", 0)
    logger.info("Flight schedule seeded: day=%d, flights=%d", sim_day, total)


async def _on_baggage_flagged(payload: dict, sim_time: datetime) -> None:
    """Handle BaggageFlagged — extend baggage_offload task in the turnaround plan."""
    flight_id = payload.get("flight_id", "")
    if not flight_id:
        return
    # Look up the aircraft registration for this flight's turnaround plan
    from db.neo4j import get_flight_by_id
    flight = await get_flight_by_id(flight_id)
    if not flight:
        return
    reg = flight.get("aircraft_registration", "")
    if not reg or reg not in _state.turnaround_plans:
        return
    plan = _state.turnaround_plans[reg]
    # Flagged baggage adds 5 min to offload time
    plan.extend_task("baggage_offload", 5)
    logger.info("Baggage flagged on %s — extended baggage_offload by 5 min (reg=%s)", flight_id, reg)


# --- Public API for manual hold/release ---

async def hold_flight(flight_id: str, reason: str, duration_min: int, sim_time: datetime) -> dict | None:
    """Place a manual hold on a flight."""
    _state.held_flights[flight_id] = {
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
        if _state.ws_broadcast:
            try:
                asyncio.create_task(_state.ws_broadcast({
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
    _state.held_flights.pop(flight_id, None)
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
