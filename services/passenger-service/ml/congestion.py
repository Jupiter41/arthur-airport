"""Congestion detection — consecutive tick counter + event emission.

If security wait exceeds threshold for N consecutive ticks, emit
SecurityCongestionDetected event.
"""

import os

THRESHOLD_MIN = int(os.getenv("SECURITY_CONGESTION_WAIT_THRESHOLD_MIN", "20"))
CONSECUTIVE = int(os.getenv("SECURITY_CONGESTION_CONSECUTIVE_TICKS", "5"))

_ticks_over_threshold: dict[str, int] = {"A": 0, "B": 0, "C": 0}


def check_congestion(terminal: str, wait_minutes: float) -> bool:
    """Check if congestion threshold has been exceeded for enough consecutive ticks.

    Returns True if SecurityCongestionDetected should be emitted.
    Resets counter after firing.
    """
    if wait_minutes > THRESHOLD_MIN:
        _ticks_over_threshold[terminal] += 1
    else:
        _ticks_over_threshold[terminal] = 0

    if _ticks_over_threshold[terminal] >= CONSECUTIVE:
        _ticks_over_threshold[terminal] = 0  # reset after firing
        return True
    return False


def get_ticks_over(terminal: str) -> int:
    """Get current count of consecutive ticks over threshold."""
    return _ticks_over_threshold.get(terminal, 0)
