"""Turnaround tracker — aircraft rotation tracking and delay propagation.

Every aircraft has exactly two legs per simulated day (arrival + departure).
When an inbound flight is delayed, the delay propagates to the outbound flight
after subtracting the turnaround buffer.
"""

import logging
import os
from datetime import datetime, timedelta

from db.neo4j import get_paired_flight, apply_delay

logger = logging.getLogger(__name__)

# Body-class classification is shared across all services — see _common/aircraft.py.
from _common.aircraft import WIDE_BODY_TYPES

CASCADE_MAX_DEPTH = int(os.getenv("CASCADE_MAX_DEPTH", "5"))
TURNAROUND_NARROW_MIN = int(os.getenv("TURNAROUND_NARROW_MIN", "30"))
TURNAROUND_WIDE_MIN = int(os.getenv("TURNAROUND_WIDE_MIN", "45"))


async def propagate_turnaround_delay(
    flight_id: str,
    aircraft_registration: str,
    aircraft_type: str,
    direction: str,
    delay_minutes: int,
    sim_time: datetime,
    depth: int = 0,
    producer_callback=None,
) -> list[dict]:
    """Propagate delay from an inbound flight to its outbound rotation.

    Returns list of {flight_id, flight_number, propagated_delay} for affected flights.
    """
    if depth >= CASCADE_MAX_DEPTH:
        logger.warning(
            "Turnaround cascade max depth reached (depth=%d) for flight %s",
            depth, flight_id,
        )
        return []

    # Only arrivals propagate to departures
    if direction != "arrival":
        return []

    if delay_minutes < 15:
        return []

    paired = await get_paired_flight(aircraft_registration, direction)
    if not paired:
        return []

    outbound_id = paired["id"]
    outbound_status = paired.get("status", "")

    # Don't propagate to flights that have already departed or are cancelled
    if outbound_status in ("departed", "airborne", "cancelled", "at_gate"):
        return []

    # Calculate propagated delay
    buffer = TURNAROUND_WIDE_MIN if aircraft_type in WIDE_BODY_TYPES else TURNAROUND_NARROW_MIN
    propagated = max(0, delay_minutes - buffer)

    if propagated <= 0:
        return []

    # Apply the delay
    outbound_estimated = paired.get("estimated_time", paired.get("scheduled_time"))
    if outbound_estimated:
        try:
            est = datetime.fromisoformat(str(outbound_estimated))
            new_est = est + timedelta(minutes=propagated)
        except (ValueError, TypeError):
            return []
    else:
        return []

    updated = await apply_delay(
        flight_id=outbound_id,
        delay_minutes=propagated,
        reason=f"turnaround_delay_from_{flight_id}",
        new_estimated_time=new_est.isoformat(),
        sim_time=sim_time,
    )

    results = []
    if updated:
        result = {
            "flight_id": outbound_id,
            "flight_number": paired.get("flight_number", ""),
            "propagated_delay": propagated,
        }
        results.append(result)

        logger.info(
            "Turnaround delay propagated: %s (%s) -> %s (%s), delay=%d min (buffer=%d, depth=%d)",
            flight_id, direction, outbound_id, paired.get("flight_number"),
            propagated, buffer, depth,
        )

        # Emit event for the delayed outbound
        if producer_callback:
            await producer_callback(
                flight_id=outbound_id,
                flight=updated,
                previous_status=outbound_status,
                new_status="delayed",
                sim_time=sim_time,
            )

    return results
