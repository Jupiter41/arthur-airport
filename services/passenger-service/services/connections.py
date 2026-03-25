"""Connection risk monitoring — MCT tracking + 3-tier risk levels.

Minimum Connection Time (MCT) = 45 sim-minutes (configurable).
Risk levels: ok → watch → at_risk → missed.
"""

import os
from datetime import datetime

MCT_MINUTES = int(os.getenv("MIN_CONNECTION_TIME_MIN", "45"))


def connection_risk(
    inbound_delay_min: int,
    time_to_connection_min: int,
) -> str:
    """Compute connection risk level.

    Args:
        inbound_delay_min: delay of inbound flight in sim-minutes
        time_to_connection_min: time until connecting flight departs

    Returns:
        Risk level: 'ok', 'watch', 'at_risk', or 'missed'
    """
    if time_to_connection_min < MCT_MINUTES:
        return "missed"
    if inbound_delay_min > 30 or time_to_connection_min < MCT_MINUTES + 15:
        return "at_risk"
    if inbound_delay_min > 15:
        return "watch"
    return "ok"


def compute_time_to_connection(
    sim_time: datetime,
    connection_estimated: str | datetime | None,
) -> int | None:
    """Compute minutes until connecting flight departs."""
    if connection_estimated is None:
        return None
    if isinstance(connection_estimated, str):
        connection_estimated = datetime.fromisoformat(
            str(connection_estimated)
        ).replace(tzinfo=None)
    delta = connection_estimated - sim_time
    return max(0, int(delta.total_seconds() / 60))


def evaluate_connecting_passengers(
    connecting_pax: list[dict],
    sim_time: datetime,
) -> list[dict]:
    """Evaluate risk for all connecting passengers.

    Returns list of passengers with updated risk levels and
    a flag indicating if the risk level changed.
    """
    results = []
    for pax in connecting_pax:
        inbound_delay = pax.get("inbound_delay") or 0
        conn_estimated = pax.get("connection_estimated") or pax.get("connection_scheduled")
        time_to_conn = compute_time_to_connection(sim_time, conn_estimated)

        if time_to_conn is None:
            continue

        new_risk = connection_risk(inbound_delay, time_to_conn)
        old_risk = pax.get("connection_risk") or "ok"

        results.append({
            "id": pax["id"],
            "name": pax.get("name", ""),
            "pnr": pax.get("pnr", ""),
            "inbound_flight": pax.get("inbound_flight"),
            "inbound_delay_minutes": inbound_delay,
            "connection_flight": pax.get("connection_flight"),
            "connection_departs_in_minutes": time_to_conn,
            "mct_minutes": MCT_MINUTES,
            "risk_level": new_risk,
            "old_risk_level": old_risk,
            "risk_changed": new_risk != old_risk,
            "baggage_count": pax.get("baggage_count", 0),
        })

    return results
