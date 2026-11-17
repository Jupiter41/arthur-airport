"""Kafka consumer for passenger-service.

Consumes: SimClockTick, FlightStatusChanged, FlightGateAssigned,
          FlightCancelled, IncidentCreated, BaggageStatusChanged (collected).
On each tick: advance departure FSM, drain security queues, check congestion,
              update ML pipeline, evaluate connections.
"""

import asyncio
from _common._profiler import phase_timer
from _common.transaction_scope import catch_up_times, current as current_tick, run_tick
from _common.checkpoint import SnapshotCodec
from services.security import SecurityCheckpoint
from _common import kafka_runtime
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from _common.idempotency import IdempotencyTracker
from _common.consumer_health import ConsumerHealthTracker
from _common.data_sources import DataSourceRegistry, SimulatedSourceAdapter

from confluent_kafka import Consumer

from db.neo4j import (
    get_passengers_by_status,
    get_security_queue_members,
    get_passengers_by_flight,
    get_connecting_passengers,
    get_departure_flights_in_window,
    get_status_counts,
    apply_status_change_atomic,
    apply_changes_atomic,
    apply_tick_atomic,
    read_tick_checkpoint,
    rebook_passengers_atomic,
)
from kafka.producer import (
    emit_passenger_status_changed,  # noqa: F401 — kept as a patchable seam for canonical-path tests
    build_passenger_status_changed_fact,
    build_passenger_alert_fact,
    emit_passenger_alert,
    emit_congestion_detected,
    emit_security_queue_updated,
    emit_bulk_state_snapshot,
    emit_boarding_progress,
    set_bulk_mode,
)
from ml.congestion import check_congestion
from ml.features import build_features
from ml.inference import load_models, predict
from ml.training import add_training_row, maybe_flush, maybe_retrain
from services.connections import evaluate_connecting_passengers
from services.security import SecuritySystem
from services.reconciliation import (
    PHYSICAL_STATUSES, MISSED_FLIGHT_STATUSES,
    PRE_DEPARTURE_FLIGHT_STATUSES, reconciliation_transition,
)
from _common.show_up import (
    SHOW_UP_WINDOW_START_MIN, is_no_show, security_due, show_up_time,
)
from services.spatial import walking_time_to_gate
from services import wheelchair
from services.state_machine import (
    get_terminal_for_flight,
    sample_dwell_minutes,
    should_move_to_at_gate,
    should_start_boarding,
    should_move_to_baggage_claim,
    should_clear_customs,
    should_depart_airport,
    is_international_flight,
    zone_for_status,
    BAGGAGE_CLAIM_TIMEOUT_MINUTES,
    BOARDING_RATE_PAX_PER_MIN,
    CUSTOMS_DELAY_MINUTES,
    DEPLANING_DELAY_MINUTES,
    GATE_OPEN_MINUTES,
)
from services.zones import move_passenger, remove_passenger
from metrics import (
    passengers_in_airport as m_pax_in_airport,
    security_queue_depth as m_sec_queue_depth,
    security_wait_minutes as m_sec_wait,
    security_lanes_open as m_sec_lanes,
    connections_at_risk as m_connections_at_risk,
    connections_missed_total as m_connections_missed,
    passengers_missed_flight_total as m_missed_flight,
    passenger_alerts_total as m_passenger_alerts,
    envelope_invalid_total as m_envelope_invalid,
    pax_commands_total as m_commands,
)
from application.commands import parse_command, OpenSecurityLane, RebookPassengers

logger = logging.getLogger(__name__)


# ── Lightweight adapter wrappers for the data source registry ──


class _BTSHistoricalAdapter:
    """Adapter wrapper for BTSPassengerSource."""

    source_id = "bts_historical"
    label = "BTS T-100 Historical"

    @property
    def is_loaded(self) -> bool:
        return _state is not None and _state._bts_adapter is not None

    def load(self) -> int:
        return 0  # loading is managed by switch_passenger_source()


# ── Class-based state holder ────────────────────────────────


class PassengerConsumerState:
    """Holds all mutable runtime state for the passenger consumer."""

    MAX_PROCESSED = 20000
    MAX_ALERTS = 200

    def __init__(self) -> None:
        self.sim_time: datetime | None = None
        self.last_tick_sim_time: datetime | None = None
        self.tick_counter = 0
        self.sim_day: int = 0
        self.security = SecuritySystem()
        self.weather_category: str = "CAVOK"
        self.active_incidents: dict[str, bool] = {"A": False, "B": False, "C": False}
        self.security_breaches: dict[str, str] = {}
        self.load_factor_sum: float = 0.0
        self.load_factor_count: int = 0
        self.cached_flights_next_90: dict[str, int] = {"A": 0, "B": 0, "C": 0}
        self.cached_pax_next_90: dict[str, float] = {"A": 0.0, "B": 0.0, "C": 0.0}
        self.alerts: list[dict] = []
        self.at_risk_connections: list[dict] = []
        self._idempotency = IdempotencyTracker(max_size=20_000)
        self.security_enqueued: set[str] = set()
        self.airside_transitioned: set[str] = set()
        self.baggage_collected: set[str] = set()
        self.passengers_at_carousel: set[str] = set()
        self.flight_carousel_zone: dict[str, str] = {}  # flight_id → carousel zone
        self.ws_broadcast: Callable[[dict], Awaitable[None]] | None = None
        # Spatial data for walking time computation
        self.gate_positions: dict[str, dict] = {}
        self.walking_zones: dict[str, dict] = {}
        # Speed mode tracking (REALTIME / FAST / BULK)
        self.current_mode: str = "REALTIME"
        self.last_mode: str = "REALTIME"
        self.last_sync_sim_time: datetime | None = None
        # No-show tracking (Phase 1.2)
        self.noshow_rate: float = 0.03  # 2-4% no-show rate (default 3%)
        # Passengers placed by this tick's warm start (per tick, not checkpointed).
        self.warm_started_ids: set[str] = set()
        # BTS source management
        self.passenger_source: str = os.getenv("PASSENGER_SOURCE", "simulation").lower()
        self._bts_adapter = None

        # Data source registry for unified listing and metadata
        self.source_registry = DataSourceRegistry(
            "passengers", env_var="PASSENGER_SOURCE", default="simulation",
        )
        self.source_registry.register(SimulatedSourceAdapter())
        self.source_registry.register(_BTSHistoricalAdapter())

    def check_idempotency(self, event_id: str) -> bool:
        return self._idempotency.is_duplicate(event_id)

    def add_alert(self, alert: dict) -> None:
        self.alerts.append(alert)
        if len(self.alerts) > self.MAX_ALERTS:
            self.alerts = self.alerts[-self.MAX_ALERTS:]


# Module-level singleton
_state = PassengerConsumerState()
_consumer: Consumer | None = None
_consumer_running = False
_consumer_health = ConsumerHealthTracker()


def _ensure_bts_adapter():
    """Lazily initialise the BTS adapter if needed."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    if _state._bts_adapter is not None:
        return _state._bts_adapter
    from services.bts_adapter import BTSPassengerSource
    csv_path = os.getenv("PASSENGER_BTS_FILE", "/app/data/bts/T100_reference.csv")
    adapter = BTSPassengerSource(csv_path)
    count = adapter.load()
    if count == 0:
        logger.warning("BTS adapter loaded 0 routes")
    _state._bts_adapter = adapter
    return adapter


def get_passenger_source_info() -> dict:
    """Return current source status and available options."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    # RC10: freshness is the owner's last committed tick (sim clock).
    from _common.data_sources import SourceHealth
    health = SourceHealth(enabled=True)
    if _state.last_tick_sim_time is not None:
        health.last_observation_at = _state.last_tick_sim_time.replace(tzinfo=None).isoformat()
    info = {
        "source": _state.passenger_source,
        "available": ["simulation", "bts_historical"],
        "registry": _state.source_registry.info(),
        "health": health.as_dict(),
    }
    if _state.passenger_source == "bts_historical" and _state._bts_adapter:
        info["bts_summary"] = _state._bts_adapter.get_summary()
    return info


def switch_passenger_source(new_source: str, csv_path: str | None = None) -> dict:
    """Switch the active passenger data source at runtime."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    valid_sources = ("simulation", "bts_historical")
    if new_source not in valid_sources:
        raise ValueError(f"Invalid passenger source '{new_source}'. Must be one of {valid_sources}")
    valid_sources = ("simulation", "bts_historical")
    if new_source not in valid_sources:
        raise ValueError(f"Invalid passenger source '{new_source}'. Must be one of {valid_sources}")
    old_source = _state.passenger_source
    _state.passenger_source = new_source
    _state.source_registry._active = new_source

    if new_source == "bts_historical":
        from services.bts_adapter import BTSPassengerSource
        path = csv_path or os.getenv("PASSENGER_BTS_FILE", "/app/data/bts/T100_reference.csv")
        adapter = BTSPassengerSource(path)
        count = adapter.load()
        _state._bts_adapter = adapter
        logger.info("Switched to BTS historical source: %d routes loaded", count)
        return {
            "source": new_source,
            "previous": old_source,
            "routes_loaded": count,
            "bts_summary": adapter.get_summary(),
        }

    # Switching to simulation
    logger.info("Switched passenger source to simulation")
    return {"source": new_source, "previous": old_source}


def get_bts_flow() -> dict | None:
    """Get BTS flow data for the current sim time."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    if _state.passenger_source != "bts_historical":
        return None
    adapter = _ensure_bts_adapter()
    sim_time = _state.sim_time
    if sim_time is None:
        return None
    flow = adapter.get_flow_at(sim_time)
    return {
        "sim_time": sim_time.isoformat(),
        "source": "bts_historical",
        "total_passengers": flow.total_passengers,
        "departing_passengers": flow.departing_passengers,
        "arriving_passengers": flow.arriving_passengers,
        "avg_load_factor": flow.avg_load_factor,
        "zone_counts": flow.zone_counts,
        "route_breakdown": flow.route_breakdown,
    }


def get_bts_summary() -> dict | None:
    """Get BTS adapter summary."""
    adapter = _ensure_bts_adapter()
    return adapter.get_summary()


async def rebuild_security_from_neo4j() -> None:
    """Rebuild in-memory security queues from Neo4j on startup.

    Loads all passengers currently in security_queue status and enqueues
    them into the in-memory SecuritySystem so queue_depth and wait_minutes
    are accurate immediately after a restart.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    from db.neo4j import get_driver
    from _common.transaction_scope import restore_owner_checkpoint
    await restore_owner_checkpoint("PassengerRuntime", _state, _TICK_CODEC, get_driver)
    await _sync_security_from_db()
    try:
        pax_list = await get_passengers_by_status("security_queue")
    except Exception as e:
        logger.error("Failed to rebuild security queues: %s", e)
        return

    count = 0
    for pax in pax_list:
        pid = pax["id"]
        zone = pax.get("location_zone") or ""
        # Extract terminal from zone like "security-A"
        terminal = zone.split("-")[-1] if "-" in zone else None
        if terminal not in ("A", "B", "C"):
            # Fallback: derive from flight
            terminal = get_terminal_for_flight(
                pax.get("gate_id"), pax.get("terminal_id"), pax.get("flight_id") or ""
            )
        is_sa = bool(pax.get("special_assistance"))
        _state.security.enqueue(terminal, pid, is_sa)
        _state.security_enqueued.add(pid)
        count += 1

    logger.info("Rebuilt security queues from Neo4j: %d passengers loaded", count)


    from db.neo4j import load_security_lanes, load_security_breaches
    for terminal, lanes in (await load_security_lanes()).items():
        checkpoint = _state.security.checkpoints.get(terminal)
        if checkpoint is not None:
            checkpoint.lanes_open = lanes
    _state.security_breaches = {
        key: terminal for key, location in (await load_security_breaches()).items()
        if (terminal := _extract_terminal_from_location(location)) is not None
    }
    for terminal, checkpoint in _state.security.checkpoints.items():
        _state.active_incidents[terminal] = terminal in _state.security_breaches.values()
        if _state.active_incidents[terminal]:
            checkpoint.freeze()
        else:
            checkpoint.unfreeze()


async def load_spatial_positions() -> None:
    """Load gate positions and walking zones from Neo4j for walking time computation."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    from db.neo4j import get_driver
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (g:Gate) WHERE g.position_x IS NOT NULL "
                "RETURN g.id AS id, g.position_x AS x, g.position_y AS y"
            )
            async for record in result:
                _state.gate_positions[record["id"]] = {
                    "position_x": record["x"],
                    "position_y": record["y"],
                }

        # Load walking zones from layout fixture if available on Terminal nodes
        # Fallback: use hardcoded zones matching layout.json
        _state.walking_zones = {
            "A": {"checkin": {"x": 500, "y": 50}, "security": {"x": 500, "y": 100}, "airside": {"x": 500, "y": 130}},
            "B": {"checkin": {"x": 500, "y": 300}, "security": {"x": 500, "y": 350}, "airside": {"x": 500, "y": 380}},
            "C": {"checkin": {"x": 500, "y": 550}, "security": {"x": 500, "y": 600}, "airside": {"x": 500, "y": 630}},
        }
        logger.info(
            "Loaded spatial positions: %d gates, %d walking zones",
            len(_state.gate_positions),
            len(_state.walking_zones),
        )
    except Exception as e:
        logger.warning("Failed to load spatial positions (walking times will use defaults): %s", e)


def set_ws_broadcast(fn):
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    _state.ws_broadcast = fn


def get_sim_time() -> datetime | None:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return _state.sim_time


def get_security() -> SecuritySystem:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return _state.security


def get_alerts() -> list[dict]:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return _state.alerts


def get_at_risk_connections() -> list[dict]:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return _state.at_risk_connections


def is_consumer_running() -> bool:
    return _consumer_running


def get_consumer_health() -> dict:
    """Return consumer health metrics for /health endpoint."""
    return _consumer_health.status()


def stop_consumer() -> None:
    global _consumer_running
    _consumer_running = False


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "pax-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": False,
        "session.timeout.ms": 10000,
    })


def _make_command_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "pax-commands-svc",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "session.timeout.ms": 10000,
    })


async def _run_command_consumer() -> None:
    """Keep commands responsive while the fact consumer awaits expensive ticks."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    global _consumer_running
    consumer = _make_command_consumer()
    consumer.subscribe(["passengers.commands"])
    loop = asyncio.get_running_loop()
    try:
        while _consumer_running:
            message = await loop.run_in_executor(None, consumer.poll, 0.1)
            if message is None or message.error():
                continue
            try:
                envelope = json.loads(message.value().decode("utf-8"))
                if (not isinstance(envelope, dict)
                        or not isinstance(envelope.get("command_id"), str)
                        or not envelope["command_id"]):
                    raise ValueError("command_id is required")
            except (ValueError, UnicodeError):
                logger.warning("Invalid command envelope", exc_info=True)
            else:
                while _consumer_running:
                    if _state.sim_time is None:
                        await asyncio.sleep(0.1)
                        continue
                    try:
                        await _handle_command(envelope)
                    except Exception:
                        logger.exception("Command handling failed; retrying %s", envelope["command_id"])
                        await asyncio.sleep(0.1)
                        continue
                    break
                if not _consumer_running:
                    break  # Never acknowledge an unfinished command on shutdown.
            await loop.run_in_executor(
                None, lambda: consumer.commit(message=message, asynchronous=False),
            )
    finally:
        _consumer_running = False
        consumer.close()


def _bootstrap_clock(envelope: dict) -> None:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    if _state.sim_time is not None:
        return
    validated = _validate_envelope(envelope)
    if validated is not None and validated[0] == "SimClockTick":
        _state.sim_time = validated[1]


async def run_consumer() -> None:
    """Main consumer loop — runs as background asyncio task."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    global _consumer, _consumer_running

    _consumer = _make_consumer()
    _consumer.subscribe([
        "sim.clock",
        "flights.events",
        "incidents.events",
        "baggage.events",
        "weather.events",
    ])
    _consumer_running = True

    logger.info(
        "Kafka consumer started (topics: sim.clock, flights.events, incidents.events, "
        "baggage.events, weather.events); dedicated passenger command consumer started"
    )

    command_task = asyncio.create_task(_run_command_consumer())
    try:
        await kafka_runtime.run_consumer_loop(
            _consumer, _dispatch, lambda: _consumer_running, _consumer_health,
            batch_size=5000, timeout=0.1, manual_commit=True,
            bootstrap_tick=_bootstrap_clock,
            commands_ready=lambda: _state.sim_time is not None,
        )
    finally:
        _consumer_running = False
        await command_task
        logger.info("Kafka consumer stopped")


def _validate_envelope(envelope: dict) -> tuple[str, datetime, dict] | None:
    """Validate Kafka envelope structure. Returns (event_type, sim_time, payload) or None."""
    event_type = envelope.get("event_type")
    if not isinstance(event_type, str):
        m_envelope_invalid.labels(reason="missing_event_type").inc()
        logger.warning("Invalid envelope: missing/non-string event_type")
        return None

    sim_time_str = envelope.get("sim_time")
    if not sim_time_str:
        m_envelope_invalid.labels(reason="missing_sim_time").inc()
        logger.warning("Invalid envelope: missing sim_time for %s", event_type)
        return None
    try:
        sim_time = datetime.fromisoformat(str(sim_time_str)).replace(tzinfo=None)
    except (ValueError, TypeError):
        m_envelope_invalid.labels(reason="unparseable_sim_time").inc()
        logger.warning("Invalid envelope: unparseable sim_time '%s'", sim_time_str)
        return None

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        m_envelope_invalid.labels(reason="missing_payload").inc()
        logger.warning("Invalid envelope: missing/non-dict payload for %s", event_type)
        return None

    return event_type, sim_time, payload


async def _dispatch(envelope: dict) -> None:
    """Route events to handlers based on event_type.

    Command envelopes (keyed on ``command_type``, from ``passengers.commands``)
    are imperatives, not facts — they take a separate path.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    # Commands are keyed on command_type (no event_type / sim_time).
    if envelope.get("command_type") is not None:
        await _handle_command(envelope)
        return

    validated = _validate_envelope(envelope)
    if validated is None:
        return
    event_type, sim_time, payload = validated

    # Idempotency check (skip for clock ticks)
    if event_type != "SimClockTick":
        event_id = envelope.get("event_id", "")
        if event_id and event_id in _state._idempotency:
            return

    if event_type != "SimClockTick":
        with phase_timer(f"event:{event_type}" if event_type in _TIMED_EVENTS else "event:other"):
            await _dispatch_fact(event_type, payload, sim_time, envelope)
    else:
        await _on_clock_tick(payload, sim_time)

    _state.check_idempotency(envelope.get("event_id", ""))


_TIMED_EVENTS = frozenset({
    "FlightStatusChanged", "FlightGateAssigned", "FlightCancelled", "IncidentCreated",
    "IncidentStatusChanged", "WeatherStateChanged", "BaggageStatusChanged",
})


async def _dispatch_fact(event_type: str, payload: dict, sim_time: datetime, envelope: dict) -> None:
    # RC4: advance the event-fed FlightView before any handler reads it, so
    # decisions see flights exactly as of the events consumed so far.
    from _common.flight_view import VIEW
    VIEW.apply(event_type, payload, sim_time)
    match event_type:
        case "FlightStatusChanged":
            await _on_flight_status_changed(payload, sim_time, envelope.get("event_id", ""))
        case "FlightGateAssigned":
            await _on_flight_gate_assigned(payload, sim_time)
        case "FlightCancelled":
            await _on_flight_cancelled(payload, sim_time, envelope.get("event_id", ""))
        case "IncidentCreated":
            await _on_incident_created(payload, sim_time)
        case "IncidentStatusChanged":
            await _on_incident_status_changed(payload, sim_time)
        case "WeatherStateChanged":
            await _on_weather_changed(payload, sim_time)
        case "BaggageStatusChanged":
            await _on_baggage_status_changed(payload, sim_time, envelope.get("event_id", ""))
        case _:
            pass





async def _handle_command(envelope: dict) -> None:
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    if envelope.get("command_type") == "RebookPassengers":
        await _handle_rebook_command(envelope)
        return
    from db.neo4j import security_lane_command_atomic
    command_id = envelope.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        raise ValueError("command_id is required")
    if _state.sim_time is None:
        raise RuntimeError("Simulation clock not available")
    command_type = envelope.get("command_type")
    cmd, error = parse_command(command_type, envelope.get("payload"))
    terminal = cmd.terminal if isinstance(cmd, OpenSecurityLane) else None
    lanes = cmd.lanes_open if isinstance(cmd, OpenSecurityLane) else None
    if error is None and terminal not in _state.security.checkpoints:
        error = "Unknown terminal"
    kind, payload, applied = await security_lane_command_atomic(
        command_id, command_type, terminal, lanes, _state.sim_time, error,
    )
    if applied:
        m_commands.labels(command_type=str(command_type), outcome=(
            "accepted" if kind == "CommandExecuted" else "rejected"
        )).inc()
        if kind == "CommandExecuted":
            _state.security.checkpoints[terminal].lanes_open = lanes
            m_sec_lanes.labels(terminal=terminal).set(lanes)


async def _handle_rebook_command(envelope: dict) -> None:
    """Atomic RebookPassengers execution + owner receipt (G1-b).

    Validates the envelope, then delegates the mutation + receipt + facts to
    ``rebook_passengers_atomic`` (one ``execute_write``). A parse rejection has no
    domain write, so it is reported directly. The domain and receipt facts are
    delivered by the PassengerOutbox loop; redelivery re-emits the stored receipt
    without re-mutating any passenger.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    command_id = envelope.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        raise ValueError("command_id is required")
    if _state.sim_time is None:
        raise RuntimeError("Simulation clock not available")

    command_type = envelope.get("command_type")
    cmd, error = parse_command(command_type, envelope.get("payload"))
    if error is not None:
        from db.neo4j import security_lane_command_atomic
        await security_lane_command_atomic(
            command_id, str(command_type), None, None, _state.sim_time, error,
        )
        m_commands.labels(command_type=str(command_type), outcome="rejected").inc()
        return

    assert isinstance(cmd, RebookPassengers)
    event_type, _payload, mutated = await rebook_passengers_atomic(
        command_id, command_type, cmd.passenger_ids, _state.sim_time,
    )
    if mutated:
        outcome = "accepted" if event_type == "CommandExecuted" else "rejected"
        m_commands.labels(command_type=command_type, outcome=outcome).inc()
        logger.info(
            "RebookPassengers %s (command_id=%s, inbound=%s)",
            outcome, command_id, cmd.inbound_flight,
        )


@dataclass
class TickContribution:
    """Intended per-tick domain changes produced by an FSM handler (G1-a).

    Each FSM handler reads Neo4j and computes the transitions it wants, returning
    them as data instead of writing directly. ``_on_clock_tick`` merges all
    contributions and commits them in ONE ``apply_tick_atomic`` transaction.
    In-memory zone/queue bookkeeping (derived, rebuildable) is still applied
    inline by the handlers — safe because a replayed tick is skipped wholesale by
    the durable ``PassengerRuntime`` checkpoint before any handler runs.
    """

    groups: list[dict] = field(default_factory=list)          # {ids,status,zone}
    dwell_items: list[tuple] = field(default_factory=list)    # (pid, dwell)
    location_updates: list[dict] = field(default_factory=list)  # {id,zone}
    facts: list[dict] = field(default_factory=list)           # {id,document}

    def merge(self, other: "TickContribution") -> None:
        self.groups.extend(other.groups)
        self.dwell_items.extend(other.dwell_items)
        self.location_updates.extend(other.location_updates)
        self.facts.extend(other.facts)


# The warm start must see the day's schedule. On a fresh stack the clock can
# start before this consumer has received FlightsScheduled, so the first tick
# found an empty FlightView, placed nobody, and the normal check-in rule then
# released every overdue passenger at once (the RC5 cold-start flood). It now
# runs on the first early tick at which the FlightView knows any departure.
WARM_START_WINDOW_TICKS = int(os.getenv("WARM_START_WINDOW_TICKS", "60"))
_warm_start_state: dict = {"done": False}


def _warm_start_due(tick_counter: int) -> bool:
    from _common.flight_view import VIEW
    if _warm_start_state["done"] or tick_counter > WARM_START_WINDOW_TICKS:
        return False
    return any(f.get("direction") == "departure" for f in VIEW.flights.values())


def _mark_warm_start_done() -> None:
    _warm_start_state["done"] = True


async def _warm_start_departures(sim_time: datetime) -> "TickContribution":
    """Place every already-due departure passenger on their own timeline (RC5).

    On a fresh simulation every passenger whose ``show_up_at`` is past is still
    ``booked``; releasing them all on the first tick flooded security for about
    three sim-hours. Each is placed where their free-flow timeline puts them
    now (``services.warm_start``), as part of the first tick's atomic commit;
    in-memory queue/zone bookkeeping follows the same rules as the FSM steps.
    See passenger SPEC "Warm start on a fresh simulation".
    """
    from services.warm_start import place_departures
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    plan = TickContribution()
    cutoff = (sim_time + timedelta(minutes=SHOW_UP_WINDOW_START_MIN)).isoformat()
    try:
        pax_list = await get_passengers_by_status(
            "booked", scheduled_before=cutoff,
            flight_statuses=list(PRE_DEPARTURE_FLIGHT_STATUSES),
            due_field="show_up_at", due_at=sim_time.isoformat(), include_missing_due=True,
        )
    except Exception as e:
        if current_tick.get() is not None:
            raise
        logger.error("Warm-start query failed: %s", e)
        return plan

    rows = {p["id"]: p for p in pax_list if p.get("direction", "departure") == "departure"}
    placements = place_departures(
        rows.values(), sim_time, _state.noshow_rate, lambda _pid: sample_dwell_minutes(),
    )
    groups: dict[tuple[str, str], list[str]] = {}
    for placed in placements:
        pax = rows[placed.passenger_id]
        gate_id = pax.get("gate_id")
        terminal = get_terminal_for_flight(gate_id, pax.get("terminal_id"), pax.get("flight_id") or "")
        status = placed.status
        if status == "departed_airport":
            zone = "no-show"
        elif status in ("checked_in", "security_queue", "airside"):
            zone = {"checked_in": "check-in", "security_queue": "security",
                    "airside": "airside"}[status] + f"-{terminal}"
        else:
            zone = zone_for_status(status, terminal, gate_id)
        groups.setdefault((status, zone), []).append(placed.passenger_id)
        if status == "security_queue":
            _state.security_enqueued.add(placed.passenger_id)
            _state.security.enqueue(terminal, placed.passenger_id, bool(pax.get("special_assistance")))
        if status == "airside":
            plan.dwell_items.append((placed.passenger_id, placed.dwell_remaining))
        if status in ("checked_in", "security_queue", "airside", "at_gate"):
            move_passenger(None, zone)
    for (status, zone), ids in groups.items():
        plan.groups.append({"ids": ids, "status": status, "zone": zone})
    _state.warm_started_ids = {p.passenger_id for p in placements}
    logger.info(
        "Warm start: placed %d due departure passengers by their own show-up time (%s)",
        len(placements), {status: len(ids) for (status, _), ids in groups.items()},
    )
    return plan



CATCH_UP_MAX_STEP_MIN = int(os.getenv("CATCH_UP_MAX_STEP_MIN", "5"))


_TICK_CODEC = SnapshotCodec(
    [SecuritySystem, SecurityCheckpoint],
    (
        "last_tick_sim_time", "sim_day", "security", "security_enqueued",
        "airside_transitioned", "baggage_collected", "passengers_at_carousel",
        "flight_carousel_zone", "current_mode", "last_mode", "last_sync_sim_time",
        "tick_counter",
    ),
    publish_fields=(
        "alerts", "at_risk_connections", "cached_flights_next_90", "cached_pax_next_90",
    ),
    # RC5: the no-show draw is a deterministic per-passenger hash, so the
    # ever-growing per-flight "drawn" set is no longer checkpointed.
    retired_fields=("noshow_drawn_flights",),
)


async def _prepare_tick(candidate: PassengerConsumerState) -> None:
    from db.neo4j import load_security_lanes
    from _common._profiler import phase_timer
    with phase_timer("prepare"):
        lanes = await load_security_lanes()
        await _sync_security_from_db()
    for terminal, cp in candidate.security.checkpoints.items():
        cp.lanes_open = lanes.get(terminal, cp.lanes_open)
        cp.frozen = _state.security.checkpoints[terminal].frozen


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    from db.neo4j import get_driver
    # Replay a coalesced backlog as bounded steps (see catch_up_times).
    from _common._profiler import tick_timer, update_speed
    update_speed(payload.get("speed_multiplier") or 60)
    for step_time in catch_up_times(_state.last_tick_sim_time, sim_time, CATCH_UP_MAX_STEP_MIN):
        with tick_timer():
            await run_tick("PassengerRuntime", "PassengerOutbox", _state,
                           _TICK_CODEC, get_driver, _advance_tick, payload, step_time, _prepare_tick)
        from kafka.producer import emit_tick_processed
        emit_tick_processed(step_time)


async def _advance_tick(payload: dict, sim_time: datetime) -> None:
    """Main tick handler — advance all passenger state machines."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]

    # G1-a: durable replay / crash-resume guard. A re-delivered or already-applied
    # tick (sim_time <= the durable PassengerRuntime checkpoint) does NOTHING —
    # checked before any state mutation or in-memory bookkeeping. The authoritative
    # guard is the locked re-check inside apply_tick_atomic; this cheap pre-read
    # avoids wasted compute on replay. In-memory caches are rebuilt from Neo4j.
    try:
        durable_last = await read_tick_checkpoint()
    except Exception:
        durable_last = None
    if durable_last is not None and sim_time <= durable_last:
        logger.debug("Skipping replayed tick %s (<= checkpoint %s)", sim_time, durable_last)
        return

    _state.tick_counter += 1
    _state.sim_time = sim_time
    _state.sim_day = payload.get("day_of_sim", 0)

    # Compute how many sim-minutes this tick covers (accounts for tick
    # skipping at high speed AND multi-minute clock steps).
    if _state.last_tick_sim_time is not None:
        delta_minutes = max(1, round((sim_time - _state.last_tick_sim_time).total_seconds() / 60))
    else:
        delta_minutes = payload.get("step_minutes", 1)
    _state.last_tick_sim_time = sim_time

    # Track simulation mode (REALTIME / FAST / BULK)
    _state.last_mode = _state.current_mode
    _state.current_mode = payload.get("mode", "REALTIME")
    is_bulk = _state.current_mode == "BULK"

    # In BULK mode, suppress ALL per-passenger Kafka events
    set_bulk_mode(is_bulk)

    try:
        # Warm start (fresh state only): place already-due departure passengers
        # on their own timelines; committed with this tick below.
        warm = TickContribution()
        _state.warm_started_ids = set()
        if _warm_start_due(_state.tick_counter):
            with phase_timer("warm_start"):
                warm = await _warm_start_departures(sim_time)
            scope = current_tick.get()
            if scope is not None:
                scope.effects.append(_mark_warm_start_done)  # only once committed
            else:
                _mark_warm_start_done()

        # === Critical path (every tick) ===

        # 1. ML feature cache (reduced frequency in BULK mode)
        ml_interval = 20 if is_bulk else 5
        if _state.tick_counter % ml_interval == 0:
            with phase_timer("ml"):
                await _ml_tick(sim_time)

        # 2b. Drain wheelchair request queue (1C — accessibility).
        #     Its own subsystem (separate Neo4j writes); not part of the FSM tx.
        with phase_timer("wheelchair"):
            await _wheelchair_tick(sim_time)

        # G1-a: the six FSM handlers now COMPUTE their intended transitions (reading
        # Neo4j + doing derived in-memory bookkeeping inline) and return them as a
        # TickContribution. All of a tick's domain writes + fact staging then commit
        # in ONE apply_tick_atomic transaction, advancing the durable checkpoint.
        plan = TickContribution()
        plan.merge(warm)
        reconcile_now = _reconcile_due(sim_time)
        for phase, step in (
            ("reconcile", lambda: (_reconcile_flight_passengers(sim_time) if reconcile_now
                                   else _empty_contribution())),
            ("booked_to_checkin", lambda: _advance_booked_to_checkin(sim_time, delta_minutes)),
            ("checkin_to_security", lambda: _advance_checkin_to_security(sim_time, delta_minutes)),
            ("security_drain", lambda: _drain_security_queues(sim_time, delta_minutes)),
            ("airside_to_gate", lambda: _advance_airside_to_gate(sim_time)),
            ("boarding", lambda: _advance_boarding(sim_time, delta_minutes)),
            ("arrivals", lambda: _advance_arrivals(sim_time)),
        ):
            with phase_timer(phase):
                plan.merge(await step())

        with phase_timer("boarding_progress"):
            await _publish_boarding_progress(sim_time)
            if _state.tick_counter % 60 == 0:
                from _common.flight_view import VIEW
                VIEW.evict(sim_time)

        with phase_timer("apply"):
            applied = await apply_tick_atomic(
                sim_time,
                status_groups=plan.groups,
                dwell_items=plan.dwell_items,
                location_updates=plan.location_updates,
                facts=plan.facts,
            )
        if not applied:
            # Single serial consumer: reaching here means the durable checkpoint
            # advanced between the pre-read and the locked write (unexpected).
            # In-memory bookkeeping already ran; it is derived and rebuilt from
            # Neo4j on the next _sync_security_from_db / restart.
            logger.warning("Tick %s not applied (checkpoint already advanced)", sim_time)

        # === Non-critical path (reduced frequency) ===

        # 8. Check connections (reduced in BULK mode)
        conn_interval = 30 if is_bulk else 10
        if _state.tick_counter % conn_interval == 0:
            with phase_timer("connections"):
                await _check_connections(sim_time)

        # 9. Check congestion (reduced in BULK mode)
        congestion_interval = 20 if is_bulk else 5
        if _state.tick_counter % congestion_interval == 0:
            for terminal in ("A", "B", "C"):
                cp = _state.security.get(terminal)
                features = _build_context_features(terminal, sim_time)
                forecast = predict(terminal, features)
                wait = cp.wait_minutes(forecast or 0)
                if check_congestion(terminal, wait):
                    event_payload = await emit_congestion_detected(
                        terminal=terminal,
                        wait_minutes=wait,
                        queue_depth=cp.queue_depth,
                        sim_time=sim_time,
                    )
                    if _state.ws_broadcast:
                        await _state.ws_broadcast({
                            "event_type": "SecurityCongestionDetected",
                            "payload": event_payload,
                        })

        # 10. Maybe retrain model (every 30 ticks = ~every 30 sim-minutes)
        if _state.tick_counter % 30 == 0:
            retrained = await maybe_retrain(_state.sim_day)
            if retrained:
                load_models()
            maybe_flush(sim_time)

        # 11. Update Prometheus gauges from the 15 s flow projection. A direct
        #     count scans every Passenger ever seeded (1.5M+ after a few weeks
        #     of sim) and used to run inside the tick transaction.
        gauge_interval = 20 if is_bulk else 5
        if _state.tick_counter % gauge_interval == 0:
            from services import flow_projection
            status_counts = flow_projection.cached() or {}
            for status, count in status_counts.items():
                m_pax_in_airport.labels(status=status).set(count)

        # Persist public measured snapshots inside the owner tick transaction.
        from db.neo4j import save_security_projection
        security_rows = [{
            "terminal": terminal, "queue_depth": cp.queue_depth,
            "sa_queue_depth": cp.sa_queue_depth, "lanes_open": cp.lanes_open,
            "frozen": cp.frozen, "wait_minutes": round(cp.wait_minutes(0), 1),
            "at": sim_time.isoformat(), "updated_at": sim_time.isoformat(),
        } for terminal, cp in _state.security.checkpoints.items()]
        await save_security_projection(security_rows)

        # Security gauges are cheap (in-memory), update every tick
        for terminal in ("A", "B", "C"):
            cp = _state.security.checkpoints.get(terminal)
            if cp:
                m_sec_queue_depth.labels(terminal=terminal).set(cp.queue_depth)
                m_sec_wait.labels(terminal=terminal).set(round(cp.wait_minutes(0), 1))
                emit_security_queue_updated(
                    terminal, cp.queue_depth, cp.lanes_open,
                    cp.wait_minutes(0), sim_time,
                    sa_queue_depth=cp.sa_queue_depth, frozen=cp.frozen,
                )
                m_sec_lanes.labels(terminal=terminal).set(cp.lanes_open)

        # 12. BULK mode: emit periodic BulkStateSnapshot
        #     Also emit on BULK→non-BULK transition (forced flush)
        leaving_bulk = _state.last_mode == "BULK" and _state.current_mode != "BULK"
        if is_bulk or leaving_bulk:
            await _maybe_emit_bulk_snapshot(sim_time)

    except Exception as e:
        logger.error("Error in clock tick processing: %s", e, exc_info=True)
        raise


BULK_SNAPSHOT_INTERVAL_SIM_MIN = int(os.getenv("BULK_SNAPSHOT_INTERVAL_MIN", "60"))


async def _maybe_emit_bulk_snapshot(sim_time: datetime) -> None:
    """Emit a BulkStateSnapshot summarising passenger state (BULK mode only).

    Triggered every ``BULK_SNAPSHOT_INTERVAL_SIM_MIN`` sim-minutes.
    Also triggers on mode transition from BULK → FAST/REALTIME.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    force = _state.last_mode == "BULK" and _state.current_mode != "BULK"

    if not force and _state.last_sync_sim_time is not None:
        elapsed = (sim_time - _state.last_sync_sim_time).total_seconds() / 60
        if elapsed < BULK_SNAPSHOT_INTERVAL_SIM_MIN:
            return

    _state.last_sync_sim_time = sim_time

    # Build summary from in-memory security queues + a single Neo4j count query
    security_wait: dict[str, float] = {}
    security_depth: dict[str, int] = {}
    for terminal in ("A", "B", "C"):
        cp = _state.security.checkpoints.get(terminal)
        if cp:
            security_wait[terminal] = round(cp.wait_minutes(0), 1)
            security_depth[terminal] = cp.queue_depth

    try:
        status_counts = await get_status_counts()
    except Exception:
        status_counts = {}

    summary = {
        "by_status": status_counts,
        "connections_at_risk": len(_state.at_risk_connections),
        "security_wait_by_terminal": security_wait,
        "security_depth_by_terminal": security_depth,
    }

    emit_bulk_state_snapshot(sim_time, summary)
    logger.info("BulkStateSnapshot emitted (pax): %s", summary.get("by_status", {}))


async def _empty_contribution() -> "TickContribution":
    return TickContribution()


# RC4: reconciliation is a recovery path, not a second primary path. It runs
# for the first ticks after a (re)start and then hourly, so it can never race
# the FlightStatusChanged handlers it exists to back up.
RECONCILE_BOOT_TICKS = int(os.getenv("RECONCILE_BOOT_TICKS", "10"))
RECONCILE_INTERVAL_MIN = int(os.getenv("RECONCILE_INTERVAL_MIN", "60"))
_reconcile_cadence: dict = {"boot_ticks": 0, "last": None}


def _reconcile_due(sim_time: datetime) -> bool:
    cadence = _reconcile_cadence
    if cadence["boot_ticks"] < RECONCILE_BOOT_TICKS:
        cadence["boot_ticks"] += 1
        cadence["last"] = sim_time
        return True
    last = cadence["last"]
    if last is None or (sim_time - last).total_seconds() >= RECONCILE_INTERVAL_MIN * 60:
        cadence["last"] = sim_time
        return True
    return False


async def _publish_boarding_progress(sim_time: datetime) -> None:
    """Boarded/total for every departure in ``boarding`` per the FlightView (RC4)."""
    from _common.flight_view import VIEW
    from db.neo4j import get_boarding_counts
    fids = [f["id"] for f in VIEW.select(statuses=["boarding"], direction="departure")]
    rows = await get_boarding_counts(fids)
    emit_boarding_progress([
        {"flight_id": r["flight_id"], "boarded": int(r["boarded"] or 0), "total": int(r["total"] or 0)}
        for r in rows
    ], sim_time)


async def _reconcile_flight_passengers(sim_time: datetime) -> TickContribution:
    """Recover a bounded cohort in the same atomic tick as normal progression."""
    from db.neo4j import get_reconciliation_candidates
    state = current_tick.get().state if current_tick.get() else globals()["_state"]
    plan = TickContribution()
    removed: set[str] = set()
    groups: dict[tuple[str, str], list[str]] = {}
    for pax in await get_reconciliation_candidates(sim_time):
        transition = reconciliation_transition(pax, sim_time)
        if transition is None:
            continue
        status, zone = transition
        pid = pax["id"]
        removed.add(pid)
        groups.setdefault(transition, []).append(pid)
        old_zone = pax.get("location_zone") if pax["status"] in PHYSICAL_STATUSES else None
        if status == "deplaning":
            move_passenger(old_zone, zone)
        elif old_zone:
            remove_passenger(old_zone)
        if pax.get("special_assistance") and status == "departed_airport":
            await wheelchair.release(pid, sim_time)
    for (status, zone), ids in groups.items():
        # RC3: the tick's PassengerStatusBatchChanged is the only publication;
        # the reason travels with the cohort (kept in BULK mode too).
        plan.groups.append({"ids": ids, "status": status, "zone": zone,
                            "reconciliation_reason": "persisted_flight_state"})
    if removed:
        # Remove stale queue membership before this candidate's normal drain.
        for cp in state.security.checkpoints.values():
            cp.queue = [pid for pid in cp.queue if pid not in removed]
            cp.sa_queue = [pid for pid in cp.sa_queue if pid not in removed]
            cp._queue_set.difference_update(removed)
            cp._sa_queue_set.difference_update(removed)
        state.security_enqueued.difference_update(removed)
        state.airside_transitioned.difference_update(removed)
        logger.info("Reconciled %s passengers with persisted flight state", len(removed))
    return plan


async def _advance_booked_to_checkin(
    sim_time: datetime, delta_minutes: int = 1
) -> TickContribution:
    """Compute booked → checked_in (or no-show) transitions, per passenger (RC5).

    Each departing passenger arrives at their own ``show_up_at`` (drawn at seed
    time from Beta(3,2) over [T-180, T-45]); there is no flight-wide release.
    At show-up, the passenger's single deterministic no-show draw is taken over
    the whole booked cohort: a no-show goes straight to ``departed_airport``
    (zone ``no-show``) and never enters the airport. Only flights still on the
    ground and open are eligible. Capped at MAX_CHECKIN_PER_TICK per tick
    (scaled by ``delta_minutes``); the remainder is picked up next tick.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    plan = TickContribution()
    MAX_CHECKIN_PER_TICK = 200 * delta_minutes

    # Earliest show-up is T-180; only passengers already due are read.
    cutoff = (sim_time + timedelta(minutes=SHOW_UP_WINDOW_START_MIN)).isoformat()
    try:
        pax_list = await get_passengers_by_status(
            "booked", scheduled_before=cutoff,
            flight_statuses=list(PRE_DEPARTURE_FLIGHT_STATUSES),
            due_field="show_up_at", due_at=sim_time.isoformat(), include_missing_due=True,
        )
    except Exception as e:
        if current_tick.get() is not None:
            raise
        logger.error("Failed to get booked passengers: %s", e)
        return plan

    checkin_ids: dict[str, list[str]] = {}
    noshow_ids: list[str] = []
    total_moved = 0
    for pax in pax_list:
        if total_moved >= MAX_CHECKIN_PER_TICK:
            break
        if pax.get("direction", "departure") != "departure":
            continue
        if pax["id"] in _state.warm_started_ids:
            continue  # placed by this tick's warm start
        scheduled = pax.get("scheduled_time") or pax.get("estimated_time")
        show_up = show_up_time(pax["id"], scheduled, pax.get("show_up_at"))
        if show_up is None or sim_time < show_up:
            continue
        total_moved += 1
        if is_no_show(pax["id"], _state.noshow_rate):
            noshow_ids.append(pax["id"])
            continue
        flight_id = pax.get("flight_id") or ""
        terminal = get_terminal_for_flight(pax.get("gate_id"), pax.get("terminal_id"), flight_id)
        new_zone = f"check-in-{terminal}"
        checkin_ids.setdefault(new_zone, []).append(pax["id"])
        move_passenger(None, new_zone)
        # 1C — register SA passengers with the wheelchair pool on check-in.
        if pax.get("special_assistance"):
            try:
                await wheelchair.request(
                    terminal=terminal,
                    passenger_id=pax["id"],
                    sim_time=sim_time,
                    scheduled_dep_iso=str(scheduled) if scheduled else None,
                    flight_id=flight_id,
                    name=pax.get("name"),
                )
            except Exception as exc:
                if current_tick.get() is not None:
                    raise
                logger.warning("wheelchair request failed for %s: %s", pax["id"], exc)

    for zone, ids in checkin_ids.items():
        plan.groups.append({"ids": ids, "status": "checked_in", "zone": zone})
    if noshow_ids:
        plan.groups.append({"ids": noshow_ids, "status": "departed_airport", "zone": "no-show"})
        logger.info("No-shows at show-up time: %d passengers", len(noshow_ids))
    return plan


async def _advance_checkin_to_security(
    sim_time: datetime, delta_minutes: int = 1
) -> TickContribution:
    """Compute checked_in → security_queue transitions, per passenger (RC5).

    A passenger joins security ``CHECKIN_PROCESS_MINUTES`` after showing up, or
    at check-in close (T-45) if that comes first — never as a whole flight.
    Capped at MAX_CHECKIN_TO_SECURITY_PER_TICK (scaled by ``delta_minutes``).
    The in-memory SecuritySystem enqueue stays inline (derived state, rebuildable
    from Neo4j); the DB status write + facts are returned for the atomic commit.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    plan = TickContribution()
    MAX_CHECKIN_TO_SECURITY_PER_TICK = 150 * delta_minutes

    cutoff = (sim_time + timedelta(minutes=SHOW_UP_WINDOW_START_MIN)).isoformat()
    try:
        pax_list = await get_passengers_by_status(
            "checked_in", scheduled_before=cutoff,
            flight_statuses=list(PRE_DEPARTURE_FLIGHT_STATUSES),
        )
    except Exception as e:
        if current_tick.get() is not None:
            raise
        logger.error("Failed to get checked_in passengers: %s", e)
        return plan

    ids_by_zone: dict[str, list[str]] = {}
    total_moved = 0
    for pax in pax_list:
        if total_moved >= MAX_CHECKIN_TO_SECURITY_PER_TICK:
            break
        if pax.get("direction", "departure") != "departure":
            continue
        pid = pax["id"]
        if pid in _state.security_enqueued:
            continue
        scheduled = pax.get("scheduled_time") or pax.get("estimated_time")
        show_up = show_up_time(pid, scheduled, pax.get("show_up_at"))
        if show_up is None or not security_due(show_up, scheduled, sim_time):
            continue
        terminal = get_terminal_for_flight(
            pax.get("gate_id"), pax.get("terminal_id"), pax.get("flight_id") or ""
        )
        _state.security_enqueued.add(pid)
        _state.security.enqueue(terminal, pid, bool(pax.get("special_assistance")))
        new_zone = f"security-{terminal}"
        ids_by_zone.setdefault(new_zone, []).append(pid)
        move_passenger(pax.get("location_zone") or f"check-in-{terminal}", new_zone)
        total_moved += 1

    for zone, ids in ids_by_zone.items():
        plan.groups.append({"ids": ids, "status": "security_queue", "zone": zone})
    return plan


async def _drain_security_queues(
    sim_time: datetime, delta_minutes: int = 1
) -> TickContribution:
    """Compute security_queue → airside transitions by draining checkpoints.

    The in-memory SecuritySystem drain (and the periodic DB reconcile) stay inline
    — authoritative in-memory queue state, rebuildable from Neo4j. The DB status +
    dwell writes and facts are returned for the atomic tick commit (G1-a).
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    plan = TickContribution()
    # Periodic DB sync (every 60 ticks) to catch missed events/restarts.
    # On normal ticks, in-memory queues are authoritative.
    if current_tick.get() is None and _state.tick_counter % 60 == 0:
        await _sync_security_from_db()

    forecast_queues = _get_forecast_queues(sim_time)
    drained = _state.security.drain_all(forecast_queues, delta_minutes)

    for terminal, (main_drained, sa_drained) in drained.items():
        all_drained = main_drained + sa_drained
        if not all_drained:
            continue
        _state.security_enqueued.difference_update(all_drained)

        new_zone = f"airside-{terminal}"
        default_old_zone = f"security-{terminal}"

        plan.groups.append({"ids": all_drained, "status": "airside", "zone": new_zone})
        # SA passengers skip dwell and route directly to gate (spec §3)
        sa_set = set(sa_drained)
        plan.dwell_items.extend(
            (pid, 0 if pid in sa_set else sample_dwell_minutes()) for pid in all_drained
        )

        for pid in all_drained:
            move_passenger(default_old_zone, new_zone)

    return plan


async def _sync_security_from_db() -> dict[str, str]:
    """Reconcile in-memory security queues against Neo4j before drain.

    This prevents stuck passengers when the service restarts mid-simulation
    or if events were missed.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    try:
        pax_list = await get_security_queue_members()
        if any(_extract_terminal_from_location(p.get("location_zone") or "") is None
               for p in pax_list):
            # Rare: a member without a terminal zone needs its gate/flight.
            pax_list = await get_passengers_by_status("security_queue")
    except Exception as e:
        if current_tick.get() is not None:
            raise
        logger.error("Failed to sync security queues from Neo4j: %s", e)
        return {}

    zone_by_pid: dict[str, str] = {}
    security_ids: set[str] = set()
    committed_ids = {pax["id"] for pax in pax_list}
    queued_ids = {
        pid for cp in _state.security.checkpoints.values()
        for pid in (*cp.queue, *cp.sa_queue)
    }
    _state.security_enqueued = queued_ids & committed_ids
    _state.airside_transitioned.difference_update(committed_ids)
    for pax in pax_list:
        pid = pax["id"]
        security_ids.add(pid)
        zone_by_pid[pid] = pax.get("location_zone") or ""

        if pid in _state.airside_transitioned:
            continue

        if pid not in _state.security_enqueued:
            terminal = _extract_terminal_from_location(zone_by_pid[pid])
            if terminal is None:
                terminal = get_terminal_for_flight(
                    pax.get("gate_id"), pax.get("terminal_id"), pax.get("flight_id") or ""
                )
            _state.security.enqueue(terminal, pid, bool(pax.get("special_assistance")))
            _state.security_enqueued.add(pid)

    # Remove stale IDs from in-memory queues when they are no longer in security_queue.
    for cp in _state.security.checkpoints.values():
        cp.queue = [pid for pid in cp.queue if pid in security_ids]
        cp._queue_set = set(cp.queue)
        cp.sa_queue = [pid for pid in cp.sa_queue if pid in security_ids]
        cp._sa_queue_set = set(cp.sa_queue)

    return zone_by_pid


def _get_forecast_queues(sim_time: datetime) -> dict[str, int]:
    """Get forecasted queue depths per terminal."""
    forecasts = {}
    for terminal in ("A", "B", "C"):
        features = _build_context_features(terminal, sim_time)
        pred = predict(terminal, features)
        forecasts[terminal] = pred if pred is not None else 0
    return forecasts


def get_forecast_context(terminal: str) -> dict:
    """Snapshot current weather, incidents and neighbouring queue conditions."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return {
        "weather_category": _state.weather_category,
        "load_factor_today": (
            _state.load_factor_sum / _state.load_factor_count
            if _state.load_factor_count else 0.8
        ),
        "incident_active": dict(_state.active_incidents),
        "adjacent_congested": {
            terminal: any(
                _state.security.get(other).wait_minutes(0) > 20
                for other in "ABC" if other != terminal
            ),
        },
    }


def _build_context_features(terminal: str, sim_time: datetime) -> dict:
    """Build feature vector for a terminal."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    return build_features(
        terminal=terminal,
        sim_time=sim_time,
        flights_next_90=_state.cached_flights_next_90,
        pax_next_90=_state.cached_pax_next_90,
        **get_forecast_context(terminal),
    )


async def _advance_airside_to_gate(sim_time: datetime) -> TickContribution:
    """Compute airside → at_gate transitions when dwell completes and gate opens."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    plan = TickContribution()
    # Only flights whose gate has opened (estimated - GATE_OPEN_MINUTES); the
    # estimate never precedes the schedule, so this scheduled bound is a superset.
    cutoff = (sim_time + timedelta(minutes=GATE_OPEN_MINUTES)).isoformat()
    try:
        # RC5: nobody walks to the gate of a flight that has already left.
        pax_list = await get_passengers_by_status(
            "airside", scheduled_before=cutoff,
            flight_statuses=list(PRE_DEPARTURE_FLIGHT_STATUSES),
        )
    except Exception as e:
        if current_tick.get() is not None:
            raise
        logger.error("Failed to get airside passengers: %s", e)
        return plan

    ids_by_zone: dict[str, list[str]] = {}

    for pax in pax_list:
        try:
            estimated = pax.get("estimated_time")
            if not estimated:
                continue

            dwell = pax.get("dwell_minutes")
            airside_at = pax.get("airside_at")

            gate_id = pax.get("gate_id")
            terminal = get_terminal_for_flight(
                gate_id,
                pax.get("terminal_id"),
                pax.get("flight_id"),
            )

            # Compute walking time from airside to gate
            gate_pos = _state.gate_positions.get(gate_id) if gate_id else None
            walk_min = walking_time_to_gate(
                terminal, gate_pos, _state.walking_zones,
                special_assistance=bool(pax.get("special_assistance")),
            )

            if not should_move_to_at_gate(sim_time, estimated, dwell, airside_at, walk_min):
                continue

            new_zone = zone_for_status("at_gate", terminal, gate_id)
            old_zone = pax.get("location_zone") or f"airside-{terminal}"

            ids_by_zone.setdefault(new_zone, []).append(pax["id"])
            move_passenger(old_zone, new_zone)

            # 1C — record SLA outcome (wheelchair only).
            if pax.get("special_assistance"):
                try:
                    await wheelchair.mark_at_gate(pax["id"], sim_time)
                except Exception as exc:
                    if current_tick.get() is not None:
                        raise
                    logger.debug("wheelchair mark_at_gate failed: %s", exc)
        except Exception as e:
            if current_tick.get() is not None:
                raise
            logger.warning("Skipping invalid airside passenger record %s: %s", pax.get("id"), e)
            continue

    for zone, ids in ids_by_zone.items():
        plan.groups.append({"ids": ids, "status": "at_gate", "zone": zone})

    return plan


async def _advance_boarding(
    sim_time: datetime, delta_minutes: int = 1
) -> TickContribution:
    """Compute at_gate → boarded transitions, gated by the aircraft (RC5).

    Progressive boarding at BOARDING_RATE while the flight is still
    ``scheduled`` / ``boarding`` / ``delayed`` and the boarding call is due.
    Nobody boards a departed, taxiing or airborne aircraft: passengers left at
    the gate become ``missed_flight`` on ``FlightStatusChanged(departed)``. The
    no-show draw happens at show-up time over the whole cohort, not here. The DB
    status writes + facts are returned for the atomic tick commit (G1-a).
    """
    plan = TickContribution()
    # Time-window: only passengers with flights departing within next 1.5 hours
    cutoff = (sim_time + timedelta(hours=1, minutes=30)).isoformat()
    try:
        pax_list = await get_passengers_by_status(
            "at_gate", scheduled_before=cutoff,
            flight_statuses=list(PRE_DEPARTURE_FLIGHT_STATUSES),
        )
    except Exception as e:
        if current_tick.get() is not None:
            raise
        logger.error("Failed to get at_gate passengers: %s", e)
        return plan

    # Group by flight
    flights: dict[str, list[dict]] = {}
    for pax in pax_list:
        fid = pax.get("flight_id") or ""
        flights.setdefault(fid, []).append(pax)

    boarding_rate = BOARDING_RATE_PAX_PER_MIN * delta_minutes

    for flight_id, pax_group in flights.items():
        if not pax_group:
            continue
        sample = pax_group[0]
        estimated = sample.get("estimated_time")
        flight_status = sample.get("flight_status", "scheduled")
        if not estimated or not should_start_boarding(sim_time, estimated, flight_status):
            continue
        to_board = pax_group[:boarding_rate]

        ids = [p["id"] for p in to_board]
        gate_id = sample.get("gate_id")
        terminal = get_terminal_for_flight(
            gate_id,
            sample.get("terminal_id"),
            flight_id,
        )
        new_zone = zone_for_status("boarded", terminal, gate_id)

        if ids:
            plan.groups.append({"ids": ids, "status": "boarded", "zone": new_zone})

        for pax in to_board:
            old_zone = pax.get("location_zone") or f"gate-{gate_id}"
            # Boarded passengers leave terminal waiting areas.
            remove_passenger(old_zone)

            # 1C — release wheelchair when boarding completes.
            if pax.get("special_assistance"):
                try:
                    await wheelchair.release(pax["id"], sim_time)
                except Exception as exc:
                    if current_tick.get() is not None:
                        raise
                    logger.debug("wheelchair release failed: %s", exc)

    return plan


async def _wheelchair_tick(sim_time: datetime) -> None:
    """Drain wheelchair queues each clock tick (1C)."""
    try:
        await wheelchair.tick(sim_time)
    except Exception as exc:
        logger.warning("wheelchair tick failed: %s", exc)


async def _advance_arrivals(sim_time: datetime) -> TickContribution:
    """Compute arrival transitions: deplaning → [customs →] baggage_claim → departed.

    Carousel re-location writes and the in-memory carousel/collected sets stay
    inline; the status transitions + facts + location updates are returned for the
    atomic tick commit (G1-a).
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    plan = TickContribution()

    def _carousel_zone_for(pax: dict) -> str | None:
        fid = pax.get("flight_id")
        if not fid:
            return None
        carousel_zone = _state.flight_carousel_zone.get(fid)
        if carousel_zone:
            return carousel_zone
        # Deterministic fallback: derive carousel from gate/terminal
        # A→1-2, B→3-4, C→5-6 (matches baggage-service logic)
        gate = pax.get("gate_id") or ""
        terminal = pax.get("terminal_id") or (gate[0].upper() if gate else "A")
        carousel_map = {"A": [1, 2], "B": [3, 4], "C": [5, 6]}
        carousels = carousel_map.get(terminal, [1, 2])
        carousel_num = carousels[hash(fid) % len(carousels)]
        return f"carousel-{carousel_num}"

    def _assign_carousels(paxes: list[dict]) -> None:
        for pax in paxes:
            pid = pax["id"]
            carousel_zone = _carousel_zone_for(pax)
            if carousel_zone and pid not in _state.passengers_at_carousel:
                move_passenger("baggage-claim", carousel_zone)
                _state.passengers_at_carousel.add(pid)
                plan.location_updates.append({"id": pid, "zone": carousel_zone})

    # deplaning → customs (international) or baggage_claim (domestic)
    try:
        deplaning = await get_passengers_by_status(
            "deplaning", due_field="deplaning_at",
            due_at=(sim_time - timedelta(minutes=DEPLANING_DELAY_MINUTES)).isoformat(),
        )
    except Exception:
        if current_tick.get() is not None:
            raise
        deplaning = []

    to_customs: list[dict] = []
    to_baggage_claim: list[dict] = []
    for pax in deplaning:
        deplaning_at = pax.get("deplaning_at")
        if should_move_to_baggage_claim(sim_time, deplaning_at):
            if is_international_flight(pax.get("flight_type")):
                to_customs.append(pax)
            else:
                to_baggage_claim.append(pax)

    if to_customs:
        ids = [p["id"] for p in to_customs]
        new_zone = "customs"
        plan.groups.append({"ids": ids, "status": "customs", "zone": new_zone})
        for pax in to_customs:
            old_zone = pax.get("location_zone") or "arrivals-hall"
            move_passenger(old_zone, new_zone)

    if to_baggage_claim:
        ids = [p["id"] for p in to_baggage_claim]
        new_zone = "baggage-claim"
        plan.groups.append({"ids": ids, "status": "baggage_claim", "zone": new_zone})
        for pax in to_baggage_claim:
            old_zone = pax.get("location_zone") or "arrivals-hall"
            move_passenger(old_zone, new_zone)
        # Assign to carousel if bags already on carousel for this flight
        _assign_carousels(to_baggage_claim)

    # customs → baggage_claim
    try:
        in_customs = await get_passengers_by_status(
            "customs", due_field="customs_at",
            due_at=(sim_time - timedelta(minutes=CUSTOMS_DELAY_MINUTES)).isoformat(),
        )
    except Exception:
        if current_tick.get() is not None:
            raise
        in_customs = []

    customs_to_bc: list[dict] = []
    for pax in in_customs:
        customs_at = pax.get("customs_at")
        if should_clear_customs(sim_time, customs_at):
            customs_to_bc.append(pax)

    if customs_to_bc:
        ids = [p["id"] for p in customs_to_bc]
        new_zone = "baggage-claim"
        plan.groups.append({"ids": ids, "status": "baggage_claim", "zone": new_zone})
        for pax in customs_to_bc:
            old_zone = pax.get("location_zone") or "customs"
            move_passenger(old_zone, new_zone)
        # Assign to carousel if bags already on carousel for this flight
        _assign_carousels(customs_to_bc)

    # baggage_claim → departed_airport
    try:
        claiming = await get_passengers_by_status(
            "baggage_claim", due_field="baggage_claim_at",
            due_at=(sim_time - timedelta(minutes=BAGGAGE_CLAIM_TIMEOUT_MINUTES)).isoformat(),
            include_ids=sorted(_state.baggage_collected),
        )
    except Exception:
        if current_tick.get() is not None:
            raise
        claiming = []

    to_depart: list[dict] = []
    for pax in claiming:
        pid = pax["id"]
        collected = pid in _state.baggage_collected
        bc_at = pax.get("baggage_claim_at")
        if should_depart_airport(sim_time, bc_at, collected):
            to_depart.append(pax)

    if to_depart:
        ids = [p["id"] for p in to_depart]
        new_zone = "arrivals-hall"
        plan.groups.append({"ids": ids, "status": "departed_airport", "zone": new_zone})
        for pax in to_depart:
            old_zone = pax.get("location_zone") or "baggage-claim"
            remove_passenger(old_zone)
            _state.baggage_collected.discard(pax["id"])
            _state.passengers_at_carousel.discard(pax["id"])

    return plan


async def _check_connections(sim_time: datetime) -> None:
    """Evaluate connecting passengers; atomically persist risk + emit alerts (G1-c).

    The connection-risk property writes, the ``missed_connection`` status write and
    the ``PassengerAlert`` facts all commit in ONE ``apply_changes_atomic``
    transaction, keyed on a deterministic per-check id (``conn-<sim_time>``) for
    durable, restart-surviving dedup. Connection alerts are low-volume and are
    staged unsampled. In-memory alert history, WS fan-out and metric counters run
    only after a successful, non-deduped commit; risk gauges and the at-risk
    snapshot (derived display state) are refreshed every call.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    try:
        conn_pax = await get_connecting_passengers()
    except Exception as e:
        if current_tick.get() is not None:
            raise
        logger.error("Failed to get connecting passengers: %s", e)
        return

    results = evaluate_connecting_passengers(conn_pax, sim_time, _state.gate_positions or None)
    new_at_risk = []

    risk_updates: list[dict] = []
    missed_ids: list[str] = []
    facts: list[dict] = []
    # Deferred post-commit effects: (alert_payload, metric_type)
    pending_alerts: list[tuple[dict, str]] = []

    for r in results:
        if r["risk_changed"]:
            new_risk = r["risk_level"]
            risk_updates.append({"id": r["id"], "risk": new_risk})

            if new_risk == "at_risk":
                message = f"Connection at risk: {r['inbound_flight']} → {r['connection_flight']}"
                fact = build_passenger_alert_fact(
                    alert_type="connection_at_risk", message=message,
                    sim_time=sim_time, passenger_id=r["id"], urgency="high",
                )
                facts.append({"id": fact["event_id"], "document": fact})
                pending_alerts.append((fact["payload"], "connection_at_risk"))

            elif new_risk == "missed":
                missed_ids.append(r["id"])
                message = f"Connection missed: {r['inbound_flight']} → {r['connection_flight']}"
                fact = build_passenger_alert_fact(
                    alert_type="connection_missed", message=message,
                    sim_time=sim_time, passenger_id=r["id"], urgency="critical",
                )
                facts.append({"id": fact["event_id"], "document": fact})
                pending_alerts.append((fact["payload"], "connection_missed"))

        if r["risk_level"] in ("at_risk", "watch"):
            new_at_risk.append(r)

    status_groups = (
        [{"ids": missed_ids, "status": "missed_connection", "zone": "arrivals-hall"}]
        if missed_ids else []
    )
    applied = False
    if risk_updates or status_groups or facts:
        applied = await apply_changes_atomic(
            f"conn-{sim_time.isoformat()}",
            sim_time,
            status_groups=status_groups,
            risk_updates=risk_updates,
            facts=facts,
        )

    if applied:
        for alert, metric_type in pending_alerts:
            if metric_type == "connection_missed":
                m_connections_missed.inc()
            m_passenger_alerts.labels(type=metric_type).inc()
            _add_alert(alert)
            if _state.ws_broadcast:
                await _state.ws_broadcast({"event_type": "PassengerAlert", "payload": alert})

    _state.at_risk_connections = new_at_risk

    # Immediately update connection risk gauges at mutation site
    at_risk_count = sum(1 for r in new_at_risk if r["risk_level"] == "at_risk")
    watch_count = sum(1 for r in new_at_risk if r["risk_level"] == "watch")
    missed_count = sum(1 for r in results if r.get("risk_level") == "missed")
    m_connections_at_risk.labels(risk_level="at_risk").set(at_risk_count)
    m_connections_at_risk.labels(risk_level="watch").set(watch_count)
    m_connections_at_risk.labels(risk_level="missed").set(missed_count)


async def _ml_tick(sim_time: datetime) -> None:
    """Collect training data and update cached flight/pax counts."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]

    # Update flight/pax data for features
    try:
        flight_data = await get_departure_flights_in_window(sim_time, 90)
    except Exception:
        flight_data = []

    flights_next_90: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    pax_next_90: dict[str, float] = {"A": 0.0, "B": 0.0, "C": 0.0}

    for fd in flight_data:
        tid = fd.get("terminal_id", "")
        terminal = str(tid)[-1] if tid and len(str(tid)) >= 3 else "A"
        if terminal in flights_next_90:
            flights_next_90[terminal] += fd.get("flight_count", 0)
            pax_next_90[terminal] += float(fd.get("total_pax", 0))

    # Cache for use by _build_context_features / _get_forecast_queues
    _state.cached_flights_next_90 = flights_next_90
    _state.cached_pax_next_90 = pax_next_90

    for terminal in ("A", "B", "C"):
        cp = _state.security.get(terminal)
        features = _build_context_features(terminal, sim_time)
        add_training_row(terminal, features, cp.queue_depth, sim_time)


# --- Flight event handlers ---

async def _on_flight_status_changed(payload: dict, sim_time: datetime, event_id: str = "") -> None:
    """React to flight status changes — handle arrivals and delays.

    G1 canonical atomic path: the passenger-state domain write and the
    PassengerStatusChanged fact delivery now commit together via
    ``apply_status_change_atomic`` (durable inbox dedup + outbox staging),
    replacing the previous ``bulk_update_status`` + direct ``emit_*`` pair.
    In-memory zone-density bookkeeping (derived, rebuildable per rule #3) is
    applied only after the transaction commits, and skipped on a deduped redelivery.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    new_status = payload.get("new_status")
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    groups: list[dict] = []
    facts: list[dict] = []
    bookkeeping: list[tuple] = []  # ("move", old, new) / ("remove", old) — after commit
    departed_count = 0

    # Arrival: flight at_gate → passengers deplaning
    if new_status == "at_gate" and payload.get("previous_status") in ("taxiing", "landed"):
        try:
            pax_list = await get_passengers_by_flight(flight_id)
        except Exception:
            pax_list = []

        gate_id = payload.get("gate_id")
        terminal = get_terminal_for_flight(gate_id, None, flight_id)
        new_zone = zone_for_status("deplaning", terminal, gate_id)

        eligible = [
            pax for pax in pax_list
            if pax.get("status") in ("checked_in", "airborne", "booked", "boarded")
        ]
        if eligible:
            groups.append({"ids": [p["id"] for p in eligible], "status": "deplaning", "zone": new_zone})
            for pax in eligible:
                fact = build_passenger_status_changed_fact(
                    passenger_id=pax["id"],
                    name=pax.get("name", ""),
                    previous_status=pax.get("status", "airborne"),
                    new_status="deplaning",
                    location_zone=new_zone,
                    sim_time=sim_time,
                    flight_id=flight_id,
                )
                facts.append({"id": fact["event_id"], "document": fact})
                bookkeeping.append(("move", pax.get("location_zone"), new_zone))

    # Departure: flight departed → boarded passengers become departed_airport
    if new_status == "departed" and payload.get("direction") == "departure":
        try:
            pax_list = await get_passengers_by_flight(flight_id)
        except Exception:
            pax_list = []

        eligible = [pax for pax in pax_list if pax.get("status") == "boarded"]
        if eligible:
            departed_count = len(eligible)
            groups.append({"ids": [p["id"] for p in eligible], "status": "departed_airport", "zone": "departed"})
            for pax in eligible:
                fact = build_passenger_status_changed_fact(
                    passenger_id=pax["id"],
                    name=pax.get("name", ""),
                    previous_status="boarded",
                    new_status="departed_airport",
                    location_zone="departed",
                    sim_time=sim_time,
                    flight_id=flight_id,
                )
                facts.append({"id": fact["event_id"], "document": fact})
                bookkeeping.append(("remove", pax.get("location_zone") or ""))

        # RC5: the aircraft left without everyone not yet boarded. They miss the
        # flight; nothing boards them afterwards.
        missed = [pax for pax in pax_list if pax.get("status") in MISSED_FLIGHT_STATUSES]
        if missed:
            missed_ids = [p["id"] for p in missed]
            groups.append({"ids": missed_ids, "status": "missed_flight", "zone": "missed-flight"})
            for pax in missed:
                fact = build_passenger_status_changed_fact(
                    passenger_id=pax["id"],
                    name=pax.get("name", ""),
                    previous_status=pax.get("status", "at_gate"),
                    new_status="missed_flight",
                    location_zone="missed-flight",
                    sim_time=sim_time,
                    flight_id=flight_id,
                )
                facts.append({"id": fact["event_id"], "document": fact})
                if pax.get("status") != "booked":
                    bookkeeping.append(("remove", pax.get("location_zone") or ""))
                bookkeeping.append(("missed", pax["id"], bool(pax.get("special_assistance"))))

    if groups:
        applied = await apply_status_change_atomic(event_id, groups, facts, sim_time)
        if applied:
            missed_ids: set[str] = set()
            for item in bookkeeping:
                if item[0] == "move":
                    move_passenger(item[1], item[2])
                elif item[0] == "missed":
                    missed_ids.add(item[1])
                    m_missed_flight.inc()
                    if item[2]:
                        try:
                            await wheelchair.release(item[1], sim_time)
                        except Exception as exc:
                            logger.debug("wheelchair release failed: %s", exc)
                else:
                    remove_passenger(item[1])
            if missed_ids:
                # Derived queue membership (rebuildable): drop the missed cohort.
                for cp in _state.security.checkpoints.values():
                    cp.queue = [pid for pid in cp.queue if pid not in missed_ids]
                    cp.sa_queue = [pid for pid in cp.sa_queue if pid not in missed_ids]
                    cp._queue_set.difference_update(missed_ids)
                    cp._sa_queue_set.difference_update(missed_ids)
                _state.security_enqueued.difference_update(missed_ids)
                _state.airside_transitioned.difference_update(missed_ids)
            if departed_count or missed_ids:
                logger.info(
                    "Flight %s departed: %d passengers departed_airport, %d missed_flight",
                    flight_id, departed_count, len(missed_ids),
                )

    # Delay: update load factor
    if new_status == "delayed":
        payload.get("delay_minutes", 0)
        _state.load_factor_sum += 0.7  # delayed flights have lower effective load
        _state.load_factor_count += 1


async def _on_flight_gate_assigned(payload: dict, sim_time: datetime) -> None:
    """Issue gate change alerts to affected passengers."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    flight_id = payload.get("flight_id")
    new_gate = payload.get("gate_id")
    old_gate = payload.get("previous_gate_id")

    if not flight_id or not new_gate or not old_gate:
        return

    try:
        pax_list = await get_passengers_by_flight(flight_id)
    except Exception:
        return

    for pax in pax_list:
        if pax.get("status") in ("checked_in", "security_queue", "airside", "at_gate"):
            alert = await emit_passenger_alert(
                alert_type="gate_change",
                message=f"Your flight has moved to gate {new_gate}.",
                sim_time=sim_time,
                passenger_id=pax["id"],
                flight_id=flight_id,
                urgency="high",
            )
            _add_alert(alert)
            if _state.ws_broadcast:
                await _state.ws_broadcast({"event_type": "PassengerAlert", "payload": alert})


async def _on_flight_cancelled(payload: dict, sim_time: datetime, event_id: str = "") -> None:
    """Mark all on-flight passengers as disrupted — atomic domain-write + facts (G1-c).

    The ``disrupted`` status write, the ``PassengerStatusChanged`` facts and the
    ``flight_cancelled`` ``PassengerAlert`` facts commit together in ONE
    ``apply_changes_atomic`` transaction with durable inbox dedup on the input
    ``event_id`` (replacing the previous write-then-direct-emit pair). In-memory
    alert history is appended only after a successful, non-deduped commit.
    """
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    try:
        pax_list = await get_passengers_by_flight(flight_id)
    except Exception:
        return

    by_zone: dict[str, list[str]] = {}
    facts: list[dict] = []
    pending_alerts: list[dict] = []
    for pax in pax_list:
        if pax.get("status") in ("boarded", "departed_airport"):
            continue
        zone = pax.get("location_zone") or "arrivals-hall"
        by_zone.setdefault(zone, []).append(pax["id"])
        status_fact = build_passenger_status_changed_fact(
            passenger_id=pax["id"],
            name=pax.get("name", ""),
            previous_status=pax.get("status", ""),
            new_status="disrupted",
            location_zone=zone,
            sim_time=sim_time,
            flight_id=flight_id,
        )
        facts.append({"id": status_fact["event_id"], "document": status_fact})
        alert_fact = build_passenger_alert_fact(
            alert_type="flight_cancelled",
            message="Your flight has been cancelled.",
            sim_time=sim_time,
            passenger_id=pax["id"],
            flight_id=flight_id,
            urgency="critical",
        )
        facts.append({"id": alert_fact["event_id"], "document": alert_fact})
        pending_alerts.append(alert_fact["payload"])

    if not facts:
        return

    status_groups = [
        {"ids": ids, "status": "disrupted", "zone": zone} for zone, ids in by_zone.items()
    ]
    applied = await apply_changes_atomic(
        event_id, sim_time, status_groups=status_groups, facts=facts,
    )
    if applied:
        for alert in pending_alerts:
            _add_alert(alert)


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle incident creation — security breach freezes affected terminal."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    incident_type = payload.get("type")
    if incident_type != "security_breach":
        return
    incident_id = payload.get("incident_id")
    if not incident_id:
        return

    location = payload.get("location", "")
    terminal = _extract_terminal_from_location(location)

    if terminal:
        _state.security_breaches[incident_id] = terminal
        _state.security.freeze_terminal(terminal)
        _state.active_incidents[terminal] = True
        logger.warning("Security breach — terminal %s frozen", terminal)


async def _on_incident_status_changed(payload: dict, sim_time: datetime) -> None:
    """Resume frozen zones when incident is resolved."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    new_status = payload.get("new_status") or payload.get("status")
    if new_status != "resolved":
        return

    incident_id = payload.get("incident_id")
    if not incident_id or (payload.get("type") != "security_breach" and incident_id not in _state.security_breaches):
        return
    location = payload.get("location", "")
    terminal = _state.security_breaches.pop(incident_id, _extract_terminal_from_location(location))
    if terminal and terminal not in _state.security_breaches.values():
        _state.security.unfreeze_terminal(terminal)
        _state.active_incidents[terminal] = False
        logger.info("Security resumed — terminal %s unfrozen", terminal)


def _extract_terminal_from_location(location: str) -> str | None:
    """Extract terminal from explicit location tokens like terminal-B or security-C."""
    if not location:
        return None

    normalized = str(location).strip().upper()
    for token in ("TERMINAL-", "SECURITY-", "AIRSIDE-", "CHECK-IN-"):
        if normalized.startswith(token):
            suffix = normalized[len(token):]
            if suffix in ("A", "B", "C"):
                return suffix

    if normalized in ("A", "B", "C"):
        return normalized

    return None


async def _on_weather_changed(payload: dict, sim_time: datetime) -> None:
    """Update cached weather category."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    cat = payload.get("category") or payload.get("new_category")
    if cat:
        _state.weather_category = cat


async def _on_baggage_status_changed(payload: dict, sim_time: datetime, event_id: str = "") -> None:
    """Track baggage collection for arrival passengers — atomic location write (G1-c).

    Carousel re-location writes commit in ONE ``apply_changes_atomic`` transaction
    with durable inbox dedup on the input ``event_id``; the derived in-memory
    carousel set and zone-density counters update only after a successful,
    non-deduped commit. ``collected`` carries no domain write (in-memory tracking
    only, rebuildable), so it stays an in-memory set update.
    """
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    new_status = payload.get("new_status")
    if new_status not in ("on_carousel", "collected"):
        return

    passenger_id = payload.get("passenger_id")
    flight_id = payload.get("flight_id")

    if new_status == "on_carousel":
        scan_zone = str(payload.get("scan_zone") or "")
        if not scan_zone.startswith("arrival-belt-"):
            return
        belt_num = scan_zone.rsplit("-", 1)[-1]
        carousel_zone = f"carousel-{belt_num}"

        # Track flight→carousel mapping so late-arriving passengers get assigned
        # (pure in-memory, idempotent on redelivery).
        already_mapped = bool(flight_id) and _state.flight_carousel_zone.get(flight_id) == carousel_zone
        if flight_id:
            _state.flight_carousel_zone[flight_id] = carousel_zone

        move_ids: list[str] = []
        if passenger_id and passenger_id not in _state.passengers_at_carousel:
            # Departure bag with known passenger
            move_ids.append(passenger_id)
        elif not passenger_id and flight_id:
            # Arrival bag — no CARRIES relationship; move all baggage_claim
            # passengers on this flight to the carousel zone. Once the flight is
            # mapped to this carousel, passengers reaching baggage claim later
            # are placed by the tick (_assign_carousels), so repeating the
            # flight read + write for every further bag (~150 per flight) only
            # finds passengers that are already there.
            if already_mapped:
                return
            try:
                pax_list = await get_passengers_by_flight(flight_id)
            except Exception:
                pax_list = []
            for pax in pax_list:
                pid = pax["id"]
                if pax.get("status") == "baggage_claim" and pid not in _state.passengers_at_carousel:
                    move_ids.append(pid)

        if move_ids:
            location_updates = [{"id": pid, "zone": carousel_zone} for pid in move_ids]
            applied = await apply_changes_atomic(
                event_id, sim_time, location_updates=location_updates,
            )
            if applied:
                for pid in move_ids:
                    move_passenger("baggage-claim", carousel_zone)
                    _state.passengers_at_carousel.add(pid)

    if new_status == "collected" and passenger_id:
        _state.baggage_collected.add(passenger_id)


def _add_alert(alert: dict) -> None:
    """Add alert to in-memory history."""
    _state = current_tick.get().state if current_tick.get() else globals()["_state"]
    _state.add_alert(alert)
