"""Unit tests for incident-service protocols — pure logic, no I/O."""

from datetime import datetime

import pytest

from tests.conftest import import_service_module

_proto = import_service_module("incident", "services.protocols")
PROTOCOL_ACTIONS = _proto.PROTOCOL_ACTIONS
DASHBOARD_COLORS = _proto.DASHBOARD_COLORS
build_alert = _proto.build_alert
get_protocol_description = _proto.get_protocol_description


SIM_TIME = datetime(2025, 6, 15, 12, 0, 0)


class TestProtocolActions:
    def test_all_protocols_defined(self):
        expected = {
            "RUNWAY_STOP", "BAGGAGE_HOLD", "ZONE_LOCKDOWN",
            "TERMINAL_LOCKDOWN", "FULL_EVACUATION", "LOW_VIS_PROCEDURES",
        }
        assert set(PROTOCOL_ACTIONS.keys()) == expected

    def test_descriptions_non_empty(self):
        for code, desc in PROTOCOL_ACTIONS.items():
            assert len(desc) > 5, f"Protocol {code} has empty description"


class TestDashboardColors:
    def test_all_severities(self):
        assert set(DASHBOARD_COLORS.keys()) == {"low", "medium", "high", "critical"}

    def test_critical_is_red(self):
        assert DASHBOARD_COLORS["critical"] == "red"


class TestBuildAlert:
    def test_alert_structure(self):
        incident = {
            "id": "inc-1",
            "type": "runway_incursion",
            "severity": "critical",
            "location": "runway-09L",
            "protocol": "RUNWAY_STOP",
        }
        alert = build_alert(incident, SIM_TIME)
        assert alert["incident_id"] == "inc-1"
        assert alert["severity"] == "critical"
        assert alert["dashboard_color"] == "red"
        assert alert["sound_alert"] is True
        assert "RUNWAY_STOP" in alert["short_message"]

    def test_alert_without_protocol(self):
        incident = {
            "id": "inc-2",
            "type": "system_failure",
            "severity": "medium",
            "location": "conveyor",
            "protocol": "",
        }
        alert = build_alert(incident, SIM_TIME)
        assert alert["sound_alert"] is False
        assert "System Failure" in alert["short_message"]

    def test_alert_title_format(self):
        incident = {
            "id": "inc-3",
            "type": "security_breach",
            "severity": "high",
            "location": "terminal-B",
            "protocol": "TERMINAL_LOCKDOWN",
        }
        alert = build_alert(incident, SIM_TIME)
        assert "HIGH" in alert["title"]
        assert "Security Breach" in alert["title"]


class TestGetProtocolDescription:
    def test_known_protocol(self):
        desc = get_protocol_description("RUNWAY_STOP")
        assert len(desc) > 0

    def test_unknown_protocol(self):
        desc = get_protocol_description("NONEXISTENT")
        assert desc == ""
