"""Passenger state machine — departure + arrival flows.

Pure logic: no I/O, no Kafka, no Neo4j. Deterministic given inputs.
"""

import random
from hashlib import sha1
from datetime import datetime, timedelta


# --- Departure flow ---
# checked_in → security_queue → airside → at_gate → boarded

# --- Arrival flow ---
# airborne → deplaning → customs (international only) → baggage_claim → departed_airport


DEPARTURE_STATES = ["checked_in", "security_queue", "airside", "at_gate", "boarded"]
ARRIVAL_STATES = ["airborne", "deplaning", "customs", "baggage_claim", "departed_airport"]

INTERNATIONAL_FLIGHT_TYPES = {"international_short", "international_long"}

CHECKIN_CUTOFF_MINUTES = 45
GATE_OPEN_MINUTES = 30
BOARDING_CALL_MINUTES = 20
BOARDING_RATE_PAX_PER_MIN = 10
DEPLANING_DELAY_MINUTES = 15
CUSTOMS_DELAY_MINUTES = 10
BAGGAGE_CLAIM_TIMEOUT_MINUTES = 45


def _to_naive_dt(value: str | datetime | None) -> datetime | None:
    """Convert ISO string or datetime to a timezone-naive datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def sample_dwell_minutes() -> int:
    """Sample per-passenger dwell time in airside zone."""
    raw = random.gauss(mu=25, sigma=12)
    return int(max(5, min(90, raw)))


def should_move_to_security_queue(
    sim_time: datetime,
    scheduled_time: str | datetime,
) -> bool:
    """Check if passengers on this flight should move to security queue.
    Trigger: sim_time >= scheduled_time - 45min (check-in cutoff).
    """
    scheduled_dt = _to_naive_dt(scheduled_time)
    if scheduled_dt is None:
        return False
    cutoff = scheduled_dt - timedelta(minutes=CHECKIN_CUTOFF_MINUTES)
    return sim_time >= cutoff


def should_move_to_at_gate(
    sim_time: datetime,
    estimated_time: str | datetime,
    dwell_minutes: int | None,
    airside_at: str | datetime | None,
    walking_minutes: float = 0.0,
) -> bool:
    """Check if a passenger in airside should move to gate.
    Trigger: sim_time >= gate_open_time (T-30) AND dwell + walking time elapsed.
    """
    estimated_dt = _to_naive_dt(estimated_time)
    if estimated_dt is None:
        return False
    gate_open = estimated_dt - timedelta(minutes=GATE_OPEN_MINUTES)

    if sim_time < gate_open:
        return False

    # Check dwell time + walking time elapsed
    if dwell_minutes is not None and airside_at is not None:
        airside_dt = _to_naive_dt(airside_at)
        if airside_dt is None:
            return False
        dwell_end = airside_dt + timedelta(minutes=dwell_minutes + walking_minutes)
        return sim_time >= dwell_end

    # No dwell info: move immediately when gate opens
    return True


def compute_boarding_batch_size(sim_minutes_elapsed: int = 1) -> int:
    """How many passengers board per tick (1 tick = 1 sim-minute)."""
    return BOARDING_RATE_PAX_PER_MIN * sim_minutes_elapsed


def should_start_boarding(
    sim_time: datetime,
    estimated_time: str | datetime,
    flight_status: str,
) -> bool:
    """Check if boarding should start (T-20 min before departure)."""
    if flight_status not in ("boarding", "scheduled", "delayed"):
        return False
    estimated_dt = _to_naive_dt(estimated_time)
    if estimated_dt is None:
        return False
    boarding_time = estimated_dt - timedelta(minutes=BOARDING_CALL_MINUTES)
    return sim_time >= boarding_time


def should_move_to_baggage_claim(
    sim_time: datetime,
    deplaning_at: str | datetime | None,
) -> bool:
    """Arrival: move from deplaning to baggage_claim T+15 min after deplaning started."""
    if deplaning_at is None:
        return False
    deplaning_dt = _to_naive_dt(deplaning_at)
    if deplaning_dt is None:
        return False
    return sim_time >= deplaning_dt + timedelta(minutes=DEPLANING_DELAY_MINUTES)


def should_clear_customs(
    sim_time: datetime,
    customs_at: str | datetime | None,
) -> bool:
    """Arrival: move from customs to baggage_claim T+10 min after customs started."""
    if customs_at is None:
        return False
    customs_dt = _to_naive_dt(customs_at)
    if customs_dt is None:
        return False
    return sim_time >= customs_dt + timedelta(minutes=CUSTOMS_DELAY_MINUTES)


def is_international_flight(flight_type: str | None) -> bool:
    """Return True if this flight type requires customs/passport control."""
    return flight_type in INTERNATIONAL_FLIGHT_TYPES


def should_depart_airport(
    sim_time: datetime,
    baggage_claim_at: str | datetime | None,
    baggage_collected: bool = False,
) -> bool:
    """Arrival: depart airport when baggage collected OR timeout (T+45)."""
    if baggage_collected:
        return True
    if baggage_claim_at is None:
        return False
    baggage_claim_dt = _to_naive_dt(baggage_claim_at)
    if baggage_claim_dt is None:
        return False
    return sim_time >= baggage_claim_dt + timedelta(minutes=BAGGAGE_CLAIM_TIMEOUT_MINUTES)


def get_terminal_from_gate(gate_id: str | None, terminal_id: str | None) -> str:
    """Extract terminal letter from gate or terminal_id."""
    if gate_id and len(gate_id) >= 1:
        first = str(gate_id)[0].upper()
        if first in ("A", "B", "C"):
            return first

    if terminal_id:
        tid = str(terminal_id).strip().upper()
        if tid in ("A", "B", "C"):
            return tid
        if tid.startswith("T-") and len(tid) >= 3 and tid[-1] in ("A", "B", "C"):
            return tid[-1]
        if "TERMINAL" in tid:
            for t in ("A", "B", "C"):
                if tid.endswith(t):
                    return t

    return "A"


def get_terminal_for_flight(gate_id: str | None, terminal_id: str | None, flight_id: str | None) -> str:
    """Get terminal for a flight. Falls back to hash-based distribution if no gate assigned."""
    if gate_id or terminal_id:
        return get_terminal_from_gate(gate_id, terminal_id)

    # No gate assigned yet — use stable hash for deterministic distribution.
    if flight_id:
        terminals = ["A", "B", "C"]
        digest = sha1(str(flight_id).encode("utf-8")).digest()
        return terminals[digest[0] % 3]

    return "A"


def zone_for_status(status: str, terminal: str, gate_id: str | None = None) -> str:
    """Determine location_zone string for a given status."""
    match status:
        case "checked_in":
            return f"check-in-{terminal}"
        case "security_queue":
            return f"security-{terminal}"
        case "airside":
            return f"airside-{terminal}"
        case "at_gate":
            return f"gate-{gate_id}" if gate_id else f"airside-{terminal}"
        case "boarded":
            return f"gate-{gate_id}" if gate_id else f"airside-{terminal}"
        case "deplaning":
            return f"gate-{gate_id}" if gate_id else "arrivals-hall"
        case "customs":
            return "customs"
        case "baggage_claim":
            return "baggage-claim"
        case "departed_airport":
            return "arrivals-hall"
        case _:
            return f"airside-{terminal}"
