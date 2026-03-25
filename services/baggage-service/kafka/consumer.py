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
from typing import Callable, Awaitable

from confluent_kafka import Consumer

from db.neo4j import (
    get_dropped_off_baggage_for_departures,
    update_baggage_status,
    flag_baggage,
    get_baggage_counts_by_status,
    get_baggage_in_pipeline,
)
from kafka.producer import (
    emit_baggage_status_changed,
    emit_baggage_flagged,
)
from services.conveyor import (
    ConveyorSystem,
    BagInZone,
)
from services.screening import screen_item
from services.offload import offload_flight_baggage
from metrics import (
    baggage_in_system as m_in_system,
    baggage_flagged_active as m_flagged,
    conveyor_zone_utilisation_pct as m_zone_util,
    conveyor_zone_status as m_zone_status,
    baggage_transitions_total as m_transitions,
    baggage_offloaded_total as m_offloaded,
    dangerous_goods_detected_total as m_dg_detected,
    screening_false_positives_total as m_false_pos,
    envelope_invalid_total as m_envelope_invalid,
)

logger = logging.getLogger(__name__)


def _track_transition(from_status: str, to_status: str) -> None:
    """Immediately update transition counter at mutation site."""
    m_transitions.labels(from_status=from_status, to_status=to_status).inc()


async def _emit_status_changed_with_metric(**kwargs) -> dict:
    """Emit a BaggageStatusChanged event and track the transition metric."""
    prev = kwargs.get("previous_status", "")
    new = kwargs.get("new_status", "")
    if prev and new:
        _track_transition(prev, new)
    return await emit_baggage_status_changed(**kwargs)


# ── Class-based state holder ────────────────────────────────


class BaggageConsumerState:
    """Holds all mutable runtime state for the baggage consumer."""

    MAX_PROCESSED = 20000

    def __init__(self) -> None:
        self.sim_time: datetime | None = None
        self.conveyor = ConveyorSystem()
        self.processed_events: set[str] = set()
        self.inducted_bag_ids: set[str] = set()
        self.ws_broadcast: Callable[[dict], Awaitable[None]] | None = None

    def check_idempotency(self, event_id: str) -> bool:
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
        """Rebuild in-memory state from Neo4j on startup (catch-up)."""
        bags = await get_baggage_in_pipeline()
        inducted = 0
        for bag in bags:
            tag = bag["id"]
            status = bag.get("status", "dropped_off")
            if status in ("inducted", "screening", "sorting"):
                zone_id = bag.get("current_zone")
                if zone_id:
                    zone = self.conveyor.get_zone(zone_id)
                    if zone:
                        zone.queue.append(BagInZone(
                            baggage_id=tag,
                            tag="",
                            flight_id=bag.get("flight_id", ""),
                            is_dg=False,
                            dg_class=None,
                            passenger_id=None,
                            terminal="A",
                            entered_at=bag.get("last_scan_at") or "",
                        ))
                self.inducted_bag_ids.add(tag)
                inducted += 1
            elif status in ("loaded", "in_hold", "flagged"):
                self.inducted_bag_ids.add(tag)
        logger.info("Rebuilt conveyor state from Neo4j: %d bags in pipeline, %d inducted total",
                     inducted, len(self.inducted_bag_ids))


# Module-level singleton
_state = BaggageConsumerState()
_consumer: Consumer | None = None
_consumer_running = False

# System failure impact mapping (constant, from SKILL.md)
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


def set_ws_broadcast(fn):
    _state.ws_broadcast = fn


def get_sim_time() -> datetime | None:
    return _state.sim_time


def get_conveyor() -> ConveyorSystem:
    return _state.conveyor


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

    # Idempotency check (skip for clock ticks — they're always unique)
    if event_type != "SimClockTick":
        event_id = envelope.get("event_id", "")
        if _state.check_idempotency(event_id):
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
    _state.sim_time = sim_time

    sim_time_str = sim_time.isoformat()

    # 1. Induct new bags: pull 'dropped_off' bags from Neo4j whose flights
    #    depart within ~90 minutes
    await _induct_new_bags(sim_time)

    # 2. Advance conveyor pipeline
    outputs = _state.conveyor.advance_tick(sim_time_str)

    # 3. Process zone outputs
    for zone_id, bags in outputs.items():
        for bag in bags:
            try:
                await _process_bag_exit(zone_id, bag, sim_time)
            except Exception as e:
                logger.error("Failed to process bag %s exiting %s: %s", bag.baggage_id, zone_id, e)

    # 4. Update Prometheus gauges
    try:
        counts = await get_baggage_counts_by_status()
        for status, count in counts.items():
            m_in_system.labels(status=status).set(count)
    except Exception:
        pass
    for z in _state.conveyor.get_zone_summary():
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
        if bag_id in _state.inducted_bag_ids:
            continue

        flight_status = bag.get("flight_status", "scheduled")

        # For flights already departed/airborne — fast-track to in_hold
        if flight_status in ("departed", "airborne"):
            _state.inducted_bag_ids.add(bag_id)
            batch_count += 1
            await update_baggage_status(
                bag_id, "in_hold", "aircraft-hold", sim_time
            )
            await _emit_status_changed_with_metric(
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

        _state.inducted_bag_ids.add(bag_id)
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

        zone_id = _state.conveyor.induct_bag(bag_in_zone, sim_time_str)

        # Update Neo4j: status → inducted
        await update_baggage_status(bag_id, "inducted", zone_id, sim_time)

        # Emit BaggageStatusChanged event
        event_payload = await _emit_status_changed_with_metric(
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
        if _state.ws_broadcast:
            await _state.ws_broadcast({
                "event_type": "BaggageStatusChanged",
                "payload": event_payload,
            })


async def _process_bag_exit(
    from_zone: str, bag: BagInZone, sim_time: datetime
) -> None:
    """Handle a bag exiting a zone — screen, flag, or advance status."""
    sim_time.isoformat()

    if from_zone.startswith("induction"):
        # Bag exits induction → now entering screening
        # The conveyor.advance_tick already placed it in a screening zone
        # Update Neo4j status
        screening_zone = _find_bag_current_zone(bag.baggage_id)
        if screening_zone:
            await update_baggage_status(
                bag.baggage_id, "screening", screening_zone, sim_time
            )
            event_payload = await _emit_status_changed_with_metric(
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                previous_status="inducted",
                new_status="screening",
                scan_zone=screening_zone,
                sim_time=sim_time,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            if _state.ws_broadcast:
                await _state.ws_broadcast({
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
            if _state.ws_broadcast:
                await _state.ws_broadcast({
                    "event_type": "BaggageFlagged",
                    "payload": event_payload,
                })
            # Remove from sorting queue (it was already placed there by advance_tick)
            _state.conveyor.remove_bag_from_all_zones(bag.baggage_id)
        else:
            # Clear — bag moves to sorting (already placed by advance_tick)
            await update_baggage_status(
                bag.baggage_id, "sorting", "sorting-matrix", sim_time
            )
            event_payload = await _emit_status_changed_with_metric(
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                previous_status="screening",
                new_status="sorting",
                scan_zone="sorting-matrix",
                sim_time=sim_time,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            if _state.ws_broadcast:
                await _state.ws_broadcast({
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
            # Set loaded_at timestamp on the LOADED_ON relationship
            if bag.flight_id:
                from db.neo4j import set_loaded_on_timestamp
                await set_loaded_on_timestamp(
                    bag.baggage_id, bag.flight_id, sim_time
                )
            event_payload = await _emit_status_changed_with_metric(
                baggage_id=bag.baggage_id,
                tag=bag.tag,
                previous_status="sorting",
                new_status="loaded",
                scan_zone=makeup_zone,
                sim_time=sim_time,
                passenger_id=bag.passenger_id,
                flight_id=bag.flight_id,
            )
            if _state.ws_broadcast:
                await _state.ws_broadcast({
                    "event_type": "BaggageStatusChanged",
                    "payload": event_payload,
                })

    elif from_zone.startswith("make-up"):
        # Bags exiting make-up are now fully loaded onto the flight.
        # Verify/set status to "loaded" and create LOADED_ON relationship
        # timestamp in case the sorting-matrix exit handler missed it.
        await update_baggage_status(
            bag.baggage_id, "loaded", from_zone, sim_time
        )
        # Ensure LOADED_ON relationship has loaded_at timestamp
        if bag.flight_id:
            from db.neo4j import set_loaded_on_timestamp
            await set_loaded_on_timestamp(
                bag.baggage_id, bag.flight_id, sim_time
            )
        event_payload = await _emit_status_changed_with_metric(
            baggage_id=bag.baggage_id,
            tag=bag.tag,
            previous_status="sorting",
            new_status="loaded",
            scan_zone=from_zone,
            sim_time=sim_time,
            passenger_id=bag.passenger_id,
            flight_id=bag.flight_id,
        )
        if _state.ws_broadcast:
            await _state.ws_broadcast({
                "event_type": "BaggageStatusChanged",
                "payload": event_payload,
            })

    elif from_zone.startswith("arrival-belt"):
        # Bags exiting arrival belt → collected
        await update_baggage_status(
            bag.baggage_id, "collected", from_zone, sim_time
        )
        event_payload = await _emit_status_changed_with_metric(
            baggage_id=bag.baggage_id,
            tag=bag.tag,
            previous_status="on_carousel",
            new_status="collected",
            scan_zone=from_zone,
            sim_time=sim_time,
            passenger_id=bag.passenger_id,
            flight_id=bag.flight_id,
        )
        if _state.ws_broadcast:
            await _state.ws_broadcast({
                "event_type": "BaggageStatusChanged",
                "payload": event_payload,
            })


def _find_bag_current_zone(baggage_id: str) -> str | None:
    """Find which zone a bag is currently in (in-memory lookup)."""
    for zone_id, zone in _state.conveyor.get_all_zones().items():
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
            event_payload = await _emit_status_changed_with_metric(
                baggage_id=bag["id"],
                tag=bag["tag"],
                previous_status="loaded",
                new_status="in_hold",
                scan_zone="aircraft-hold",
                sim_time=sim_time,
                passenger_id=bag.get("passenger_id"),
                flight_id=flight_id,
            )
            if _state.ws_broadcast:
                await _state.ws_broadcast({
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
                passenger_id=bag.get("passenger_id"),
                terminal="A",
                entered_at=sim_time.isoformat(),
            )
            arrival_zone = _state.conveyor.get_zone(f"arrival-belt-{carousel}")
            if arrival_zone:
                arrival_zone.queue.append(bag_in_zone)

            await update_baggage_status(
                bag["id"], "on_carousel", f"arrival-belt-{carousel}", sim_time
            )
            from db.neo4j import set_baggage_carousel
            await set_baggage_carousel(bag["id"], carousel, sim_time)

            event_payload = await _emit_status_changed_with_metric(
                baggage_id=bag["id"],
                tag=bag["tag"],
                previous_status="in_hold",
                new_status="on_carousel",
                scan_zone=f"arrival-belt-{carousel}",
                sim_time=sim_time,
                passenger_id=bag.get("passenger_id"),
                flight_id=flight_id,
            )
            if _state.ws_broadcast:
                await _state.ws_broadcast({
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
        conveyor_system=_state.conveyor,
        produce_status_changed_fn=_emit_status_changed_with_metric,
    )


async def _on_incident_created(payload: dict, sim_time: datetime) -> None:
    """Handle IncidentCreated — halt affected conveyor zones."""
    incident_type = payload.get("type")
    if incident_type != "system_failure":
        return

    location = payload.get("location", "")
    affected_zones = FAILURE_IMPACT.get(location, [])
    for zone_id in affected_zones:
        _state.conveyor.set_zone_status(zone_id, "offline")
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
        _state.conveyor.set_zone_status(zone_id, "normal")
        m_zone_status.labels(zone_id=zone_id).set(0)  # normal
        logger.info(
            "Zone %s restored to NORMAL after incident resolved at %s",
            zone_id, location,
        )
