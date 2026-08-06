"""Unit tests for the manual "Apply" path (analysis-service autonomous.apply_recommendation).

Covers the pure apply-by-id logic that backs the operator "Apply" button:
find the recommendation, mark it applied, record a tagged action-log entry,
and reject unknown/already-applied ids. No Kafka/Neo4j — the router emits the
event; this function only mutates in-memory state and returns the log entry.
"""

from datetime import datetime, timedelta

from tests.conftest import import_service_module

_auto = import_service_module("analysis", "services.autonomous")
_domain = import_service_module("analysis", "models.domain")

apply_recommendation = _auto.apply_recommendation
Recommendation = _domain.Recommendation
ActionType = _domain.ActionType

NOW = datetime(2024, 6, 15, 14, 30, 0)


def _rec(rec_id: str, *, applied: bool = False) -> Recommendation:
    return Recommendation(
        id=rec_id,
        bottleneck_id=f"bn-{rec_id}",
        action_type=ActionType.REASSIGN_GATE,
        description="Reassign next arrival to Terminal B",
        expected_impact="Free gate pressure",
        cost="5 min walk",
        confidence_score=0.8,
        expiry_sim_time=NOW + timedelta(minutes=45),
        priority_rank=1,
        parameters={"alternate_terminal": "B"},
        applied=applied,
    )


class TestApplyRecommendation:
    def test_applies_known_recommendation(self):
        recs = [_rec("rec-1")]
        entry = apply_recommendation(recs, "rec-1", NOW)
        assert entry is not None
        assert entry["recommendation_id"] == "rec-1"
        assert entry["action_type"] == "reassign_gate"
        assert entry["initiated_by"] == "operator"
        assert entry["applied_at"] == NOW.isoformat()
        # The recommendation object is marked applied in place.
        assert recs[0].applied is True
        assert recs[0].applied_at == NOW

    def test_carries_parameters_into_log(self):
        recs = [_rec("rec-1")]
        entry = apply_recommendation(recs, "rec-1", NOW)
        assert entry["parameters"] == {"alternate_terminal": "B"}

    def test_initiated_by_is_overridable(self):
        recs = [_rec("rec-1")]
        entry = apply_recommendation(recs, "rec-1", NOW, initiated_by="agent")
        assert entry["initiated_by"] == "agent"

    def test_unknown_id_returns_none(self):
        recs = [_rec("rec-1")]
        assert apply_recommendation(recs, "does-not-exist", NOW) is None

    def test_already_applied_returns_none(self):
        recs = [_rec("rec-1", applied=True)]
        assert apply_recommendation(recs, "rec-1", NOW) is None

    def test_double_apply_is_rejected(self):
        recs = [_rec("rec-1")]
        first = apply_recommendation(recs, "rec-1", NOW)
        second = apply_recommendation(recs, "rec-1", NOW)
        assert first is not None
        assert second is None

    def test_registers_bottleneck_cooldown(self):
        # Applying must register a cooldown so the autonomous engine does not
        # immediately re-action the same bottleneck.
        recs = [_rec("rec-1")]
        apply_recommendation(recs, "rec-1", NOW)
        assert _auto._bottleneck_cooldowns.get("bn-rec-1") == NOW

    def test_appends_to_action_log(self):
        before = len(_auto.get_action_log())
        recs = [_rec("rec-log")]
        apply_recommendation(recs, "rec-log", NOW)
        after = _auto.get_action_log()
        assert len(after) == before + 1
        assert after[-1]["recommendation_id"] == "rec-log"
