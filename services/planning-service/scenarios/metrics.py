"""Planning service metrics — tracks run timing for estimation and Prometheus."""

from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from prometheus_client import Counter, Gauge, Histogram


@dataclass
class RunTimingSample:
    """A single timing sample from a completed scenario run."""

    horizon: str
    monte_carlo_runs: int
    sim_days: int
    duration_seconds: float
    timestamp: float = field(default_factory=time.monotonic)


class PlanningMetrics:
    """Tracks run timing for estimation and exposes Prometheus metrics."""

    def __init__(self, max_samples: int = 200):
        self._samples: deque[RunTimingSample] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

        # Prometheus metrics
        self.scenarios_created = Counter(
            "planning_scenarios_created_total",
            "Total planning scenarios created",
            ["template"],
        )
        self.scenarios_completed = Counter(
            "planning_scenarios_completed_total",
            "Total planning scenarios completed",
            ["status"],
        )
        self.scenario_duration = Histogram(
            "planning_scenario_duration_seconds",
            "Time to complete a planning scenario",
            buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800],
        )
        self.active_scenarios = Gauge(
            "planning_active_scenarios",
            "Number of currently running scenarios",
        )
        self.mc_runs_total = Counter(
            "planning_mc_runs_total",
            "Total Monte Carlo individual runs executed",
        )

    def record_completion(
        self,
        horizon: str,
        monte_carlo_runs: int,
        sim_days: int,
        duration_seconds: float,
    ) -> None:
        """Record a completed scenario's timing for future estimation."""
        sample = RunTimingSample(
            horizon=horizon,
            monte_carlo_runs=monte_carlo_runs,
            sim_days=sim_days,
            duration_seconds=duration_seconds,
        )
        with self._lock:
            self._samples.append(sample)

        self.scenario_duration.observe(duration_seconds)
        self.scenarios_completed.labels(status="completed").inc()
        self.mc_runs_total.inc(monte_carlo_runs * 2)  # baseline + scenario

    def record_failure(self) -> None:
        self.scenarios_completed.labels(status="failed").inc()

    def estimate_duration(self, horizon: str, monte_carlo_runs: int) -> dict:
        """Estimate scenario duration based on historical runs.

        Returns a dict with estimated seconds, confidence, and method used.
        """
        from scenarios.runner import _horizon_to_days

        sim_days = min(_horizon_to_days(horizon), 30)
        total_day_runs = sim_days * monte_carlo_runs * 2  # ×2 for baseline

        with self._lock:
            samples = list(self._samples)

        if not samples:
            # Default heuristic: ~0.15s per day-run (conservative)
            est = total_day_runs * 0.15
            return {
                "estimated_seconds": round(est, 1),
                "confidence": "low",
                "method": "heuristic",
                "per_day_run_ms": 150,
                "total_day_runs": total_day_runs,
                "human_readable": _format_duration(est),
            }

        # Calculate per-day-run timing from historical data
        rates = []
        for s in samples:
            day_runs = s.sim_days * s.monte_carlo_runs * 2
            if day_runs > 0:
                rates.append(s.duration_seconds / day_runs)

        if not rates:
            est = total_day_runs * 0.15
            return {
                "estimated_seconds": round(est, 1),
                "confidence": "low",
                "method": "heuristic",
                "per_day_run_ms": 150,
                "total_day_runs": total_day_runs,
                "human_readable": _format_duration(est),
            }

        avg_rate = statistics.mean(rates)
        est = total_day_runs * avg_rate

        confidence = "high" if len(rates) >= 5 else "medium"

        return {
            "estimated_seconds": round(est, 1),
            "confidence": confidence,
            "method": "historical",
            "samples_used": len(rates),
            "per_day_run_ms": round(avg_rate * 1000, 1),
            "total_day_runs": total_day_runs,
            "human_readable": _format_duration(est),
        }

    def get_timing_stats(self) -> dict:
        """Get overall timing statistics."""
        with self._lock:
            samples = list(self._samples)

        if not samples:
            return {"total_runs": 0, "avg_per_day_run_ms": 150}

        rates = []
        for s in samples:
            day_runs = s.sim_days * s.monte_carlo_runs * 2
            if day_runs > 0:
                rates.append(s.duration_seconds / day_runs)

        return {
            "total_runs": len(samples),
            "avg_per_day_run_ms": round(statistics.mean(rates) * 1000, 1) if rates else 150,
            "min_per_day_run_ms": round(min(rates) * 1000, 1) if rates else 0,
            "max_per_day_run_ms": round(max(rates) * 1000, 1) if rates else 0,
        }


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 1:
        return "< 1 second"
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f} minutes"
    hours = minutes / 60
    return f"{hours:.1f} hours"


# Module-level singleton
planning_metrics = PlanningMetrics()
