"""Baggage conveyor spatial model — inter-terminal transit times.

Computes conveyor transit time based on the source terminal (check-in or
arrival) and destination terminal (gate make-up or arrival carousel).

Time model per segment (from ROADMAP.md):
  Check-in desk → induction belt:               2 min
  Induction belt → screening (same terminal):    3 min
  Screening:                                     2 min/item
  Screening → sorting matrix:                    2 min
  Sorting matrix → make-up (same terminal):      4 min
  Sorting matrix → make-up (adjacent terminal):  8 min
  Sorting matrix → make-up (far terminal):      12 min
  Loading from make-up to aircraft hold:         5–8 min
"""

# Terminal adjacency: A-B adjacent, B-C adjacent, A-C far
_TERMINAL_ORDER = {"A": 0, "B": 1, "C": 2}

# Transit time from sorting matrix to make-up, by terminal distance
SORTING_TO_MAKEUP_SAME = 4       # minutes, same terminal
SORTING_TO_MAKEUP_ADJACENT = 8   # minutes, adjacent terminal (A↔B, B↔C)
SORTING_TO_MAKEUP_FAR = 12       # minutes, far terminal (A↔C)


def terminal_distance(from_terminal: str, to_terminal: str) -> int:
    """Return abstract distance: 0 = same, 1 = adjacent, 2 = far."""
    a = _TERMINAL_ORDER.get(from_terminal, 0)
    b = _TERMINAL_ORDER.get(to_terminal, 0)
    return abs(a - b)


def sorting_to_makeup_minutes(from_terminal: str, to_terminal: str) -> float:
    """Transit time from sorting matrix to make-up carousel."""
    d = terminal_distance(from_terminal, to_terminal)
    if d == 0:
        return SORTING_TO_MAKEUP_SAME
    elif d == 1:
        return SORTING_TO_MAKEUP_ADJACENT
    else:
        return SORTING_TO_MAKEUP_FAR


def bag_conveyor_time(
    checkin_terminal: str,
    gate_terminal: str,
) -> float:
    """Total conveyor time (minutes) from check-in to gate make-up.

    Sums: induction (2) + screening transit (3) + screening (2) +
          screening→sorting (2) + sorting→make-up (variable).
    """
    fixed_segments = 2 + 3 + 2 + 2  # induction + to_screening + screening + to_sorting
    transit = sorting_to_makeup_minutes(checkin_terminal, gate_terminal)
    return fixed_segments + transit


def arrival_carousel_for_terminal(terminal: str) -> list[int]:
    """Return carousel numbers for a terminal's arrival belts.

    A → carousels 1-2, B → 3-4, C → 5-6.
    """
    mapping = {"A": [1, 2], "B": [3, 4], "C": [5, 6]}
    return mapping.get(terminal, [1, 2])
