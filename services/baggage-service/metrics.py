"""Prometheus metrics for baggage-service."""

from prometheus_client import Counter, Gauge

baggage_in_system = Gauge(
    "baggage_in_system",
    "Items per status",
    ["status"],
)

baggage_flagged_active = Gauge(
    "baggage_flagged_active",
    "Currently flagged items",
)

conveyor_zone_utilisation_pct = Gauge(
    "conveyor_zone_utilisation_pct",
    "Utilisation per zone",
    ["zone_id"],
)

conveyor_zone_status = Gauge(
    "conveyor_zone_status",
    "0=normal 1=degraded 2=offline",
    ["zone_id"],
)

baggage_transitions_total = Counter(
    "baggage_transitions_total",
    "Status transitions",
    ["from_status", "to_status"],
)

dangerous_goods_detected_total = Counter(
    "dangerous_goods_detected_total",
    "DG detections by class",
    ["dg_class"],
)

screening_false_positives_total = Counter(
    "screening_false_positives_total",
    "False positive detections",
)

baggage_offloaded_total = Counter(
    "baggage_offloaded_total",
    "Offloads by reason",
    ["reason"],
)
