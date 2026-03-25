"""Metric contract tests — validate metrics.py against MONITORING.md catalogue.

Verifies that:
1. Every expected metric family is defined in code with the correct type
2. Label names match expected dimensions
3. Label cardinality is bounded (no unbounded label sets)

Uses AST parsing (no imports, no registry collisions).
"""

import ast
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Expected metric catalogue (from MONITORING.md §3) ──────────

# Each entry: (metric_name, expected_type_str, frozenset_of_label_names)
# Label names match the CODE.

EXPECTED_METRICS: dict[str, list[tuple[str, str, frozenset[str]]]] = {
    "flight-service": [
        ("flight_status_transitions_total", "Counter", frozenset({"from_status", "to_status"})),
        ("flights_active", "Gauge", frozenset({"status"})),
        ("flights_delayed_current", "Gauge", frozenset()),
        ("flights_cancelled_total", "Counter", frozenset({"reason"})),
        ("runway_queue_depth", "Gauge", frozenset({"runway_id", "direction"})),
        ("runway_capacity_per_hour", "Gauge", frozenset({"runway_id", "direction"})),
        ("cascade_depth", "Histogram", frozenset()),
        ("gate_conflicts_resolved_total", "Counter", frozenset()),
        ("turnaround_delay_minutes", "Histogram", frozenset({"aircraft_type"})),
        ("envelope_invalid_total", "Counter", frozenset({"reason"})),
    ],
    "passenger-service": [
        ("passengers_in_airport", "Gauge", frozenset({"status"})),
        ("security_queue_depth", "Gauge", frozenset({"terminal"})),
        ("security_wait_minutes", "Gauge", frozenset({"terminal"})),
        ("security_lanes_open", "Gauge", frozenset({"terminal"})),
        ("connections_at_risk", "Gauge", frozenset({"risk_level"})),
        ("connections_missed_total", "Counter", frozenset()),
        ("passenger_alerts_total", "Counter", frozenset({"type"})),
        ("zone_load_pct", "Gauge", frozenset({"zone_id"})),
        ("envelope_invalid_total", "Counter", frozenset({"reason"})),
    ],
    "baggage-service": [
        ("baggage_in_system", "Gauge", frozenset({"status"})),
        ("baggage_flagged_active", "Gauge", frozenset()),
        ("conveyor_zone_utilisation_pct", "Gauge", frozenset({"zone_id"})),
        ("conveyor_zone_status", "Gauge", frozenset({"zone_id"})),
        ("baggage_transitions_total", "Counter", frozenset({"from_status", "to_status"})),
        ("dangerous_goods_detected_total", "Counter", frozenset({"dg_class"})),
        ("screening_false_positives_total", "Counter", frozenset()),
        ("baggage_offloaded_total", "Counter", frozenset({"reason"})),
        ("envelope_invalid_total", "Counter", frozenset({"reason"})),
    ],
    "weather-service": [
        ("weather_category", "Gauge", frozenset()),
        ("weather_transitions_total", "Counter", frozenset({"from_cat", "to_cat"})),
        ("visibility_m", "Gauge", frozenset()),
        ("wind_speed_kt", "Gauge", frozenset()),
        ("wind_gust_kt", "Gauge", frozenset()),
        ("runway_arrival_rate", "Gauge", frozenset()),
        ("runway_departure_rate", "Gauge", frozenset()),
        ("holding_stack_depth", "Gauge", frozenset()),
        ("flights_delayed_by_weather_total", "Counter", frozenset({"category"})),
        ("envelope_invalid_total", "Counter", frozenset({"reason"})),
    ],
    "incident-service": [
        ("incidents_active", "Gauge", frozenset({"type", "severity"})),
        ("incidents_created_total", "Counter", frozenset({"type", "severity", "trigger"})),
        ("incident_ttr_minutes", "Histogram", frozenset({"type"})),
        ("cascade_events_total", "Counter", frozenset({"parent_type"})),
        ("cascade_depth_max", "Gauge", frozenset()),
        ("protocols_activated_total", "Counter", frozenset({"protocol"})),
        ("flights_impacted_by_incidents_total", "Counter", frozenset({"incident_type"})),
        ("envelope_invalid_total", "Counter", frozenset({"reason"})),
    ],
    "sim-orchestrator": [
        ("sim_tick_total", "Counter", frozenset()),
        ("sim_tick_latency_ms", "Histogram", frozenset()),
        ("sim_speed_multiplier", "Gauge", frozenset()),
        ("sim_day_number", "Gauge", frozenset()),
        ("sim_paused", "Gauge", frozenset()),
        ("sim_events_injected_total", "Counter", frozenset({"type"})),
    ],
}

MAX_LABELS_PER_METRIC = 3


def _parse_metrics_file(service: str) -> dict[str, tuple[str, str, frozenset[str]]]:
    """Parse a metrics.py via AST and return {metric_name: (name, type, labels)}."""
    path = os.path.join(ROOT, "services", service, "metrics.py")
    with open(path) as f:
        tree = ast.parse(f.read(), filename=path)

    result: dict[str, tuple[str, str, frozenset[str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        # Get the constructor name (Counter, Gauge, Histogram)
        func = value.func
        if isinstance(func, ast.Name):
            type_name = func.id
        elif isinstance(func, ast.Attribute):
            type_name = func.attr
        else:
            continue
        if type_name not in ("Counter", "Gauge", "Histogram"):
            continue

        # First positional arg is the metric name
        if not value.args:
            continue
        name_node = value.args[0]
        if not isinstance(name_node, ast.Constant) or not isinstance(name_node.value, str):
            continue
        metric_name = name_node.value

        # Look for label names in the third positional arg (list of strings)
        labels: frozenset[str] = frozenset()
        if len(value.args) >= 3:
            label_node = value.args[2]
            if isinstance(label_node, ast.List):
                labels = frozenset(
                    elt.value for elt in label_node.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                )

        result[metric_name] = (metric_name, type_name, labels)

    return result


# ── Tests ───────────────────────────────────────────────────────


@pytest.mark.parametrize("service", list(EXPECTED_METRICS.keys()))
def test_expected_metrics_exist(service: str):
    """Every metric from the catalogue exists in the service's metrics.py."""
    defined = _parse_metrics_file(service)

    for metric_name, expected_type, expected_labels in EXPECTED_METRICS[service]:
        assert metric_name in defined, (
            f"{service}: metric '{metric_name}' missing from metrics.py"
        )
        _, actual_type, actual_labels = defined[metric_name]
        assert actual_type == expected_type, (
            f"{service}/{metric_name}: expected {expected_type}, got {actual_type}"
        )
        assert actual_labels == expected_labels, (
            f"{service}/{metric_name}: expected labels {expected_labels}, "
            f"got {actual_labels}"
        )


@pytest.mark.parametrize("service", list(EXPECTED_METRICS.keys()))
def test_no_unexpected_metrics(service: str):
    """No surprise metrics in code that aren't in the catalogue."""
    defined = _parse_metrics_file(service)
    expected_names = {m[0] for m in EXPECTED_METRICS[service]}

    for name in defined:
        assert name in expected_names, (
            f"{service}: unexpected metric '{name}' in metrics.py — "
            f"add to MONITORING.md or remove from code"
        )


@pytest.mark.parametrize("service", list(EXPECTED_METRICS.keys()))
def test_label_cardinality_bounded(service: str):
    """No metric has too many label dimensions (prevents cardinality explosion)."""
    defined = _parse_metrics_file(service)

    for name, (_, _, labels) in defined.items():
        assert len(labels) <= MAX_LABELS_PER_METRIC, (
            f"{service}/{name}: has {len(labels)} labels {labels} — "
            f"max allowed is {MAX_LABELS_PER_METRIC}"
        )


# Services that consume Kafka events and need envelope validation
_CONSUMER_SERVICES = [s for s in EXPECTED_METRICS if s != "sim-orchestrator"]


@pytest.mark.parametrize("service", _CONSUMER_SERVICES)
def test_envelope_invalid_total_present(service: str):
    """Every consumer service must define envelope_invalid_total."""
    defined = _parse_metrics_file(service)
    assert "envelope_invalid_total" in defined, (
        f"{service}: must define envelope_invalid_total counter"
    )
