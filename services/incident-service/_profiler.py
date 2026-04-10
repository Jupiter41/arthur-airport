"""Simulation tick performance profiler (P6-3).

Measures wall-clock time spent processing each SimClockTick and exposes
Prometheus metrics for tick budget utilisation monitoring.

Usage in kafka/consumer.py:
    from _profiler import tick_timer, update_speed

    with tick_timer():
        # ... process tick ...

    update_speed(speed_multiplier)  # call when speed changes
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from contextlib import contextmanager

from prometheus_client import Gauge, Histogram

logger = logging.getLogger(__name__)

_SERVICE = os.getenv("OTEL_SERVICE_NAME", "unknown")

# ── Prometheus metrics ──────────────────────────────────────

tick_processing_seconds = Histogram(
    "service_tick_processing_seconds",
    "Wall-clock time spent processing a single SimClockTick",
    ["service"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

tick_budget_utilisation_pct = Gauge(
    "service_tick_budget_utilisation_pct",
    "Percentage of tick budget consumed (100% = exactly real-time)",
    ["service"],
)

tick_processing_last_ms = Gauge(
    "service_tick_processing_last_ms",
    "Most recent tick processing time in milliseconds",
    ["service"],
)

# ── State ───────────────────────────────────────────────────

_speed: float = 60.0  # current sim speed multiplier
_recent: deque[float] = deque(maxlen=100)  # last 100 tick durations


def update_speed(speed: float) -> None:
    """Update the current simulation speed multiplier."""
    global _speed
    if speed > 0:
        _speed = speed


@contextmanager
def tick_timer():
    """Context manager to measure tick processing time.

    Updates Prometheus metrics and internal statistics.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        _recent.append(elapsed)

        tick_processing_seconds.labels(service=_SERVICE).observe(elapsed)
        tick_processing_last_ms.labels(service=_SERVICE).set(elapsed * 1000)

        # Budget utilisation: how much of the available real-time did we use?
        # At 60x speed, 1 sim-minute = 1 real second → budget = 1.0s
        # At 3600x, 1 sim-minute = ~16.7ms → budget is tight
        budget_seconds = 60.0 / max(_speed, 1.0)
        utilisation = (elapsed / budget_seconds) * 100.0 if budget_seconds > 0 else 0.0
        tick_budget_utilisation_pct.labels(service=_SERVICE).set(utilisation)


def get_perf_stats() -> dict:
    """Return recent tick processing statistics for the /perf endpoint."""
    if not _recent:
        return {
            "service": _SERVICE,
            "speed": _speed,
            "sample_count": 0,
            "avg_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "budget_ms": 60_000.0 / max(_speed, 1.0),
            "avg_utilisation_pct": 0.0,
        }

    sorted_times = sorted(_recent)
    n = len(sorted_times)
    avg = sum(sorted_times) / n
    budget = 60.0 / max(_speed, 1.0)

    return {
        "service": _SERVICE,
        "speed": _speed,
        "sample_count": n,
        "avg_ms": round(avg * 1000, 3),
        "p95_ms": round(sorted_times[int(n * 0.95)] * 1000, 3),
        "p99_ms": round(sorted_times[int(n * 0.99)] * 1000, 3),
        "max_ms": round(sorted_times[-1] * 1000, 3),
        "budget_ms": round(budget * 1000, 3),
        "avg_utilisation_pct": round((avg / budget) * 100, 2) if budget > 0 else 0.0,
    }
