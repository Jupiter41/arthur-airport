"""Baggage warm start for a fresh simulation (RC6 follow-up).

A simulation that starts at 06:00 finds every departing bag still
``dropped_off``, including the bags of passengers who, on their own timeline,
checked in hours ago. Inducting them all on the first ticks put ≈6,600 bags
into a BHS sized for ≈6,600/h airport-wide, so the 05:00–08:59 departures
short-shipped 36–74% of their bags (live, fresh stack).

Mirrors the passenger warm start: each bag is placed where its passenger's
free-flow timeline puts it at the start time. A bag dropped long enough ago to
have cleared the BHS is ``loaded`` with its full induction → screening →
sorting → make-up scan trail (so the RC6 "no unscreened bag in a hold"
invariant holds); anything dropped more recently stays ``dropped_off`` for the
normal, capacity-limited induction. No-show passengers never dropped a bag.

Pure: no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from _common.show_up import CHECKIN_PROCESS_MINUTES, DEFAULT_NOSHOW_RATE, is_no_show, show_up_time

# Free-flow time from bag drop to the make-up carousel exit (induction,
# screening, sorting and make-up at an idle BHS).
WARM_BHS_MINUTES = 20


@dataclass(frozen=True)
class BagPlacement:
    baggage_id: str
    flight_id: str
    terminal: str
    trail: tuple[tuple[str, str], ...]   # (status, zone) in order; the last is the final state


def _naive(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def trail_for(terminal: str, index: int) -> tuple[tuple[str, str], ...]:
    from services.conveyor import TERMINAL_MAKEUP, TERMINAL_SCREENING
    units = TERMINAL_SCREENING.get(terminal, TERMINAL_SCREENING["A"])
    carousels = TERMINAL_MAKEUP.get(terminal, TERMINAL_MAKEUP["A"])
    return (
        ("inducted", f"induction-{terminal}"),
        ("screening", units[index % len(units)]),
        ("sorting", "sorting-matrix"),
        ("loaded", carousels[index % len(carousels)]),
    )


def place_bags(rows: Iterable[dict], sim_time: datetime,
               noshow_rate: float = DEFAULT_NOSHOW_RATE) -> list[BagPlacement]:
    """Bags whose passenger's timeline already cleared the BHS at ``sim_time``.

    ``rows`` carry ``id``, ``flight_id``, ``passenger_id``, ``scheduled_time``
    (or ``estimated_time``), ``show_up_at`` and ``terminal`` (A/B/C).
    """
    now = sim_time.replace(tzinfo=None)
    placements: list[BagPlacement] = []
    for index, bag in enumerate(rows):
        pid = bag.get("passenger_id")
        dep = _naive(bag.get("scheduled_time") or bag.get("estimated_time"))
        if not pid or dep is None or is_no_show(pid, noshow_rate):
            continue
        show = show_up_time(pid, dep, bag.get("show_up_at"))
        if show is None:
            continue
        dropped = show + timedelta(minutes=CHECKIN_PROCESS_MINUTES)
        if dropped + timedelta(minutes=WARM_BHS_MINUTES) > now:
            continue
        terminal = bag.get("terminal") or "A"
        placements.append(BagPlacement(bag["id"], bag["flight_id"], terminal,
                                       trail_for(terminal, index)))
    return placements
