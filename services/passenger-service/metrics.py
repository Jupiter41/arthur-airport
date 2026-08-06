"""Prometheus metrics for passenger-service."""

from prometheus_client import Counter, Gauge

passengers_in_airport = Gauge(
    "passengers_in_airport",
    "Pax count per status",
    ["status"],
)

security_queue_depth = Gauge(
    "security_queue_depth",
    "Queue depth per checkpoint",
    ["terminal"],
)

security_wait_minutes = Gauge(
    "security_wait_minutes",
    "Estimated wait per terminal",
    ["terminal"],
)

security_lanes_open = Gauge(
    "security_lanes_open",
    "Open lanes per terminal",
    ["terminal"],
)

connections_at_risk = Gauge(
    "connections_at_risk",
    "Connections by risk level",
    ["risk_level"],
)

connections_missed_total = Counter(
    "connections_missed_total",
    "Cumulative missed connections",
)

passenger_alerts_total = Counter(
    "passenger_alerts_total",
    "Alerts by type",
    ["type"],
)

zone_load_pct = Gauge(
    "zone_load_pct",
    "Load percent per zone",
    ["zone_id"],
)

envelope_invalid_total = Counter(
    "envelope_invalid_total",
    "Rejected Kafka envelopes",
    ["reason"],
)

pax_commands_total = Counter(
    "pax_commands_total",
    "passengers.commands consumed by command_type and outcome (accepted/rejected)",
    ["command_type", "outcome"],
)
