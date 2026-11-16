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
        if flight in ("arrived", "completed") and status in (
            "booked", "checked_in", "security_queue", "airside", "at_gate", "boarded", "airborne",
        ):
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
