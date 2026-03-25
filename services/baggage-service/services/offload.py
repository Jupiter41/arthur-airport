"""Offload handling — flight cancellation → baggage offload + carousel return.

When a flight is cancelled, all baggage in 'loaded' or 'in_hold' status must be:
1. Removed from the loading pipeline (in-memory conveyor)
2. Status changed to 'offloaded' in Neo4j
3. Assigned a return carousel (round-robin 1–6)
4. Eventually moved to 'on_carousel' for passenger collection
"""

import logging
from datetime import datetime

from db.neo4j import (
    get_flight_baggage,
    update_baggage_status,
    set_baggage_carousel,
)

logger = logging.getLogger(__name__)

# Track which flights have already been offloaded (idempotency)
_offloaded_flights: set[str] = set()


async def offload_flight_baggage(
    flight_id: str,
    sim_time: datetime,
    conveyor_system,
    produce_status_changed_fn,
) -> list[dict]:
    """Offload all baggage for a cancelled flight.

    Args:
        flight_id: The cancelled flight ID
        sim_time: Current simulation time
        conveyor_system: The ConveyorSystem instance to remove bags from
        produce_status_changed_fn: Callback to emit BaggageStatusChanged events

    Returns:
        List of offloaded baggage dicts
    """
    # Idempotency: skip if already offloaded
    if flight_id in _offloaded_flights:
        logger.info("Flight %s already offloaded — skipping", flight_id)
        return []

    _offloaded_flights.add(flight_id)

    # Get all baggage loaded on this flight in loadable states
    bags = await get_flight_baggage(
        flight_id,
        statuses=["loaded", "in_hold", "sorting", "screening", "inducted", "dropped_off"],
    )

    if not bags:
        logger.info("No baggage to offload for flight %s", flight_id)
        return []

    # Assign a return carousel (deterministic based on flight_id)
    carousel = (hash(flight_id) % 6) + 1
    sim_time.isoformat()

    offloaded: list[dict] = []
    for bag in bags:
        bag_id = bag["id"]
        tag = bag["tag"]
        previous_status = bag["status"]

        # Remove from in-memory conveyor if present
        conveyor_system.remove_bag_from_all_zones(bag_id)

        # Update Neo4j: status → offloaded, assign carousel
        await update_baggage_status(
            bag_id,
            "offloaded",
            scan_zone=f"arrival-belt-{carousel}",
            sim_time=sim_time,
        )
        await set_baggage_carousel(bag_id, carousel, sim_time)

        # Emit BaggageStatusChanged event
        await produce_status_changed_fn(
            baggage_id=bag_id,
            tag=tag,
            previous_status=previous_status,
            new_status="offloaded",
            scan_zone=f"arrival-belt-{carousel}",
            sim_time=sim_time,
        )

        offloaded.append({
            "id": bag_id,
            "tag": tag,
            "previous_status": previous_status,
            "carousel": carousel,
        })

    logger.info(
        "Offloaded %d bags for flight %s → arrival-belt-%d",
        len(offloaded), flight_id, carousel,
    )
    return offloaded
