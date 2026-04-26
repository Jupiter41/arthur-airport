"""Kafka consumer for passenger-service.

Consumes: SimClockTick, FlightStatusChanged, FlightGateAssigned,
          FlightCancelled, IncidentCreated, BaggageStatusChanged (collected).
On each tick: advance departure FSM, drain security queues, check congestion,
              update ML pipeline, evaluate connections.
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from _common.idempotency import IdempotencyTracker
from _common.consumer_health import ConsumerHealthTracker

from confluent_kafka import Consumer

from db.neo4j import (
    get_passengers_by_status,
    get_passengers_by_flight,
    update_passenger_status,
    bulk_update_status,
    bulk_set_dwell,
    set_connection_risk,
    get_connecting_passengers,
    get_departure_flights_in_window,
    get_status_counts,
    update_passenger_location,
)
from kafka.producer import (
    emit_passenger_status_changed,
    emit_passenger_alert,
    emit_congestion_detected,
    emit_bulk_state_snapshot,
    set_tick_batch_mode,
    set_bulk_mode,
)
from ml.congestion import check_congestion
from ml.features import build_features
from ml.inference import load_models, predict
from ml.training import add_training_row, maybe_flush, maybe_retrain
from services.connections import evaluate_connecting_passengers
from services.security import SecuritySystem
from services.spatial import walking_time_to_gate
from services.state_machine import (
    get_terminal_for_flight,
    sample_dwell_minutes,
    should_move_to_at_gate,
    should_move_to_security_queue,
    should_start_boarding,
    should_move_to_baggage_claim,
    should_clear_customs,
    should_depart_airport,
    is_international_flight,
    zone_for_status,
    BOARDING_RATE_PAX_PER_MIN,
)
from services.zones import move_passenger, remove_passenger
from metrics import (
    passengers_in_airport as m_pax_in_airport,
    security_queue_depth as m_sec_queue_depth,
    security_wait_minutes as m_sec_wait,
    security_lanes_open as m_sec_lanes,
    connections_at_risk as m_connections_at_risk,
    connections_missed_total as m_connections_missed,
    passenger_alerts_total as m_passenger_alerts,
    envelope_invalid_total as m_envelope_invalid,
)

logger = logging.getLogger(__name__)


# ── Class-based state holder ────────────────────────────────


class PassengerConsumerState:
    """Holds all mutable runtime state for the passenger consumer."""

    MAX_PROCESSED = 20000
    MAX_ALERTS = 200

    def __init__(self) -> None:
        self.sim_time: datetime | None = None
        self.last_tick_sim_time: datetime | None = None
        self.sim_day: int = 0
        self.security = SecuritySystem()
        self.weather_category: str = "CAVOK"
        self.active_incidents: dict[str, bool] = {"A": False, "B": False, "C": False}
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
        self.noshow_drawn_flights: set[str] = set()  # flights that had no-show draw
        self.noshow_rate: float = 0.03  # 2-4% no-show rate (default 3%)

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


async def rebuild_security_from_neo4j() -> None:
    """Rebuild in-memory security queues from Neo4j on startup.

    Loads all passengers currently in security_queue status and enqueues
    them into the in-memory SecuritySystem so queue_depth and wait_minutes
    are accurate immediately after a restart.
    """
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


async def load_spatial_positions() -> None:
    """Load gate positions and walking zones from Neo4j for walking time computation."""
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
    _state.ws_broadcast = fn


def get_sim_time() -> datetime | None:
    return _state.sim_time


def get_security() -> SecuritySystem:
    return _state.security


def get_alerts() -> list[dict]:
    return _state.alerts


def get_at_risk_connections() -> list[dict]:
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
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })


async def run_consumer() -> None:
    """Main consumer loop — runs as background asyncio task."""
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

    loop = asyncio.get_event_loop()
    logger.info(
        "Kafka consumer started (topics: sim.clock, flights.events, incidents.events, baggage.events, weather.events)"
    )

    try:
        while _consumer_running:
            # Batch-consume to allow tick skipping when behind
            msgs = await loop.run_in_executor(None, lambda: _consumer.consume(500, timeout=1.0))
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

            _consumer_health.mark_message()
    finally:
        _consumer.close()
        _consumer_running = False
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
    """Route events to handlers based on event_type."""
    validated = _validate_envelope(envelope)
    if validated is None:
        return
    event_type, sim_time, payload = validated

    # Idempotency check (skip for clock ticks)
    if event_type != "SimClockTick":
        event_id = envelope.get("event_id", "")
        if _state.check_idempotency(event_id):
            return

    match event_type:
        case "SimClockTick":
            await _on_clock_tick(payload, sim_time)
        case "FlightStatusChanged":
            await _on_flight_status_changed(payload, sim_time)
        case "FlightGateAssigned":
            await _on_flight_gate_assigned(payload, sim_time)
        case "FlightCancelled":
            await _on_flight_cancelled(payload, sim_time)
        case "IncidentCreated":
            await _on_incident_created(payload, sim_time)
        case "IncidentStatusChanged":
            await _on_incident_status_changed(payload, sim_time)
        case "WeatherStateChanged":
            await _on_weather_changed(payload, sim_time)
        case "BaggageStatusChanged":
            await _on_baggage_status_changed(payload, sim_time)
        case _:
            pass


_tick_counter: int = 0


async def _warm_start_departures(sim_time: datetime) -> None:
    """Pre-advance departure passengers for flights near departure at sim start.

    At sim start all departure passengers are 'booked'.  For flights departing
    within the next 2 hours, advance passengers to realistic pipeline states
    as if the airport had already been operating.  This prevents the startup
    burst from cascading into mass cancellations.
    """
    cutoff = (sim_time + timedelta(hours=2)).isoformat()
    try:
        pax_list = await get_passengers_by_status("booked", scheduled_before=cutoff)
    except Exception as e:
        logger.error("Warm-start query failed: %s", e)
        return

    flights: dict[str, list[dict]] = {}
    for pax in pax_list:
        fid = pax.get("flight_id") or ""
        flights.setdefault(fid, []).append(pax)

    total_advanced = 0
    for flight_id, pax_group in flights.items():
        if not pax_group:
            continue
        sample = pax_group[0]
        if sample.get("direction", "departure") != "departure":
            continue
        scheduled = sample.get("scheduled_time") or sample.get("estimated_time")
        if not scheduled:
            continue
        try:
            sched_dt = datetime.fromisoformat(str(scheduled)).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue

        minutes_until = (sched_dt - sim_time).total_seconds() / 60
        terminal = get_terminal_for_flight(
            sample.get("gate_id"), sample.get("terminal_id"), flight_id,
        )
        gate_id = sample.get("gate_id")
        ids = [p["id"] for p in pax_group]

        if minutes_until <= 0:
            # Past departure → boarded
            zone = zone_for_status("boarded", terminal, gate_id)
            await bulk_update_status(ids, "boarded", zone, sim_time)
        elif minutes_until <= 50:
            # Departs in <50 min → at gate (GATE_OPEN_MINUTES)
            zone = zone_for_status("at_gate", terminal, gate_id)
            await bulk_update_status(ids, "at_gate", zone, sim_time)
        elif minutes_until <= 90:
            # Departs in 50-90 min → airside (through security already)
            zone = f"airside-{terminal}"
            await bulk_update_status(ids, "airside", zone, sim_time)
            dwell_items = [(pid, 0) for pid in ids]
            await bulk_set_dwell(dwell_items)
        elif minutes_until <= 120:
            # Departs in 90-120 min → checked in (arriving at airport)
            zone = f"check-in-{terminal}"
            await bulk_update_status(ids, "checked_in", zone, sim_time)
        else:
            continue

        total_advanced += len(ids)

    logger.info("Warm-start: advanced %d departure passengers to pipeline states", total_advanced)


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    """Main tick handler — advance all passenger state machines."""
    global _tick_counter
    _tick_counter += 1
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

    set_tick_batch_mode(True)
    try:
        # Warm-start: pre-advance early departure passengers on first tick
        if _tick_counter == 1:
            await _warm_start_departures(sim_time)

        # === Critical path (every tick) ===

        # 1. ML feature cache (reduced frequency in BULK mode)
        ml_interval = 20 if is_bulk else 5
        if _tick_counter % ml_interval == 0:
            await _ml_tick(sim_time)

        # 2. Move booked passengers to checked_in at T-120
        await _advance_booked_to_checkin(sim_time, delta_minutes)

        # 3. Move checked_in passengers to security_queue when check-in closes
        await _advance_checkin_to_security(sim_time, delta_minutes)

        # 4. Drain security queues
        await _drain_security_queues(sim_time, delta_minutes)

        # 5. Move airside passengers to at_gate when dwells complete
        await _advance_airside_to_gate(sim_time)

        # 6. Board passengers at gates
        await _advance_boarding(sim_time, delta_minutes)

        # 7. Advance arrival flow
        await _advance_arrivals(sim_time)

        # === Non-critical path (reduced frequency) ===

        # 8. Check connections (reduced in BULK mode)
        conn_interval = 30 if is_bulk else 10
        if _tick_counter % conn_interval == 0:
            await _check_connections(sim_time)

        # 9. Check congestion (reduced in BULK mode)
        congestion_interval = 20 if is_bulk else 5
        if _tick_counter % congestion_interval == 0:
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
        if _tick_counter % 30 == 0:
            retrained = await maybe_retrain(_state.sim_day)
            if retrained:
                load_models()
            maybe_flush(sim_time)

        # 11. Update Prometheus gauges (reduced in BULK mode)
        gauge_interval = 20 if is_bulk else 5
        if _tick_counter % gauge_interval == 0:
            try:
                status_counts = await get_status_counts()
                for status, count in status_counts.items():
                    m_pax_in_airport.labels(status=status).set(count)
            except Exception:
                pass

        # Security gauges are cheap (in-memory), update every tick
        for terminal in ("A", "B", "C"):
            cp = _state.security.checkpoints.get(terminal)
            if cp:
                m_sec_queue_depth.labels(terminal=terminal).set(cp.queue_depth)
                m_sec_wait.labels(terminal=terminal).set(round(cp.wait_minutes(0), 1))
                m_sec_lanes.labels(terminal=terminal).set(cp.lanes_open)

        # 12. BULK mode: emit periodic BulkStateSnapshot
        if is_bulk:
            await _maybe_emit_bulk_snapshot(sim_time)

    except Exception as e:
        logger.error("Error in clock tick processing: %s", e, exc_info=True)
    finally:
        set_tick_batch_mode(False)


BULK_SNAPSHOT_INTERVAL_SIM_MIN = int(os.getenv("BULK_SNAPSHOT_INTERVAL_MIN", "60"))


async def _maybe_emit_bulk_snapshot(sim_time: datetime) -> None:
    """Emit a BulkStateSnapshot summarising passenger state (BULK mode only).

    Triggered every ``BULK_SNAPSHOT_INTERVAL_SIM_MIN`` sim-minutes.
    Also triggers on mode transition from BULK → FAST/REALTIME.
    """
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


CHECKIN_OPEN_MINUTES = 120  # Passengers arrive at check-in T-120 min before departure


async def _advance_booked_to_checkin(sim_time: datetime, delta_minutes: int = 1) -> None:
    """Move booked passengers to checked_in at T-120 (check-in opens).

    Batched: up to MAX_CHECKIN_PER_TICK passengers per tick to simulate
    gradual arrival at the airport.  Scales with ``delta_minutes`` so that
    high-speed tick skipping doesn't reduce throughput.
    """
    MAX_CHECKIN_PER_TICK = 200 * delta_minutes

    # Only query booked passengers whose flights depart within next 3 hours
    cutoff = (sim_time + timedelta(hours=3)).isoformat()
    try:
        pax_list = await get_passengers_by_status("booked", scheduled_before=cutoff)
    except Exception as e:
        logger.error("Failed to get booked passengers: %s", e)
        return

    # Group by flight
    flights: dict[str, list[dict]] = {}
    for pax in pax_list:
        fid = pax.get("flight_id") or ""
        flights.setdefault(fid, []).append(pax)

    total_moved = 0

    for flight_id, pax_group in flights.items():
        if not pax_group:
            continue
        if total_moved >= MAX_CHECKIN_PER_TICK:
            break
        sample = pax_group[0]
        scheduled = sample.get("scheduled_time") or sample.get("estimated_time")
        if not scheduled:
            continue
        direction = sample.get("direction", "departure")
        if direction != "departure":
            continue

        try:
            sched_dt = datetime.fromisoformat(str(scheduled)).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue

        if sim_time < sched_dt - timedelta(minutes=CHECKIN_OPEN_MINUTES):
            continue

        terminal = get_terminal_for_flight(
            sample.get("gate_id"), sample.get("terminal_id"), flight_id
        )
        new_zone = f"check-in-{terminal}"

        remaining = MAX_CHECKIN_PER_TICK - total_moved
        batch = pax_group[:remaining]
        ids = [p["id"] for p in batch]
        await bulk_update_status(ids, "checked_in", new_zone, sim_time)
        for pax in batch:
            move_passenger(None, new_zone)
            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status="booked",
                new_status="checked_in",
                location_zone=new_zone,
                sim_time=sim_time,
                flight_id=flight_id,
                flight_number=pax.get("flight_number"),
            )
        total_moved += len(batch)


async def _advance_checkin_to_security(sim_time: datetime, delta_minutes: int = 1) -> None:
    """Move checked_in passengers to security_queue at T-45.

    Batched: moves up to MAX_CHECKIN_TO_SECURITY_PER_TICK passengers per tick
    across all flights to prevent security queue overload.  Scales with
    ``delta_minutes`` so high-speed tick skipping doesn't reduce throughput.
    """
    MAX_CHECKIN_TO_SECURITY_PER_TICK = 80 * delta_minutes  # ~80 pax/min across all terminals

    # Only query checked_in passengers whose flights depart within next 2 hours
    cutoff = (sim_time + timedelta(hours=2)).isoformat()
    try:
        pax_list = await get_passengers_by_status("checked_in", scheduled_before=cutoff)
    except Exception as e:
        logger.error("Failed to get checked_in passengers: %s", e)
        return

    # Group by flight for batched processing
    flights: dict[str, list[dict]] = {}
    for pax in pax_list:
        fid = pax.get("flight_id") or ""
        flights.setdefault(fid, []).append(pax)

    total_moved = 0

    for flight_id, pax_group in flights.items():
        if not pax_group:
            continue
        if total_moved >= MAX_CHECKIN_TO_SECURITY_PER_TICK:
            break

        # Use first passenger's flight info (same flight)
        sample = pax_group[0]
        scheduled = sample.get("scheduled_time") or sample.get("estimated_time")
        if not scheduled:
            continue

        # Only departure flights
        direction = sample.get("direction", "departure")
        if direction != "departure":
            continue

        if not should_move_to_security_queue(sim_time, scheduled):
            continue

        terminal = get_terminal_for_flight(
            sample.get("gate_id"), sample.get("terminal_id"), flight_id
        )

        ids_to_move = []
        for pax in pax_group:
            if total_moved >= MAX_CHECKIN_TO_SECURITY_PER_TICK:
                break
            pid = pax["id"]
            if pid in _state.security_enqueued:
                continue
            _state.security_enqueued.add(pid)
            is_sa = bool(pax.get("special_assistance"))
            _state.security.enqueue(terminal, pid, is_sa)
            ids_to_move.append(pid)
            total_moved += 1

        if ids_to_move:
            new_zone = f"security-{terminal}"
            await bulk_update_status(ids_to_move, "security_queue", new_zone, sim_time)

            for pax in pax_group:
                if pax["id"] in ids_to_move:
                    old_zone = pax.get("location_zone") or f"check-in-{terminal}"
                    move_passenger(old_zone, new_zone)
                    await emit_passenger_status_changed(
                        passenger_id=pax["id"],
                        name=pax.get("name", ""),
                        previous_status="checked_in",
                        new_status="security_queue",
                        location_zone=new_zone,
                        sim_time=sim_time,
                        flight_id=flight_id,
                        flight_number=pax.get("flight_number"),
                    )


async def _drain_security_queues(sim_time: datetime, delta_minutes: int = 1) -> None:
    """Drain security checkpoints and move passengers to airside."""
    # Periodic DB sync (every 60 ticks) to catch missed events/restarts.
    # On normal ticks, in-memory queues are authoritative.
    if _tick_counter % 60 == 0:
        await _sync_security_from_db()

    forecast_queues = _get_forecast_queues(sim_time)
    drained = _state.security.drain_all(forecast_queues, delta_minutes)

    for terminal, (main_drained, sa_drained) in drained.items():
        all_drained = main_drained + sa_drained
        if not all_drained:
            continue

        new_zone = f"airside-{terminal}"
        default_old_zone = f"security-{terminal}"

        # Batch: update status + set dwell in two UNWIND queries (not N individual writes)
        await bulk_update_status(all_drained, "airside", new_zone, sim_time)
        # SA passengers skip dwell and route directly to gate (spec §3)
        sa_set = set(sa_drained)
        dwell_items = [(pid, 0 if pid in sa_set else sample_dwell_minutes()) for pid in all_drained]
        await bulk_set_dwell(dwell_items)

        for pid in all_drained:
            move_passenger(default_old_zone, new_zone)
            await emit_passenger_status_changed(
                passenger_id=pid,
                name="",
                previous_status="security_queue",
                new_status="airside",
                location_zone=new_zone,
                sim_time=sim_time,
            )


async def _sync_security_from_db() -> dict[str, str]:
    """Reconcile in-memory security queues against Neo4j before drain.

    This prevents stuck passengers when the service restarts mid-simulation
    or if events were missed.
    """
    try:
        pax_list = await get_passengers_by_status("security_queue")
    except Exception as e:
        logger.error("Failed to sync security queues from Neo4j: %s", e)
        return {}

    zone_by_pid: dict[str, str] = {}
    security_ids: set[str] = set()
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


def _build_context_features(terminal: str, sim_time: datetime) -> dict:
    """Build feature vector for a terminal."""
    # Compute adjacent congestion from security system
    adjacent = {}
    for t in ("A", "B", "C"):
        if t != terminal:
            wait = _state.security.get(t).wait_minutes(0)
            adjacent[t] = wait > 20
    adjacent[terminal] = False

    # Use cached flight/pax data (updated in _ml_tick on every tick)
    load_factor = _state.load_factor_sum / _state.load_factor_count if _state.load_factor_count > 0 else 0.8

    return build_features(
        terminal=terminal,
        sim_time=sim_time,
        weather_category=_state.weather_category,
        flights_next_90=_state.cached_flights_next_90,
        pax_next_90=_state.cached_pax_next_90,
        load_factor_today=load_factor,
        incident_active=_state.active_incidents,
        adjacent_congested=adjacent,
    )


async def _advance_airside_to_gate(sim_time: datetime) -> None:
    """Move airside passengers to at_gate when dwell completes and gate opens."""
    # Time-window: only passengers with flights departing within next 2 hours
    cutoff = (sim_time + timedelta(hours=2)).isoformat()
    try:
        pax_list = await get_passengers_by_status("airside", scheduled_before=cutoff)
    except Exception as e:
        logger.error("Failed to get airside passengers: %s", e)
        return

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

            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status="airside",
                new_status="at_gate",
                location_zone=new_zone,
                sim_time=sim_time,
                flight_id=pax.get("flight_id"),
                flight_number=pax.get("flight_number"),
            )
        except Exception as e:
            logger.warning("Skipping invalid airside passenger record %s: %s", pax.get("id"), e)
            continue

    for zone, ids in ids_by_zone.items():
        await bulk_update_status(ids, "at_gate", zone, sim_time)


async def _advance_boarding(sim_time: datetime, delta_minutes: int = 1) -> None:
    """Board passengers at_gate → boarded, progressive at BOARDING_RATE."""
    # Time-window: only passengers with flights departing within next 1.5 hours
    cutoff = (sim_time + timedelta(hours=1, minutes=30)).isoformat()
    try:
        pax_list = await get_passengers_by_status("at_gate", scheduled_before=cutoff)
    except Exception as e:
        logger.error("Failed to get at_gate passengers: %s", e)
        return

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

        if not estimated:
            continue

        # P1-2-3: No-show draw — once per flight when boarding starts
        if flight_id not in _state.noshow_drawn_flights:
            boarding_eligible = (
                should_start_boarding(sim_time, estimated, flight_status)
                or flight_status in ("airborne", "departed", "taxiing")
            )
            if boarding_eligible:
                _state.noshow_drawn_flights.add(flight_id)
                noshow_ids: set[str] = set()
                noshow_rate = _state.noshow_rate
                for pax in pax_group:
                    if random.random() < noshow_rate:
                        noshow_ids.add(pax["id"])
                if noshow_ids:
                    gate_id = sample.get("gate_id")
                    terminal = get_terminal_for_flight(gate_id, sample.get("terminal_id"), flight_id)
                    for pax in pax_group:
                        if pax["id"] in noshow_ids:
                            old_zone = pax.get("location_zone") or ""
                            await update_passenger_status(pax["id"], "departed_airport", "no-show", sim_time)
                            remove_passenger(old_zone)
                            await emit_passenger_status_changed(
                                passenger_id=pax["id"],
                                name=pax.get("name", ""),
                                previous_status="at_gate",
                                new_status="departed_airport",
                                location_zone="no-show",
                                sim_time=sim_time,
                                flight_id=flight_id,
                                flight_number=pax.get("flight_number"),
                            )
                    pax_group = [p for p in pax_group if p["id"] not in noshow_ids]
                    logger.info("No-shows on flight %s: %d passengers", flight_id, len(noshow_ids))

        # If flight is already airborne/departed, bulk-board all remaining pax
        if flight_status in ("airborne", "departed", "taxiing"):
            to_board = pax_group
        elif should_start_boarding(sim_time, estimated, flight_status):
            # Board up to BOARDING_RATE × delta passengers per tick
            to_board = pax_group[:boarding_rate]
        else:
            continue

        ids = [p["id"] for p in to_board]
        gate_id = sample.get("gate_id")
        terminal = get_terminal_for_flight(
            gate_id,
            sample.get("terminal_id"),
            flight_id,
        )
        new_zone = zone_for_status("boarded", terminal, gate_id)

        await bulk_update_status(ids, "boarded", new_zone, sim_time)

        for pax in to_board:
            old_zone = pax.get("location_zone") or f"gate-{gate_id}"
            # Boarded passengers leave terminal waiting areas.
            remove_passenger(old_zone)

            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status="at_gate",
                new_status="boarded",
                location_zone=new_zone,
                sim_time=sim_time,
                flight_id=flight_id,
                flight_number=pax.get("flight_number"),
            )


async def _advance_arrivals(sim_time: datetime) -> None:
    """Advance arrival passengers: deplaning → [customs →] baggage_claim → departed_airport."""
    # deplaning → customs (international) or baggage_claim (domestic)
    try:
        deplaning = await get_passengers_by_status("deplaning")
    except Exception:
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
        await bulk_update_status(ids, "customs", new_zone, sim_time)
        for pax in to_customs:
            old_zone = pax.get("location_zone") or "arrivals-hall"
            move_passenger(old_zone, new_zone)
            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status="deplaning",
                new_status="customs",
                location_zone=new_zone,
                sim_time=sim_time,
                flight_id=pax.get("flight_id"),
                flight_number=pax.get("flight_number"),
            )

    if to_baggage_claim:
        ids = [p["id"] for p in to_baggage_claim]
        new_zone = "baggage-claim"
        await bulk_update_status(ids, "baggage_claim", new_zone, sim_time)
        for pax in to_baggage_claim:
            old_zone = pax.get("location_zone") or "arrivals-hall"
            move_passenger(old_zone, new_zone)
            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status="deplaning",
                new_status="baggage_claim",
                location_zone=new_zone,
                sim_time=sim_time,
                flight_id=pax.get("flight_id"),
                flight_number=pax.get("flight_number"),
            )
        # Assign to carousel if bags already on carousel for this flight
        for pax in to_baggage_claim:
            fid = pax.get("flight_id")
            pid = pax["id"]
            carousel_zone = _state.flight_carousel_zone.get(fid) if fid else None
            if not carousel_zone and fid:
                # Deterministic fallback: derive carousel from gate/terminal
                # A→1-2, B→3-4, C→5-6 (matches baggage-service logic)
                gate = pax.get("gate_id") or ""
                terminal = pax.get("terminal_id") or (gate[0].upper() if gate else "A")
                carousel_map = {"A": [1, 2], "B": [3, 4], "C": [5, 6]}
                carousels = carousel_map.get(terminal, [1, 2])
                carousel_num = carousels[hash(fid) % len(carousels)]
                carousel_zone = f"carousel-{carousel_num}"
            if carousel_zone and pid not in _state.passengers_at_carousel:
                move_passenger("baggage-claim", carousel_zone)
                _state.passengers_at_carousel.add(pid)
                await update_passenger_location(pid, carousel_zone)

    # customs → baggage_claim
    try:
        in_customs = await get_passengers_by_status("customs")
    except Exception:
        in_customs = []

    customs_to_bc: list[dict] = []
    for pax in in_customs:
        customs_at = pax.get("customs_at")
        if should_clear_customs(sim_time, customs_at):
            customs_to_bc.append(pax)

    if customs_to_bc:
        ids = [p["id"] for p in customs_to_bc]
        new_zone = "baggage-claim"
        await bulk_update_status(ids, "baggage_claim", new_zone, sim_time)
        for pax in customs_to_bc:
            old_zone = pax.get("location_zone") or "customs"
            move_passenger(old_zone, new_zone)
            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status="customs",
                new_status="baggage_claim",
                location_zone=new_zone,
                sim_time=sim_time,
                flight_id=pax.get("flight_id"),
                flight_number=pax.get("flight_number"),
            )
        # Assign to carousel if bags already on carousel for this flight
        for pax in customs_to_bc:
            fid = pax.get("flight_id")
            pid = pax["id"]
            carousel_zone = _state.flight_carousel_zone.get(fid) if fid else None
            if not carousel_zone and fid:
                gate = pax.get("gate_id") or ""
                terminal = pax.get("terminal_id") or (gate[0].upper() if gate else "A")
                carousel_map = {"A": [1, 2], "B": [3, 4], "C": [5, 6]}
                carousels = carousel_map.get(terminal, [1, 2])
                carousel_num = carousels[hash(fid) % len(carousels)]
                carousel_zone = f"carousel-{carousel_num}"
            if carousel_zone and pid not in _state.passengers_at_carousel:
                move_passenger("baggage-claim", carousel_zone)
                _state.passengers_at_carousel.add(pid)
                await update_passenger_location(pid, carousel_zone)

    # baggage_claim → departed_airport
    try:
        claiming = await get_passengers_by_status("baggage_claim")
    except Exception:
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
        await bulk_update_status(ids, "departed_airport", new_zone, sim_time)
        for pax in to_depart:
            old_zone = pax.get("location_zone") or "baggage-claim"
            remove_passenger(old_zone)
            _state.baggage_collected.discard(pax["id"])
            _state.passengers_at_carousel.discard(pax["id"])
            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status="baggage_claim",
                new_status="departed_airport",
                location_zone=new_zone,
                sim_time=sim_time,
                flight_id=pax.get("flight_id"),
                flight_number=pax.get("flight_number"),
            )


async def _check_connections(sim_time: datetime) -> None:
    """Evaluate all connecting passengers and emit alerts on risk change."""
    try:
        conn_pax = await get_connecting_passengers()
    except Exception as e:
        logger.error("Failed to get connecting passengers: %s", e)
        return

    results = evaluate_connecting_passengers(conn_pax, sim_time, _state.gate_positions or None)
    new_at_risk = []

    for r in results:
        if r["risk_changed"]:
            new_risk = r["risk_level"]
            r["old_risk_level"]

            await set_connection_risk(r["id"], new_risk)

            if new_risk == "at_risk":
                m_passenger_alerts.labels(type="connection_at_risk").inc()
                alert = await emit_passenger_alert(
                    alert_type="connection_at_risk",
                    message=f"Connection at risk: {r['inbound_flight']} → {r['connection_flight']}",
                    sim_time=sim_time,
                    passenger_id=r["id"],
                    urgency="high",
                )
                _add_alert(alert)
                if _state.ws_broadcast:
                    await _state.ws_broadcast({"event_type": "PassengerAlert", "payload": alert})

            elif new_risk == "missed":
                m_connections_missed.inc()
                m_passenger_alerts.labels(type="connection_missed").inc()
                await update_passenger_status(
                    r["id"], "missed_connection",
                    "arrivals-hall", sim_time,
                )
                alert = await emit_passenger_alert(
                    alert_type="connection_missed",
                    message=f"Connection missed: {r['inbound_flight']} → {r['connection_flight']}",
                    sim_time=sim_time,
                    passenger_id=r["id"],
                    urgency="critical",
                )
                _add_alert(alert)
                if _state.ws_broadcast:
                    await _state.ws_broadcast({"event_type": "PassengerAlert", "payload": alert})

        if r["risk_level"] in ("at_risk", "watch"):
            new_at_risk.append(r)

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

async def _on_flight_status_changed(payload: dict, sim_time: datetime) -> None:
    """React to flight status changes — handle arrivals and delays."""
    new_status = payload.get("new_status")
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    # Arrival: flight at_gate → passengers deplaning
    if new_status == "at_gate" and payload.get("previous_status") in ("taxiing", "landed"):
        try:
            pax_list = await get_passengers_by_flight(flight_id)
        except Exception:
            pax_list = []

        gate_id = payload.get("gate_id")
        terminal = get_terminal_for_flight(gate_id, None, flight_id)
        new_zone = zone_for_status("deplaning", terminal, gate_id)

        # Collect eligible passengers and batch-update
        eligible = [
            pax for pax in pax_list
            if pax.get("status") in ("checked_in", "airborne", "booked", "boarded")
        ]
        if eligible:
            ids = [pax["id"] for pax in eligible]
            await bulk_update_status(ids, "deplaning", new_zone, sim_time)
            for pax in eligible:
                old_zone = pax.get("location_zone")
                move_passenger(old_zone, new_zone)
                await emit_passenger_status_changed(
                    passenger_id=pax["id"],
                    name=pax.get("name", ""),
                    previous_status=pax.get("status", "airborne"),
                    new_status="deplaning",
                    location_zone=new_zone,
                    sim_time=sim_time,
                    flight_id=flight_id,
                )

    # Departure: flight departed → boarded passengers become departed_airport
    if new_status == "departed" and payload.get("direction") == "departure":
        try:
            pax_list = await get_passengers_by_flight(flight_id)
        except Exception:
            pax_list = []

        eligible = [
            pax for pax in pax_list
            if pax.get("status") == "boarded"
        ]
        if eligible:
            ids = [pax["id"] for pax in eligible]
            await bulk_update_status(ids, "departed_airport", "departed", sim_time)
            for pax in eligible:
                old_zone = pax.get("location_zone") or ""
                remove_passenger(old_zone)
                await emit_passenger_status_changed(
                    passenger_id=pax["id"],
                    name=pax.get("name", ""),
                    previous_status="boarded",
                    new_status="departed_airport",
                    location_zone="departed",
                    sim_time=sim_time,
                    flight_id=flight_id,
                )
            logger.info("Flight %s departed: %d passengers departed_airport", flight_id, len(eligible))

    # Delay: update load factor
    if new_status == "delayed":
        payload.get("delay_minutes", 0)
        _state.load_factor_sum += 0.7  # delayed flights have lower effective load
        _state.load_factor_count += 1


async def _on_flight_gate_assigned(payload: dict, sim_time: datetime) -> None:
    """Issue gate change alerts to affected passengers."""
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


async def _on_flight_cancelled(payload: dict, sim_time: datetime) -> None:
    """Mark all on-flight passengers as disrupted."""
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    try:
        pax_list = await get_passengers_by_flight(flight_id)
    except Exception:
        return

    for pax in pax_list:
        if pax.get("status") not in ("boarded", "departed_airport"):
            old_zone = pax.get("location_zone")
            await update_passenger_status(
                pax["id"], "disrupted", old_zone or "arrivals-hall", sim_time,
            )
            await emit_passenger_status_changed(
                passenger_id=pax["id"],
                name=pax.get("name", ""),
                previous_status=pax.get("status", ""),
                new_status="disrupted",
                location_zone=old_zone or "arrivals-hall",
                sim_time=sim_time,
                flight_id=flight_id,
            )
            alert = await emit_passenger_alert(
                alert_type="flight_cancelled",
                message="Your flight has been cancelled.",
                sim_time=sim_time,
                passenger_id=pax["id"],
                flight_id=flight_id,
                urgency="critical",
            )
            _add_alert(alert)


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle incident creation — security breach freezes affected terminal."""
    incident_type = payload.get("type")
    if incident_type != "security_breach":
        return

    location = payload.get("location", "")
    terminal = _extract_terminal_from_location(location)

    if terminal:
        _state.security.freeze_terminal(terminal)
        _state.active_incidents[terminal] = True
        logger.warning("Security breach — terminal %s frozen", terminal)


async def _on_incident_status_changed(payload: dict, sim_time: datetime) -> None:
    """Resume frozen zones when incident is resolved."""
    new_status = payload.get("new_status") or payload.get("status")
    if new_status != "resolved":
        return

    location = payload.get("location", "")
    terminal = _extract_terminal_from_location(location)
    if terminal:
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
    cat = payload.get("category") or payload.get("new_category")
    if cat:
        _state.weather_category = cat


async def _on_baggage_status_changed(payload: dict, sim_time: datetime) -> None:
    """Track baggage collection for arrival passengers."""
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
        if flight_id:
            _state.flight_carousel_zone[flight_id] = carousel_zone

        if passenger_id and passenger_id not in _state.passengers_at_carousel:
            # Departure bag with known passenger
            move_passenger("baggage-claim", carousel_zone)
            _state.passengers_at_carousel.add(passenger_id)
            await update_passenger_location(passenger_id, carousel_zone)
        elif not passenger_id and flight_id:
            # Arrival bag — no CARRIES relationship; move all baggage_claim
            # passengers on this flight to the carousel zone.
            try:
                pax_list = await get_passengers_by_flight(flight_id)
            except Exception:
                pax_list = []
            for pax in pax_list:
                pid = pax["id"]
                if pax.get("status") == "baggage_claim" and pid not in _state.passengers_at_carousel:
                    move_passenger("baggage-claim", carousel_zone)
                    _state.passengers_at_carousel.add(pid)
                    await update_passenger_location(pid, carousel_zone)

    if new_status == "collected" and passenger_id:
        _state.baggage_collected.add(passenger_id)


def _add_alert(alert: dict) -> None:
    """Add alert to in-memory history."""
    _state.add_alert(alert)
