"""Unit tests for the A9 approval queue (analysis-service services.approval_queue).

Covers the pure, in-memory building blocks that back the human Approve/Reject
loop for autonomous/agent-proposed actions:

  - classify(): the gating rule → AUTO / HUMAN / BLOCK / SKIP
  - propose(): pending vs auto-approved
  - approve()/reject()/mark_executed(): legal + illegal state transitions
  - take_unemitted(): each proposal emitted exactly once
  - to_flight_command(): the honest recommendation→command mapping

No Kafka/Neo4j — the router/consumer emit events; this module only mutates
in-memory state and enforces transitions.
"""

from datetime import datetime

import pytest

from tests.conftest import import_service_module

_aq = import_service_module("analysis", "services.approval_queue")

classify = _aq.classify
propose = _aq.propose
approve = _aq.approve
reject = _aq.reject
mark_executed = _aq.mark_executed
take_unemitted = _aq.take_unemitted
to_flight_command = _aq.to_flight_command
get = _aq.get
list_all = _aq.list_all
list_pending = _aq.list_pending
clear = _aq.clear

AUTO = _aq.AUTO
HUMAN = _aq.HUMAN
BLOCK = _aq.BLOCK
SKIP = _aq.SKIP
PENDING = _aq.PENDING
APPROVED = _aq.APPROVED
REJECTED = _aq.REJECTED
EXECUTED = _aq.EXECUTED

NOW = datetime(2024, 6, 15, 14, 30, 0)


@pytest.fixture(autouse=True)
def _clean_queue():
    clear()
    yield
    clear()


def _propose(**overrides) -> object:
    kwargs = dict(
        action_type="reassign_gate",
        description="Reassign flight to gate B12",
        parameters={},
        confidence_score=0.9,
        proposed_by="autonomous",
        proposed_at=NOW,
        recommendation_id="rec-1",
        bottleneck_id="bn-1",
        requires_human=True,
    )
    kwargs.update(overrides)
    return propose(**kwargs)


# ── classify: the gating rule ────────────────────────────────


class TestClassify:
    def test_blocked_beats_everything(self):
        # Blocked wins even when safe + confident.
        assert classify("x", 0.99, safety_guarded=True, blocked=True, threshold=0.8) == BLOCK

    def test_safety_guarded_requires_human_regardless_of_confidence(self):
        assert classify("ground_delay_program", 0.99, safety_guarded=True, blocked=False, threshold=0.8) == HUMAN

    def test_confident_unguarded_auto(self):
        assert classify("reassign_gate", 0.85, safety_guarded=False, blocked=False, threshold=0.8) == AUTO

    def test_at_threshold_is_auto(self):
        # >= threshold, not strictly greater.
        assert classify("reassign_gate", 0.80, safety_guarded=False, blocked=False, threshold=0.8) == AUTO

    def test_below_threshold_skips(self):
        assert classify("reassign_gate", 0.79, safety_guarded=False, blocked=False, threshold=0.8) == SKIP


# ── propose ──────────────────────────────────────────────────


class TestPropose:
    def test_requires_human_is_pending(self):
        p = _propose(requires_human=True)
        assert p.status == PENDING
        assert p.requires_human is True
        assert list_pending() == [p]

    def test_auto_is_approved_not_pending(self):
        p = _propose(requires_human=False)
        assert p.status == APPROVED
        assert list_pending() == []

    def test_parameters_are_copied_not_aliased(self):
        params = {"flight_id": "ART100"}
        p = _propose(parameters=params)
        params["flight_id"] = "MUTATED"
        assert p.parameters["flight_id"] == "ART100"

    def test_appended_to_queue(self):
        p = _propose()
        assert get(p.id) is p
        assert p in list_all()


# ── approve / reject / mark_executed transitions ─────────────


class TestTransitions:
    def test_approve_pending(self):
        p = _propose(requires_human=True)
        result = approve(p.id, NOW, decided_by="alice")
        assert result is p
        assert p.status == APPROVED
        assert p.decided_by == "alice"
        assert p.decided_at == NOW.isoformat()

    def test_approve_unknown_returns_none(self):
        assert approve("nope", NOW, decided_by="alice") is None

    def test_approve_already_approved_returns_none(self):
        p = _propose(requires_human=False)  # already APPROVED
        assert approve(p.id, NOW, decided_by="alice") is None

    def test_reject_pending(self):
        p = _propose(requires_human=True)
        result = reject(p.id, NOW, decided_by="bob", reason="unsafe")
        assert result is p
        assert p.status == REJECTED
        assert p.decided_by == "bob"
        assert p.reject_reason == "unsafe"

    def test_reject_non_pending_returns_none(self):
        p = _propose(requires_human=False)  # APPROVED
        assert reject(p.id, NOW, decided_by="bob") is None

    def test_mark_executed_requires_approved(self):
        p = _propose(requires_human=False)  # APPROVED
        result = mark_executed(p.id, NOW)
        assert result is p
        assert p.status == EXECUTED
        assert p.executed_at == NOW.isoformat()

    def test_mark_executed_on_pending_returns_none(self):
        p = _propose(requires_human=True)  # PENDING
        assert mark_executed(p.id, NOW) is None

    def test_mark_executed_unknown_returns_none(self):
        assert mark_executed("nope", NOW) is None

    def test_full_human_lifecycle(self):
        p = _propose(requires_human=True)
        approve(p.id, NOW, decided_by="alice")
        mark_executed(p.id, NOW)
        assert p.status == EXECUTED


# ── take_unemitted ───────────────────────────────────────────


class TestTakeUnemitted:
    def test_returns_all_fresh_then_none(self):
        a = _propose()
        b = _propose()
        first = take_unemitted()
        assert {p.id for p in first} == {a.id, b.id}
        # Second call: all already emitted.
        assert take_unemitted() == []

    def test_new_proposal_after_emit_is_returned(self):
        _propose()
        take_unemitted()
        c = _propose()
        assert take_unemitted() == [c]

    def test_to_dict_omits_emitted_flag(self):
        p = _propose()
        assert "emitted" not in p.to_dict()


# ── to_flight_command: the honest mapping ────────────────────


class TestToFlightCommand:
    def test_reassign_gate_with_concrete_target(self):
        cmd = to_flight_command("reassign_gate", {"flight_id": "ART100", "gate_id": "B12"})
        assert cmd == ("ReassignGate", {"flight_id": "ART100", "gate_id": "B12"})

    def test_reassign_gate_without_gate_is_none(self):
        assert to_flight_command("reassign_gate", {"flight_id": "ART100"}) is None

    def test_reassign_gate_without_flight_is_none(self):
        # Aggregate/terminal-level recommendation → no concrete command.
        assert to_flight_command("reassign_gate", {"gate_id": "B12"}) is None

    def test_hold_connecting_flight_maps_to_holdflight(self):
        cmd = to_flight_command(
            "hold_connecting_flight",
            {"flight_id": "ART100", "duration_min": 10, "reason": "connecting_pax"},
        )
        assert cmd == (
            "HoldFlight",
            {"flight_id": "ART100", "reason": "connecting_pax", "duration_min": 10},
        )

    def test_delay_taxi_uses_hold_minutes_alias_and_default_reason(self):
        cmd = to_flight_command("delay_taxi", {"flight_id": "ART100", "hold_minutes": 5})
        assert cmd == (
            "HoldFlight",
            {"flight_id": "ART100", "reason": "delay_taxi", "duration_min": 5},
        )

    def test_hold_with_zero_duration_is_none(self):
        assert to_flight_command("hold_connecting_flight", {"flight_id": "ART100", "duration_min": 0}) is None

    def test_hold_with_bool_duration_is_none(self):
        # bool is an int subclass — must be rejected.
        assert to_flight_command("hold_connecting_flight", {"flight_id": "ART100", "duration_min": True}) is None

    def test_missing_flight_id_is_none(self):
        assert to_flight_command("hold_connecting_flight", {"duration_min": 10}) is None

    def test_unmapped_action_is_none(self):
        assert to_flight_command("open_security_lane", {"flight_id": "ART100"}) is None
