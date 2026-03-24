"""Prometheus metrics for incident-service."""

from prometheus_client import Counter, Gauge, Histogram

incidents_active = Gauge(
    "incidents_active",
    "Active incidents",
    ["type", "severity"],
)

incidents_created_total = Counter(
    "incidents_created_total",
    "All incidents created",
    ["type", "severity", "trigger"],
)

incident_ttr_minutes = Histogram(
    "incident_ttr_minutes",
    "Time-to-resolve in minutes",
    ["type"],
    buckets=[5, 15, 30, 60, 120],
)

cascade_events_total = Counter(
    "cascade_events_total",
    "Child incidents spawned",
    ["parent_type"],
)

cascade_depth_max = Gauge(
    "cascade_depth_max",
    "Deepest active cascade",
)

protocols_activated_total = Counter(
    "protocols_activated_total",
    "Emergency protocols fired",
    ["protocol"],
)

flights_impacted_by_incidents_total = Counter(
    "flights_impacted_by_incidents_total",
    "Flights affected",
    ["incident_type"],
)
