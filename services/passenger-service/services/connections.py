"""Connection risk monitoring — MCT tracking + 3-tier risk levels.

Minimum Connection Time (MCT) = 45 sim-minutes (configurable).
Risk levels: ok → watch → at_risk → missed.
"""

import math
import os
from datetime import datetime

MCT_MINUTES = int(os.getenv("MIN_CONNECTION_TIME_MIN", "45"))


def connection_risk(
    inbound_delay_min: int,
    time_to_connection_min: int,
    walking_minutes: float = 0.0,
) -> str:
    """Compute connection risk level.

    Args:
        inbound_delay_min: delay of inbound flight in sim-minutes
        time_to_connection_min: time until connecting flight departs
        walking_minutes: walking time between arrival gate and departure gate

    Returns:
        Risk level: 'ok', 'watch', 'at_risk', or 'missed'
    """
    effective_mct = MCT_MINUTES + walking_minutes
    if time_to_connection_min < effective_mct:
        return "missed"
    if inbound_delay_min > 30 or time_to_connection_min < effective_mct + 15:
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


_WALKING_SPEED = 84.0  # m/min
_SPECIAL_ASSIST_MULT = 2.5


def _walking_time_between_gates(
    from_pos: dict | None,
    to_pos: dict | None,
    special_assistance: bool = False,
) -> float:
    """Walking time between two gate positions (for connection risk)."""
    if from_pos is None or to_pos is None:
        return 10.0  # default cross-terminal fallback

    fx = from_pos.get("position_x", from_pos.get("x"))
    fy = from_pos.get("position_y", from_pos.get("y"))
    tx = to_pos.get("position_x", to_pos.get("x"))
    ty = to_pos.get("position_y", to_pos.get("y"))

    if any(v is None for v in (fx, fy, tx, ty)):
        return 10.0

    dist = math.sqrt((tx - fx) ** 2 + (ty - fy) ** 2)
    time_min = dist / _WALKING_SPEED
    if special_assistance:
        time_min *= _SPECIAL_ASSIST_MULT
    return time_min


def evaluate_connecting_passengers(
    connecting_pax: list[dict],
    sim_time: datetime,
    gate_positions: dict[str, dict] | None = None,
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

        # Compute walking time between arrival and departure gates
        walk_min = 0.0
        if gate_positions:
            inbound_gate = pax.get("inbound_gate_id")
            conn_gate = pax.get("connection_gate_id")
            from_pos = gate_positions.get(inbound_gate) if inbound_gate else None
            to_pos = gate_positions.get(conn_gate) if conn_gate else None
            walk_min = _walking_time_between_gates(from_pos, to_pos, bool(pax.get("special_assistance")))

        new_risk = connection_risk(inbound_delay, time_to_conn, walk_min)
        old_risk = pax.get("connection_risk") or "ok"

        results.append({
            "id": pax["id"],
            "name": pax.get("name", ""),
            "pnr": pax.get("pnr", ""),
            "inbound_flight": pax.get("inbound_flight"),
            "inbound_delay_minutes": inbound_delay,
            "connection_flight": pax.get("connection_flight"),
            "connection_departs_in_minutes": time_to_conn,
            "walking_minutes": round(walk_min, 1),
            "mct_minutes": MCT_MINUTES,
            "risk_level": new_risk,
            "old_risk_level": old_risk,
            "risk_changed": new_risk != old_risk,
            "baggage_count": pax.get("baggage_count", 0),
        })

    return results
