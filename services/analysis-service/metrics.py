"""Prometheus metrics for analysis-service."""

from prometheus_client import Counter, Gauge, Histogram

# Bottleneck metrics
bottlenecks_active = Gauge(
    "analysis_bottlenecks_active",
    "Number of active bottlenecks",
    ["type", "severity"],
)

bottlenecks_detected_total = Counter(
    "analysis_bottlenecks_detected_total",
    "Total bottlenecks detected",
    ["type"],
)

# Recommendation metrics
recommendations_generated_total = Counter(
    "analysis_recommendations_generated_total",
    "Total recommendations generated",
    ["action_type"],
)

recommendations_applied_total = Counter(
    "analysis_recommendations_applied_total",
    "Total recommendations applied",
    ["action_type", "mode"],  # mode: manual | autonomous
)

# What-if metrics
whatif_queries_total = Counter(
    "analysis_whatif_queries_total",
    "Total what-if queries executed",
)

whatif_duration_seconds = Histogram(
    "analysis_whatif_duration_seconds",
    "What-if projection computation time",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

# Autonomous mode
autonomous_actions_total = Counter(
    "analysis_autonomous_actions_total",
    "Total autonomous actions taken",
    ["action_type"],
)

# Kafka consumer lag
consumer_lag = Gauge(
    "analysis_consumer_events_processed",
    "Events processed by the analysis consumer",
    ["topic"],
)

# Envelope errors
envelope_invalid_total = Counter(
    "analysis_envelope_invalid_total",
    "Invalid Kafka envelopes received",
)
