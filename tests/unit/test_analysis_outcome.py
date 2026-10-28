"""Unit tests for automatic outcome measurement (roadmap G8).

Covers the two pure pieces: which executed proposals are due, and what the
observed outcome is. The sim-clock scheduler + Neo4j persistence are exercised
by the live test.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tests.conftest import import_service_module

_outcome = import_service_module("analysis", "services.outcome")
due_for_outcome = _outcome.due_for_outcome
measure_outcome = _outcome.measure_outcome
DELAY = _outcome.OUTCOME_DELAY_MIN

NOW = datetime(2024, 6, 15, 14, 0, 0)


def _doc(**kw):
    base = {"id": "p1", "status": "executed", "actual_outcome": None,
            "executed_at": (NOW - timedelta(minutes=DELAY)).isoformat(),
            "action_type": "resolve_incident", "parameters": {}}
    base.update(kw)
    return base


class TestDueForOutcome:
    def test_executed_and_elapsed_is_due(self):
        assert due_for_outcome([_doc()], NOW) == [_doc()]

    def test_not_yet_elapsed_is_not_due(self):
        d = _doc(executed_at=(NOW - timedelta(minutes=DELAY - 1)).isoformat())
        assert due_for_outcome([d], NOW) == []

    def test_already_measured_is_not_due(self):
        assert due_for_outcome([_doc(actual_outcome={"x": 1})], NOW) == []

    def test_non_executed_is_not_due(self):
        assert due_for_outcome([_doc(status="approved")], NOW) == []

    def test_unparseable_executed_at_is_not_due(self):
        assert due_for_outcome([_doc(executed_at="not-a-date")], NOW) == []
        assert due_for_outcome([_doc(executed_at=None)], NOW) == []

    def test_timezone_aware_now_does_not_raise(self):
        # state.sim_time can be tz-aware; executed_at parses to naive. The compare
        # must normalise rather than raise TypeError (regression guard).
        aware_now = NOW.replace(tzinfo=timezone.utc)
        assert due_for_outcome([_doc()], aware_now) == [_doc()]


class TestMeasureIncident:
    def test_resolved_when_incident_gone(self):
        state = SimpleNamespace(active_incidents={})
        o = measure_outcome("resolve_incident", {"incident_id": "inc-1"}, state)
        assert o["measurable"] and o["bottleneck_resolved"] is True

    def test_not_resolved_when_still_active(self):
        state = SimpleNamespace(active_incidents={"inc-1": {"status": "active"}})
        o = measure_outcome("resolve_incident", {"incident_id": "inc-1"}, state)
        assert o["bottleneck_resolved"] is False and o["incident_status"] == "active"

    def test_contain_satisfied_by_contained_status(self):
        state = SimpleNamespace(active_incidents={"inc-1": {"status": "contained"}})
        o = measure_outcome("contain_incident", {"incident_id": "inc-1"}, state)
        assert o["bottleneck_resolved"] is True


class TestMeasureOther:
    def test_reassign_gate_resolved_when_gated(self):
        state = SimpleNamespace(flights={"f1": SimpleNamespace(gate="B07")})
        o = measure_outcome("reassign_gate", {"flight_id": "f1"}, state)
        assert o["bottleneck_resolved"] is True and o["gate"] == "B07"

    def test_reassign_gate_not_resolved_without_gate(self):
        state = SimpleNamespace(flights={"f1": SimpleNamespace(gate=None)})
        o = measure_outcome("reassign_gate", {"flight_id": "f1"}, state)
        assert o["bottleneck_resolved"] is False

    def test_open_security_lane_reports_wait(self):
        state = SimpleNamespace(security={"B": SimpleNamespace(forecast_wait_minutes=12, open_lanes=5)})
        o = measure_outcome("open_security_lane", {"terminal": "B"}, state)
        assert o["measurable"] and o["current_wait_minutes"] == 12 and o["open_lanes"] == 5

    def test_unknown_action_is_not_measurable(self):
        o = measure_outcome("ground_delay_program", {}, SimpleNamespace())
        assert o["measurable"] is False and "reason" in o
