"""Kafka consumer for flight-service.

Consumes: SimClockTick, WeatherStateChanged, IncidentCreated, IncidentStatusChanged, FlightScheduleSeeded
On each tick: evaluates all active flights through the FSM, assigns runways, resolves gates.
"""

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from _common import kafka_runtime
from _common import outbox as outbox_common
from _common.idempotency import IdempotencyTracker
from _common.command_store import load_receipt_in_tx, save_receipt_in_tx
from _common.consumer_health import ConsumerHealthTracker
from _common.airport_config import load_airport_runtime_config

from confluent_kafka import Consumer

from db.neo4j import (
    get_active_flights,
    get_active_incident_impacts,
    update_flight_status_in_tx,
    assign_flight_to_gate_in_tx,
    set_manual_hold_in_tx,
    next_outbox_revision,
    get_driver,
    get_boarded_percentage,
    assign_flight_to_runway_in_tx,
    is_gate_occupied,
    get_flight_by_id,
    release_gate_in_tx,
    get_open_runway,
    get_paired_flight,
    seed_ground_vehicles,
)
from kafka.producer import (
    build_fact,
    emit_flight_status_changed,
    emit_flight_gate_assigned,
    emit_turnaround_task_changed,
    emit_bulk_state_snapshot,
    emit_minimum_fuel_warning,
    emit_ground_vehicle_dispatched,
    emit_ground_vehicle_returned,
)
from services.state_machine import evaluate_transition
from application.decisions import (
    boarding_delay_update,
    resolve_delay_reason,
    suppress_transition_for_turnaround,
)
from application.commands import (
    GroundDelayProgram,
    HoldFlight,
    ReassignGate,
    parse_command,
    validate_hold_precondition,
)
from services.runway_queue import RunwayQueue
from services.gate_resolver import ensure_gate_assigned
from services.turnaround import propagate_turnaround_delay
from services.turnaround_plan import (
    TurnaroundPlan,
    create_turnaround_plan,
    nominal_turnaround_minutes,
)
from services.spatial import taxi_time_from_positions
from services.ground_vehicles import GroundVehiclePool, VEHICLE_TASK_MAP
from metrics import (
    flight_status_transitions_total as m_transitions,
    flights_active as m_active,
    flights_delayed_current as m_delayed,
    flights_cancelled_total as m_cancelled,
    envelope_invalid_total as m_envelope_invalid,
    ground_vehicle_utilisation_pct as m_vehicle_util,
    ground_vehicle_contention_total as m_vehicle_contention,
    flight_commands_total as m_commands,
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
        self.active_incident_locations: dict[str, str] = {}
        self.weather_affected_runways: set[str] = set()
        self._idempotency = IdempotencyTracker(max_size=10_000)
        self.ws_broadcast: Callable[[dict], Awaitable[None]] | None = None
        self.turnaround_plans: dict[str, TurnaroundPlan] = {}  # keyed by aircraft_registration
        # Spatial layout caches (populated from Neo4j on startup)
        self.gate_positions: dict[str, dict] = {}   # gate_id → {position_x, position_y}
        self.runway_positions: dict[str, dict] = {}  # runway_id → {threshold_x, threshold_y}
        # Speed mode tracking (REALTIME / FAST / BULK)
        self.current_mode: str = "REALTIME"
        self.last_mode: str = "REALTIME"
        self.last_sync_sim_time: datetime | None = None
        # ── Noise model state (Phase 1.2) ──
        # Tracks flights already evaluated for stochastic draws (one draw per flight)
        self.crew_delay_drawn: set[str] = set()        # flight_ids that had crew delay draw
        self.ctot_assigned: set[str] = set()            # flight_ids with CTOT slot
        self.equipment_failure_drawn: set[str] = set()  # flight_ids with equipment failure draw
        self.diversion_drawn: set[str] = set()          # flight_ids with diversion draw
        # Holding stack tracking: flight_id -> minutes in holding
        self.holding_minutes: dict[str, int] = {}
        self.fuel_warned: set[str] = set()              # flight_ids that got MinimumFuelWarning
        self.fuel_panpan: set[str] = set()              # flight_ids that declared PAN PAN
        # Settings cache (updated from sim-orchestrator via settings event)
        self.noise_settings: dict = {
            "crew_delay_probability": 0.05,
            "crew_delay_min": 5,
            "crew_delay_max": 15,
            "ctot_probability_peak": 0.10,
            "ctot_delay_min": 5,
            "ctot_delay_max": 30,
            "equipment_failure_rate": 0.01,
            "equipment_failure_delay_min": 8,
            "equipment_failure_delay_max": 20,
            "diversion_rate": 0.003,
            "holding_fuel_burn_kg_per_hr": 2500,
            "holding_fuel_warn_minutes": 30,
            "holding_fuel_panpan_minutes": 45,
        }
        self.peak_hours: set[int] = set(load_airport_runtime_config().simulation.peak_hours)
        # ── Ground vehicle pool (Phase 1.3) ──
        self.vehicle_pool = GroundVehiclePool()
        self.vehicles_initialized: bool = False
        # Track which tasks already have a vehicle dispatched: (reg, task_name) → vehicle_id
        self.task_vehicles: dict[tuple[str, str], str] = {}

    def check_idempotency(self, event_id: str) -> bool:
        """Returns True if the event has already been processed (duplicate)."""
        return self._idempotency.is_duplicate(event_id)

    async def rebuild_from_neo4j(self) -> None:
        """Rebuild manual holds and incident impact sets from Neo4j."""
        from db.neo4j import get_manual_holds
        self.held_flights = await get_manual_holds()
        try:
            self.active_incident_locations = await get_active_incident_impacts()
        except Exception as e:
            logger.error("Failed to rebuild incident impacts: %s", e)
            return

        self.refresh_incident_impacts()

        logger.info(
            "Rebuilt flight state from Neo4j: %d affected runways, %d affected gates",
            len(self.incident_affected_runways),
            len(self.incident_affected_gates),
        )

        # Load spatial positions for taxi time computation
        await self._load_spatial_positions()

    def refresh_incident_impacts(self) -> None:
        self.incident_affected_runways = set(self.weather_affected_runways)
        self.incident_affected_gates.clear()
        for location in self.active_incident_locations.values():
            if "runway" in location.lower():
                runway_id = location.replace("runway-", "")
                self.incident_affected_runways.add(runway_id)
            if "gate" in location.lower():
                gate_id = location.replace("gate-", "")
                self.incident_affected_gates.add(gate_id)

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
            # Share gate positions with ground vehicle pool
            self.vehicle_pool.set_gate_positions(self.gate_positions)
        except Exception as e:
            logger.warning("Failed to load spatial positions (using defaults): %s", e)

        # Initialize ground vehicle fleet (Phase 1.3)
        if not self.vehicles_initialized:
            await self._initialize_vehicles()

    async def _initialize_vehicles(self) -> None:
        """Create ground vehicle fleet and persist to Neo4j."""
        try:
            vehicles = self.vehicle_pool.initialize_fleet()
            vehicle_dicts = [
                {
                    "id": v.id,
                    "type": v.vehicle_type,
                    "status": v.status,
                    "position_x": v.position_x,
                    "position_y": v.position_y,
                    "current_gate": v.current_gate,
                }
                for v in vehicles
            ]
            count = await seed_ground_vehicles(vehicle_dicts)
            self.vehicles_initialized = True
            logger.info("Ground vehicle fleet seeded: %d vehicles in Neo4j", count)
        except Exception as e:
            logger.warning("Failed to initialize ground vehicles: %s", e)


# Module-level singleton
_cavok = load_airport_runtime_config().operations.weather_capacity["CAVOK"]
_state = FlightConsumerState()
_consumer: Consumer | None = None
_consumer_running = False
_consumer_health = ConsumerHealthTracker()


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


def get_consumer_health() -> dict:
    """Return consumer health metrics for /health endpoint."""
    return _consumer_health.status()


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


_TOPICS = [
    "sim.clock",
    "weather.events",
    "incidents.events",
    "flights.schedule",
    "baggage.events",
    "flights.commands",
]


async def run_consumer() -> None:
    """Main consumer loop — runs as background asyncio task."""
    global _consumer, _consumer_running
    _consumer = _make_consumer()
    _consumer.subscribe(_TOPICS)
    _consumer_running = True
    logger.info("Kafka consumer started (topics: %s)", _TOPICS)
    try:
        await kafka_runtime.run_consumer_loop(
            _consumer, _dispatch, lambda: _consumer_running, _consumer_health,
        )
    finally:
        _consumer_running = False
        _consumer = None


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
    """Route events to handlers based on event_type.

    Command envelopes (keyed on ``command_type``, from ``flights.commands``) are
    imperatives, not facts — they take a separate path.
    """
    # Commands are keyed on command_type (no event_type / sim_time).
    if envelope.get("command_type") is not None:
        await _handle_command(envelope)
        return

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



# Bounded process-local fast dedup. The durable guard is the CommandReceipt
# node read via load_receipt_in_tx inside the command transaction; this cache
# only spares a re-read on a hot in-process redelivery.
_command_results: dict[str, tuple[str, dict]] = {}


async def _handle_command(envelope: dict) -> None:
    """Execute an operator/agent command from ``flights.commands`` atomically (G1-b).

    One ``session.execute_write`` per command covers: the durable redelivery
    check (``load_receipt_in_tx`` on ``command_id``), the domain write(s), the
    domain fact(s) staged to the outbox, the command receipt node
    (``save_receipt_in_tx``) and the ``CommandExecuted``/``CommandRejected``
    receipt fact staged to the outbox — all commit together or none do. A
    redelivered command finds the receipt and re-mutates nothing; the receipt
    fact is delivered by the outbox (at-least-once, stable id), so no separate
    re-emit is needed. In-memory caches / WS / metrics run only post-commit.
    """
    command_id = envelope.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        raise ValueError("command_id is required")
    sim_time = _state.sim_time
    if sim_time is None:
        raise RuntimeError("Simulation clock not available")

    # Hot-path dedup: already committed in this process → outbox owns delivery.
    if command_id in _command_results:
        return

    command_type = envelope.get("command_type")
    # Validate + read + check preconditions OUTSIDE the write transaction.
    run = await _plan_command(envelope, sim_time)
    receipt_event_id = f"cmd:{command_id}"

    async def apply(tx):
        existing = await load_receipt_in_tx(tx, command_id)
        if existing is not None:
            # Durable redelivery dedup: do not re-mutate or re-stage.
            return existing, None
        reason, domain_facts, post = await run(tx)
        receipt = (
            "CommandRejected" if reason else "CommandExecuted",
            {"command_id": command_id, "command_type": command_type, "reason": reason},
        )
        receipt_fact = {"id": receipt_event_id, "document": build_fact(
            receipt_event_id, receipt[0], sim_time, receipt[1])}
        revision = await next_outbox_revision(tx)
        await save_receipt_in_tx(tx, command_id, receipt)
        await outbox_common.stage_outbox(
            tx, "FlightOutbox", [*domain_facts, receipt_fact], revision,
        )
        return receipt, post

    async with get_driver().session() as session:
        receipt, post = await session.execute_write(apply)

    _command_results[command_id] = receipt
    if len(_command_results) > 10_000:
        del _command_results[next(iter(_command_results))]
    if post is not None:
        post()


def _reject(command_type, reason: str, log: str | None = None):
    """A planned command that only records a rejection receipt (no domain write)."""
    async def run(tx):
        if log:
            logger.warning(log)

        def post():
            m_commands.labels(command_type=str(command_type), outcome="rejected").inc()
        return reason, [], post
    return run


async def _plan_command(envelope: dict, sim_time: datetime):
    """Validate + read + build the in-transaction executor for a command.

    Returns an async ``run(tx) -> (reason, domain_facts, post_commit)``: on the
    accepted path it performs the domain write(s) on ``tx`` and returns the
    staged domain facts; on the rejected path it writes nothing and returns a
    reason string. ``post_commit`` applies in-memory/WS/metric side effects.
    """
    command_type = envelope.get("command_type")
    cmd, error = parse_command(command_type, envelope.get("payload"))
    if error is not None:
        return _reject(command_type, error, f"Rejected command {command_type}: {error}")

    if isinstance(cmd, (HoldFlight, ReassignGate)):
        flight = await get_flight_by_id(cmd.flight_id)
        if not flight:
            return _reject(command_type, "Flight not found",
                           f"Rejected command {command_type}: flight {cmd.flight_id} not found")

        if isinstance(cmd, HoldFlight):
            precondition_error = validate_hold_precondition(flight.get("status", ""))
            if precondition_error is not None:
                return _reject(command_type, precondition_error,
                               f"Rejected HoldFlight {cmd.flight_id}: {precondition_error}")

            async def run(tx):
                updated, facts = await _apply_hold_in_tx(
                    tx, flight, cmd.reason, cmd.duration_min, sim_time)
                if updated is None:
                    return "Flight hold could not be saved", [], lambda: (
                        m_commands.labels(command_type=command_type, outcome="rejected").inc())

                def post():
                    _hold_post_commit(flight, cmd.reason, cmd.duration_min, updated, sim_time)
                    m_commands.labels(command_type=command_type, outcome="accepted").inc()
                    logger.info("Executed HoldFlight for %s (%s, %dmin)",
                                cmd.flight_id, cmd.reason, cmd.duration_min)
                return None, facts, post
            return run

        # ReassignGate
        if await is_gate_occupied(cmd.gate_id, exclude_flight_id=cmd.flight_id):
            return _reject(command_type, "Gate reassignment rejected",
                           f"ReassignGate {cmd.flight_id} → {cmd.gate_id}: gate occupied")
        flight_number = flight.get("flight_number", "")

        async def run(tx):
            ok, facts = await _apply_reassign_in_tx(
                tx, cmd.flight_id, cmd.gate_id, sim_time, flight_number)
            if not ok:
                return "Gate reassignment rejected", [], lambda: (
                    m_commands.labels(command_type=command_type, outcome="rejected").inc())

            def post():
                _reassign_post_commit(cmd.flight_id, flight_number, cmd.gate_id, sim_time)
                m_commands.labels(command_type=command_type, outcome="accepted").inc()
                logger.info("ReassignGate for %s → gate %s: accepted", cmd.flight_id, cmd.gate_id)
            return None, facts, post
        return run

    if isinstance(cmd, GroundDelayProgram):
        eligible: list[dict] = []
        skipped = 0
        for fid in dict.fromkeys(cmd.flight_ids):
            flight = await get_flight_by_id(fid)
            if (flight is None or flight.get("direction") != "departure"
                    or validate_hold_precondition(flight.get("status", ""))):
                skipped += 1
                continue
            eligible.append(flight)

        async def run(tx):
            held_facts: list[dict] = []
            held_posts: list = []
            held = 0
            for flight in eligible:
                updated, facts = await _apply_hold_in_tx(
                    tx, flight, cmd.reason, cmd.stagger_minutes, sim_time)
                if updated is None:
                    continue
                held += 1
                held_facts.extend(facts)
                held_posts.append((flight, updated))
            if held == 0:
                return (f"GroundDelayProgram: no flights held ({skipped} skipped)", [],
                        lambda: m_commands.labels(command_type=command_type, outcome="rejected").inc())

            def post():
                for flight, updated in held_posts:
                    _hold_post_commit(flight, cmd.reason, cmd.stagger_minutes, updated, sim_time)
                m_commands.labels(command_type=command_type, outcome="accepted").inc()
                logger.info("GroundDelayProgram: held %d flights, skipped %d (stagger=%dmin)",
                            held, skipped + (len(eligible) - held), cmd.stagger_minutes)
            return None, held_facts, post
        return run

    # Unknown command shape — reject without mutating.
    return _reject(command_type, "Unsupported command")

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

    # 2. Assign runway slots from the queue. G1: each USES_RUNWAY write + its
    #    FlightRunwayAssigned fact commit atomically (durable inbox dedup +
    #    staged outbox); the in-memory runway_id is refreshed after commit.
    runway_assignments = _state.runway_queue.assign_slots(sim_time)
    for assignment in runway_assignments:
        runway_id = await get_open_runway(ils_required=_state.runway_queue.ils_required)
        if not runway_id:
            continue
        assign_flight_id = assignment["flight_id"]
        operation = assignment["operation"]
        # Find flight info for the event payload.
        matched = next((f for f in flights if f["id"] == assign_flight_id), None)
        flight_number = matched["flight_number"] if matched else ""
        sim_time_iso = sim_time.isoformat()
        event_id = f"rwy:{assign_flight_id}:{runway_id}:{operation}:{sim_time_iso}"
        facts: list[dict] = []
        if not is_bulk:
            facts = [{"id": event_id, "document": build_fact(
                event_id, "FlightRunwayAssigned", sim_time, {
                    "flight_id": assign_flight_id,
                    "flight_number": flight_number,
                    "runway_id": runway_id,
                    "operation": operation,
                })}]

        async def _assign_runway(tx, _fid=assign_flight_id, _rw=runway_id, _op=operation):
            await assign_flight_to_runway_in_tx(tx, _fid, _rw, _op, sim_time)

        await _commit_flight_writes(event_id, sim_time, facts, [_assign_runway])
        if matched is not None:
            matched["runway_id"] = runway_id

    # 3. Process each flight through the FSM
    for flight in flights:
        await _process_flight(flight, sim_time)

    # 3a. Holding fuel burn tracking (P1-2-6)
    _track_holding_fuel_burn(flights, sim_time, step_minutes, is_bulk)

    # 3b. Equipment failure injection on turnaround plans (P1-2-4)
    _check_equipment_failures(sim_time)

    # 3c. Advance all active turnaround plans (delta-aware)
    _advance_turnaround_plans(sim_time, step_minutes)

    # 3d. Advance ground vehicle pool (Phase 1.3)
    _advance_ground_vehicles(sim_time, is_bulk)

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

    # 4b. Ground vehicle utilisation metrics (Phase 1.3)
    for vtype, pct in _state.vehicle_pool.utilisation_by_type().items():
        m_vehicle_util.labels(vehicle_type=vtype).set(pct)

    # 5. BULK mode: emit periodic BulkStateSnapshot
    #    Also emit on BULK→non-BULK transition (forced flush)
    leaving_bulk = _state.last_mode == "BULK" and _state.current_mode != "BULK"
    if is_bulk or leaving_bulk:
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


# ── Noise model helpers (Phase 1.2) ────────────────────────


def _is_peak_hour(sim_time: datetime) -> bool:
    """Check if current sim hour is a peak hour."""
    return sim_time.hour in _state.peak_hours


def _draw_crew_delay(flight_id: str) -> int:
    """Draw a crew readiness delay for a flight. Returns delay minutes or 0."""
    if flight_id in _state.crew_delay_drawn:
        return 0
    _state.crew_delay_drawn.add(flight_id)
    ns = _state.noise_settings
    if random.random() < ns["crew_delay_probability"]:
        delay = random.randint(ns["crew_delay_min"], ns["crew_delay_max"])
        logger.info("Crew delay drawn for %s: %d min", flight_id, delay)
        return delay
    return 0


def _draw_ctot(flight_id: str, sim_time: datetime) -> int:
    """Draw a CTOT slot delay for a departure during peak hours. Returns delay minutes or 0."""
    if flight_id in _state.ctot_assigned:
        return 0
    if not _is_peak_hour(sim_time):
        return 0
    _state.ctot_assigned.add(flight_id)
    ns = _state.noise_settings
    if random.random() < ns["ctot_probability_peak"]:
        delay = random.randint(ns["ctot_delay_min"], ns["ctot_delay_max"])
        logger.info("CTOT assigned for %s: %d min", flight_id, delay)
        return delay
    return 0


def _draw_diversion(flight_id: str) -> bool:
    """Draw whether an arriving flight should be diverted. Returns True if diverted."""
    if flight_id in _state.diversion_drawn:
        return False
    _state.diversion_drawn.add(flight_id)
    ns = _state.noise_settings
    # Higher diversion rate in LIFR weather
    rate = ns["diversion_rate"]
    if _state.runway_queue.weather_category == "LIFR":
        rate *= 3.0
    elif _state.runway_queue.weather_category == "IMC":
        rate *= 1.5
    if random.random() < rate:
        logger.info("Diversion drawn for %s", flight_id)
        return True
    return False


def _track_holding_fuel_burn(
    flights: list[dict],
    sim_time: datetime,
    step_minutes: int,
    is_bulk: bool,
) -> None:
    """Track fuel burn for aircraft in holding (approach state waiting for runway).

    P1-2-6: After 30 min → MinimumFuelWarning. After 45 min → PAN PAN priority.
    """
    ns = _state.noise_settings
    warn_min = ns["holding_fuel_warn_minutes"]
    panpan_min = ns["holding_fuel_panpan_minutes"]
    fuel_rate = ns["holding_fuel_burn_kg_per_hr"]

    # Build set of flights currently in approach (holding)
    holding_ids = set()
    for f in flights:
        if f.get("status") == "approach" and f.get("direction") == "arrival":
            holding_ids.add(f["id"])

    # Update holding minutes
    for fid in list(_state.holding_minutes.keys()):
        if fid not in holding_ids:
            # No longer in holding — remove
            _state.holding_minutes.pop(fid, None)

    for f in flights:
        fid = f["id"]
        if fid not in holding_ids:
            continue
        # Increment holding time
        if fid not in _state.holding_minutes:
            _state.holding_minutes[fid] = 0
        _state.holding_minutes[fid] += step_minutes

        hold_min = _state.holding_minutes[fid]
        fuel_remaining = max(0, 20000 - int(fuel_rate * hold_min / 60))

        # MinimumFuelWarning at warn threshold
        if hold_min >= warn_min and fid not in _state.fuel_warned:
            _state.fuel_warned.add(fid)
            if not is_bulk:
                emit_minimum_fuel_warning(
                    flight_id=fid,
                    flight_number=f.get("flight_number", ""),
                    holding_minutes=hold_min,
                    fuel_remaining_kg=fuel_remaining,
                    is_panpan=False,
                    sim_time=sim_time,
                )
            logger.warning("MinimumFuelWarning: %s holding %d min", f.get("flight_number"), hold_min)

        # PAN PAN at panpan threshold — give priority landing
        if hold_min >= panpan_min and fid not in _state.fuel_panpan:
            _state.fuel_panpan.add(fid)
            # Re-enqueue as emergency to get priority
            _state.runway_queue.enqueue_arrival(fid, sim_time.isoformat(), is_emergency=True)
            if not is_bulk:
                emit_minimum_fuel_warning(
                    flight_id=fid,
                    flight_number=f.get("flight_number", ""),
                    holding_minutes=hold_min,
                    fuel_remaining_kg=fuel_remaining,
                    is_panpan=True,
                    sim_time=sim_time,
                )
            logger.warning("PAN PAN declared: %s holding %d min", f.get("flight_number"), hold_min)


def _check_equipment_failures(sim_time: datetime) -> None:
    """P1-2-4: Stochastic equipment failure on active turnaround tasks.

    1% chance per flight — checked once when the turnaround plan starts.
    Adds 8–20 min to a random in-progress task.
    """
    ns = _state.noise_settings
    for reg, plan in _state.turnaround_plans.items():
        if reg in _state.equipment_failure_drawn:
            continue
        if not plan.started_at:
            continue
        # Only draw once per turnaround
        _state.equipment_failure_drawn.add(reg)
        if random.random() >= ns["equipment_failure_rate"]:
            continue
        # Find an in-progress task to fail
        in_progress = [t for t in plan.tasks.values()
                       if t.status.value == "in_progress" and t.name != "deplaning"]
        if not in_progress:
            # Pick a pending task instead
            pending = [t for t in plan.tasks.values()
                       if t.status.value == "pending" and t.name not in ("deplaning", "pushback")]
            if pending:
                in_progress = pending
        if not in_progress:
            continue
        target = random.choice(in_progress)
        extra = random.randint(ns["equipment_failure_delay_min"], ns["equipment_failure_delay_max"])
        plan.extend_task(target.name, extra)
        logger.info(
            "Equipment failure on %s: task %s extended by %d min (reg=%s)",
            plan.arrival_flight_id, target.name, extra, reg,
        )


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
                _handle_task_vehicles(reg, plan, changed, intermediate, is_bulk)
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
            _handle_task_vehicles(reg, plan, changed, sim_time, is_bulk)
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


def _handle_task_vehicles(
    reg: str,
    plan: TurnaroundPlan,
    changed_tasks: list,
    sim_time: datetime,
    is_bulk: bool,
) -> None:
    """Dispatch or release ground vehicles based on turnaround task changes."""
    gate_id = plan.gate_id or ""

    for task in changed_tasks:
        task_key = (reg, task.name)

        if task.status.value == "in_progress" and task.name in VEHICLE_TASK_MAP:
            # Dispatch a vehicle for this task
            vehicle, transit = _state.vehicle_pool.request_vehicle(
                task.name, gate_id, plan.arrival_flight_id, sim_time,
            )
            if vehicle:
                _state.task_vehicles[task_key] = vehicle.id
                if transit > 0:
                    # Extend task duration by transit time
                    plan.extend_task(task.name, transit)
                if not is_bulk:
                    emit_ground_vehicle_dispatched(
                        vehicle_id=vehicle.id,
                        vehicle_type=vehicle.vehicle_type,
                        gate_id=gate_id,
                        flight_id=plan.arrival_flight_id,
                        task_name=task.name,
                        transit_minutes=transit,
                        sim_time=sim_time,
                    )
            else:
                # Contention — delay task until vehicle becomes available
                vehicle_type = VEHICLE_TASK_MAP[task.name]
                m_vehicle_contention.labels(vehicle_type=vehicle_type).inc()
                # Add 5-minute wait for contention (vehicle will be auto-dispatched when available)
                plan.extend_task(task.name, 5)

        elif task.status.value == "completed" and task_key in _state.task_vehicles:
            # Release the vehicle
            vid = _state.task_vehicles.pop(task_key)
            released, return_transit = _state.vehicle_pool.release_vehicle(vid, sim_time)
            if released and not is_bulk:
                v = _state.vehicle_pool.vehicles.get(vid)
                if v:
                    emit_ground_vehicle_returned(
                        vehicle_id=vid,
                        vehicle_type=v.vehicle_type,
                        sim_time=sim_time,
                    )


def _advance_ground_vehicles(sim_time: datetime, is_bulk: bool) -> None:
    """Advance ground vehicle pool — transit arrivals, returns, and pending dispatch."""
    events = _state.vehicle_pool.advance(sim_time)
    if is_bulk:
        return
    for event_type, vehicle in events:
        if event_type == "dispatched":
            emit_ground_vehicle_dispatched(
                vehicle_id=vehicle.id,
                vehicle_type=vehicle.vehicle_type,
                gate_id=vehicle.current_gate or "",
                flight_id=vehicle.flight_id or "",
                task_name=vehicle.task_name or "",
                transit_minutes=0,
                sim_time=sim_time,
            )
        elif event_type == "returned":
            emit_ground_vehicle_returned(
                vehicle_id=vehicle.id,
                vehicle_type=vehicle.vehicle_type,
                sim_time=sim_time,
            )


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
                _state.runway_queue.enqueue_arrival(
                    flight_id, str(estimated),
                    aircraft_type=flight.get("aircraft_type", "A320"),
                )
        except (ValueError, TypeError):
            pass

    # For departures ready to depart, enqueue for runway (only if not already assigned)
    if current_status == "boarding" and direction == "departure" and not flight.get("runway_id"):
        estimated = flight.get("estimated_time", "")
        if boarded_pct >= 0.95:
            _state.runway_queue.enqueue_departure(
                flight_id, str(estimated),
                aircraft_type=flight.get("aircraft_type", "A320"),
            )

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
    # Arrivals can't reach `arrived` until deplaning is done; departures can't
    # (re-)enter `boarding` until the aircraft is cleaned and ready. The pure
    # decision lives in application.decisions; we supply the plan's flags.
    reg = flight.get("aircraft_registration", "")
    if reg and reg in _state.turnaround_plans:
        plan = _state.turnaround_plans[reg]
        if suppress_transition_for_turnaround(
            new_status,
            direction,
            deplaning_done=plan.deplaning_done,
            ready_for_boarding=plan.ready_for_boarding,
        ):
            new_status = None  # wait for turnaround progress

    # ── Noise model draws (Phase 1.2) ──

    is_bulk = _state.current_mode == "BULK"

    # P1-2-5: Diversion — arriving flights in approach may be diverted
    if (current_status == "approach" and direction == "arrival"
            and new_status != "landed"):
        if _draw_diversion(flight_id):
            # Divert the flight — it never arrives at KART. G1: the 'diverted'
            # status write + FlightDiverted + FlightStatusChanged facts commit
            # atomically (durable inbox dedup + staged outbox) instead of a
            # direct update-then-emit. In-memory queue/holding cleanup runs only
            # after commit, and only when newly applied.
            sim_time_iso = sim_time.isoformat()
            event_id = f"div:{flight_id}:{sim_time_iso}"
            reason = ("weather_below_minimums"
                      if _state.runway_queue.weather_category in ("LIFR", "IMC")
                      else "medical_emergency")
            facts: list[dict] = []
            if not is_bulk:
                diverted_id = event_id
                fsc_id = f"fsc:{flight_id}:{current_status}:diverted:{sim_time_iso}"
                facts = [
                    {"id": diverted_id, "document": build_fact(
                        diverted_id, "FlightDiverted", sim_time, {
                            "flight_id": flight_id,
                            "flight_number": flight["flight_number"],
                            "reason": reason,
                        })},
                    {"id": fsc_id, "document": build_fact(
                        fsc_id, "FlightStatusChanged", sim_time, {
                            "flight_id": flight_id,
                            "flight_number": flight["flight_number"],
                            "previous_status": current_status,
                            "new_status": "diverted",
                            "gate_id": flight.get("gate_id"),
                            "runway_id": flight.get("runway_id"),
                            "delay_minutes": flight.get("delay_minutes", 0),
                            "reason": "diverted",
                            "direction": direction,
                            "destination_iata": flight.get("destination_iata"),
                        })},
                ]

            async def _divert(tx, _fid=flight_id):
                await update_flight_status_in_tx(
                    tx, _fid, "diverted", delay_reason="diversion",
                )

            processed = await _commit_flight_writes(
                event_id, sim_time, facts, [_divert],
            )
            if processed:
                _state.runway_queue.remove(flight_id)
                _state.holding_minutes.pop(flight_id, None)
                logger.info("Flight %s DIVERTED", flight["flight_number"])
            return  # skip normal transition

    # P1-2-1: Crew readiness delay — 5% chance at boarding → departed
    if new_status == "departed" and direction == "departure":
        crew_delay = _draw_crew_delay(flight_id)
        if crew_delay > 0:
            # Block the departure and add the delay. G1: the single 'boarding'
            # re-write (with the pushed estimated_time) + FlightStatusChanged
            # fact commit atomically, replacing two update_flight_status calls
            # and a direct emit.
            current_delay = flight.get("delay_minutes", 0) or 0
            new_delay = current_delay + crew_delay
            est = flight.get("estimated_time")
            new_est_str = None
            if est:
                try:
                    new_est_str = (datetime.fromisoformat(str(est))
                                   + timedelta(minutes=crew_delay)).isoformat()
                except (ValueError, TypeError):
                    pass
            sim_time_iso = sim_time.isoformat()
            event_id = f"crew:{flight_id}:{sim_time_iso}"
            facts: list[dict] = []
            if not is_bulk:
                fsc_id = f"fsc:{flight_id}:boarding:boarding:crew:{sim_time_iso}"
                facts = [{"id": fsc_id, "document": build_fact(
                    fsc_id, "FlightStatusChanged", sim_time, {
                        "flight_id": flight_id,
                        "flight_number": flight["flight_number"],
                        "previous_status": "boarding",
                        "new_status": "boarding",
                        "gate_id": flight.get("gate_id"),
                        "runway_id": flight.get("runway_id"),
                        "delay_minutes": new_delay,
                        "reason": "crew_readiness",
                        "direction": direction,
                        "destination_iata": flight.get("destination_iata"),
                    })}]

            async def _crew_delay(tx, _fid=flight_id, _d=new_delay, _est=new_est_str):
                await update_flight_status_in_tx(
                    tx, _fid, "boarding",
                    delay_minutes=_d, delay_reason="crew_readiness",
                    estimated_time=_est,
                )

            await _commit_flight_writes(event_id, sim_time, facts, [_crew_delay])
            new_status = None  # suppress the departed transition this tick

    # P1-2-2: CTOT slot allocation — 10% of departures during peak get a CTOT delay
    if new_status == "departed" and direction == "departure":
        ctot_delay = _draw_ctot(flight_id, sim_time)
        if ctot_delay > 0:
            # G1: the 'boarding' re-write (delay + pushed estimated_time) and
            # the FlightCTOTAssigned fact commit atomically (durable inbox dedup
            # + staged outbox), replacing update-then-emit.
            current_delay = flight.get("delay_minutes", 0) or 0
            new_delay = current_delay + ctot_delay
            est = flight.get("estimated_time")
            new_est_str = None
            if est:
                try:
                    new_est_str = (datetime.fromisoformat(str(est))
                                   + timedelta(minutes=ctot_delay)).isoformat()
                except (ValueError, TypeError):
                    pass
            sim_time_iso = sim_time.isoformat()
            event_id = f"ctot:{flight_id}:{sim_time_iso}"
            facts: list[dict] = []
            if not is_bulk:
                facts = [{"id": event_id, "document": build_fact(
                    event_id, "FlightCTOTAssigned", sim_time, {
                        "flight_id": flight_id,
                        "flight_number": flight["flight_number"],
                        "ctot_delay_minutes": ctot_delay,
                    })}]

            async def _ctot(tx, _fid=flight_id, _d=new_delay, _est=new_est_str):
                await update_flight_status_in_tx(
                    tx, _fid, "boarding",
                    delay_minutes=_d, delay_reason="ctot_slot",
                    estimated_time=_est,
                )

            await _commit_flight_writes(event_id, sim_time, facts, [_ctot])
            new_status = None  # suppress the departed transition this tick

    if new_status is None:
        # Check for delay accumulation on boarding flights past departure time.
        # Use scheduled_time (original schedule) so delay_minutes tracks total
        # delay consistently with noise-model delays (crew/CTOT) that push
        # estimated_time forward.  Previously this used estimated_time, which
        # caused delay_minutes to stall after noise delays and the 90-min
        # force-departure grace to trigger much too late.
        scheduled = flight.get("scheduled_time") or flight.get("estimated_time")
        update = boarding_delay_update(
            current_status,
            direction,
            scheduled,
            sim_time,
            boarded_pct,
            flight.get("delay_minutes", 0) or 0,
            flight.get("delay_reason", ""),
        )
        if update is not None:
            delay, reason = update
            # G1: delay accumulation is a silent domain write (no fact), but it
            # still commits through the atomic boundary so a redelivered tick is
            # deduped on its deterministic id rather than re-adding the delay.
            sim_time_iso = sim_time.isoformat()
            event_id = f"bdelay:{flight_id}:{reason}:{sim_time_iso}"

            async def _accumulate(tx, _fid=flight_id, _d=delay, _r=reason):
                await update_flight_status_in_tx(
                    tx, _fid, "boarding", delay_minutes=_d, delay_reason=_r,
                )

            await _commit_flight_writes(event_id, sim_time, [], [_accumulate])
        return

    # Execute the transition
    await _execute_transition(flight, current_status, new_status, sim_time)


async def _commit_transition(
    flight: dict,
    previous_status: str,
    new_status: str,
    sim_time: datetime,
    update_kwargs: dict,
    delay_minutes: int,
    extra_writes: list | None = None,
    extra_facts: list[dict] | None = None,
) -> bool:
    """Atomically commit a status transition + its FlightStatusChanged fact (G1).

    Within ONE ``session.execute_write`` managed transaction: durable inbox
    dedup, the status domain write, any ``extra_writes`` (async callables taking
    the tx — e.g. a gate release folded in for cancellation/departure), the
    inbox marker, and the staged FlightStatusChanged outbox fact plus any
    ``extra_facts`` (e.g. FlightCancelled) — all commit together or none do. The
    background outbox loop later delivers the facts to ``flights.events`` with
    stable event_ids (at-least-once, stable IDs). Returns True when newly
    applied, False when this exact transition was already committed (replay),
    in which case the caller must not re-run its in-memory side effects.
    """
    flight_id = flight["id"]
    direction = flight.get("direction", "departure")
    sim_time_iso = sim_time.isoformat()
    # Deterministic id: a redelivered tick that recomputes the same transition
    # dedups against the persistent inbox instead of re-applying/re-emitting.
    event_id = f"fsc:{flight_id}:{previous_status}:{new_status}:{sim_time_iso}"
    payload = {
        "flight_id": flight_id,
        "flight_number": flight["flight_number"],
        "previous_status": previous_status,
        "new_status": new_status,
        "gate_id": flight.get("gate_id"),
        "runway_id": flight.get("runway_id"),
        "delay_minutes": delay_minutes,
        "reason": None,
        "direction": direction,
        "destination_iata": flight.get("destination_iata"),
    }
    fact = build_fact(event_id, "FlightStatusChanged", sim_time, payload)
    facts = [{"id": event_id, "document": fact}, *(extra_facts or [])]
    writes = list(extra_writes or [])

    async def apply(tx) -> bool:
        if await outbox_common.inbox_seen(tx, "FlightInbox", event_id):
            return False
        revision = await next_outbox_revision(tx)
        await update_flight_status_in_tx(
            tx, flight_id, new_status,
            delay_minutes=update_kwargs.get("delay_minutes", delay_minutes),
            delay_reason=update_kwargs.get("delay_reason"),
            estimated_time=update_kwargs.get("estimated_time"),
            actual_time=update_kwargs.get("actual_time"),
        )
        for write in writes:
            await write(tx)
        await outbox_common.mark_inbox(tx, "FlightInbox", event_id, sim_time_iso)
        await outbox_common.stage_outbox(tx, "FlightOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def _commit_flight_writes(
    event_id: str,
    sim_time: datetime,
    facts: list[dict],
    writes: list,
) -> bool:
    """Atomically commit arbitrary flight domain writes + staged facts (G1).

    Generalises ``_commit_transition`` for the discrete tick-driven handlers
    (diversion, CTOT, crew-readiness delay, runway assignment) that are not a
    plain status transition: a durable ``FlightInbox`` dedup on ``event_id``,
    the supplied ``writes`` (async callables taking the managed tx), the inbox
    marker, and the staged outbox ``facts`` all commit together or none do.

    ``facts`` may be empty (BULK mode suppresses emission) — the domain write
    and inbox marker still commit so a redelivered tick is deduped. Returns True
    when newly applied, False when ``event_id`` was already committed (replay).
    """
    sim_time_iso = sim_time.isoformat()

    async def apply(tx) -> bool:
        if await outbox_common.inbox_seen(tx, "FlightInbox", event_id):
            return False
        revision = await next_outbox_revision(tx)
        for write in writes:
            await write(tx)
        await outbox_common.mark_inbox(tx, "FlightInbox", event_id, sim_time_iso)
        await outbox_common.stage_outbox(tx, "FlightOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


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
    # G1: writes to fold into the status transaction (e.g. gate release) and
    # extra facts to stage with FlightStatusChanged (e.g. FlightCancelled).
    # In-memory cleanup that must only run once, post-commit, is collected here.
    tx_writes: list = []
    extra_facts: list[dict] = []
    post_commit_actions: list = []

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
            # G1: release the gate inside the status transaction so the
            # ASSIGNED_TO delete commits atomically with the 'departed' write.
            tx_writes.append(lambda tx, _fid=flight_id: release_gate_in_tx(tx, _fid))

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
            # Resolve the delay reason (hold > runway incident > gate incident >
            # existing reason > operational). Pure decision; state lookups here.
            hold = _state.held_flights.get(flight_id)
            update_kwargs["delay_reason"] = resolve_delay_reason(
                flight.get("delay_reason", ""),
                is_held=flight_id in _state.held_flights,
                hold_reason=hold.get("reason") if hold else None,
                runway_incident=flight.get("runway_id") in _state.incident_affected_runways,
                gate_incident=flight.get("gate_id") in _state.incident_affected_gates,
            )

        case "cancelled":
            update_kwargs["delay_reason"] = "delay_exceeded_180min"
            # G1: the gate release and the FlightCancelled fact commit atomically
            # with the 'cancelled' status write + its FlightStatusChanged fact.
            tx_writes.append(lambda tx, _fid=flight_id: release_gate_in_tx(tx, _fid))
            cancelled_id = f"cancel:{flight_id}:{sim_time.isoformat()}"
            extra_facts.append({"id": cancelled_id, "document": build_fact(
                cancelled_id, "FlightCancelled", sim_time, {
                    "flight_id": flight_id,
                    "flight_number": flight_number,
                    "reason": "delay_exceeded_180min",
                })})

            def _cancel_cleanup(_fid=flight_id):
                # In-memory bookkeeping runs once, only after the commit.
                _state.runway_queue.remove(_fid)
                _state.held_flights.pop(_fid, None)

            post_commit_actions.append(_cancel_cleanup)

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
                    plan.gate_id = flight.get("gate_id", "")
                    started_tasks = plan.start(sim_time)
                    _state.turnaround_plans[reg] = plan
                    is_bulk = _state.current_mode == "BULK"
                    # Dispatch vehicles for initially started tasks (Phase 1.3)
                    _handle_task_vehicles(reg, plan, started_tasks, sim_time, is_bulk)
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
            # Arrival fully completed — release gate and clean up turnaround.
            if direction == "arrival":
                # G1: fold the gate release into the status transaction.
                tx_writes.append(lambda tx, _fid=flight_id: release_gate_in_tx(tx, _fid))

                def _cleanup_turnaround(_reg=flight.get("aircraft_registration", "")):
                    if _reg and _reg in _state.turnaround_plans:
                        plan = _state.turnaround_plans[_reg]
                        if plan.is_complete:
                            del _state.turnaround_plans[_reg]

                post_commit_actions.append(_cleanup_turnaround)

    # Atomic domain write + staged FlightStatusChanged fact (G1). The old direct
    # update_flight_status + emit_flight_status_changed pair is replaced by one
    # managed transaction; the outbox loop delivers the fact. A False result
    # means this exact transition was already committed (durable replay dedup) —
    # skip the in-memory/metric side effects so nothing is double-counted.
    processed = await _commit_transition(
        flight, previous_status, new_status, sim_time, update_kwargs, delay_minutes,
        extra_writes=tx_writes, extra_facts=extra_facts,
    )
    if not processed:
        logger.debug(
            "Flight %s transition %s -> %s already committed (inbox dedup)",
            flight_number, previous_status, new_status,
        )
        return

    # Deferred in-memory cleanup (runway queue / holds / turnaround plans): run
    # once, only now that the transaction committed, so a deduped replay never
    # re-applies them.
    for action in post_commit_actions:
        action()

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
        direction=flight.get("direction"),
        destination_iata=flight.get("destination_iata"),
    )


async def _on_weather_changed(payload: dict, sim_time: datetime) -> None:
    """Handle WeatherStateChanged — update runway capacity."""
    _state.sim_time = sim_time

    category = payload.get("new_category", "CAVOK")
    arrival_rate = payload.get("recommended_arrival_rate", _cavok.arrival)
    departure_rate = payload.get("recommended_departure_rate", _cavok.departure)
    runway_impact = payload.get("runway_impact", "none")

    _state.runway_queue.update_capacity(arrival_rate, departure_rate, category)

    # If severe weather, close affected runways
    if runway_impact == "closed":
        _state.weather_affected_runways = {"09L", "27R", "09R", "27L"}
    elif runway_impact == "single_runway":
        # Only ILS runways remain open — close non-ILS
        _state.weather_affected_runways = {"09R", "27L"}
    else:
        # Clear weather-related runway closures
        _state.weather_affected_runways.clear()
    _state.refresh_incident_impacts()

    logger.info(
        "Weather updated: %s (arr=%d/hr, dep=%d/hr, impact=%s)",
        category, arrival_rate, departure_rate, runway_impact,
    )


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentCreated — hold flights on affected runway or gate."""
    location = payload.get("location", "")
    incident_type = payload.get("type", "")
    incident_id = payload.get("incident_id")
    if not incident_id:
        return
    _state.active_incident_locations[incident_id] = location
    _state.refresh_incident_impacts()

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

    if new_status == "resolved":
        _state.active_incident_locations.pop(payload.get("incident_id"), None)
        _state.refresh_incident_impacts()
        logger.info("Incident resolved at %s; remaining restrictions reconciled", location)


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
#
# The domain write + its FlightStatusChanged/FlightGateAssigned fact are made
# atomic through shared ``_apply_*_in_tx`` helpers (G1-b). The REST executors
# below run one ``execute_write`` each; the command path (``_plan_command``)
# reuses the same helpers inside the command transaction so the domain write,
# domain fact, command receipt and receipt fact all commit together.


def _hold_fact(flight: dict, updated: dict, delay: int, reason: str, sim_time: datetime) -> dict:
    fid = flight["id"]
    event_id = f"hold:{fid}:{sim_time.isoformat()}"
    return {"id": event_id, "document": build_fact(
        event_id, "FlightStatusChanged", sim_time, {
            "flight_id": fid,
            "flight_number": updated.get("flight_number", ""),
            "previous_status": flight.get("status", "boarding"),
            "new_status": "delayed",
            "gate_id": flight.get("gate_id"),
            "runway_id": flight.get("runway_id"),
            "delay_minutes": delay,
            "reason": reason,
            "direction": flight.get("direction"),
            "destination_iata": flight.get("destination_iata"),
        })}


async def _apply_hold_in_tx(
    tx, flight: dict, reason: str, duration_min: int, sim_time: datetime,
) -> tuple[dict | None, list[dict]]:
    """Manual-hold domain write on ``tx``; returns (updated_flight, facts)."""
    est = flight.get("estimated_time") or flight.get("scheduled_time")
    try:
        current_estimate = datetime.fromisoformat(str(est)) if est else sim_time
    except (ValueError, TypeError):
        return None, []
    estimated = (current_estimate + timedelta(minutes=duration_min)).isoformat()
    delay = int(flight.get("delay_minutes") or 0) + duration_min
    updated = await set_manual_hold_in_tx(
        tx, flight["id"], reason, duration_min, estimated, delay, sim_time)
    if updated is None:
        return None, []
    return updated, [_hold_fact(flight, updated, delay, reason, sim_time)]


def _hold_post_commit(flight: dict, reason: str, duration_min: int, updated: dict, sim_time: datetime) -> None:
    """In-memory hold bookkeeping + WS broadcast — runs only after commit."""
    fid = flight["id"]
    _state.held_flights[fid] = {
        "reason": reason, "expected_duration_minutes": duration_min,
        "held_at": sim_time.isoformat(),
    }
    if _state.ws_broadcast:
        try:
            asyncio.create_task(_state.ws_broadcast({
                "type": "FlightStatusChanged",
                "flight_id": fid,
                "flight_number": updated.get("flight_number", ""),
                "previous_status": "boarding",
                "new_status": "delayed",
                "sim_time": sim_time.isoformat(),
            }))
        except Exception:
            pass


async def hold_flight(flight_id: str, reason: str, duration_min: int, sim_time: datetime) -> dict | None:
    """Place a manual hold on a flight (REST path) — atomic write + staged fact."""
    flight = await get_flight_by_id(flight_id)
    if flight is None:
        return None

    async def apply(tx):
        updated, facts = await _apply_hold_in_tx(tx, flight, reason, duration_min, sim_time)
        if updated is None:
            return None
        revision = await next_outbox_revision(tx)
        await outbox_common.stage_outbox(tx, "FlightOutbox", facts, revision)
        return updated

    async with get_driver().session() as session:
        updated = await session.execute_write(apply)
    if updated:
        _hold_post_commit(flight, reason, duration_min, updated, sim_time)
    return updated


async def release_flight(flight_id: str, sim_time: datetime) -> dict | None:
    """Release a manual hold on a flight (REST path) — atomic write + staged fact."""
    flight = await get_flight_by_id(flight_id)
    if not flight:
        return None

    direction = flight.get("direction", "departure")
    new_status = "boarding" if direction == "departure" else "approach"
    event_id = f"release:{flight_id}:{sim_time.isoformat()}"
    fact = {"id": event_id, "document": build_fact(
        event_id, "FlightStatusChanged", sim_time, {
            "flight_id": flight_id,
            "flight_number": flight.get("flight_number", ""),
            "previous_status": "delayed",
            "new_status": new_status,
            "gate_id": flight.get("gate_id"),
            "runway_id": flight.get("runway_id"),
            "delay_minutes": flight.get("delay_minutes", 0),
            "reason": None,
            "direction": direction,
            "destination_iata": flight.get("destination_iata"),
        })}

    async def apply(tx):
        updated = await update_flight_status_in_tx(tx, flight_id, new_status)
        if updated is None:
            return None
        revision = await next_outbox_revision(tx)
        await outbox_common.stage_outbox(tx, "FlightOutbox", [fact], revision)
        return updated

    async with get_driver().session() as session:
        updated = await session.execute_write(apply)
    if updated:
        _state.held_flights.pop(flight_id, None)
    return updated


def _reassign_fact(flight_id: str, flight_number: str, gate_id: str, sim_time: datetime) -> tuple[str, dict]:
    event_id = f"fga:{flight_id}:{gate_id}:{sim_time.isoformat()}:reassignment"
    fact = {"id": event_id, "document": build_fact(event_id, "FlightGateAssigned", sim_time, {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "gate_id": gate_id,
        "reason": "reassignment",
    })}
    return event_id, fact


async def _apply_reassign_in_tx(
    tx, flight_id: str, gate_id: str, sim_time: datetime, flight_number: str,
) -> tuple[bool, list[dict]]:
    """Gate-reassignment domain write on ``tx``; returns (ok, facts).

    ``ok`` is False when the gate was taken concurrently (the in-tx
    ``assign_flight_to_gate_in_tx`` authority), in which case nothing is staged.
    """
    if not await assign_flight_to_gate_in_tx(tx, flight_id, gate_id, sim_time):
        return False, []
    _, fact = _reassign_fact(flight_id, flight_number, gate_id, sim_time)
    return True, [fact]


def _reassign_post_commit(flight_id: str, flight_number: str, gate_id: str, sim_time: datetime) -> None:
    if _state.ws_broadcast:
        try:
            asyncio.create_task(_state.ws_broadcast({
                "type": "FlightGateAssigned",
                "flight_id": flight_id,
                "flight_number": flight_number,
                "gate_id": gate_id,
                "sim_time": sim_time.isoformat(),
            }))
        except Exception:
            pass


async def reassign_gate(flight_id: str, gate_id: str, sim_time: datetime) -> dict | None:
    """Reassign a flight to a specific gate (REST path).

    Re-links the ``ASSIGNED_TO`` relationship and stages the
    ``FlightGateAssigned`` fact atomically (inbox dedup + outbox). Returns the
    flight dict on success, or ``None`` if the flight doesn't exist or the
    target gate is occupied by another flight.
    """
    flight = await get_flight_by_id(flight_id)
    if not flight:
        return None

    # Don't double-book: reject if the gate is held by a *different* flight.
    if await is_gate_occupied(gate_id, exclude_flight_id=flight_id):
        logger.warning("ReassignGate: gate %s occupied — refusing to reassign %s", gate_id, flight_id)
        return None

    flight_number = flight.get("flight_number", "")
    sim_time_iso = sim_time.isoformat()
    event_id, _ = _reassign_fact(flight_id, flight_number, gate_id, sim_time)

    async def apply(tx) -> str | None:
        if await outbox_common.inbox_seen(tx, "FlightInbox", event_id):
            return "duplicate"
        ok, facts = await _apply_reassign_in_tx(tx, flight_id, gate_id, sim_time, flight_number)
        if not ok:
            return None  # gate taken concurrently — nothing staged
        revision = await next_outbox_revision(tx)
        await outbox_common.mark_inbox(tx, "FlightInbox", event_id, sim_time_iso)
        await outbox_common.stage_outbox(tx, "FlightOutbox", facts, revision)
        return "ok"

    async with get_driver().session() as session:
        outcome = await session.execute_write(apply)

    if outcome is None:
        return None

    # Broadcast to WebSocket only for a freshly applied reassignment.
    if outcome == "ok":
        _reassign_post_commit(flight_id, flight_number, gate_id, sim_time)

    flight["gate_id"] = gate_id
    return flight
