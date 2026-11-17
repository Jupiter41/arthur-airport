"""G4 cross-consumer contracts, executable semantics and honest replay gates."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from zipfile import ZipFile

import pytest

from tests.conftest import import_service_module

import_service_module("analysis", "services.effect_adapter")
from _common.effects import (  # noqa: E402
                             Action, Bag, EffectState, Flight, Gate, Security,
                             EFFECT_MODEL_VERSION, apply, planning_actions, planning_window, step)
from _common.effect_replay import validate_replay  # noqa: E402
from _common.effect_policy import require_compatible  # noqa: E402


def _state():
    return EffectState(security={"A": Security(queue=360, lanes=4, wait=30, arrivals_per_minute=12)},
                       flights={"F": Flight(status="boarding", passengers=100),
                                "F2": Flight(status="scheduled", passengers=100),
                                "arrival": Flight(direction="arrival", status="approach")},
                       gates={"A1": Gate(terminal="A"), "B1": Gate(terminal="B", occupant="other")},
                       bags={"bag": Bag(zone="sort", flight_id="F")}, baggage_zones={"sort": 10},
                       incidents={"incident": "active"})


def test_step_wrapper_deterministic_and_never_mutates_input():
    state = _state()
    saved = state.model_dump()
    action = Action(action_type="open_security_lane", parameters={"terminal": "A", "lanes_open": 5})
    projected, _ = step(state, [action])
    for _ in range(29):
        projected, _ = step(projected)
    result = apply([action], state, 30)
    assert result.projected == projected
    assert result == apply([action], state, 30)
    assert state.model_dump() == saved
    assert result.predictions[action.action_type]["delta"] == pytest.approx(-12)
    assert result.projected.security["A"].queue == 270
    assert result.baseline.security["A"].queue == 360


def test_uniform_gdp_and_hold_match_owner_preconditions():
    action = Action(action_type="ground_delay_program", parameters={
        "flight_ids": ["F", "F", "F2", "arrival", "missing"], "stagger_minutes": 10})
    result = apply([action], _state(), 30)
    assert result.projected.flights["F"].delay == result.projected.flights["F2"].delay == 10
    assert result.projected.flights["arrival"].delay == 0
    assert result.impact_value == 0  # no invented missed-connection/airborne-hold savings


def test_baggage_redirection_is_one_bag_not_symbolic_congestion_relief():
    result = apply([Action(action_type="redirect_baggage", parameters={"bag_id": "bag", "target_flight_id": "F2"})], _state(), 30)
    assert result.projected.baggage_zones["sort"] == 9
    assert result.projected.bags["bag"].flight_id == "F2"
    assert result.projected.bags["bag"].status == "redirected"
    assert result.projected.bags["bag"].zone is None


@pytest.mark.parametrize("kind", ["rebook_passengers", "fast_track_passengers", "redistribute_vehicles", "expedite_loading"])
def test_advisory_actions_have_no_effect_model(kind):
    result = apply([Action(action_type=kind)], _state(), 30)
    assert result.projected == result.baseline
    assert result.action_status == ["no_effect_model"] and result.impact_value == 0


def test_gate_assignment_conserves_inventory_and_checks_availability():
    state = _state()
    valid = Action(action_type="reassign_gate", parameters={"flight_id": "F", "gate_id": "A1"})
    blocked = Action(action_type="reassign_gate", parameters={"flight_id": "F", "gate_id": "B1"})
    assert apply([blocked], state, 1).action_status == ["unavailable"]
    result = apply([valid], state, 1)
    assert len(result.projected.gates) == len(state.gates)
    assert result.projected.gates["A1"].occupant == "F" and result.projected.flights["F"].gate == "A1"


def test_calibration_changes_predictions_once_without_creating_resources():
    state = _state()
    action = Action(action_type="open_security_lane", parameters={"terminal": "A", "lanes_open": 5})
    neutral = apply([action], state, 30)
    calibrated = apply([action], state, 30, factors={action.action_type: 0.5})
    assert calibrated.projected == neutral.projected
    assert calibrated.impact_value == pytest.approx(neutral.impact_value / 2)
    assert calibrated.predictions[action.action_type]["delta"] == pytest.approx(-6)


def test_combined_actions_do_not_double_count_the_same_queue_benefit():
    action = Action(action_type="open_security_lane", parameters={"terminal": "A", "lanes_open": 5})
    assert apply([action, action], _state(), 30).impact_value == apply([action], _state(), 30).impact_value


def test_baggage_targets_rebuild_from_graph_and_facts_without_live_mutation():
    module = import_service_module("analysis", "services.state")
    adapter = importlib.import_module("services.effect_adapter")
    state = module.OperationalState()
    state.restore_graph({"flights": [], "gates": [], "incidents": [], "weather": [], "baggage": [],
                         "baggage_targets": [{"id": "bag", "flight_id": "old", "zone": "sort", "status": "sorting"}]})
    state.flights["new"] = module.FlightState(flight_id="new")
    result, _ = adapter.project(state, "redirect_baggage", {"bag_id": "bag", "target_flight_id": "new"})
    assert result.projected.bags["bag"].flight_id == "new"
    assert state.baggage_targets["bag"]["flight_id"] == "old"
    state.on_baggage_status_changed({"baggage_id": "bag", "flight_id": "new", "scan_zone": "redirected", "new_status": "redirected"})
    assert adapter.from_operational(state).bags["bag"].flight_id == "new"


def test_planning_windows_do_not_cap_runways_for_gdp_or_create_gates():
    ivs = [{"action": "gdp_start", "sim_minute": 60, "duration_minutes": 120, "params": {"cap_pct": 0.5}},
           {"action": "gate_swap", "sim_minute": 60, "duration_minutes": 120, "params": {"delta": 5}}]
    assert planning_window(ivs, None, 60) == (1, 0)
    actions = planning_actions(ivs, 60, _state())
    assert actions[0].parameters["stagger_minutes"] == 60
    assert actions[1].parameters["gate_id"] == "A1"
    assert planning_actions(ivs, 61, _state()) == []


def _proposal():
    adapter = import_service_module("analysis", "services.effect_adapter")
    module = importlib.import_module("services.state")
    outcome = importlib.import_module("services.outcome")
    state = module.OperationalState()
    state.sim_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sec = state.security["Terminal A"]
    sec.queue_depth, sec.observed_wait_minutes, sec.last_updated = 360, 30, state.sim_time
    params = {"terminal": "A", "new_lane_count": 5}
    baseline = outcome.observe_baseline("open_security_lane", params, state, state.sim_time, 0.9)
    return state, adapter, {"id": "P", "action_type": "open_security_lane", "parameters": params,
                            "status": "executed", "baseline": baseline,
                            "actual_outcome": {"attribution": {"calibration_eligible": True, "attributed_effect": -12}}}


def test_whatif_ranking_g8_and_rl_share_the_same_effect():
    state, adapter, doc = _proposal()
    domain = importlib.import_module("models.domain")
    whatif = importlib.import_module("services.whatif")
    ranking = importlib.import_module("services.ranking")
    env_module = importlib.import_module("services.rl.env")
    result, _ = adapter.project(state, doc["action_type"], doc["parameters"])
    rec = domain.Recommendation.model_construct(action_type=domain.ActionType.OPEN_SECURITY_LANE,
                                                parameters=doc["parameters"], confidence_score=0.9)
    bn = domain.Bottleneck.model_construct(metrics={}, affected_entity_count=360)
    ranking.score_recommendation(rec, bn, state)
    assert rec.impact_value == result.impact_value
    assert doc["baseline"]["predicted"] == result.predictions[doc["action_type"]]
    request = domain.WhatIfRequest(actions=[domain.WhatIfAction(action_type=doc["action_type"], parameters=doc["parameters"])], horizon_minutes=30)
    response = whatif.run_what_if(state, request)
    assert response.effect_model_version == EFFECT_MODEL_VERSION
    assert response.projections[0].avg_queue_depth == 90  # 270 pax / 3 terminals
    env = env_module.AirportOpsEnv(initial_state=env_module.state_from_operational(state))
    env.reset(seed=7)
    env.step(1)
    for _ in range(29):
        env.step(0)
    assert env._state["effect_state"]["security"]["A"]["queue"] == 270
    assert state.security["Terminal A"].queue_depth == 360


def test_replay_thresholds_duplicates_and_errors_are_honest():
    _, _, doc = _proposal()
    documents = [{**deepcopy(doc), "id": f"P{i}"} for i in range(20)]
    assert validate_replay(documents[:19])["by_action_type"]["open_security_lane"]["status"] == "unvalidated"
    assert validate_replay(documents)["by_action_type"]["open_security_lane"]["status"] == "passed"
    duplicate = validate_replay([*documents, documents[0]])
    assert duplicate["by_action_type"]["open_security_lane"]["samples"] == 20
    for d in documents:
        d["actual_outcome"]["attribution"]["attributed_effect"] = -1
    assert validate_replay(documents)["by_action_type"]["open_security_lane"]["status"] == "failed"
    assert validate_replay([])["by_action_type"]["redirect_baggage"]["status"] == "unvalidated"


@pytest.mark.parametrize("version", [None, "old-env"])
def test_legacy_and_incompatible_policies_are_refused(tmp_path, version):
    path = tmp_path / "policy.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps({"effect_model_version": version} if version else {}))
    with pytest.raises(ValueError, match="retrain"):
        require_compatible(path)


def test_action_free_step_copies_security_and_never_mutates_its_input():
    """The no-action fast path (no deep copy) must keep every step independent."""
    state = _state()
    saved = state.model_dump()
    first, _ = step(state)
    second, _ = step(first)
    assert state.model_dump() == saved
    assert first.security["A"] is not state.security["A"]
    assert second.security["A"] is not first.security["A"]
    assert first.security["A"].queue != state.security["A"].queue or state.security["A"].queue == 0
    # A later action-bearing step deep-copies, so shared untouched parts stay safe.
    third, _ = step(second, [Action(action_type="reassign_gate", parameters={"flight_id": "F2", "gate_id": "A1"})])
    assert third.flights["F2"].gate == "A1" and state.flights["F2"].gate != "A1"
