"""Prometheus metrics for flight-service."""

from prometheus_client import Counter, Gauge, Histogram

flight_status_transitions_total = Counter(
    "flight_status_transitions_total",
    "All state transitions",
    ["from_status", "to_status"],
)

flights_active = Gauge(
    "flights_active",
    "Active flights per status",
    ["status"],
)

flights_delayed_current = Gauge(
    "flights_delayed_current",
    "Currently delayed flights",
)

flights_cancelled_total = Counter(
    "flights_cancelled_total",
    "Cancellations by reason",
    ["reason"],
)

runway_queue_depth = Gauge(
    "runway_queue_depth",
    "Queue depth per runway",
    ["runway_id", "direction"],
)

runway_capacity_per_hour = Gauge(
    "runway_capacity_per_hour",
    "Current capacity per runway",
    ["runway_id", "direction"],
)

cascade_depth = Histogram(
    "cascade_depth",
    "Delay cascade chain depth",
    buckets=[1, 2, 3, 4, 5],
)

gate_conflicts_resolved_total = Counter(
    "gate_conflicts_resolved_total",
    "Gate reassignments",
)

turnaround_delay_minutes = Histogram(
    "turnaround_delay_minutes",
    "Turnaround delay distribution",
    ["aircraft_type"],
    buckets=[5, 10, 15, 30, 45, 60, 90, 120],
)
