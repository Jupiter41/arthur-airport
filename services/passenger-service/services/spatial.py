"""Spatial utilities — walking time from airport layout positions.

All positions are on a normalized 0-1000 grid where 1 unit ≈ 1 metre.
Walking speed: ~84 m/min (1.4 m/s).
Special assistance: walking time × 2.5.
"""

import math
from typing import Optional

from _common.airport_config import load_airport_runtime_config

WALKING_SPEED = load_airport_runtime_config().operations.walking_speed_m_min  # m/min (1.4 m/s)
SPECIAL_ASSIST_MULT = 2.5


def euclidean_distance(
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """Euclidean distance between two points on the grid."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def walking_time_minutes(
    from_x: float, from_y: float,
    to_x: float, to_y: float,
    special_assistance: bool = False,
) -> float:
    """Compute walking time between two points in the terminal."""
    dist = euclidean_distance(from_x, from_y, to_x, to_y)
    time_min = dist / WALKING_SPEED
    if special_assistance:
        time_min *= SPECIAL_ASSIST_MULT
    return time_min


def walking_time_to_gate(
    terminal: str,
    gate_pos: Optional[dict],
    walking_zones: Optional[dict] = None,
    special_assistance: bool = False,
) -> float:
    """Compute walking time from airside exit to gate.

    Uses the airside center of the passenger's terminal as the starting point.
    """
    if gate_pos is None or walking_zones is None:
        return 5.0  # default fallback

    gx = gate_pos.get("position_x", gate_pos.get("x"))
    gy = gate_pos.get("position_y", gate_pos.get("y"))
    if gx is None or gy is None:
        return 5.0

    zone = walking_zones.get(terminal, {})
    airside = zone.get("airside", {})
    ax = airside.get("x", 500)
    ay = airside.get("y", 400)

    return walking_time_minutes(ax, ay, gx, gy, special_assistance)


def walking_time_between_gates(
    from_gate_pos: Optional[dict],
    to_gate_pos: Optional[dict],
    special_assistance: bool = False,
) -> float:
    """Compute walking time between two gates (for connection risk).

    Used when a connecting passenger needs to walk from arrival gate
    to departure gate, potentially across terminals.
    """
    if from_gate_pos is None or to_gate_pos is None:
        return 10.0  # default cross-terminal fallback

    fx = from_gate_pos.get("position_x", from_gate_pos.get("x"))
    fy = from_gate_pos.get("position_y", from_gate_pos.get("y"))
    tx = to_gate_pos.get("position_x", to_gate_pos.get("x"))
    ty = to_gate_pos.get("position_y", to_gate_pos.get("y"))

    if any(v is None for v in (fx, fy, tx, ty)):
        return 10.0

    return walking_time_minutes(fx, fy, tx, ty, special_assistance)
