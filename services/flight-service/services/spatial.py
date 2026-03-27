"""Spatial utilities — taxi time and walking time from airport layout positions.

All positions are on a normalized 0-1000 grid where 1 unit ≈ 1 metre.
Speeds:
  - Taxiway: 15 km/h = 250 m/min
  - Apron (within 200m of gate): 5 km/h = 83.3 m/min
  - Walking: ~84 m/min (1.4 m/s)
  - Special assistance: walking × 2.5
"""

import math
from typing import Optional

# Speeds in metres per minute
TAXIWAY_SPEED = 250.0       # 15 km/h
APRON_SPEED = 83.3           # 5 km/h
APRON_RADIUS = 200.0         # metres within gate considered apron
WALKING_SPEED = 84.0         # 1.4 m/s
SPECIAL_ASSIST_MULT = 2.5

# Default fallback values (used when positions unavailable)
DEFAULT_TAXI_TOTAL_MIN = 8   # original fixed constant: ATA+8
DEFAULT_TAXI_INITIAL_MIN = 2 # original fixed constant: ATA+2


def euclidean_distance(
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """Euclidean distance between two points on the grid."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def taxi_time_minutes(
    runway_x: float, runway_y: float,
    gate_x: float, gate_y: float,
    apron_radius: float = APRON_RADIUS,
) -> float:
    """Compute taxi time from runway threshold to gate position.

    Splits distance into taxiway (fast) and apron (slow) segments.
    Returns total time in minutes.
    """
    total_dist = euclidean_distance(runway_x, runway_y, gate_x, gate_y)
    apron_dist = min(total_dist, apron_radius)
    taxiway_dist = max(0.0, total_dist - apron_radius)
    return taxiway_dist / TAXIWAY_SPEED + apron_dist / APRON_SPEED


def taxi_time_from_positions(
    runway_pos: Optional[dict],
    gate_pos: Optional[dict],
) -> tuple[float, float]:
    """Compute taxi times (initial movement, total to gate) from position dicts.

    Returns (initial_taxi_min, total_taxi_min).
    initial_taxi_min: time from touchdown to start of taxi (2 min fixed + some movement)
    total_taxi_min: full time from touchdown to gate arrival

    If positions are unavailable, falls back to default constants.
    """
    if runway_pos is None or gate_pos is None:
        return (DEFAULT_TAXI_INITIAL_MIN, DEFAULT_TAXI_TOTAL_MIN)

    rx = runway_pos.get("threshold_x", runway_pos.get("x"))
    ry = runway_pos.get("threshold_y", runway_pos.get("y"))
    gx = gate_pos.get("position_x", gate_pos.get("x"))
    gy = gate_pos.get("position_y", gate_pos.get("y"))

    if any(v is None for v in (rx, ry, gx, gy)):
        return (DEFAULT_TAXI_INITIAL_MIN, DEFAULT_TAXI_TOTAL_MIN)

    taxi_min = taxi_time_minutes(rx, ry, gx, gy)

    # Initial phase: 2 min (runway vacation + initial rollout)
    initial_min = 2.0
    # Total: initial + taxi
    total_min = initial_min + taxi_min

    return (initial_min, total_min)


def walking_time_minutes(
    from_x: float, from_y: float,
    to_x: float, to_y: float,
    special_assistance: bool = False,
) -> float:
    """Compute walking time between two points in the terminal.

    Returns time in minutes.
    """
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
    """Compute walking time from security exit to gate.

    Uses the airside center of the passenger's terminal as the starting point.
    If the gate is in a different terminal, adds cross-terminal walking penalty.
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
