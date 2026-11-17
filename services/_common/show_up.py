"""RC5 — per-passenger airport arrival ("show-up") and no-show model.

Shared by the seeder (draws ``show_up_at`` once per departing passenger) and
passenger-service (releases each passenger into check-in at their own time).
Replaces the old flight-wide step function (whole cohort checked in at T-120,
sent to security at T-45). See passenger SPEC §3 "Check-in queue".

    show_up_at = T - 180 min + 135 min × Beta(3, 2)      over [T-180, T-45]
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

SHOW_UP_WINDOW_START_MIN = 180   # earliest arrival, minutes before departure
SHOW_UP_WINDOW_END_MIN = 45      # check-in close
SHOW_UP_ALPHA = 3.0
SHOW_UP_BETA = 2.0
CHECKIN_PROCESS_MINUTES = 10     # check-in desk / bag drop before security
DEFAULT_NOSHOW_RATE = 0.03       # 2-4% no-show rate (default 3%)

_SPAN_MIN = SHOW_UP_WINDOW_START_MIN - SHOW_UP_WINDOW_END_MIN


def _naive(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def draw_show_up(scheduled: str | datetime, rng: random.Random) -> datetime:
    """Seed-time draw of one passenger's airport arrival time."""
    dep = _naive(scheduled)
    if dep is None:
        raise ValueError(f"invalid scheduled time: {scheduled!r}")
    fraction = rng.betavariate(SHOW_UP_ALPHA, SHOW_UP_BETA)
    at = dep - timedelta(minutes=SHOW_UP_WINDOW_START_MIN) + timedelta(minutes=_SPAN_MIN * fraction)
    # Minute resolution keeps the stored ISO string fixed-width ("…THH:MM:00").
    return at.replace(second=0, microsecond=0)


def _unit(passenger_id: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{passenger_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def show_up_time(
    passenger_id: str, scheduled: str | datetime | None, stored: str | datetime | None = None
) -> datetime | None:
    """A passenger's show-up time: the stored draw, else a deterministic one.

    Records seeded before RC5 have no ``show_up_at``; they get the same
    Beta(3,2) distribution from a hash of their ID, so restarts agree.
    """
    value = _naive(stored)
    if value is not None:
        return value
    dep = _naive(scheduled)
    if dep is None:
        return None
    rng = random.Random(int(_unit(passenger_id, "show-up") * 2**32))
    return draw_show_up(dep, rng)


def is_no_show(passenger_id: str, rate: float) -> bool:
    """Deterministic once-per-passenger no-show draw over the booked cohort."""
    return rate > 0 and _unit(passenger_id, "no-show") < rate


def security_due(show_up: datetime, scheduled: str | datetime | None, sim_time: datetime) -> bool:
    """Checked-in passenger joins security after processing, or at check-in close."""
    if sim_time >= show_up + timedelta(minutes=CHECKIN_PROCESS_MINUTES):
        return True
    dep = _naive(scheduled)
    return dep is not None and sim_time >= dep - timedelta(minutes=SHOW_UP_WINDOW_END_MIN)
