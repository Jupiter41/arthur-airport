"""Kafka consumer for baggage-service.

Consumes: SimClockTick, FlightStatusChanged, FlightCancelled,
          IncidentCreated (system_failure), IncidentStatusChanged
On each tick: advances conveyor pipeline, inducts new bags, screens items.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

from confluent_kafka import Consumer

from db.neo4j import (
    get_dropped_off_baggage_for_departures,
    update_baggage_status,
    flag_baggage,
    get_baggage_counts_by_status,
)
from kafka.producer import (
    emit_baggage_status_changed,
    emit_baggage_flagged,
)
from services.conveyor import (
    ConveyorSystem,
    BagInZone,
    ZONE_TO_STATUS,
)
from services.screening import screen_item
from services.offload import offload_flight_baggage
from metrics import (
    baggage_in_system as m_in_system,
    baggage_flagged_active as m_flagged,
    conveyor_zone_utilisation_pct as m_zone_util,
    conveyor_zone_status as m_zone_status,
    baggage_transitions_total as m_transitions,
    dangerous_goods_detected_total as m_dg_detected,
    screening_false_positives_total as m_false_pos,
    baggage_offloaded_total as m_offloaded,
)

logger = logging.getLogger(__name__)

_consumer: Consumer | None = None
_consumer_running = False

# --- State ---
_sim_time: datetime | None = None
_conveyor = ConveyorSystem()

# Idempotency: track processed event IDs
_processed_events: set[str] = set()
_MAX_PROCESSED = 20000

# Track bags already inducted (by baggage_id) to avoid re-induction
_inducted_bag_ids: set[str] = set()

# System failure impact mapping (from SKILL.md)
FAILURE_IMPACT: dict[str, list[str]] = {
    "conveyor-sorting": ["sorting-matrix"],
    "conveyor-induction-A": ["induction-A"],
    "conveyor-induction-B": ["induction-B"],
    "conveyor-induction-C": ["induction-C"],
    "power-A": ["induction-A", "screening-unit-1", "screening-unit-2"],
    "power-B": ["induction-B", "screening-unit-3", "screening-unit-4"],
    "power-C": ["induction-C", "screening-unit-5", "screening-unit-6"],
    "screening-unit-1": ["screening-unit-1"],
    "screening-unit-2": ["screening-unit-2"],
    "screening-unit-3": ["screening-unit-3"],
    "screening-unit-4": ["screening-unit-4"],
    "screening-unit-5": ["screening-unit-5"],
    "screening-unit-6": ["screening-unit-6"],
}

# WebSocket broadcast callback
_ws_broadcast = None


def set_ws_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def get_sim_time() -> datetime | None:
    return _sim_time


def get_conveyor() -> ConveyorSystem:
    return _conveyor


def is_consumer_running() -> bool:
    return _consumer_running


def stop_consumer() -> None:
    global _consumer_running
    _consumer_running = False


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "bag-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })


async def run_consumer() -> None:
    """Main consumer loop — runs as background asyncio task."""
    global _consumer, _consumer_running

    _consumer = _make_consumer()
    _consumer.subscribe(["sim.clock", "flights.events", "incidents.events"])
    _consumer_running = True

    loop = asyncio.get_event_loop()
    logger.info(
        "Kafka consumer started (topics: sim.clock, flights.events, incidents.events)"
    )

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

    # Idempotency check (skip for clock ticks — they're always unique)
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
        return
    try:
        sim_time = datetime.fromisoformat(sim_time_str)
        # Strip timezone to keep all comparisons naive (lesson from sprint-3)
        sim_time = sim_time.replace(tzinfo=None)
    except (ValueError, TypeError):
        return

    match event_type:
        case "SimClockTick":
            await _on_clock_tick(payload, sim_time)
        case "FlightStatusChanged":
            await _on_flight_status_changed(payload, sim_time)
        case "FlightCancelled":
            await _on_flight_cancelled(payload, sim_time)
        case "IncidentCreated":
            await _on_incident_created(payload, sim_time)
        case "IncidentStatusChanged":
            await _on_incident_status_changed(payload, sim_time)
        case _:
            pass


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    """Process SimClockTick — induct new bags and advance conveyor pipeline."""
    global _sim_time
    _sim_time = sim_time

    sim_time_str = sim_time.isoformat()

    # 1. Induct new bags: pull 'dropped_off' bags from Neo4j whose flights
    #    depart within ~90 minutes
    await _induct_new_bags(sim_time)

    # 2. Advance conveyor pipeline
    outputs = _conveyor.advance_tick(sim_time_str)

    # 3. Process zone outputs
    for zone_id, bags in outputs.items():
        for bag in bags:
            # Determine what happens to this bag now that it left the zone
            await _process_bag_exit(zone_id, bag, sim_time)

    # 4. Update Prometheus gauges
    try:
        counts = await get_baggage_counts_by_status()
        for status, count in counts.items():
            m_in_system.labels(status=status).set(count)
    except Exception:
        pass
    for z in _conveyor.get_zone_summary():
        m_zone_util.labels(zone_id=z["zone_id"]).set(z["utilisation_pct"])
        status_val = {"normal": 0, "degraded": 1, "offline": 2}.get(z["status"], 0)
        m_zone_status.labels(zone_id=z["zone_id"]).set(status_val)


async def _induct_new_bags(sim_time: datetime) -> None:
    """Pull dropped_off bags from Neo4j and add them to the induction belt.

    For flights that have already departed/are airborne, fast-track bags directly
    to 'in_hold' (they would have been processed before departure in reality).
    For flights still at the airport, feed bags into the conveyor normally.
    """
    try:
        bags = await get_dropped_off_baggage_for_departures(sim_time)
    except Exception as e:
        logger.error("Failed to query dropped_off bags: %s", e)
        return

    sim_time_str = sim_time.isoformat()

    # Limit batch size per tick to avoid blocking
    batch_count = 0
    MAX_BATCH_PER_TICK = 500

    for bag in bags:
        if batch_count >= MAX_BATCH_PER_TICK:
            break

        bag_id = bag["id"]

        # Skip if already inducted
        if bag_id in _inducted_bag_ids:
            continue

        flight_status = bag.get("flight_status", "scheduled")

        # For flights already departed/airborne — fast-track to in_hold
        if flight_status in ("departed", "airborne"):
            _inducted_bag_ids.add(bag_id)
            batch_count += 1
            await update_baggage_status(
                bag_id, "in_hold", "aircraft-hold", sim_time
            )
            await emit_baggage_status_changed(
                baggage_id=bag_id,
                tag=bag["tag"],
                previous_status="dropped_off",
                new_status="in_hold",
                scan_zone="aircraft-hold",
                sim_time=sim_time,
                passenger_id=bag.get("passenger_id"),
                flight_id=bag.get("flight_id"),
            )
            continue

        # For flights still at the airport: check 90-min window
        est_time_str = bag.get("estimated_time")
        if est_time_str:
            try:
                est_time = datetime.fromisoformat(str(est_time_str)).replace(tzinfo=None)
                if est_time - sim_time > timedelta(minutes=90):
                    continue
            except (ValueError, TypeError):
                pass

        _inducted_bag_ids.add(bag_id)
        batch_count += 1

        # Determine terminal from gate assignment (fallback to round-robin)
        terminal = "A"
        terminal_id = bag.get("terminal_id")
        if terminal_id and len(str(terminal_id)) >= 3:
            # terminal_id is like "T-A", "T-B", "T-C"
            terminal = str(terminal_id)[-1]
        if terminal not in "ABC":
            terminal = "A"

        bag_in_zone = BagInZone(
            baggage_id=bag_id,
            tag=bag["tag"],
            flight_id=bag.get("flight_id", ""),
            is_dg=bool(bag.get("is_dg")),
            dg_class=bag.get("dg_class"),
            passenger_id=bag.get("passenger_id"),
            terminal=terminal,
            entered_at=sim_time_str,
        )

        zone_id = _conveyor.induct_bag(bag_in_zone, sim_time_str)

        # Update Neo4j: status → inducted
        await update_baggage_status(bag_id, "inducted", zone_id, sim_time)

        # Emit BaggageStatusChanged event
        event_payload = await emit_baggage_status_changed(
            baggage_id=bag_id,
            tag=bag["tag"],
            previous_status="dropped_off",
            new_status="inducted",
            scan_zone=zone_id,
            sim_time=sim_time,
            passenger_id=bag.get("passenger_id"),
            flight_id=bag.get("flight_id"),
        )

        # Broadcast to WebSocket
        if _ws_broadcast:
            await _ws_broadcast({
                "event_type": "BaggageStatusChanged",
                "payload": event_payload,
            })


async def _process_bag_exit(
    from_zone: str, bag: BagInZone, sim_time: datetime
) -> None:
    """Handle a bag exiting a zone — screen, flag, or advance status."""
    sim_time_str = sim_time.isoformat()

    if from_zone.startswith("induction"):
        # Bag exits induction → now entering screening
        # The conveyor.advance_tick already placed it in a screening zone
        # Update Neo4j status
        screening_zone = _find_bag_current_zone(bag.baggage_id)
        if screening_zone:
            await update_baggage_status(
                bag.baggage_id, "screening", screening_zone, sim_time
            )
            event_payload = await emit_baggage_status_changed(
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                previous_status="inducted",
                new_status="screening",
                scan_zone=screening_zone,
                sim_time=sim_time,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "BaggageStatusChanged",
                    "payload": event_payload,
                })

    elif from_zone.startswith("screening"):
        # Bag exits screening → apply DG detection
        result = screen_item(bag.baggage_id, bag.is_dg, bag.dg_class)

        if result in ("flagged", "false_positive"):
            # Flag this bag
            flag_reason = (
                "dangerous_goods_detected"
                if result == "flagged"
                else "false_positive"
            )
            if result == "flagged":
                m_dg_detected.labels(dg_class=str(bag.dg_class or "unknown")).inc()
                m_flagged.inc(1)
            else:
                m_false_pos.inc()
            await flag_baggage(
                bag.baggage_id,
                flag_reason,
                from_zone,
                sim_time,
            )
            event_payload = await emit_baggage_flagged(
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                flag_reason=flag_reason,
                scan_zone=from_zone,
                sim_time=sim_time,
                dg_class=bag.dg_class,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "BaggageFlagged",
                    "payload": event_payload,
                })
            # Remove from sorting queue (it was already placed there by advance_tick)
            _conveyor.remove_bag_from_all_zones(bag.baggage_id)
        else:
            # Clear — bag moves to sorting (already placed by advance_tick)
            await update_baggage_status(
                bag.baggage_id, "sorting", "sorting-matrix", sim_time
            )
            event_payload = await emit_baggage_status_changed(
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                previous_status="screening",
                new_status="sorting",
                scan_zone="sorting-matrix",
                sim_time=sim_time,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "BaggageStatusChanged",
                    "payload": event_payload,
                })

    elif from_zone == "sorting-matrix":
        # Bag exits sorting → now in a make-up area (already placed by advance_tick)
        makeup_zone = _find_bag_current_zone(bag.baggage_id)
        if makeup_zone:
            await update_baggage_status(
                bag.baggage_id, "loaded", makeup_zone, sim_time
            )
            event_payload = await emit_baggage_status_changed(
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                previous_status="sorting",
                new_status="loaded",
                scan_zone=makeup_zone,
                sim_time=sim_time,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "BaggageStatusChanged",
                    "payload": event_payload,
                })

    elif from_zone.startswith("make-up"):
        # Bags exiting make-up are now fully loaded — remove from conveyor
        # They stay in "loaded" status until flight departs
        pass

    elif from_zone.startswith("arrival-belt"):
        # Bags exiting arrival belt → collected
        await update_baggage_status(
            bag.baggage_id, "collected", from_zone, sim_time
        )
        event_payload = await emit_baggage_status_changed(
            baggage_id=bag.baggage_id,
            tag=bag.tag,
            previous_status="on_carousel",
            new_status="collected",
            scan_zone=from_zone,
            sim_time=sim_time,
            passenger_id=bag.passenger_id,
            flight_id=bag.flight_id,
        )
        if _ws_broadcast:
            await _ws_broadcast({
                "event_type": "BaggageStatusChanged",
                "payload": event_payload,
            })


def _find_bag_current_zone(baggage_id: str) -> str | None:
    """Find which zone a bag is currently in (in-memory lookup)."""
    for zone_id, zone in _conveyor.get_all_zones().items():
        for bag in zone.queue:
            if bag.baggage_id == baggage_id:
                return zone_id
    return None


async def _on_flight_status_changed(payload: dict, sim_time: datetime) -> None:
    """React to flight status changes — handle departures and arrivals."""
    new_status = payload.get("new_status")
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    if new_status == "departed":
        # Flight departed — bags in 'loaded' → 'in_hold'
        from db.neo4j import get_flight_baggage
        bags = await get_flight_baggage(flight_id, statuses=["loaded"])
        for bag in bags:
            await update_baggage_status(
                bag["id"], "in_hold", "aircraft-hold", sim_time
            )
            event_payload = await emit_baggage_status_changed(
                baggage_id=bag["id"],
                tag=bag["tag"],
                previous_status="loaded",
                new_status="in_hold",
                scan_zone="aircraft-hold",
                sim_time=sim_time,
            )
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "BaggageStatusChanged",
                    "payload": event_payload,
                })

    elif new_status == "at_gate" and payload.get("previous_status") in (
        "taxiing", "landed"
    ):
        # Arrival flight reached gate — bags 'in_hold' → 'arrived' → 'on_carousel'
        from db.neo4j import get_flight_baggage
        bags = await get_flight_baggage(flight_id, statuses=["in_hold"])
        carousel = (hash(flight_id) % 6) + 1
        for bag in bags:
            await update_baggage_status(
                bag["id"], "arrived", f"arrival-belt-{carousel}", sim_time
            )

            # Place bag on arrival belt in conveyor
            bag_in_zone = BagInZone(
                baggage_id=bag["id"],
                tag=bag["tag"],
                flight_id=flight_id,
                is_dg=False,
                dg_class=None,
                passenger_id=None,
                terminal="A",
                entered_at=sim_time.isoformat(),
            )
            arrival_zone = _conveyor.get_zone(f"arrival-belt-{carousel}")
            if arrival_zone:
                arrival_zone.queue.append(bag_in_zone)

            await update_baggage_status(
                bag["id"], "on_carousel", f"arrival-belt-{carousel}", sim_time
            )
            from db.neo4j import set_baggage_carousel
            await set_baggage_carousel(bag["id"], carousel, sim_time)

            event_payload = await emit_baggage_status_changed(
                baggage_id=bag["id"],
                tag=bag["tag"],
                previous_status="in_hold",
                new_status="on_carousel",
                scan_zone=f"arrival-belt-{carousel}",
                sim_time=sim_time,
            )
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "BaggageStatusChanged",
                    "payload": event_payload,
                })

    elif new_status == "cancelled":
        # Flight cancelled — offload all baggage
        await _on_flight_cancelled(payload, sim_time)


async def _on_flight_cancelled(payload: dict, sim_time: datetime) -> None:
    """Handle FlightCancelled — offload all loaded baggage."""
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    await offload_flight_baggage(
        flight_id=flight_id,
        sim_time=sim_time,
        conveyor_system=_conveyor,
        produce_status_changed_fn=emit_baggage_status_changed,
    )


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentCreated — halt affected conveyor zones."""
    incident_type = payload.get("type")
    if incident_type != "system_failure":
        return

    location = payload.get("location", "")
    affected_zones = FAILURE_IMPACT.get(location, [])
    for zone_id in affected_zones:
        _conveyor.set_zone_status(zone_id, "offline")
        m_zone_status.labels(zone_id=zone_id).set(2)  # offline
        logger.warning(
            "Zone %s set OFFLINE due to system_failure at %s",
            zone_id, location,
        )


async def _on_incident_status_changed(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentStatusChanged — resume zones when incident resolved."""
    new_status = payload.get("new_status") or payload.get("status")
    if new_status != "resolved":
        return

    location = payload.get("location", "")
    affected_zones = FAILURE_IMPACT.get(location, [])
    for zone_id in affected_zones:
        _conveyor.set_zone_status(zone_id, "normal")
        m_zone_status.labels(zone_id=zone_id).set(0)  # normal
        logger.info(
            "Zone %s restored to NORMAL after incident resolved at %s",
            zone_id, location,
        )
