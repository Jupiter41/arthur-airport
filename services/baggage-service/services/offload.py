"""Offload handling — flight cancellation → baggage offload + carousel return.

When a flight is cancelled, all baggage in a loadable state must be:
1. Status changed to 'offloaded' in Neo4j (+ return carousel)
2. Removed from the loading pipeline (in-memory conveyor)
3. Eventually moved to 'on_carousel' for passenger collection

G1-c: the Neo4j status write, the durable ``BaggageInbox`` marker (flight-scoped
dedup, replacing the former in-memory ``_offloaded_flights`` set) and the staged
``BaggageStatusChanged`` facts commit together in ONE ``session.execute_write``.
The in-memory conveyor (a Neo4j-derived, rebuildable cache per rule #3) and
metrics update only *after* the commit succeeds.
"""

import logging
from datetime import datetime

from _common import outbox
from db.neo4j import (
    get_driver,
    get_flight_baggage,
    next_outbox_revision_tx,
    write_baggage_statuses_tx,
)
from kafka.producer import build_status_changed_fact, is_bulk_mode

logger = logging.getLogger(__name__)

OFFLOAD_STATUSES = ["loaded", "in_hold", "sorting", "screening", "inducted", "dropped_off"]


def _offload_inbox_id(flight_id: str) -> str:
    """Flight-scoped durable dedup key (one offload per cancelled flight)."""
    return f"offload:{flight_id}"


async def offload_flight_baggage(
    flight_id: str,
    sim_time: datetime,
    conveyor_system,
) -> list[dict]:
    """Atomically offload all baggage for a cancelled flight.

    Returns the list of offloaded baggage dicts (with ``previous_status`` and
    ``carousel``) so the caller can update per-transition metrics post-commit.
    Returns ``[]`` when there is nothing to offload or the flight was already
    offloaded (durable, flight-scoped dedup via ``BaggageInbox``).
    """
    bags = await get_flight_baggage(flight_id, statuses=OFFLOAD_STATUSES)
    if not bags:
        logger.info("No baggage to offload for flight %s", flight_id)
        return []

    # Deterministic return carousel based on flight_id.
    carousel = (hash(flight_id) % 6) + 1
    zone = f"arrival-belt-{carousel}"
    changes = [
        {"id": bag["id"], "status": "offloaded", "zone": zone, "carousel": carousel}
        for bag in bags
    ]

    # BULK speed mode suppresses per-bag facts (aggregated via BulkStateSnapshot);
    # the domain write + inbox marker stay atomic regardless.
    suppress = is_bulk_mode()
    facts = [] if suppress else [
        build_status_changed_fact(
            id_base=_offload_inbox_id(flight_id),
            baggage_id=bag["id"],
            tag=bag["tag"],
            previous_status=bag["status"],
            new_status="offloaded",
            scan_zone=zone,
            sim_time=sim_time,
            passenger_id=bag.get("passenger_id"),
            flight_id=flight_id,
        )
        for bag in bags
    ]
    inbox_id = _offload_inbox_id(flight_id)

    async def apply(tx) -> bool:
        if await outbox.inbox_seen(tx, "BaggageInbox", inbox_id):
            return False  # already offloaded — no re-write, no re-stage
        revision = await next_outbox_revision_tx(tx)
        await write_baggage_statuses_tx(tx, changes, sim_time)
        await outbox.mark_inbox(tx, "BaggageInbox", inbox_id, sim_time.isoformat())
        await outbox.stage_outbox(tx, "BaggageOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        applied = await session.execute_write(apply)

    if not applied:
        logger.info("Flight %s already offloaded — skipping", flight_id)
        return []

    # Post-commit only: evict from the rebuildable conveyor cache.
    offloaded: list[dict] = []
    for bag in bags:
        conveyor_system.remove_bag_from_all_zones(bag["id"])
        offloaded.append({
            "id": bag["id"],
            "tag": bag["tag"],
            "previous_status": bag["status"],
            "carousel": carousel,
        })

    logger.info(
        "Offloaded %d bags for flight %s → arrival-belt-%d",
        len(offloaded), flight_id, carousel,
    )
    return offloaded
