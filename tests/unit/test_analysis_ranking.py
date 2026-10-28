"""Unit tests for the recommendation impact/cost ranking (roadmap G5).

Proves the recommender ranks by impact * confidence / cost rather than
confidence alone: a high-impact, slightly-lower-confidence intervention
outranks a trivial high-confidence one.
"""

from datetime import datetime, timedelta

import pytest

from tests.conftest import import_service_module

_ranking = import_service_module("analysis", "services.ranking")
estimate_impact_cost = _ranking.estimate_impact_cost
score_recommendation = _ranking.score_recommendation
COST_FLOOR = _ranking.COST_FLOOR

_domain = import_service_module("analysis", "models.domain")
ActionType = _domain.ActionType
Bottleneck = _domain.Bottleneck
BottleneckSeverity = _domain.BottleneckSeverity
BottleneckType = _domain.BottleneckType
Recommendation = _domain.Recommendation

NOW = datetime(2024, 6, 15, 14, 30, 0)


def _bn(bn_type=BottleneckType.SECURITY_QUEUE, affected=10, **metrics) -> Bottleneck:
    return Bottleneck(
        id="bn-1",
        type=bn_type,
        severity=BottleneckSeverity.WARNING,
        zone="Terminal A",
        root_cause="t",
        estimated_duration_minutes=30,
        affected_entity_count=affected,
        detected_at=NOW,
        metrics=metrics,
    )


def _rec(action: ActionType, confidence=0.8, **params) -> Recommendation:
    return Recommendation(
        id="rec-1",
        bottleneck_id="bn-1",
        action_type=action,
        description="d",
        expected_impact="i",
        cost="c",
        confidence_score=confidence,
        expiry_sim_time=NOW + timedelta(minutes=30),
        priority_rank=1,
        parameters=params,
    )


class TestScoring:
    def test_cost_is_floored(self):
        rec = _rec(ActionType.EARLY_GATE_CALL)
        _, cost = estimate_impact_cost(rec, _bn(affected=0))
        assert cost >= COST_FLOOR

    def test_score_populates_fields(self):
        rec = _rec(ActionType.OPEN_SECURITY_LANE, new_lane_count=5)
        bn = _bn(forecast_wait_minutes=30, queue_depth=100)
        score = score_recommendation(rec, bn)
        assert rec.impact_value > 0
        assert rec.cost_value >= COST_FLOOR
        assert rec.priority_score == pytest.approx(
            rec.impact_value * rec.confidence_score / rec.cost_value
        )
        assert score == rec.priority_score

    def test_hold_connection_scales_with_passengers_saved(self):
        few = _rec(ActionType.HOLD_CONNECTING_FLIGHT, passengers_saved=2, hold_minutes=15)
        many = _rec(ActionType.HOLD_CONNECTING_FLIGHT, passengers_saved=40, hold_minutes=15)
        bn = _bn(BottleneckType.CONNECTION_CLUSTER)
        assert estimate_impact_cost(many, bn)[0] > estimate_impact_cost(few, bn)[0]

    def test_bool_passenger_count_rejected(self):
        # bool is an int subclass — must not be read as a passenger count.
        rec = _rec(ActionType.HOLD_CONNECTING_FLIGHT, passengers_saved=True, hold_minutes=10)
        bn = _bn(BottleneckType.CONNECTION_CLUSTER, passenger_count=0)
        assert estimate_impact_cost(rec, bn)[0] == 0.0


class TestRankingOverridesConfidence:
    def test_high_impact_beats_higher_confidence_trivial_action(self):
        bn = _bn(BottleneckType.CONNECTION_CLUSTER)
        # Trivial announcement: very high confidence, tiny impact.
        trivial = _rec(ActionType.EARLY_GATE_CALL, confidence=0.99)
        # Saving 40 connections: lower confidence, huge impact.
        big = _rec(
            ActionType.HOLD_CONNECTING_FLIGHT,
            confidence=0.70,
            passengers_saved=40,
            hold_minutes=15,
        )
        score_recommendation(trivial, bn)
        score_recommendation(big, bn)
        assert big.confidence_score < trivial.confidence_score
        assert big.priority_score > trivial.priority_score
