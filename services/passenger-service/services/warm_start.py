"""Per-passenger warm start for a fresh simulation (RC5 follow-up).

A simulation that starts at 06:00 finds every passenger whose ``show_up_at``
is already past still ``booked``. Releasing them all on the first tick dumped
≈4,100 passengers into check-in and security at once and backed security up
for about three sim-hours. Instead, each of them is placed where their own
free-flow timeline puts them at the start time (passenger SPEC "Warm start").

Pure: no I/O. The consumer turns the placements into one tick contribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from _common.show_up import (
    CHECKIN_PROCESS_MINUTES, SHOW_UP_WINDOW_END_MIN, is_no_show, show_up_time,
)

from services.state_machine import (
    BOARDING_CALL_MINUTES, BOARDING_RATE_PAX_PER_MIN, GATE_OPEN_MINUTES,
)

WARM_SECURITY_MINUTES = 5      # free-flow time through a security lane


@dataclass(frozen=True)
class Placement:
    passenger_id: str
    status: str                 # checked_in | security_queue | airside | at_gate | boarded | departed_airport
    dwell_remaining: int = 0    # airside only: minutes left before walking to the gate


def _naive(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def place_departures(
    rows: Iterable[dict],
    sim_time: datetime,
    noshow_rate: float,
    dwell_minutes: Callable[[str], int],
) -> list[Placement]:
    """Place each due ``booked`` departure passenger on their own timeline.

    ``rows`` carry ``id``, ``flight_id``, ``scheduled_time`` (or
    ``estimated_time``) and ``show_up_at``. Passengers not yet due are omitted
    (they stay ``booked`` for the normal check-in rule).
    """
    now = sim_time.replace(tzinfo=None)
    placements: list[Placement] = []
    # Per flight: (gate_arrival, pid) of passengers at the gate or beyond, so
    # boarding slots follow gate-arrival order at the boarding rate.
    gate_queue: dict[str, list[tuple[datetime, str, datetime]]] = {}

    for pax in rows:
        pid = pax["id"]
        dep = _naive(pax.get("scheduled_time") or pax.get("estimated_time"))
        show = show_up_time(pid, dep, pax.get("show_up_at"))
        if dep is None or show is None or now < show:
            continue
        if is_no_show(pid, noshow_rate):
            placements.append(Placement(pid, "departed_airport"))
            continue
        security_in = min(show + timedelta(minutes=CHECKIN_PROCESS_MINUTES),
                          dep - timedelta(minutes=SHOW_UP_WINDOW_END_MIN))
        security_in = max(security_in, show)
        if now < security_in:
            placements.append(Placement(pid, "checked_in"))
            continue
        airside_at = security_in + timedelta(minutes=WARM_SECURITY_MINUTES)
        if now < airside_at:
            placements.append(Placement(pid, "security_queue"))
            continue
        dwell = max(0, int(dwell_minutes(pid)))
        at_gate = max(dep - timedelta(minutes=GATE_OPEN_MINUTES),
                      airside_at + timedelta(minutes=dwell))
        if now < at_gate:
            elapsed = int((now - airside_at).total_seconds() // 60)
            placements.append(Placement(pid, "airside", max(0, dwell - elapsed)))
            continue
        gate_queue.setdefault(pax.get("flight_id") or "", []).append((at_gate, pid, dep))

    for entries in gate_queue.values():
        entries.sort()
        for rank, (_, pid, dep) in enumerate(entries):
            slot = dep - timedelta(minutes=BOARDING_CALL_MINUTES) \
                + timedelta(minutes=rank / BOARDING_RATE_PAX_PER_MIN)
            placements.append(Placement(pid, "boarded" if now >= slot else "at_gate"))
    return placements
