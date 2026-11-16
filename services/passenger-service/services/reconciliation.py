"""Pure recovery rules for passengers whose flight facts were missed."""
from datetime import datetime, timezone

PHYSICAL_STATUSES = (
    "checked_in", "security_queue", "airside", "at_gate", "deplaning",
    "customs", "baggage_claim", "disrupted",
)
FORWARD_FLIGHT_STATUSES = (
    "scheduled", "boarding", "delayed", "departed", "airborne",
    "approach", "landed", "taxiing", "at_gate",
)
# RC5: a departing passenger only progresses toward a flight still on the ground
# and open. Nobody checks in, clears to the gate or boards after departure.
PRE_DEPARTURE_FLIGHT_STATUSES = ("scheduled", "boarding", "delayed")
# Statuses that become ``missed_flight`` when the flight departs without them.
MISSED_FLIGHT_STATUSES = ("booked", "checked_in", "security_queue", "airside", "at_gate")


def reconciliation_transition(pax: dict, sim_time: datetime) -> tuple[str, str] | None:
    """Return current airport disposition, without inventing historical boarding."""
    value = pax.get("actual_time") or pax.get("scheduled_time")
    try:
        observed = datetime.fromisoformat(str(value))
        if observed.tzinfo is not None:
            observed = observed.astimezone(timezone.utc).replace(tzinfo=None)
        now = sim_time
        if now.tzinfo is not None:
            now = now.astimezone(timezone.utc).replace(tzinfo=None)
        if observed > now:
            return None
    except (TypeError, ValueError):
        return None
    status, flight = pax.get("status"), pax.get("flight_status")
    if pax.get("direction") == "departure":
        left = flight in ("departed", "airborne", "approach", "landed", "taxiing",
                          "at_gate", "arrived", "completed")
        if left and status in MISSED_FLIGHT_STATUSES:
            # RC5: the aircraft left without them — never board them afterwards.
            return "missed_flight", "missed-flight"
        if flight in ("arrived", "completed") and status in ("boarded", "airborne"):
            return "departed_airport", "flight-finished"
        if flight in ("departed", "airborne") and status == "boarded":
            return "departed_airport", "departed"
    elif pax.get("direction") == "arrival":
        if status in ("airborne", "booked", "checked_in", "boarded"):
            if flight in ("at_gate", "arrived", "completed"):
                return "deplaning", "arrivals-hall"
            if flight == "diverted":
                return "departed_airport", "diverted"
    return None
