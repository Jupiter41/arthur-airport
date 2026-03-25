"""Passenger state machine — departure + arrival flows.

Pure logic: no I/O, no Kafka, no Neo4j. Deterministic given inputs.
"""

import random
from hashlib import sha1
from datetime import datetime, timedelta


# --- Departure flow ---
# checked_in → security_queue → airside → at_gate → boarded

# --- Arrival flow ---
# airborne → deplaning → baggage_claim → departed_airport


DEPARTURE_STATES = ["checked_in", "security_queue", "airside", "at_gate", "boarded"]
ARRIVAL_STATES = ["airborne", "deplaning", "baggage_claim", "departed_airport"]

CHECKIN_CUTOFF_MINUTES = 45
GATE_OPEN_MINUTES = 30
BOARDING_CALL_MINUTES = 20
BOARDING_RATE_PAX_PER_MIN = 10
DEPLANING_DELAY_MINUTES = 15
BAGGAGE_CLAIM_TIMEOUT_MINUTES = 45


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
    if isinstance(scheduled_time, str):
        scheduled_time = datetime.fromisoformat(str(scheduled_time)).replace(tzinfo=None)
    cutoff = scheduled_time - timedelta(minutes=CHECKIN_CUTOFF_MINUTES)
    return sim_time >= cutoff


def should_move_to_at_gate(
    sim_time: datetime,
    estimated_time: str | datetime,
    dwell_minutes: int | None,
    airside_at: str | datetime | None,
) -> bool:
    """Check if a passenger in airside should move to gate.
    Trigger: sim_time >= gate_open_time (T-30) AND dwell elapsed.
    """
    if isinstance(estimated_time, str):
        estimated_time = datetime.fromisoformat(str(estimated_time)).replace(tzinfo=None)
    gate_open = estimated_time - timedelta(minutes=GATE_OPEN_MINUTES)

    if sim_time < gate_open:
        return False

    # Check dwell time elapsed
    if dwell_minutes is not None and airside_at is not None:
        if isinstance(airside_at, str):
            airside_at = datetime.fromisoformat(str(airside_at)).replace(tzinfo=None)
        dwell_end = airside_at + timedelta(minutes=dwell_minutes)
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
    if isinstance(estimated_time, str):
        estimated_time = datetime.fromisoformat(str(estimated_time)).replace(tzinfo=None)
    boarding_time = estimated_time - timedelta(minutes=BOARDING_CALL_MINUTES)
    return sim_time >= boarding_time


def should_move_to_baggage_claim(
    sim_time: datetime,
    deplaning_at: str | datetime | None,
) -> bool:
    """Arrival: move from deplaning to baggage_claim T+15 min after deplaning started."""
    if deplaning_at is None:
        return False
    if isinstance(deplaning_at, str):
        deplaning_at = datetime.fromisoformat(str(deplaning_at)).replace(tzinfo=None)
    return sim_time >= deplaning_at + timedelta(minutes=DEPLANING_DELAY_MINUTES)


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
    if isinstance(baggage_claim_at, str):
        baggage_claim_at = datetime.fromisoformat(str(baggage_claim_at)).replace(tzinfo=None)
    return sim_time >= baggage_claim_at + timedelta(minutes=BAGGAGE_CLAIM_TIMEOUT_MINUTES)


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
        case "baggage_claim":
            return "baggage-claim"
        case "departed_airport":
            return "arrivals-hall"
        case _:
            return f"airside-{terminal}"
