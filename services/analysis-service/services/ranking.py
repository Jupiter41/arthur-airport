"""Rank the shared G4 projection's benefit * calibrated confidence / cost."""
from __future__ import annotations

from _common.effects import Action, EFFECT_MODEL_VERSION, EffectState, Security, apply, parameters, security_throughput
from models.domain import Bottleneck, Recommendation
from services import calibration
from services.effect_adapter import project

COST_FLOOR = parameters().cost_floor


def _projection(rec: Recommendation, bn: Bottleneck, state=None):
    if state is not None:
        return project(state, rec.action_type.value, rec.parameters)[0]
    # Offline scoring can project terminal totals; absent entity targets remain unobserved.
    params = parameters()
    lanes = int(rec.parameters.get("new_lane_count", rec.parameters.get("lanes_open", 5))) - 1
    lanes = max(0, lanes)
    name = str(rec.parameters.get("terminal", getattr(bn, "zone", "A"))).removeprefix("Terminal ")
    compact = EffectState(security={name: Security(
        queue=max(0, bn.metrics.get("queue_depth", bn.affected_entity_count)), lanes=lanes,
        wait=max(0, bn.metrics.get("forecast_wait_minutes", 0)),
        arrivals_per_minute=security_throughput(lanes, params))})
    factor = calibration.factors(rec.action_type.value).impact
    return apply([Action(action_type=rec.action_type.value, parameters=rec.parameters)], compact,
                 params.prediction_horizon_minutes, params=params, factors={rec.action_type.value: factor})


def estimate_impact_cost(rec: Recommendation, bn: Bottleneck, state=None) -> tuple[float, float]:
    projection = _projection(rec, bn, state)
    return projection.impact_value, projection.cost_value


def score_recommendation(rec: Recommendation, bn: Bottleneck, state=None) -> float:
    projection = _projection(rec, bn, state)
    factors = calibration.factors(rec.action_type.value)
    rec.effect_model_version = EFFECT_MODEL_VERSION
    rec.effect_status = projection.action_status[0]
    rec.projection = projection.predictions.get(rec.action_type.value)
    if rec.projection and rec.projection.get("metric") == "security_wait_minutes":
        rec.expected_impact = f"Projected wait change {rec.projection['delta']:.1f} min over {parameters().prediction_horizon_minutes} sim-minutes"
    elif rec.effect_status == "no_effect_model":
        rec.expected_impact = "Advisory: no shared effect model"
    rec.impact_value = projection.impact_value
    rec.cost_value = projection.cost_value
    rec.calibration_impact_factor = factors.impact
    rec.calibration_confidence_factor = factors.confidence
    rec.calibration_samples = factors.samples
    confidence = min(1.0, rec.confidence_score * factors.confidence)
    rec.priority_score = rec.impact_value * confidence / rec.cost_value
    return rec.priority_score
