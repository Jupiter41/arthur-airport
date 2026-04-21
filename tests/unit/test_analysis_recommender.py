"""Unit tests for analysis-service recommender.

Tests the recommendation engine: generates ranked interventions for detected
bottlenecks, checks correct action types, parameter passing, and ranking.
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

from tests.conftest import import_service_module

_state_mod = import_service_module("analysis", "services.state")
OperationalState = _state_mod.OperationalState
FlightState = _state_mod.FlightState
SecurityState = _state_mod.SecurityState

_rec_mod = import_service_module("analysis", "services.recommender")
generate_recommendations = _rec_mod.generate_recommendations

_domain_mod = import_service_module("analysis", "models.domain")
ActionType = _domain_mod.ActionType
Bottleneck = _domain_mod.Bottleneck
BottleneckSeverity = _domain_mod.BottleneckSeverity
BottleneckType = _domain_mod.BottleneckType


NOW = datetime(2024, 6, 15, 14, 30, 0)


@pytest.fixture
def state():
    s = OperationalState()
    s.sim_time = NOW
    return s


def _make_bottleneck(bn_type: BottleneckType, zone: str, **metrics) -> Bottleneck:
    return Bottleneck(
        id="bn-test-01",
        type=bn_type,
        severity=BottleneckSeverity.WARNING,
        zone=zone,
        root_cause="test bottleneck",
        estimated_duration_minutes=30,
        affected_entity_count=10,
        detected_at=NOW,
        metrics=metrics,
    )


class TestSecurityQueueRecommendations:
    def test_generates_open_lane_rec(self, state: OperationalState):
        state.security["Terminal A"].open_lanes = 4
        state.security["Terminal A"].queue_depth = 80
        state.security["Terminal A"].forecast_wait_minutes = 25
        bn = _make_bottleneck(
            BottleneckType.SECURITY_QUEUE, "Terminal A",
            forecast_wait_minutes=25, open_lanes=4,
        )
        recs = generate_recommendations(state, [bn], max_total=10)
        open_lane = [r for r in recs if r.action_type == ActionType.OPEN_SECURITY_LANE]
        assert len(open_lane) >= 1
        assert open_lane[0].parameters["terminal"] == "Terminal A"

    def test_generates_early_gate_call(self, state: OperationalState):
        state.security["Terminal B"].queue_depth = 70
        state.security["Terminal B"].forecast_wait_minutes = 22
        state.flights["dep-1"] = FlightState(
            flight_id="dep-1", status="scheduled",
            flight_type="departure", terminal="Terminal B",
        )
        bn = _make_bottleneck(
            BottleneckType.SECURITY_QUEUE, "Terminal B",
            forecast_wait_minutes=22,
        )
        recs = generate_recommendations(state, [bn], max_total=10)
        gate_call = [r for r in recs if r.action_type == ActionType.EARLY_GATE_CALL]
        assert len(gate_call) >= 1


class TestGateRecommendations:
    def test_reassign_gate_when_alternate_available(self, state: OperationalState):
        # Terminal A full, Terminal B has room
        for i in range(14):
            state.flights[f"f-{i}"] = FlightState(
                flight_id=f"f-{i}", status="at_gate",
                gate=f"A{i:02d}", terminal="Terminal A",
            )
        bn = _make_bottleneck(BottleneckType.GATE_UTILISATION, "Terminal A")
        recs = generate_recommendations(state, [bn], max_total=10)
        reassign = [r for r in recs if r.action_type == ActionType.REASSIGN_GATE]
        assert len(reassign) >= 1

    def test_delay_taxi_when_flights_waiting(self, state: OperationalState):
        state.flights["landed-1"] = FlightState(
            flight_id="landed-1", status="landed",
        )
        bn = _make_bottleneck(BottleneckType.GATE_UTILISATION, "Terminal A")
        recs = generate_recommendations(state, [bn], max_total=10)
        taxi = [r for r in recs if r.action_type == ActionType.DELAY_TAXI]
        assert len(taxi) >= 1


class TestConnectionRecoveryRecommendations:
    def test_hold_connecting_flight(self, state: OperationalState):
        bn = _make_bottleneck(
            BottleneckType.CONNECTION_CLUSTER, "in1->out1",
            inbound_flight="in1", outbound_flight="out1",
            passenger_count=8, inbound_delay=20,
        )
        recs = generate_recommendations(state, [bn], max_total=10)
        hold = [r for r in recs if r.action_type == ActionType.HOLD_CONNECTING_FLIGHT]
        assert len(hold) >= 1
        assert hold[0].parameters["passengers_saved"] == 8


class TestRunwayCapacityRecommendations:
    def test_ground_delay_program(self, state: OperationalState):
        bn = _make_bottleneck(
            BottleneckType.RUNWAY_CAPACITY, "airport",
            runway_capacity_pct=45,
        )
        recs = generate_recommendations(state, [bn], max_total=10)
        gdp = [r for r in recs if r.action_type == ActionType.GROUND_DELAY_PROGRAM]
        assert len(gdp) >= 1


class TestGenerateRecommendations:
    def test_returns_empty_without_sim_time(self, state: OperationalState):
        state.sim_time = None
        bn = _make_bottleneck(BottleneckType.SECURITY_QUEUE, "Terminal A")
        recs = generate_recommendations(state, [bn])
        assert recs == []

    def test_skips_resolved_bottlenecks(self, state: OperationalState):
        bn = _make_bottleneck(BottleneckType.SECURITY_QUEUE, "Terminal A")
        bn.resolved_at = NOW
        recs = generate_recommendations(state, [bn], max_total=10)
        assert recs == []

    def test_max_total_limits_output(self, state: OperationalState):
        state.security["Terminal A"].open_lanes = 4
        state.security["Terminal A"].queue_depth = 80
        state.security["Terminal B"].queue_depth = 60
        bn1 = _make_bottleneck(
            BottleneckType.SECURITY_QUEUE, "Terminal A",
            forecast_wait_minutes=25,
        )
        bn2 = _make_bottleneck(
            BottleneckType.SECURITY_QUEUE, "Terminal B",
            forecast_wait_minutes=22,
        )
        bn2.id = "bn-test-02"
        recs = generate_recommendations(state, [bn1, bn2], max_total=2)
        assert len(recs) <= 2

    def test_recs_sorted_by_confidence(self, state: OperationalState):
        state.security["Terminal A"].open_lanes = 4
        state.security["Terminal A"].queue_depth = 80
        bn = _make_bottleneck(
            BottleneckType.SECURITY_QUEUE, "Terminal A",
            forecast_wait_minutes=25, open_lanes=4,
        )
        state.flights["dep-1"] = FlightState(
            flight_id="dep-1", status="scheduled",
            flight_type="departure", terminal="Terminal A",
        )
        recs = generate_recommendations(state, [bn], max_total=10)
        if len(recs) >= 2:
            assert recs[0].confidence_score >= recs[1].confidence_score
