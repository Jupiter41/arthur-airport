"""Unit tests for A9 autonomous → approval-queue routing.

Covers how ``evaluate_and_apply`` now routes each recommendation through the
approval queue's gating rule:

  - confident, unguarded actions auto-apply AND leave an auto-approved+executed
    proposal for audit;
  - safety-guarded actions are NOT applied — they are enqueued PENDING for a
    human, and the bottleneck goes on cooldown so they aren't re-proposed;
  - operator-blocked / below-threshold actions are dropped;
  - cooldown suppresses re-action of the same bottleneck.

Also covers ``record_proposal_execution`` (the audit entry an approved proposal
produces, which activates ``record_outcome``).
"""

from datetime import datetime, timedelta

import pytest

from tests.conftest import import_service_module

_auto = import_service_module("analysis", "services.autonomous")
_domain = import_service_module("analysis", "models.domain")
# Reference the SAME approval_queue instance autonomous.py holds. Calling
# import_service_module again would clear services.* and yield a second module
# with its own _queue, breaking state-sharing with evaluate_and_apply.
_aq = _auto.approval_queue

evaluate_and_apply = _auto.evaluate_and_apply
record_proposal_execution = _auto.record_proposal_execution
get_action_log = _auto.get_action_log
update_settings = _auto.update_settings
get_settings = _auto.get_settings

Recommendation = _domain.Recommendation
ActionType = _domain.ActionType
AutonomousSettings = _domain.AutonomousSettings
AutonomousMode = _domain.AutonomousMode

NOW = datetime(2024, 6, 15, 14, 30, 0)


def _rec(rec_id: str, *, action_type=ActionType.REASSIGN_GATE, confidence=0.9, parameters=None) -> Recommendation:
    return Recommendation(
        id=rec_id,
        bottleneck_id=f"bn-{rec_id}",
        action_type=action_type,
        description=f"Do {action_type.value}",
        expected_impact="Relieve pressure",
        cost="low",
        confidence_score=confidence,
        expiry_sim_time=NOW + timedelta(minutes=45),
        priority_rank=1,
        parameters=parameters or {},
        applied=False,
    )


@pytest.fixture(autouse=True)
def _reset():
    # Isolate module-level state between tests.
    _aq.clear()
    _auto._action_log.clear()
    _auto._bottleneck_cooldowns.clear()
    _auto._last_check_sim_time = None
    saved = get_settings()
    yield
    _aq.clear()
    _auto._action_log.clear()
    _auto._bottleneck_cooldowns.clear()
    _auto._last_check_sim_time = None
    update_settings(saved)


def _enable(**overrides):
    kwargs = dict(mode=AutonomousMode.RULE_BASED, confidence_threshold=0.80)
    kwargs.update(overrides)
    update_settings(AutonomousSettings(**kwargs))


class TestAutoApply:
    def test_confident_unguarded_is_applied_and_audited(self):
        _enable()
        rec = _rec("rec-1", confidence=0.9)
        actions = evaluate_and_apply([rec], NOW)

        assert len(actions) == 1
        assert rec.applied is True
        # An auto-approved+executed proposal was recorded for audit.
        props = _aq.list_all()
        assert len(props) == 1
        assert props[0].status == _aq.EXECUTED
        assert props[0].requires_human is False

    def test_below_threshold_is_skipped(self):
        _enable(confidence_threshold=0.95)
        rec = _rec("rec-1", confidence=0.9)
        actions = evaluate_and_apply([rec], NOW)
        assert actions == []
        assert rec.applied is False
        assert _aq.list_all() == []

    def test_blocked_action_is_dropped(self):
        _enable(blocked_actions=[ActionType.REASSIGN_GATE])
        rec = _rec("rec-1", action_type=ActionType.REASSIGN_GATE, confidence=0.99)
        actions = evaluate_and_apply([rec], NOW)
        assert actions == []
        assert rec.applied is False
        assert _aq.list_all() == []


class TestSafetyGuarded:
    def test_safety_guarded_is_proposed_not_applied(self):
        _enable()
        rec = _rec("rec-1", action_type=ActionType.GROUND_DELAY_PROGRAM, confidence=0.99)
        # GROUND_DELAY_PROGRAM is blocked by default; use a clean settings that
        # only marks it safety-guarded (not blocked).
        update_settings(AutonomousSettings(
            mode=AutonomousMode.RULE_BASED, confidence_threshold=0.80, blocked_actions=[],
        ))
        actions = evaluate_and_apply([rec], NOW)

        assert actions == []            # not auto-applied
        assert rec.applied is False
        pending = _aq.list_pending()
        assert len(pending) == 1        # surfaced for a human
        assert pending[0].action_type == "ground_delay_program"
        assert pending[0].requires_human is True

    def test_safety_guarded_registers_cooldown(self):
        update_settings(AutonomousSettings(
            mode=AutonomousMode.RULE_BASED, confidence_threshold=0.80, blocked_actions=[],
        ))
        rec = _rec("rec-1", action_type=ActionType.REBOOK_PASSENGERS, confidence=0.99)
        evaluate_and_apply([rec], NOW)
        assert rec.bottleneck_id in _auto._bottleneck_cooldowns

        # Same bottleneck within cooldown → not re-proposed.
        rec2 = _rec("rec-1", action_type=ActionType.REBOOK_PASSENGERS, confidence=0.99)
        evaluate_and_apply([rec2], NOW + timedelta(minutes=5))
        assert len(_aq.list_pending()) == 1


class TestRecordProposalExecution:
    def test_appends_audit_entry(self):
        proposal = {
            "id": "prop-abc",
            "recommendation_id": "rec-1",
            "action_type": "reassign_gate",
            "description": "Reassign to B12",
            "confidence_score": 0.9,
            "proposed_by": "autonomous",
            "parameters": {"flight_id": "ART100", "gate_id": "B12"},
        }
        entry = record_proposal_execution(proposal, NOW, decided_by="alice")

        assert entry["proposal_id"] == "prop-abc"
        assert entry["recommendation_id"] == "rec-1"
        assert entry["initiated_by"] == "autonomous"
        assert entry["approved_by"] == "alice"
        assert entry["parameters"] == {"flight_id": "ART100", "gate_id": "B12"}
        assert entry["actual_outcome"] is None
        assert entry in get_action_log()

    def test_parameters_default_to_empty(self):
        entry = record_proposal_execution({"id": "prop-x"}, NOW, decided_by="bob")
        assert entry["parameters"] == {}
