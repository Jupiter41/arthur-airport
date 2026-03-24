"""Unit tests for incident-service lifecycle — pure logic, no I/O."""

import importlib
import sys
import os
import types
from unittest.mock import MagicMock

import pytest

# We need to import lifecycle.py which depends on db.neo4j (neo4j driver).
# Since this is a unit test, we mock the db layer before importing.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SVC_DIR = os.path.join(ROOT, "services", "incident-service")

# Clear any cached services/db modules
for k in list(sys.modules):
    if k == "services" or k.startswith("services.") or k == "db" or k.startswith("db."):
        del sys.modules[k]

# Insert incident-service path
for p in list(sys.path):
    if "services" in p and p.endswith(("-service", "sim-orchestrator")):
        sys.path.remove(p)
sys.path.insert(0, SVC_DIR)

# Pre-install mock db.neo4j before importing lifecycle
_mock_db = types.ModuleType("db")
_mock_db_neo4j = types.ModuleType("db.neo4j")
for fn_name in [
    "create_incident_node", "create_spawned_relationship",
    "get_active_incidents_with_ttr", "get_incident_by_id",
    "resolve_children", "update_incident_status", "update_ttr_remaining",
]:
    setattr(_mock_db_neo4j, fn_name, MagicMock())
_mock_db.neo4j = _mock_db_neo4j
sys.modules["db"] = _mock_db
sys.modules["db.neo4j"] = _mock_db_neo4j

from services.lifecycle import (
    VALID_TRANSITIONS,
    TTR_RANGES,
    DEFAULT_DESCRIPTIONS,
    PROTOCOLS,
    sample_ttr,
)


class TestValidTransitions:
    def test_active_can_contain(self):
        assert "contained" in VALID_TRANSITIONS["active"]

    def test_active_can_resolve(self):
        assert "resolved" in VALID_TRANSITIONS["active"]

    def test_contained_can_resolve(self):
        assert "resolved" in VALID_TRANSITIONS["contained"]

    def test_resolved_is_terminal(self):
        assert len(VALID_TRANSITIONS["resolved"]) == 0

    def test_contained_cannot_go_back_to_active(self):
        assert "active" not in VALID_TRANSITIONS["contained"]

    def test_resolved_cannot_go_anywhere(self):
        assert "active" not in VALID_TRANSITIONS["resolved"]
        assert "contained" not in VALID_TRANSITIONS["resolved"]

    def test_all_statuses_present(self):
        assert set(VALID_TRANSITIONS.keys()) == {"active", "contained", "resolved"}


class TestTTRRanges:
    def test_runway_incursion_has_ttr(self):
        assert TTR_RANGES["runway_incursion"] is not None
        low, high = TTR_RANGES["runway_incursion"]
        assert low < high

    def test_severe_weather_no_ttr(self):
        assert TTR_RANGES["severe_weather"] is None

    def test_security_congestion_no_ttr(self):
        assert TTR_RANGES["security_congestion"] is None

    def test_sample_ttr_within_range(self):
        for _ in range(100):
            ttr = sample_ttr("runway_incursion")
            low, high = TTR_RANGES["runway_incursion"]
            assert low <= ttr <= high

    def test_sample_ttr_none_for_weather(self):
        assert sample_ttr("severe_weather") is None


class TestProtocols:
    def test_runway_incursion_protocol(self):
        assert PROTOCOLS["runway_incursion"]["critical"] == "RUNWAY_STOP"

    def test_security_breach_escalation(self):
        assert PROTOCOLS["security_breach"]["medium"] == "ZONE_LOCKDOWN"
        assert PROTOCOLS["security_breach"]["high"] == "TERMINAL_LOCKDOWN"
        assert PROTOCOLS["security_breach"]["critical"] == "FULL_EVACUATION"

    def test_baggage_fire_protocol(self):
        assert PROTOCOLS["baggage_fire"]["medium"] == "BAGGAGE_HOLD"

    def test_severe_weather_protocol(self):
        assert PROTOCOLS["severe_weather"]["medium"] == "LOW_VIS_PROCEDURES"

    def test_system_failure_no_protocol(self):
        assert len(PROTOCOLS["system_failure"]) == 0

    def test_all_primary_types_have_protocols(self):
        primary_types = [
            "runway_incursion", "baggage_fire", "security_breach",
            "severe_weather", "system_failure",
        ]
        for t in primary_types:
            assert t in PROTOCOLS


class TestDefaultDescriptions:
    def test_all_primary_types_described(self):
        primary_types = [
            "runway_incursion", "baggage_fire", "security_breach",
            "severe_weather", "system_failure", "security_congestion",
        ]
        for t in primary_types:
            assert t in DEFAULT_DESCRIPTIONS
            assert len(DEFAULT_DESCRIPTIONS[t]) > 10
