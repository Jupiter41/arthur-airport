"""Flight state machine — pure logic, no I/O.

9-state FSM with explicit transition rules. All transitions depend on
sim_time and contextual conditions (runway/gate availability, boarding %).

States: scheduled, boarding, delayed, departed, airborne, approach, landed, taxiing, at_gate
Terminal states: cancelled, at_gate (arrivals), airborne→completed (departures implicit)
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Wide-body aircraft types (longer turnaround buffer)
WIDE_BODY_TYPES = {"B77W", "A333", "A332", "B748", "A380"}

# Explicit valid transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"boarding", "delayed", "cancelled"},
    "boarding": {"departed", "delayed", "cancelled"},
    "delayed": {"boarding", "approach", "cancelled"},
    "departed": {"airborne"},
    "airborne": {"approach"},
    "approach": {"landed", "delayed"},
    "landed": {"taxiing"},
    "taxiing": {"at_gate"},
    "at_gate": set(),       # terminal state for arrivals
    "cancelled": set(),     # terminal state
}

# Terminal states — flights in these states are never processed by the FSM
TERMINAL_STATES = {"at_gate", "cancelled"}

# Active departure states (flight hasn't departed yet)
PRE_DEPARTURE_STATES = {"scheduled", "boarding", "delayed"}


def can_transition(current: str, target: str) -> bool:
    """Check if a transition from current to target is valid."""
    return target in VALID_TRANSITIONS.get(current, set())


def evaluate_transition(
    flight: dict,
    sim_time: datetime,
    runway_available: bool = True,
    gate_available: bool = True,
    boarded_pct: float = 1.0,
    has_hold: bool = False,
) -> str | None:
    """Evaluate whether a flight should transition to a new state.

    Pure function — no side effects. Returns the target state or None.

    Args:
        flight: dict with at least {status, direction, estimated_time, actual_time,
                delay_minutes, aircraft_type, gate_id}
        sim_time: current simulation time
        runway_available: whether a runway is available for this flight
        gate_available: whether the assigned gate is available
        boarded_pct: fraction of passengers boarded (0.0–1.0)
        has_hold: whether the flight is under manual hold
    """
    status = flight["status"]
    direction = flight.get("direction", "departure")

    if status in TERMINAL_STATES:
        return None

    estimated_time = _parse_time(flight.get("estimated_time"))
    if estimated_time is None:
        return None

    delay_minutes = flight.get("delay_minutes", 0) or 0

    match status:
        case "scheduled":
            return _eval_scheduled(flight, sim_time, estimated_time, direction, gate_available)

        case "boarding":
            return _eval_boarding(flight, sim_time, estimated_time, boarded_pct, has_hold, delay_minutes)

        case "delayed":
            return _eval_delayed(flight, sim_time, estimated_time, direction, has_hold, delay_minutes, runway_available)

        case "departed":
            return _eval_departed(flight, sim_time, estimated_time)

        case "airborne":
            return _eval_airborne(flight, sim_time, estimated_time, direction)

        case "approach":
            return _eval_approach(flight, sim_time, estimated_time, runway_available)

        case "landed":
            return _eval_landed(flight, sim_time)

        case "taxiing":
            return _eval_taxiing(flight, sim_time, gate_available)

    return None


def _parse_time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        # Strip timezone info to keep everything naive for comparison
        return value.replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _eval_scheduled(flight: dict, sim_time: datetime, estimated_time: datetime,
                    direction: str, gate_available: bool) -> str | None:
    # Departures: T-60 minutes -> boarding (if gate assigned)
    if direction == "departure":
        if sim_time >= estimated_time - timedelta(minutes=60):
            if flight.get("gate_id") and gate_available:
                return "boarding"
            elif not flight.get("gate_id"):
                return "boarding"  # will need gate assignment, consumer handles it
    # Arrivals: T-20 minutes -> approach
    else:
        if sim_time >= estimated_time - timedelta(minutes=20):
            return "approach"
    return None


def _eval_boarding(flight: dict, sim_time: datetime, estimated_time: datetime,
                   boarded_pct: float, has_hold: bool, delay_minutes: int) -> str | None:
    # Manual hold or weather/incident hold → delayed
    if has_hold:
        return "delayed"

    # Auto-cancel after 180 min delay
    if delay_minutes >= 180:
        return "cancelled"

    # Ready to depart: T-0 and boarding >= 95%
    if sim_time >= estimated_time and boarded_pct >= 0.95:
        return "departed"

    # If past departure time but not enough passengers, add delay and keep boarding
    # (the consumer loop will handle incrementing delay_minutes)
    return None


def _eval_delayed(flight: dict, sim_time: datetime, estimated_time: datetime,
                  direction: str, has_hold: bool, delay_minutes: int,
                  runway_available: bool) -> str | None:
    # Auto-cancel after 180 min delay
    if delay_minutes >= 180:
        return "cancelled"

    # Hold lifted → return to previous active state
    if not has_hold:
        if direction == "departure":
            return "boarding"
        else:
            # Arrival was in approach → return to approach
            if runway_available:
                return "approach"
    return None


def _eval_departed(flight: dict, sim_time: datetime, estimated_time: datetime) -> str | None:
    # T+5 minutes after departure → airborne
    if sim_time >= estimated_time + timedelta(minutes=5):
        return "airborne"
    return None


def _eval_airborne(flight: dict, sim_time: datetime, estimated_time: datetime,
                   direction: str) -> str | None:
    # Only arrivals approach — departures stay airborne (terminal for departures)
    if direction == "arrival":
        if sim_time >= estimated_time - timedelta(minutes=20):
            return "approach"
    return None


def _eval_approach(flight: dict, sim_time: datetime, estimated_time: datetime,
                   runway_available: bool) -> str | None:
    # At ETA, if runway available → landed
    if sim_time >= estimated_time:
        if runway_available:
            return "landed"
        else:
            return "delayed"  # enters holding stack
    return None


def _eval_landed(flight: dict, sim_time: datetime) -> str | None:
    actual_time = _parse_time(flight.get("actual_time"))
    if actual_time is None:
        return None
    # ATA + 2 minutes → taxiing
    if sim_time >= actual_time + timedelta(minutes=2):
        return "taxiing"
    return None


def _eval_taxiing(flight: dict, sim_time: datetime, gate_available: bool) -> str | None:
    actual_time = _parse_time(flight.get("actual_time"))
    if actual_time is None:
        return None
    # ATA + 8 minutes → at_gate (if gate available)
    if sim_time >= actual_time + timedelta(minutes=8) and gate_available:
        return "at_gate"
    return None
