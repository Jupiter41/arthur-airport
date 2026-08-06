"""Pure transition decisions — no I/O, no in-memory state, no RNG.

These functions were extracted verbatim (behaviour-preserving) from the
side-effect-heavy ``_process_flight`` / ``_execute_transition`` in
``kafka/consumer.py``. Keeping them pure lets the FSM-adjacent business rules be
unit-tested directly, without mocking Neo4j, Kafka, or the consumer's global
state. The consumer (the adapter) gathers the inputs and applies the effects;
the *decision* lives here.
"""

from __future__ import annotations

from datetime import datetime

# Delay reasons produced by the noise model (Phase 1.2). When a boarding flight
# accrues incomplete-boarding delay, an existing noise reason must not be
# clobbered by the generic "boarding_incomplete" label.
NOISE_DELAY_REASONS: frozenset[str] = frozenset(
    {"crew_readiness", "ctot_slot", "equipment_failure"}
)


def suppress_transition_for_turnaround(
    new_status: str | None,
    direction: str,
    *,
    deplaning_done: bool,
    ready_for_boarding: bool,
) -> bool:
    """Whether a proposed transition must wait on turnaround progress.

    Call this only when the aircraft has an active turnaround plan; the two
    readiness flags come from that plan.

    - An arrival cannot reach ``arrived`` until deplaning has completed.
    - A departure cannot (re-)enter ``boarding`` until the aircraft is cleaned
      and ready for boarding.

    Returns True if the transition should be held back this tick.
    """
    if new_status == "arrived" and direction == "arrival" and not deplaning_done:
        return True
    if new_status == "boarding" and direction == "departure" and not ready_for_boarding:
        return True
    return False


def resolve_delay_reason(
    base_reason: str | None,
    *,
    is_held: bool,
    hold_reason: str | None,
    runway_incident: bool,
    gate_incident: bool,
) -> str:
    """Resolve the delay_reason to record when a flight transitions to delayed.

    Priority: a manual/weather hold wins, then a runway incident, then a gate
    incident, then whatever reason the flight already carried, defaulting to
    ``operational``.
    """
    if is_held:
        return hold_reason or "manual_hold"
    if runway_incident:
        return "runway_incident"
    if gate_incident:
        return "gate_incident"
    return base_reason or "operational"


def boarding_delay_update(
    current_status: str,
    direction: str,
    scheduled: datetime | str | None,
    sim_time: datetime,
    boarded_pct: float,
    current_delay_minutes: int,
    current_reason: str | None,
) -> tuple[int, str] | None:
    """Delay to record for a boarding departure that is past its scheduled time.

    Mirrors the consumer's delay-accumulation branch: when a departure is still
    boarding after its *scheduled* time and boarding is below the 95% ready
    threshold, delay_minutes should track the elapsed minutes since schedule.
    Uses scheduled_time (not estimated_time) so noise-model delays that push
    estimated_time forward don't stall the counter.

    Returns ``(new_delay_minutes, reason)`` when the delay should be bumped, or
    ``None`` when there is nothing to update (wrong state, unparseable time, not
    yet past schedule, boarding effectively complete, or no increase).
    """
    if current_status != "boarding" or direction != "departure":
        return None
    if scheduled is None:
        return None

    sched = _parse_time(scheduled)
    if sched is None:
        return None

    if sim_time > sched and boarded_pct < 0.95:
        delay = int((sim_time - sched).total_seconds() / 60)
        if delay > (current_delay_minutes or 0):
            reason = (
                current_reason
                if current_reason in NOISE_DELAY_REASONS
                else "boarding_incomplete"
            )
            return delay, reason
    return None


def _parse_time(value: datetime | str) -> datetime | None:
    """Parse an ISO timestamp to a naive datetime, or None if unparseable.

    Matches the consumer's original ``datetime.fromisoformat(str(...))`` inside
    a try/except; timezone info is dropped for naive comparison against
    sim_time.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None
