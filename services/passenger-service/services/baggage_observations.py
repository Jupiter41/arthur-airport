"""Passenger-owned durable baggage observations; safe before passenger seeding."""
from __future__ import annotations

from datetime import datetime

from _common import outbox
from _common.kafka_runtime import build_envelope
from db.neo4j import get_driver, next_outbox_revision


async def observe(payload: dict, sim_time: datetime, event_id: str, *, allow_move: bool = True) -> list[dict]:
    """Commit the consumed observation and any lifecycle-valid move before ACK."""
    pid, status = payload.get("passenger_id"), payload.get("new_status")
    zone = str(payload.get("scan_zone") or "")
    if not pid or status not in ("on_carousel", "collected"):
        return []
    if status == "on_carousel" and not zone.startswith("arrival-belt-"):
        return []
    at = sim_time.isoformat()
    bid = payload.get("baggage_id")
    input_id = (f"baggage-observation:{bid}:{status}:{at}" if bid else
                event_id or f"baggage-observation:{pid}:{status}:{at}")
    carousel = "carousel-" + zone.rsplit("-", 1)[-1] if status == "on_carousel" else None

    async def apply(tx) -> list[dict]:
        if await outbox.inbox_seen(tx, "PassengerInbox", input_id):
            return []
        revision = await next_outbox_revision(tx)
        await (await tx.run(
            "MERGE (o:PassengerBaggageObservation {id:$pid}) "
            "SET o.flight_id = coalesce($fid, o.flight_id), "
            "o.observed_at = CASE WHEN o.observed_at IS NULL OR $at > o.observed_at "
            "THEN $at ELSE o.observed_at END "
            "FOREACH (_ IN CASE WHEN $status = 'collected' AND "
            "(o.collected_at IS NULL OR $at < o.collected_at) THEN [1] ELSE [] END | "
            "SET o.collected_at = $at) "
            "FOREACH (_ IN CASE WHEN $status = 'on_carousel' AND "
            "(o.carousel_at IS NULL OR $at >= o.carousel_at) THEN [1] ELSE [] END | "
            "SET o.carousel_at = $at, o.carousel_zone = $zone)",
            pid=pid, fid=payload.get("flight_id"), status=status, at=at, zone=carousel,
        )).consume()
        # Read the persisted observation, not the potentially stale input zone.
        moved = await (await tx.run(
            "MATCH (p:Passenger {id:$pid, status:'baggage_claim'}) "
            "MATCH (o:PassengerBaggageObservation {id:$pid}) "
            "WHERE $move = true AND $status = 'on_carousel' AND o.carousel_at <= $at "
            "AND coalesce(p.location_zone, '') <> o.carousel_zone "
            "WITH p, o, p.location_zone AS old_zone "
            "SET p.location_zone = o.carousel_zone "
            "RETURN p.id AS id, old_zone, p.location_zone AS zone",
            pid=pid, status=status, at=at, move=allow_move,
        )).data()
        document = build_envelope("PassengerBaggageObserved", sim_time, {
            "passenger_id": pid, "flight_id": payload.get("flight_id"),
            "status": status, "scan_zone": zone, "observed_at": at,
            "location_updates": moved,
        }, "passenger-service")
        document["event_id"] = f"{input_id}:observation:{pid}"
        await outbox.mark_inbox(tx, "PassengerInbox", input_id, at)
        await outbox.stage_outbox(tx, "PassengerOutbox", [
            {"id": document["event_id"], "document": document},
        ], revision)
        return moved

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def bootstrap() -> int:
    """Startup-only timestamped snapshot for missed/expired collection inputs.

    Reads linked arrival identities once. No tick decision reads baggage-owner
    nodes; observation timestamps are fenced when the passenger tick uses them.
    """
    async with get_driver().session() as session:
        rows = await (await session.run(
            "MATCH (p:Passenger) WHERE p.status IN "
            "['booked','airborne','deplaning','customs','baggage_claim'] "
            "MATCH (p)-[:CARRIES]->(b)-[:LOADED_ON]->(f:Flight {direction:'arrival'}) "
            "WHERE (b:Baggage OR b:BaggageArchive) AND b.status IN ['on_carousel','collected'] "
            "AND b.last_scan_at IS NOT NULL "
            "RETURN p.id AS passenger_id, f.id AS flight_id, b.id AS baggage_id, b.status AS new_status, "
            "b.last_scan_zone AS scan_zone, b.last_scan_at AS at",
        )).data()
    for row in rows:
        await observe(row, datetime.fromisoformat(row["at"]),
                      f"baggage-bootstrap:{row['baggage_id']}:{row['new_status']}:{row['at']}", allow_move=False)
    return len(rows)
