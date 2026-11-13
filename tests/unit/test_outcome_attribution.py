"""G8: baseline/counterfactual attribution and prediction calibration (A58)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.conftest import import_service_module

outcome = import_service_module("analysis", "services.outcome")
calibration = import_service_module("analysis", "services.calibration")

T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=31)


def _sec(wait, at, lanes=4):
    return SimpleNamespace(observed_wait_minutes=wait, last_updated=at, open_lanes=lanes)


def _security_state(waits, at):
    return SimpleNamespace(security={f"Terminal {k}": _sec(v, at) for k, v in waits.items()})


def test_security_lane_difference_in_differences():
    before = _security_state({"A": 30, "B": 20, "C": 10}, T0)
    baseline = outcome.observe_baseline("open_security_lane", {"terminal": "Terminal A", "new_lane_count": 5},
                                        before, T0, 0.85)
    assert baseline["predicted"] == {"metric": "security_wait_minutes", "delta": -6.0}
    after = _security_state({"A": 18, "B": 16, "C": 8}, T1)
    measured = outcome.measure_outcome("open_security_lane", {"terminal": "A"}, after)
    attribution = outcome.attribute(baseline, measured, outcome.post_observation(baseline, after))
    assert attribution["method"] == "difference_in_differences"
    assert attribution["treated_change"] == -12
    assert attribution["control_change"] == -3            # untreated checkpoints improved too
    assert attribution["attributed_effect"] == -9          # only 9 min is beyond the counterfactual
    assert attribution["counterfactual_after"] == 27
    assert attribution["calibration_eligible"] is True and attribution["causal_claim"] is False


def test_stale_observations_are_not_attributed():
    before = _security_state({"A": 30, "B": 20}, T0)
    baseline = outcome.observe_baseline("open_security_lane", {"terminal": "A"}, before, T0, 0.85)
    stale = _security_state({"A": 10, "B": 20}, T0)       # projection never refreshed after execution
    measured = outcome.measure_outcome("open_security_lane", {"terminal": "A"}, stale)
    attribution = outcome.attribute(baseline, measured, outcome.post_observation(baseline, stale))
    assert attribution["calibration_eligible"] is False
    assert "refreshed" in attribution["reason"]


def test_security_without_fresh_controls_is_pre_post_only():
    before = _security_state({"A": 30, "B": 20}, T0)
    baseline = outcome.observe_baseline("open_security_lane", {"terminal": "A"}, before, T0, 0.85)
    after = SimpleNamespace(security={"Terminal A": _sec(20, T1), "Terminal B": _sec(20, T0)})
    measured = outcome.measure_outcome("open_security_lane", {"terminal": "A"}, after)
    attribution = outcome.attribute(baseline, measured, outcome.post_observation(baseline, after))
    assert attribution["method"] == "pre_post" and attribution["calibration_eligible"] is False
    assert attribution["control_count"] == 0


def test_gate_reassignment_lift_over_untreated_control_rate():
    flights = {
        "F1": SimpleNamespace(gate=None, status="holding"),
        "F2": SimpleNamespace(gate=None, status="holding"),
        "F3": SimpleNamespace(gate=None, status="landed"),
        "F4": SimpleNamespace(gate="A1", status="boarding"),   # not waiting → not a control
    }
    state = SimpleNamespace(flights=flights)
    baseline = outcome.observe_baseline("reassign_gate", {"flight_id": "F1", "gate_id": "B7"}, state, T0, 0.7)
    assert baseline["controls"] == ["F2", "F3"] and baseline["treated"] == 0
    flights["F1"].gate, flights["F2"].gate = "B7", "C2"
    measured = outcome.measure_outcome("reassign_gate", {"flight_id": "F1", "gate_id": "B7"}, state)
    attribution = outcome.attribute(baseline, measured, outcome.post_observation(baseline, state))
    assert attribution["method"] == "untreated_control_rate"
    assert attribution["control_rate"] == 0.5
    assert attribution["attributed_effect"] == 0.5
    assert attribution["predicted_probability"] == 0.7


def test_incident_attribution_uses_persisted_statuses():
    state = SimpleNamespace(active_incidents={"I1": {"status": "active"}, "I2": {"status": "active"},
                                              "I3": {"status": "resolved"}})
    baseline = outcome.observe_baseline("resolve_incident", {"incident_id": "I1"}, state, T0, 0.9)
    assert baseline["controls"] == ["I2"]
    statuses = {"I1": "resolved", "I2": "active"}
    measured = outcome.measure_outcome("resolve_incident", {"incident_id": "I1"},
                                       SimpleNamespace(active_incidents={"I1": {"status": "resolved"}}))
    attribution = outcome.attribute(baseline, measured, outcome.post_observation(baseline, state, statuses))
    assert attribution["attributed_effect"] == 1 and attribution["control_rate"] == 0


def test_unmodelled_actions_have_no_baseline():
    assert outcome.observe_baseline("ground_delay_program", {}, SimpleNamespace(), T0, 0.5) is None
    attribution = outcome.attribute(None, {"measurable": False, "reason": "x"}, {})
    assert attribution["calibration_eligible"] is False


def _executed(action_type, attribution, confidence=0.8):
    return {"status": "executed", "action_type": action_type, "confidence_score": confidence,
            "actual_outcome": {"measurable": True, "attribution": attribution}}


def test_calibration_shrinks_towards_neutral_and_ignores_ineligible():
    security = {"calibration_eligible": True, "metric": "security_wait_minutes",
                "attributed_effect": -3.0, "predicted_effect": -6.0}
    documents = [_executed("open_security_lane", security) for _ in range(5)]
    documents.append(_executed("open_security_lane", {"calibration_eligible": False,
                                                      "attributed_effect": -50.0, "predicted_effect": -6.0}))
    snapshot = calibration.build(documents)
    entry = snapshot["by_action_type"]["open_security_lane"]
    assert entry["samples"] == 5 and snapshot["measured_outcomes"] == 6
    assert entry["effect_ratio"] == 0.5
    assert entry["impact_factor"] == pytest.approx(0.75)        # (5*0.5 + 5) / 10
    assert entry["success_rate"] == 1.0
    assert entry["confidence_factor"] == pytest.approx((5 * 1.25 + 5) / 10)
    assert entry["brier_score"] == pytest.approx(0.04)
    assert calibration.factors("open_security_lane", snapshot).impact == pytest.approx(0.75)
    assert calibration.factors("reassign_gate", snapshot) == calibration.Factors()


def test_calibration_factors_are_bounded():
    assert calibration.shrink(100.0, 1000) == calibration.FACTOR_MAX
    assert calibration.shrink(0.0, 1000) == calibration.FACTOR_MIN
    assert calibration.shrink(3.0, 0) == 1.0


def test_ranking_applies_calibration_factors():
    ranking = import_service_module("analysis", "services.ranking")
    cal = __import__("services.calibration", fromlist=["refresh"])
    domain = __import__("models.domain", fromlist=["Recommendation"])
    bn = domain.Bottleneck.model_construct(metrics={"forecast_wait_minutes": 20, "queue_depth": 10},
                                           affected_entity_count=10)
    rec = domain.Recommendation.model_construct(action_type=domain.ActionType.OPEN_SECURITY_LANE,
                                                parameters={"new_lane_count": 5}, confidence_score=0.8)
    cal.refresh([])
    base = ranking.score_recommendation(rec, bn)
    security = {"calibration_eligible": True, "metric": "security_wait_minutes",
                "attributed_effect": -1.0, "predicted_effect": -4.0}
    cal.refresh([_executed("open_security_lane", security) for _ in range(20)])
    calibrated = ranking.score_recommendation(rec, bn)
    assert rec.calibration_samples == 20 and rec.calibration_impact_factor < 1
    assert calibrated < base
    cal.refresh([])
