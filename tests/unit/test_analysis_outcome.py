"""Unit tests for automatic outcome measurement (roadmap G8).

Covers the two pure pieces: which executed proposals are due, and what the
observed outcome is. The sim-clock scheduler + Neo4j persistence are exercised
by the live test.
"""

from datetime import datetime, timedelta, timezone
import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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

    @pytest.mark.parametrize("executed_at,expected", [
        ("2024-06-15T15:30:00+02:00", True),
        ("2024-06-15T13:30:00-02:00", False),
    ])
    def test_offsets_compare_instants_not_local_clock_faces(self, executed_at, expected):
        doc = _doc(executed_at=executed_at)
        assert bool(due_for_outcome([doc], NOW.replace(tzinfo=timezone.utc))) is expected

    def test_elapsed_minutes_retains_delay_after_downtime(self):
        assert _outcome.elapsed_minutes("2024-06-15T14:00:00+02:00", NOW) == 120


class TestMeasureIncident:
    def test_missing_incident_is_unknown(self):
        state = SimpleNamespace(active_incidents={})
        o = measure_outcome("resolve_incident", {"incident_id": "inc-1"}, state)
        assert o["measurable"] is False and "bottleneck_resolved" not in o

    def test_persisted_resolved_incident_is_measurable(self):
        state = SimpleNamespace(active_incidents={"inc-1": {"status": "resolved"}})
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
        o = measure_outcome("reassign_gate", {"flight_id": "f1", "gate_id": "B07"}, state)
        assert o["bottleneck_resolved"] is True and o["gate"] == "B07"

    def test_reassign_gate_not_resolved_without_gate(self):
        state = SimpleNamespace(flights={"f1": SimpleNamespace(gate=None)})
        o = measure_outcome("reassign_gate", {"flight_id": "f1", "gate_id": "B07"}, state)
        assert o["bottleneck_resolved"] is False

    def test_open_security_lane_reports_wait(self):
        state = SimpleNamespace(security={"Terminal B": SimpleNamespace(
            forecast_wait_minutes=99, observed_wait_minutes=12, open_lanes=5, last_updated=NOW)})
        o = measure_outcome("open_security_lane", {"terminal": "B"}, state)
        assert o["measurable"] and o["current_wait_minutes"] == 12 and o["open_lanes"] == 5
        assert o["observed_at"] == NOW.isoformat()

    def test_gate_assignment_to_another_gate_is_not_success(self):
        state = SimpleNamespace(flights={"f1": SimpleNamespace(gate="A01")})
        o = measure_outcome("reassign_gate", {"flight_id": "f1", "gate_id": "B07"}, state)
        assert o["bottleneck_resolved"] is False

    def test_unknown_flight_and_unobserved_checkpoint_are_not_measurable(self):
        state = SimpleNamespace(flights={}, security={
            "Terminal B": SimpleNamespace(open_lanes=4, last_updated=None)})
        assert not measure_outcome("reassign_gate", {"flight_id": "missing", "gate_id": "B07"}, state)["measurable"]
        assert not measure_outcome("open_security_lane", {"terminal": "B"}, state)["measurable"]

    def test_unknown_action_is_not_measurable(self):
        o = measure_outcome("ground_delay_program", {}, SimpleNamespace())
        assert o["measurable"] is False and "reason" in o


@pytest.mark.parametrize("incident,measurable", [({"status": "resolved"}, True), (None, False)])
def test_scheduler_reads_persisted_incident_and_records_actual_elapsed(monkeypatch, incident, measurable):
    from tests.unit.test_consumer_burst_recovery import context

    consumer = context("analysis", monkeypatch)
    store = importlib.import_module("services.proposal_store")
    db = importlib.import_module("db.neo4j")
    doc = _doc(executed_at=(NOW - timedelta(minutes=45)).isoformat(),
               parameters={"incident_id": "synthetic-incident"})
    monkeypatch.setattr(store, "list_documents", AsyncMock(return_value=[doc]))
    save = AsyncMock(return_value=doc)
    read = AsyncMock(return_value={"synthetic-incident": incident["status"]} if incident else {})
    monkeypatch.setattr(store, "record_outcome", save)
    monkeypatch.setattr(db, "query_incident_statuses", read)
    # The active-only cache has no incident, even for a legitimately resolved one.
    consumer.state.active_incidents.clear()
    asyncio.run(consumer._measure_due_outcomes(NOW))
    read.assert_awaited_once_with(["synthetic-incident"])
    measured = save.await_args.args[1]
    assert measured["measurable"] is measurable
    assert measured["measured_sim_minutes"] == 45
    assert save.await_args.args[0] == "p1" and save.await_args.args[2] == NOW
    if measurable:
        assert measured["bottleneck_resolved"] is True
    # Legacy proposals without a dispatch baseline are never used for calibration.
    assert measured["attribution"]["calibration_eligible"] is False
