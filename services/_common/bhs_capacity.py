"""RC6 — size generated bag volume against baggage-handling capacity.

Two specs used to be tuned independently (bags per passenger in
SIMULATION.md, zone throughputs in baggage SPEC §3) and drifted to a 2.7×
structural deficit. This module is the one check both sides must pass:

    peak hourly bags ≤ capacity_headroom × min-stage capacity

per terminal and airport-wide (see SIMULATION.md "BHS sizing check").
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, Mapping

from _common.airport_config import BaggageSystemConfig


def terminal_of(flight: Mapping) -> str:
    """Terminal a departing flight's bags are inducted at (gate's terminal)."""
    gate = str(flight.get("gate_id") or "")
    return gate[0].upper() if gate[:1].isalpha() else "A"


def demand_by_terminal_hour(
    bags: Iterable[Mapping], flights_by_id: Mapping[str, Mapping]
) -> Counter:
    """Count departing bags by ``(terminal, scheduled departure hour)``."""
    demand: Counter = Counter()
    for bag in bags:
        flight = flights_by_id.get(bag.get("flight_id", ""))
        if not flight or not flight.get("scheduled_time"):
            continue
        hour = datetime.fromisoformat(str(flight["scheduled_time"])).hour
        demand[(terminal_of(flight), hour)] += 1
    return demand


def check_capacity(demand: Counter, cfg: BaggageSystemConfig) -> list[dict]:
    """Return one violation dict per terminal/airport peak above the headroom."""
    violations: list[dict] = []
    by_terminal: dict[str, Counter] = {}
    airport: Counter = Counter()
    for (terminal, hour), count in demand.items():
        by_terminal.setdefault(terminal, Counter())[hour] += count
        airport[hour] += count

    def _check(scope: str, hourly: Counter, capacity: int) -> None:
        if not hourly:
            return
        hour, peak = max(hourly.items(), key=lambda kv: kv[1])
        limit = cfg.capacity_headroom * capacity
        if peak > limit:
            violations.append({
                "scope": scope, "hour": hour, "peak_bags": peak,
                "capacity_hr": capacity, "limit": round(limit),
                "utilisation": round(peak / capacity, 3) if capacity else None,
            })

    for terminal in sorted(by_terminal):
        _check(terminal, by_terminal[terminal], cfg.terminal_min_stage_hr(terminal))
    _check("airport", airport, cfg.airport_min_stage_hr())
    return violations
