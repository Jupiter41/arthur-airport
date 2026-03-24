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
from datetime import datetime, timedelta

from confluent_kafka import Consumer

from db.neo4j import (
    get_passengers_by_status,
    get_passengers_by_flight,
    update_passenger_status,
    bulk_update_status,
    set_passenger_dwell,
    set_connection_risk,
    get_connecting_passengers,
    get_departure_flights_in_window,
    get_status_counts,
)
from kafka.producer import (
    emit_passenger_status_changed,
    emit_passenger_alert,
    emit_congestion_detected,
)
from ml.congestion import check_congestion
from ml.features import build_features
from ml.inference import is_model_trained, load_models, predict, get_feature_importance
from ml.training import add_training_row, maybe_flush, maybe_retrain
from services.connections import evaluate_connecting_passengers
from services.security import SecuritySystem
from services.state_machine import (
    get_terminal_from_gate,
    get_terminal_for_flight,
    sample_dwell_minutes,
    should_move_to_at_gate,
    should_move_to_security_queue,
    should_start_boarding,
    should_move_to_baggage_claim,
    should_depart_airport,
    zone_for_status,
    BOARDING_RATE_PAX_PER_MIN,
)
from services.zones import move_passenger, rebuild_from_neo4j, get_density
from metrics import (
    passengers_in_airport as m_pax_in_airport,
    security_queue_depth as m_sec_queue_depth,
    security_wait_minutes as m_sec_wait,
    security_lanes_open as m_sec_lanes,
    connections_at_risk as m_conn_at_risk,
    connections_missed_total as m_conn_missed,
    passenger_alerts_total as m_pax_alerts,
    zone_load_pct as m_zone_load,
)

logger = logging.getLogger(__name__)

_consumer: Consumer | None = None
_consumer_running = False

# --- State ---
_sim_time: datetime | None = None
_sim_day: int = 0
_security = SecuritySystem()

# Weather category cache (from weather.events)
_weather_category: str = "CAVOK"

# Active incidents per terminal
_active_incidents: dict[str, bool] = {"A": False, "B": False, "C": False}

# Load factor tracking
_load_factor_sum: float = 0.0
_load_factor_count: int = 0

# Alert history (in-memory, last 200)
_alerts: list[dict] = []
_MAX_ALERTS = 200

# At-risk connections cache
_at_risk_connections: list[dict] = []

# Idempotency
_processed_events: set[str] = set()
_MAX_PROCESSED = 20000

# Track which passengers have been enqueued in security
_security_enqueued: set[str] = set()

# Passengers we've already transitioned to airside
_airside_transitioned: set[str] = set()

# Baggage collected set — passenger IDs whose bags are collected
_baggage_collected: set[str] = set()

# WebSocket broadcast callback
_ws_broadcast = None


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
        _security.enqueue(terminal, pid, is_sa)
        _security_enqueued.add(pid)
        count += 1

    logger.info("Rebuilt security queues from Neo4j: %d passengers loaded", count)


def set_ws_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def get_sim_time() -> datetime | None:
    return _sim_time


def get_security() -> SecuritySystem:
    return _security


def get_alerts() -> list[dict]:
    return _alerts


def get_at_risk_connections() -> list[dict]:
    return _at_risk_connections


def is_consumer_running() -> bool:
    return _consumer_running


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
    _consumer.subscribe(["sim.clock", "flights.events", "incidents.events", "baggage.events"])
    _consumer_running = True

    loop = asyncio.get_event_loop()
    logger.info("Kafka consumer started (topics: sim.clock, flights.events, incidents.events, baggage.events)")

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
    event_id = envelope.get("event_id", "")
    event_type = envelope.get("event_type")
    payload = envelope.get("payload", {})

    # Idempotency check (skip for clock ticks)
    if event_type != "SimClockTick":
        if event_id in _processed_events:
            return
        _processed_events.add(event_id)
        if len(_processed_events) > _MAX_PROCESSED:
            excess = len(_processed_events) - _MAX_PROCESSED
            for _ in range(excess):
                _processed_events.pop()

    sim_time_str = envelope.get("sim_time")
    if not sim_time_str:
        logger.debug("Event dropped: missing sim_time")
        return
    try:
        sim_time = datetime.fromisoformat(sim_time_str).replace(tzinfo=None)
    except (ValueError, TypeError):
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


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    """Main tick handler — advance all passenger state machines."""
    global _sim_time, _sim_day
    _sim_time = sim_time
    _sim_day = payload.get("day_of_sim", 0)

    try:
        # 1. Move checked_in passengers to security_queue when check-in closes
        await _advance_checkin_to_security(sim_time)

        # 2. Drain security queues
        await _drain_security_queues(sim_time)

        # 3. Move airside passengers to at_gate when dwells complete
        await _advance_airside_to_gate(sim_time)

        # 4. Board passengers at gates
        await _advance_boarding(sim_time)

        # 5. Advance arrival flow
        await _advance_arrivals(sim_time)

        # 6. Check connections
        await _check_connections(sim_time)

        # 7. ML: collect training data + check congestion
        await _ml_tick(sim_time)

        # 8. Maybe retrain model
        retrained = await maybe_retrain(_sim_day)
        if retrained:
            load_models()

        # 9. Flush training data periodically
        maybe_flush(sim_time)

        # 10. Update Prometheus gauges
        try:
            status_counts = await get_status_counts()
            for status, count in status_counts.items():
                m_pax_in_airport.labels(status=status).set(count)
        except Exception:
            pass

        for terminal in ("A", "B", "C"):
            cp = _security.checkpoints.get(terminal)
            if cp:
                m_sec_queue_depth.labels(terminal=terminal).set(cp.queue_depth)
                m_sec_wait.labels(terminal=terminal).set(round(cp.wait_minutes(0), 1))
                m_sec_lanes.labels(terminal=terminal).set(cp.lanes_open)

    except Exception as e:
        logger.error("Error in clock tick processing: %s", e, exc_info=True)


async def _advance_checkin_to_security(sim_time: datetime) -> None:
    """Move checked_in passengers to security_queue at T-45."""
    try:
        pax_list = await get_passengers_by_status("checked_in")
    except Exception as e:
        logger.error("Failed to get checked_in passengers: %s", e)
        return

    # Group by flight for batched processing
    flights: dict[str, list[dict]] = {}
    for pax in pax_list:
        fid = pax.get("flight_id") or ""
        flights.setdefault(fid, []).append(pax)

    for flight_id, pax_group in flights.items():
        if not pax_group:
            continue

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
            pid = pax["id"]
            if pid in _security_enqueued:
                continue
            _security_enqueued.add(pid)
            is_sa = bool(pax.get("special_assistance"))
            _security.enqueue(terminal, pid, is_sa)
            ids_to_move.append(pid)

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


async def _drain_security_queues(sim_time: datetime) -> None:
    """Drain security checkpoints and move passengers to airside."""
    forecast_queues = _get_forecast_queues(sim_time)
    drained = _security.drain_all(forecast_queues)

    for terminal, (main_drained, sa_drained) in drained.items():
        all_drained = main_drained + sa_drained
        if not all_drained:
            continue

        new_zone = f"airside-{terminal}"
        old_zone = f"security-{terminal}"

        await bulk_update_status(all_drained, "airside", new_zone, sim_time)

        for pid in all_drained:
            move_passenger(old_zone, new_zone)
            # Sample dwell time for each passenger
            dwell = sample_dwell_minutes()
            await set_passenger_dwell(pid, dwell)

            await emit_passenger_status_changed(
                passenger_id=pid,
                name="",
                previous_status="security_queue",
                new_status="airside",
                location_zone=new_zone,
                sim_time=sim_time,
            )


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
            wait = _security.get(t).wait_minutes(0)
            adjacent[t] = wait > 20
    adjacent[terminal] = False

    # Simple flight/pax estimates from in-memory state
    flights_next = {"A": 0, "B": 0, "C": 0}
    pax_next: dict[str, float] = {"A": 0, "B": 0, "C": 0}

    # Use cached data if available (updated on tick)
    load_factor = _load_factor_sum / _load_factor_count if _load_factor_count > 0 else 0.8

    return build_features(
        terminal=terminal,
        sim_time=sim_time,
        weather_category=_weather_category,
        flights_next_90=flights_next,
        pax_next_90=pax_next,
        load_factor_today=load_factor,
        incident_active=_active_incidents,
        adjacent_congested=adjacent,
    )


async def _advance_airside_to_gate(sim_time: datetime) -> None:
    """Move airside passengers to at_gate when dwell completes and gate opens."""
    try:
        pax_list = await get_passengers_by_status("airside")
    except Exception as e:
        logger.error("Failed to get airside passengers: %s", e)
        return

    ids_by_zone: dict[str, list[str]] = {}

    for pax in pax_list:
        estimated = pax.get("estimated_time")
        if not estimated:
            continue

        dwell = pax.get("dwell_minutes")
        airside_at = pax.get("airside_at")

        if not should_move_to_at_gate(sim_time, estimated, dwell, airside_at):
            continue

        gate_id = pax.get("gate_id")
        terminal = get_terminal_from_gate(gate_id, pax.get("terminal_id"))
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

    for zone, ids in ids_by_zone.items():
        await bulk_update_status(ids, "at_gate", zone, sim_time)


async def _advance_boarding(sim_time: datetime) -> None:
    """Board passengers at_gate → boarded, progressive at BOARDING_RATE."""
    try:
        pax_list = await get_passengers_by_status("at_gate")
    except Exception as e:
        logger.error("Failed to get at_gate passengers: %s", e)
        return

    # Group by flight
    flights: dict[str, list[dict]] = {}
    for pax in pax_list:
        fid = pax.get("flight_id") or ""
        flights.setdefault(fid, []).append(pax)

    for flight_id, pax_group in flights.items():
        if not pax_group:
            continue
        sample = pax_group[0]
        estimated = sample.get("estimated_time")
        flight_status = sample.get("flight_status", "scheduled")

        if not estimated:
            continue

        # If flight is already airborne/departed, bulk-board all remaining pax
        if flight_status in ("airborne", "departed", "taxiing"):
            to_board = pax_group
        elif should_start_boarding(sim_time, estimated, flight_status):
            # Board up to BOARDING_RATE passengers per tick
            to_board = pax_group[:BOARDING_RATE_PAX_PER_MIN]
        else:
            continue

        ids = [p["id"] for p in to_board]
        gate_id = sample.get("gate_id")
        terminal = get_terminal_from_gate(gate_id, sample.get("terminal_id"))
        new_zone = zone_for_status("boarded", terminal, gate_id)

        await bulk_update_status(ids, "boarded", new_zone, sim_time)

        for pax in to_board:
            old_zone = pax.get("location_zone") or f"gate-{gate_id}"
            # Don't update zone density for boarded — they're leaving the airport
            move_passenger(old_zone, new_zone)

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
    """Advance arrival passengers: deplaning → baggage_claim → departed_airport."""
    # deplaning → baggage_claim
    try:
        deplaning = await get_passengers_by_status("deplaning")
    except Exception:
        deplaning = []

    for pax in deplaning:
        deplaning_at = pax.get("deplaning_at")
        if should_move_to_baggage_claim(sim_time, deplaning_at):
            old_zone = pax.get("location_zone") or "arrivals-hall"
            new_zone = "baggage-claim"
            await update_passenger_status(pax["id"], "baggage_claim", new_zone, sim_time)
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

    # baggage_claim → departed_airport
    try:
        claiming = await get_passengers_by_status("baggage_claim")
    except Exception:
        claiming = []

    for pax in claiming:
        pid = pax["id"]
        collected = pid in _baggage_collected
        bc_at = pax.get("baggage_claim_at")
        if should_depart_airport(sim_time, bc_at, collected):
            old_zone = pax.get("location_zone") or "baggage-claim"
            new_zone = "arrivals-hall"
            await update_passenger_status(pid, "departed_airport", new_zone, sim_time)
            move_passenger(old_zone, new_zone)
            _baggage_collected.discard(pid)
            await emit_passenger_status_changed(
                passenger_id=pid,
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
    global _at_risk_connections
    try:
        conn_pax = await get_connecting_passengers()
    except Exception as e:
        logger.error("Failed to get connecting passengers: %s", e)
        return

    results = evaluate_connecting_passengers(conn_pax, sim_time)
    new_at_risk = []

    for r in results:
        if r["risk_changed"]:
            new_risk = r["risk_level"]
            old_risk = r["old_risk_level"]

            await set_connection_risk(r["id"], new_risk)

            if new_risk == "at_risk":
                alert = await emit_passenger_alert(
                    alert_type="connection_at_risk",
                    message=f"Connection at risk: {r['inbound_flight']} → {r['connection_flight']}",
                    sim_time=sim_time,
                    passenger_id=r["id"],
                    urgency="high",
                )
                _add_alert(alert)
                if _ws_broadcast:
                    await _ws_broadcast({"event_type": "PassengerAlert", "payload": alert})

            elif new_risk == "missed":
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
                if _ws_broadcast:
                    await _ws_broadcast({"event_type": "PassengerAlert", "payload": alert})

        if r["risk_level"] in ("at_risk", "watch"):
            new_at_risk.append(r)

    _at_risk_connections = new_at_risk


async def _ml_tick(sim_time: datetime) -> None:
    """Collect training data and check congestion for all terminals."""
    # Update flight/pax data for features
    try:
        flight_data = await get_departure_flights_in_window(sim_time, 90)
    except Exception:
        flight_data = []

    flights_next_90: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    pax_next_90: dict[str, float] = {"A": 0, "B": 0, "C": 0}

    for fd in flight_data:
        tid = fd.get("terminal_id", "")
        terminal = str(tid)[-1] if tid and len(str(tid)) >= 3 else "A"
        if terminal in flights_next_90:
            flights_next_90[terminal] += fd.get("flight_count", 0)
            pax_next_90[terminal] += float(fd.get("total_pax", 0))

    for terminal in ("A", "B", "C"):
        cp = _security.get(terminal)

        # Build adjacent congestion
        adjacent = {}
        for t in ("A", "B", "C"):
            if t != terminal:
                wait = _security.get(t).wait_minutes(0)
                adjacent[t] = wait > 20
        adjacent[terminal] = False

        load_factor = _load_factor_sum / _load_factor_count if _load_factor_count > 0 else 0.8

        features = build_features(
            terminal=terminal,
            sim_time=sim_time,
            weather_category=_weather_category,
            flights_next_90=flights_next_90,
            pax_next_90=pax_next_90,
            load_factor_today=load_factor,
            incident_active=_active_incidents,
            adjacent_congested=adjacent,
        )

        # Add training row
        add_training_row(terminal, features, cp.queue_depth, sim_time)

        # Check congestion
        forecast = predict(terminal, features)
        wait = cp.wait_minutes(forecast or 0)

        if check_congestion(terminal, wait):
            event_payload = await emit_congestion_detected(
                terminal=terminal,
                wait_minutes=wait,
                queue_depth=cp.queue_depth,
                sim_time=sim_time,
            )
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "SecurityCongestionDetected",
                    "payload": event_payload,
                })


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

        for pax in pax_list:
            if pax.get("status") in ("checked_in", "airborne"):
                gate_id = payload.get("gate_id")
                terminal = get_terminal_from_gate(gate_id, None)
                new_zone = zone_for_status("deplaning", terminal, gate_id)
                old_zone = pax.get("location_zone")
                await update_passenger_status(pax["id"], "deplaning", new_zone, sim_time)
                if old_zone:
                    move_passenger(old_zone, new_zone)
                else:
                    move_passenger(None, new_zone)
                await emit_passenger_status_changed(
                    passenger_id=pax["id"],
                    name=pax.get("name", ""),
                    previous_status=pax.get("status", "airborne"),
                    new_status="deplaning",
                    location_zone=new_zone,
                    sim_time=sim_time,
                    flight_id=flight_id,
                )

    # Delay: update load factor
    if new_status == "delayed":
        delay_min = payload.get("delay_minutes", 0)
        global _load_factor_sum, _load_factor_count
        _load_factor_sum += 0.7  # delayed flights have lower effective load
        _load_factor_count += 1


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
            if _ws_broadcast:
                await _ws_broadcast({"event_type": "PassengerAlert", "payload": alert})


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
    # Extract terminal from location (e.g. "security-B" → "B")
    terminal = None
    for t in ("A", "B", "C"):
        if t.lower() in location.lower() or f"-{t}" in location:
            terminal = t
            break

    if terminal:
        _security.freeze_terminal(terminal)
        _active_incidents[terminal] = True
        logger.warning("Security breach — terminal %s frozen", terminal)


async def _on_incident_status_changed(payload: dict, sim_time: datetime) -> None:
    """Resume frozen zones when incident is resolved."""
    new_status = payload.get("new_status") or payload.get("status")
    if new_status != "resolved":
        return

    location = payload.get("location", "")
    for t in ("A", "B", "C"):
        if t.lower() in location.lower() or f"-{t}" in location:
            _security.unfreeze_terminal(t)
            _active_incidents[t] = False
            logger.info("Security resumed — terminal %s unfrozen", t)


async def _on_weather_changed(payload: dict, sim_time: datetime) -> None:
    """Update cached weather category."""
    global _weather_category
    cat = payload.get("category") or payload.get("new_category")
    if cat:
        _weather_category = cat


async def _on_baggage_status_changed(payload: dict, sim_time: datetime) -> None:
    """Track baggage collection for arrival passengers."""
    new_status = payload.get("new_status")
    if new_status != "collected":
        return
    passenger_id = payload.get("passenger_id")
    if passenger_id:
        _baggage_collected.add(passenger_id)


def _add_alert(alert: dict) -> None:
    """Add alert to in-memory history."""
    global _alerts
    _alerts.append(alert)
    if len(_alerts) > _MAX_ALERTS:
        _alerts = _alerts[-_MAX_ALERTS:]
