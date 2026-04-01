"""Cross-service event chain contract tests.

Validates the handoff points between services identified in the
sprint-16 audit (BUG-1 through BUG-4). These are static analysis
+ pure-logic tests — no Neo4j or Kafka needed.

Ref: docs/lessons-learned/sprint-16-full-audit-report.md §6.
"""

import ast
import os
import re
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ──────────────────────────────────────────────────

def _read_source(service: str, module_path: str) -> str:
    """Read the raw source of a service module."""
    svc_dir = os.path.join(ROOT, "services", service)
    parts = module_path.replace(".", os.sep) + ".py"
    path = os.path.join(svc_dir, parts)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _import_baggage_consumer():
    """Import baggage-service consumer with mocked I/O dependencies."""
    svc_dir = os.path.join(ROOT, "services", "baggage-service")

    # Clean
    for k in list(sys.modules):
        if k in ("services", "db", "kafka", "metrics") or any(
            k.startswith(p) for p in ("services.", "db.", "kafka.", "metrics.")
        ):
            del sys.modules[k]
    for p in list(sys.path):
        if "services" in p and p.endswith(("-service", "sim-orchestrator")):
            sys.path.remove(p)
    sys.path.insert(0, svc_dir)

    # Mock db.neo4j
    _mock_db = types.ModuleType("db")
    _mock_db_neo4j = types.ModuleType("db.neo4j")
    for fn in [
        "get_session", "init_neo4j", "close_neo4j", "check_neo4j",
        "get_all_baggage", "get_baggage_by_tag", "get_baggage_by_flight",
        "create_baggage_node", "update_baggage_status", "get_baggage_stats",
        "get_flagged_baggage", "mark_baggage_loaded", "mark_baggage_collected",
    ]:
        setattr(_mock_db_neo4j, fn, MagicMock())
    _mock_db.neo4j = _mock_db_neo4j
    sys.modules["db"] = _mock_db
    sys.modules["db.neo4j"] = _mock_db_neo4j

    # Mock kafka.producer
    _mock_kafka = types.ModuleType("kafka")
    _mock_kafka_prod = types.ModuleType("kafka.producer")
    for fn in [
        "emit_baggage_status_changed", "emit_baggage_flagged",
        "check_kafka", "emit_bulk_state_snapshot",
    ]:
        setattr(_mock_kafka_prod, fn, AsyncMock())
    _mock_kafka.producer = _mock_kafka_prod
    sys.modules["kafka"] = _mock_kafka
    sys.modules["kafka.producer"] = _mock_kafka_prod

    # Mock metrics
    _mock_metrics = types.ModuleType("metrics")
    _gauge = MagicMock()
    _gauge.labels.return_value = _gauge
    for attr in dir(MagicMock()):
        if not attr.startswith("_"):
            pass
    for name in [
        "baggage_total", "baggage_by_status", "baggage_flagged",
        "baggage_load_time", "baggage_screen_time",
        "m_zone_status", "m_conveyor_throughput", "m_bags_processed",
        "m_bags_flagged", "m_bulk_skipped", "baggage_by_flight_type",
    ]:
        setattr(_mock_metrics, name, _gauge)
    sys.modules["metrics"] = _mock_metrics

    import importlib
    mod = importlib.import_module("kafka.consumer")
    return mod


def _import_incident_consumer():
    """Import incident-service consumer with mocked I/O dependencies."""
    svc_dir = os.path.join(ROOT, "services", "incident-service")

    # Clean
    for k in list(sys.modules):
        if k in ("services", "db", "kafka", "metrics") or any(
            k.startswith(p) for p in ("services.", "db.", "kafka.", "metrics.")
        ):
            del sys.modules[k]
    for p in list(sys.path):
        if "services" in p and p.endswith(("-service", "sim-orchestrator")):
            sys.path.remove(p)
    sys.path.insert(0, svc_dir)

    # Mock db.neo4j
    _mock_db = types.ModuleType("db")
    _mock_db_neo4j = types.ModuleType("db.neo4j")
    for fn in [
        "get_session", "init_neo4j", "close_neo4j", "check_neo4j",
        "create_incident_node", "create_spawned_relationship",
        "create_affects_relationship",
        "get_active_incidents_with_ttr", "get_incident_by_id",
        "get_flights_at_gate", "get_flights_on_runway",
        "resolve_children", "update_incident_status", "update_ttr_remaining",
        "find_active_incident_by_type_and_location",
    ]:
        setattr(_mock_db_neo4j, fn, AsyncMock(return_value=None))
    _mock_db.neo4j = _mock_db_neo4j
    sys.modules["db"] = _mock_db
    sys.modules["db.neo4j"] = _mock_db_neo4j

    # Mock kafka.producer
    _mock_kafka = types.ModuleType("kafka")
    _mock_kafka_prod = types.ModuleType("kafka.producer")
    for fn in [
        "emit_incident_created", "emit_incident_status_changed",
        "emit_incident_cascaded", "emit_incident_alert",
    ]:
        setattr(_mock_kafka_prod, fn, MagicMock())
    _mock_kafka.producer = _mock_kafka_prod
    sys.modules["kafka"] = _mock_kafka
    sys.modules["kafka.producer"] = _mock_kafka_prod

    # Mock metrics
    _mock_metrics = types.ModuleType("metrics")
    _gauge = MagicMock()
    _gauge.labels.return_value = _gauge
    for name in [
        "incidents_active", "incidents_created_total",
        "incident_ttr_minutes", "cascade_events_total",
        "cascade_depth_max", "protocols_activated_total",
        "envelope_invalid_total",
    ]:
        setattr(_mock_metrics, name, _gauge)
    sys.modules["metrics"] = _mock_metrics

    # Mock services.cascade
    _mock_svc = types.ModuleType("services")
    _mock_cascade = types.ModuleType("services.cascade")
    _mock_cascade.fire_pending_cascades = AsyncMock()
    _mock_cascade.CASCADE_MAX_DEPTH = 5
    _mock_cascade.CASCADE_RULES = {}
    _mock_cascade._check_and_mark_cascaded = MagicMock(return_value=False)
    _mock_cascade._cascaded_incidents = set()
    _mock_svc.cascade = _mock_cascade
    sys.modules["services"] = _mock_svc
    sys.modules["services.cascade"] = _mock_cascade

    # Mock services.protocols
    _mock_protocols = types.ModuleType("services.protocols")
    _mock_protocols.build_alert = MagicMock(return_value={
        "incident_id": "test", "severity": "high", "title": "test",
        "short_message": "test", "at": datetime.now().isoformat(),
    })
    _mock_svc.protocols = _mock_protocols
    sys.modules["services.protocols"] = _mock_protocols

    # Mock services.lifecycle
    _mock_lifecycle = types.ModuleType("services.lifecycle")
    _mock_lifecycle.create_incident = AsyncMock()
    _mock_lifecycle.resolve_incident = AsyncMock()
    _mock_lifecycle.set_lifecycle_callbacks = MagicMock()
    _mock_lifecycle.tick_ttr = AsyncMock()
    _mock_svc.lifecycle = _mock_lifecycle
    sys.modules["services.lifecycle"] = _mock_lifecycle

    import importlib
    mod = importlib.import_module("kafka.consumer")
    return mod


# ══════════════════════════════════════════════════════════════
# BUG-1: DG class type mismatch — string vs integer comparison
# ══════════════════════════════════════════════════════════════

class TestBug1DGClassTypeComparison:
    """BUG-1: str(dg_class) != '3' must work for both string and int dg_class.

    Baggage-service emits dg_class as a string (from the producer signature:
    `dg_class: str | None`), but the comparison must be robust to both types
    because JSON deserialization can produce either.
    """

    def test_dg_class_string_3_passes_guard(self):
        """When dg_class='3' (string), the guard `str(dg_class) != '3'` is False → proceeds."""
        dg_class = "3"
        assert str(dg_class) == "3", "String '3' should pass the DG class guard"

    def test_dg_class_int_3_passes_guard(self):
        """When dg_class=3 (integer, e.g. from JSON), the guard still works after fix."""
        dg_class = 3
        assert str(dg_class) == "3", "Integer 3 should pass the DG class guard via str()"

    def test_dg_class_other_values_blocked(self):
        """Non-class-3 values should be blocked by the guard."""
        for val in ["1", "2", "4", "9", 1, 9, None, "", "flammable"]:
            assert str(val) != "3", f"Value {val!r} should NOT pass the DG class guard"

    def test_source_uses_str_cast(self):
        """Static analysis: incident-service consumer uses str(dg_class) not raw comparison."""
        source = _read_source("incident-service", "kafka.consumer")
        # The fixed code should have str(dg_class)
        assert "str(dg_class)" in source, (
            "incident-service consumer must use str(dg_class) for type-safe comparison"
        )
        # Should NOT have bare `dg_class != 3` (int comparison)
        # Use AST to check there's no raw `dg_class != 3` comparison
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and comparator.value == 3:
                        # Check if left side is bare Name "dg_class" (not wrapped in str())
                        if isinstance(node.left, ast.Name) and node.left.id == "dg_class":
                            pytest.fail(
                                "Found bare `dg_class != 3` comparison — "
                                "should be `str(dg_class) != '3'`"
                            )


# ══════════════════════════════════════════════════════════════
# BUG-2: BaggageFlagged field name mismatch (zone_id vs scan_zone)
# ══════════════════════════════════════════════════════════════

class TestBug2BaggageFlaggedFieldName:
    """BUG-2: incident-service must read `scan_zone` from BaggageFlagged payload,
    matching what baggage-service actually emits.
    """

    def test_baggage_producer_emits_scan_zone(self):
        """Verify baggage-service producer uses field name 'scan_zone'."""
        source = _read_source("baggage-service", "kafka.producer")
        # The emit_baggage_flagged function must include scan_zone in payload
        assert '"scan_zone"' in source or "'scan_zone'" in source, (
            "baggage-service producer must emit 'scan_zone' field in BaggageFlagged"
        )

    def test_incident_consumer_reads_scan_zone(self):
        """Verify incident-service consumer reads 'scan_zone' not 'zone_id'."""
        source = _read_source("incident-service", "kafka.consumer")
        # Find the _on_baggage_flagged function and check it reads scan_zone
        assert 'payload.get("scan_zone"' in source, (
            "incident-service must read 'scan_zone' from BaggageFlagged payload"
        )
        # Verify it does NOT read the old wrong field name
        assert 'payload.get("zone_id"' not in source, (
            "incident-service must NOT read 'zone_id' — "
            "the correct field is 'scan_zone' per EVENT_BUS.md"
        )

    def test_event_bus_spec_field_name(self):
        """Verify EVENT_BUS.md documents 'scan_zone' for BaggageFlagged."""
        spec_path = os.path.join(ROOT, "docs", "architecture", "EVENT_BUS.md")
        with open(spec_path, encoding="utf-8") as f:
            spec = f.read()
        # Find the BaggageFlagged section
        assert "scan_zone" in spec, (
            "EVENT_BUS.md must document 'scan_zone' field in BaggageFlagged schema"
        )

    def test_field_name_alignment_producer_to_consumer(self):
        """Cross-check: every field that incident-service reads from BaggageFlagged
        must exist in the baggage-service producer payload."""
        producer_src = _read_source("baggage-service", "kafka.producer")
        consumer_src = _read_source("incident-service", "kafka.consumer")

        # Extract field names from payload dict in emit_baggage_flagged
        producer_fields = set(re.findall(r'"(\w+)":\s', producer_src))

        # Extract payload.get("...") calls in _on_baggage_flagged
        # Find the function body
        flagged_match = re.search(
            r'async def _on_baggage_flagged\(.*?\n(?=\nasync def |\nclass |\Z)',
            consumer_src,
            re.DOTALL,
        )
        assert flagged_match, "Could not find _on_baggage_flagged function"
        func_body = flagged_match.group()
        consumer_reads = set(re.findall(r'payload\.get\("(\w+)"', func_body))

        for field in consumer_reads:
            assert field in producer_fields, (
                f"incident-service reads '{field}' from BaggageFlagged "
                f"but baggage-service producer does not emit it. "
                f"Producer fields: {producer_fields}"
            )


# ══════════════════════════════════════════════════════════════
# BUG-3: System failure location key mismatch (incident→baggage)
# ══════════════════════════════════════════════════════════════

class TestBug3SystemFailureLocationAlignment:
    """BUG-3: incident-service system_failure locations must match
    baggage-service FAILURE_IMPACT keys exactly.
    """

    def test_incident_locations_match_failure_impact(self):
        """Conveyor/power system_failure locations generated by incident-service
        must be keys in baggage-service's FAILURE_IMPACT map.
        Non-baggage IT failures (check-in-system, fids-system) are excluded
        because they don't affect the conveyor."""
        # Extract system_failure locations from incident-service _pick_location
        inc_source = _read_source("incident-service", "kafka.consumer")
        loc_match = re.search(
            r'def _pick_location.*?event_type == "system_failure".*?\[(.*?)\]',
            inc_source,
            re.DOTALL,
        )
        assert loc_match, "Could not find system_failure locations in _pick_location"
        loc_str = loc_match.group(1)
        incident_locations = set(re.findall(r'"([^"]+)"', loc_str))

        # Extract FAILURE_IMPACT keys from baggage-service
        bag_source = _read_source("baggage-service", "kafka.consumer")
        fi_match = re.search(
            r'FAILURE_IMPACT.*?{(.*?)}',
            bag_source,
            re.DOTALL,
        )
        assert fi_match, "Could not find FAILURE_IMPACT in baggage consumer"
        fi_str = fi_match.group(1)
        baggage_keys = set(re.findall(r'"([^"]+)":\s*\[', fi_str))

        # Only conveyor/power/screening locations need to be in FAILURE_IMPACT.
        # IT system failures (check-in-system, fids-system) don't affect baggage.
        NON_BAGGAGE_LOCATIONS = {"check-in-system", "fids-system"}
        baggage_relevant = incident_locations - NON_BAGGAGE_LOCATIONS

        unmatched = baggage_relevant - baggage_keys
        assert not unmatched, (
            f"Incident-service generates baggage-relevant system_failure locations "
            f"{unmatched} not found in baggage-service FAILURE_IMPACT. "
            f"FAILURE_IMPACT keys: {sorted(baggage_keys)}"
        )

    def test_no_terminal_dash_power_pattern(self):
        """The old bug used 'terminal-A-power' format. Verify it's gone."""
        source = _read_source("incident-service", "kafka.consumer")
        assert "terminal-A-power" not in source, (
            "Old location format 'terminal-A-power' found — "
            "should be 'power-A' to match baggage FAILURE_IMPACT"
        )
        assert "terminal-B-power" not in source
        assert "terminal-C-power" not in source

    def test_power_locations_use_correct_format(self):
        """Verify power outage locations use 'power-X' format."""
        source = _read_source("incident-service", "kafka.consumer")
        power_locs = re.findall(r'"(power-[A-C])"', source)
        assert len(power_locs) >= 2, (
            "Expected at least 'power-A' and 'power-B' in system_failure locations"
        )

    def test_incident_status_changed_includes_location(self):
        """When an incident is resolved, the IncidentStatusChanged event must
        include 'location' so baggage-service can look up affected zones."""
        source = _read_source("incident-service", "kafka.producer")
        # Find emit_incident_status_changed function
        assert '"location"' in source, (
            "IncidentStatusChanged payload must include 'location' field "
            "so baggage-service can restore affected zones on resolve"
        )


# ══════════════════════════════════════════════════════════════
# BUG-4: No duplicate probabilistic injection
# ══════════════════════════════════════════════════════════════

class TestBug4NoDuplicateProbabilisticInjection:
    """BUG-4: Only incident-service should generate probabilistic incidents.
    sim-orchestrator must NOT independently inject probabilistic events.
    """

    def test_sim_orchestrator_hour_boundary_no_injection(self):
        """sim-orchestrator's _on_hour_boundary must NOT call
        evaluate_probabilistic_events or emit_inject_incident."""
        source = _read_source("sim-orchestrator", "main")
        # Find the _on_hour_boundary function
        func_match = re.search(
            r'async def _on_hour_boundary\(.*?\n(?=\nasync def |\ndef |\nclass |\Z)',
            source,
            re.DOTALL,
        )
        assert func_match, "Could not find _on_hour_boundary in sim-orchestrator main"
        func_body = func_match.group()

        # Should NOT call evaluate_probabilistic_events
        assert "evaluate_probabilistic_events" not in func_body, (
            "sim-orchestrator _on_hour_boundary must NOT call "
            "evaluate_probabilistic_events — this is handled by incident-service"
        )
        # Should NOT call emit_inject_incident
        assert "emit_inject_incident" not in func_body, (
            "sim-orchestrator _on_hour_boundary must NOT call "
            "emit_inject_incident for probabilistic events"
        )

    def test_incident_service_has_probabilistic_handler(self):
        """incident-service must have _evaluate_probabilistic_events."""
        source = _read_source("incident-service", "kafka.consumer")
        assert "async def _evaluate_probabilistic_events" in source, (
            "incident-service must define _evaluate_probabilistic_events"
        )

    def test_incident_service_has_weather_modifiers(self):
        """incident-service probabilistic handler should have weather-aware modifiers
        (this is why it was kept over sim-orchestrator's simpler implementation)."""
        source = _read_source("incident-service", "kafka.consumer")
        assert "current_weather_category" in source, (
            "incident-service should use weather state for probability modifiers"
        )

    def test_incident_service_base_probabilities_match_spec(self):
        """Verify base probabilities match the documented spec values."""
        source = _read_source("incident-service", "kafka.consumer")
        # Extract BASE_PROBABILITIES
        probs_match = re.search(
            r'BASE_PROBABILITIES\s*=\s*{(.*?)}', source, re.DOTALL
        )
        assert probs_match, "Could not find BASE_PROBABILITIES"
        probs_str = probs_match.group(1)

        # Parse expected probabilities from default env values
        expected = {
            "runway_incursion": 0.005,
            "baggage_fire": 0.008,
            "security_breach": 0.010,
            "system_failure": 0.015,
        }
        for event_type, expected_prob in expected.items():
            # Match the env default string — may have trailing zeros or not
            # e.g. "0.005" or "0.010" or "0.01"
            assert f'"{event_type}"' in probs_str, (
                f"BASE_PROBABILITIES missing '{event_type}'"
            )
            # Extract the actual default value from the float(os.getenv(... , "X")) pattern
            pattern = rf'"{event_type}":\s*float\(.*?,\s*"([\d.]+)"\)'
            match = re.search(pattern, probs_str)
            assert match, (
                f"Could not parse default prob for '{event_type}' from BASE_PROBABILITIES"
            )
            actual = float(match.group(1))
            assert abs(actual - expected_prob) < 1e-6, (
                f"BASE_PROBABILITIES['{event_type}'] default is {actual}, "
                f"expected {expected_prob}"
            )

    def test_sim_orchestrator_injector_exists_but_unused_at_hour_boundary(self):
        """The injector module may exist for scenario/manual use, but must NOT
        be called from the hour boundary callback."""
        main_src = _read_source("sim-orchestrator", "main")
        # Check that injector is not imported for hour-boundary use
        func_match = re.search(
            r'async def _on_hour_boundary\(.*?\n(?=\nasync def |\ndef |\nclass |\Z)',
            main_src,
            re.DOTALL,
        )
        func_body = func_match.group() if func_match else ""
        assert "injector" not in func_body, (
            "sim-orchestrator _on_hour_boundary should not reference injector"
        )


# ══════════════════════════════════════════════════════════════
# Cross-service event envelope contract
# ══════════════════════════════════════════════════════════════

class TestEventEnvelopeContract:
    """Verify all services produce events matching the EVENT_BUS.md envelope format."""

    def test_all_producers_include_event_id(self):
        """Every event producer must include event_id in the envelope."""
        for svc, module in [
            ("flight-service", "kafka.producer"),
            ("passenger-service", "kafka.producer"),
            ("baggage-service", "kafka.producer"),
            ("weather-service", "kafka.producer"),
            ("incident-service", "kafka.producer"),
        ]:
            source = _read_source(svc, module)
            assert "event_id" in source, (
                f"{svc} producer must include 'event_id' in event envelope"
            )

    def test_all_producers_include_sim_time(self):
        """Every event producer must include sim_time in the envelope."""
        for svc, module in [
            ("flight-service", "kafka.producer"),
            ("passenger-service", "kafka.producer"),
            ("baggage-service", "kafka.producer"),
            ("weather-service", "kafka.producer"),
            ("incident-service", "kafka.producer"),
        ]:
            source = _read_source(svc, module)
            assert "sim_time" in source, (
                f"{svc} producer must include 'sim_time' in event envelope"
            )

    def test_all_consumers_check_idempotency(self):
        """Every consumer must check event_id for idempotency."""
        for svc, module in [
            ("flight-service", "kafka.consumer"),
            ("passenger-service", "kafka.consumer"),
            ("baggage-service", "kafka.consumer"),
            ("incident-service", "kafka.consumer"),
        ]:
            source = _read_source(svc, module)
            assert "idempotency" in source.lower() or "processed_events" in source or "check_idempotency" in source, (
                f"{svc} consumer must implement idempotency checking"
            )


# ══════════════════════════════════════════════════════════════
# Topic subscription alignment
# ══════════════════════════════════════════════════════════════

class TestTopicSubscriptionAlignment:
    """Verify consumer topic subscriptions match EVENT_BUS.md §2."""

    def test_incident_service_subscribes_to_baggage_events(self):
        """incident-service must subscribe to baggage.events to receive BaggageFlagged."""
        source = _read_source("incident-service", "kafka.consumer")
        assert "baggage.events" in source, (
            "incident-service must subscribe to 'baggage.events' "
            "to receive BaggageFlagged for DG fire auto-trigger"
        )

    def test_baggage_service_subscribes_to_incidents_events(self):
        """baggage-service must subscribe to incidents.events to handle system failures."""
        source = _read_source("baggage-service", "kafka.consumer")
        assert "incidents.events" in source, (
            "baggage-service must subscribe to 'incidents.events' "
            "to handle system_failure zone offline/restore"
        )

    def test_flight_service_subscribes_to_weather_events(self):
        """flight-service must subscribe to weather.events per EVENT_BUS.md."""
        source = _read_source("flight-service", "kafka.consumer")
        assert "weather.events" in source, (
            "flight-service must subscribe to 'weather.events'"
        )

    def test_flight_service_subscribes_to_incidents_events(self):
        """flight-service must subscribe to incidents.events per EVENT_BUS.md."""
        source = _read_source("flight-service", "kafka.consumer")
        assert "incidents.events" in source, (
            "flight-service must subscribe to 'incidents.events'"
        )

    def test_passenger_service_subscribes_to_incidents_events(self):
        """passenger-service must subscribe to incidents.events per EVENT_BUS.md."""
        source = _read_source("passenger-service", "kafka.consumer")
        assert "incidents.events" in source, (
            "passenger-service must subscribe to 'incidents.events'"
        )
