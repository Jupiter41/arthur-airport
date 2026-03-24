"""Prometheus metrics for sim-orchestrator."""

from prometheus_client import Counter, Gauge, Histogram

sim_tick_total = Counter(
    "sim_tick_total",
    "Total clock ticks emitted",
)

sim_tick_latency_ms = Histogram(
    "sim_tick_latency_ms",
    "Real time per tick in milliseconds",
    buckets=[10, 50, 100, 500],
)

sim_speed_multiplier = Gauge(
    "sim_speed_multiplier",
    "Current speed setting",
)

sim_day_number = Gauge(
    "sim_day_number",
    "Current simulated day",
)

sim_paused = Gauge(
    "sim_paused",
    "1 if paused, 0 if running",
)

sim_events_injected_total = Counter(
    "sim_events_injected_total",
    "Probabilistic events fired",
    ["type"],
)
