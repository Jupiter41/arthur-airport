"""Unit tests for analysis-service detectors.

Tests the six bottleneck detection functions against known operational state
configurations — ensuring correct detection, severity, dedup, and resolution.
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
BaggageZoneState = _state_mod.BaggageZoneState
VehicleTypeState = _state_mod.VehicleTypeState

_det_mod = import_service_module("analysis", "services.detectors")
detect_all = _det_mod.detect_all
check_resolved = _det_mod.check_resolved
SECURITY_WAIT_WARNING_MIN = _det_mod.SECURITY_WAIT_WARNING_MIN
SECURITY_WAIT_CRITICAL_MIN = _det_mod.SECURITY_WAIT_CRITICAL_MIN
GATE_FREE_WARNING = _det_mod.GATE_FREE_WARNING
GATE_FREE_CRITICAL = _det_mod.GATE_FREE_CRITICAL
MAKEUP_UTIL_WARNING_PCT = _det_mod.MAKEUP_UTIL_WARNING_PCT
MAKEUP_UTIL_CRITICAL_PCT = _det_mod.MAKEUP_UTIL_CRITICAL_PCT
VEHICLE_UTIL_WARNING_PCT = _det_mod.VEHICLE_UTIL_WARNING_PCT
RUNWAY_CAPACITY_LOW_PCT = _det_mod.RUNWAY_CAPACITY_LOW_PCT
CONNECTION_CLUSTER_MIN_PAX = _det_mod.CONNECTION_CLUSTER_MIN_PAX

_domain_mod = import_service_module("analysis", "models.domain")
BottleneckType = _domain_mod.BottleneckType
BottleneckSeverity = _domain_mod.BottleneckSeverity
Bottleneck = _domain_mod.Bottleneck


NOW = datetime(2024, 6, 15, 14, 30, 0)


@pytest.fixture
def state():
    s = OperationalState()
    s.sim_time = NOW
    return s


# ── Security Queue Detector ─────────────────────────────────


class TestSecurityQueueDetector:
    def test_no_bottleneck_below_threshold(self, state: OperationalState):
        state.security["Terminal A"].forecast_wait_minutes = 10.0
        state.security["Terminal A"].forecast_confidence = 0.9
        bns = detect_all(state, {})
        sec = [b for b in bns if b.type == BottleneckType.SECURITY_QUEUE]
        assert len(sec) == 0

    def test_warning_at_threshold(self, state: OperationalState):
        state.security["Terminal B"].forecast_wait_minutes = SECURITY_WAIT_WARNING_MIN + 1
        state.security["Terminal B"].forecast_confidence = 0.8
        state.security["Terminal B"].queue_depth = 50
        bns = detect_all(state, {})
        sec = [b for b in bns if b.type == BottleneckType.SECURITY_QUEUE]
        assert len(sec) == 1
        assert sec[0].severity == BottleneckSeverity.WARNING
        assert sec[0].zone == "Terminal B"

    def test_critical_at_high_wait(self, state: OperationalState):
        state.security["Terminal A"].forecast_wait_minutes = SECURITY_WAIT_CRITICAL_MIN + 5
        state.security["Terminal A"].forecast_confidence = 0.85
        state.security["Terminal A"].queue_depth = 120
        bns = detect_all(state, {})
        sec = [b for b in bns if b.type == BottleneckType.SECURITY_QUEUE]
        assert len(sec) == 1
        assert sec[0].severity == BottleneckSeverity.CRITICAL

    def test_low_confidence_no_detection(self, state: OperationalState):
        state.security["Terminal C"].forecast_wait_minutes = 40.0
        state.security["Terminal C"].forecast_confidence = 0.5
        bns = detect_all(state, {})
        sec = [b for b in bns if b.type == BottleneckType.SECURITY_QUEUE]
        assert len(sec) == 0

    def test_dedup_existing_bottleneck(self, state: OperationalState):
        state.security["Terminal A"].forecast_wait_minutes = 25.0
        state.security["Terminal A"].forecast_confidence = 0.9
        existing_bn = Bottleneck(
            id="bn-existing",
            type=BottleneckType.SECURITY_QUEUE,
            severity=BottleneckSeverity.WARNING,
            zone="Terminal A",
            root_cause="test",
            estimated_duration_minutes=15,
            affected_entity_count=10,
            detected_at=NOW,
        )
        bns = detect_all(state, {"bn-existing": existing_bn})
        sec = [b for b in bns if b.type == BottleneckType.SECURITY_QUEUE and b.zone == "Terminal A"]
        assert len(sec) == 0

    def test_resolved_when_wait_drops(self, state: OperationalState):
        state.security["Terminal A"].forecast_wait_minutes = 10.0
        bn = Bottleneck(
            id="bn-test",
            type=BottleneckType.SECURITY_QUEUE,
            severity=BottleneckSeverity.WARNING,
            zone="Terminal A",
            root_cause="test",
            estimated_duration_minutes=15,
            affected_entity_count=10,
            detected_at=NOW,
        )
        assert check_resolved(state, bn)


# ── Gate Utilisation Detector ────────────────────────────────


class TestGateUtilisationDetector:
    def test_no_bottleneck_plenty_free_gates(self, state: OperationalState):
        bns = detect_all(state, {})
        gate = [b for b in bns if b.type == BottleneckType.GATE_UTILISATION]
        assert len(gate) == 0

    def test_detects_low_free_gates_with_waiting(self, state: OperationalState):
        # Fill up Terminal A with flights at gates
        for i in range(13):
            fid = f"flight-{i}"
            state.flights[fid] = FlightState(
                flight_id=fid, status="at_gate",
                gate=f"A{i:02d}", terminal="Terminal A",
            )
        # One flight needing a gate
        state.flights["waiting-1"] = FlightState(
            flight_id="waiting-1", status="holding",
            terminal="Terminal A",
        )
        bns = detect_all(state, {})
        gate = [b for b in bns if b.type == BottleneckType.GATE_UTILISATION]
        assert len(gate) >= 1
        assert gate[0].zone == "Terminal A"

    def test_critical_when_zero_free(self, state: OperationalState):
        for i in range(14):
            fid = f"flight-{i}"
            state.flights[fid] = FlightState(
                flight_id=fid, status="boarding",
                gate=f"A{i:02d}", terminal="Terminal A",
            )
        state.flights["waiting"] = FlightState(
            flight_id="waiting", status="landed",
        )
        bns = detect_all(state, {})
        gate = [b for b in bns if b.type == BottleneckType.GATE_UTILISATION]
        assert any(b.severity == BottleneckSeverity.CRITICAL for b in gate)

    def test_resolved_when_gates_freed(self, state: OperationalState):
        bn = Bottleneck(
            id="bn-gate",
            type=BottleneckType.GATE_UTILISATION,
            severity=BottleneckSeverity.WARNING,
            zone="Terminal A",
            root_cause="test",
            estimated_duration_minutes=30,
            affected_entity_count=1,
            detected_at=NOW,
        )
        assert check_resolved(state, bn)


# ── Baggage Throughput Detector ──────────────────────────────


class TestBaggageThroughputDetector:
    def test_no_bottleneck_normal_util(self, state: OperationalState):
        state.baggage_zones["MU-A-1"] = BaggageZoneState(
            zone="MU-A-1", capacity=150, current_count=60, utilisation_pct=40.0,
        )
        bns = detect_all(state, {})
        bag = [b for b in bns if b.type == BottleneckType.BAGGAGE_THROUGHPUT]
        assert len(bag) == 0

    def test_no_bottleneck_high_util_short_duration(self, state: OperationalState):
        state.baggage_zones["MU-B-1"] = BaggageZoneState(
            zone="MU-B-1", capacity=150, current_count=140, utilisation_pct=93.3,
        )
        # Just started being over threshold
        state.makeup_over_threshold_since["MU-B-1"] = NOW - timedelta(minutes=2)
        bns = detect_all(state, {})
        bag = [b for b in bns if b.type == BottleneckType.BAGGAGE_THROUGHPUT]
        assert len(bag) == 0

    def test_detects_after_duration_threshold(self, state: OperationalState):
        state.baggage_zones["MU-C-1"] = BaggageZoneState(
            zone="MU-C-1", capacity=150, current_count=140, utilisation_pct=93.3,
        )
        state.makeup_over_threshold_since["MU-C-1"] = NOW - timedelta(minutes=6)
        bns = detect_all(state, {})
        bag = [b for b in bns if b.type == BottleneckType.BAGGAGE_THROUGHPUT]
        assert len(bag) == 1
        assert bag[0].severity == BottleneckSeverity.WARNING

    def test_critical_at_very_high_util(self, state: OperationalState):
        state.baggage_zones["MU-A-2"] = BaggageZoneState(
            zone="MU-A-2", capacity=150, current_count=148,
            utilisation_pct=MAKEUP_UTIL_CRITICAL_PCT + 1,
        )
        state.makeup_over_threshold_since["MU-A-2"] = NOW - timedelta(minutes=10)
        bns = detect_all(state, {})
        bag = [b for b in bns if b.type == BottleneckType.BAGGAGE_THROUGHPUT]
        assert len(bag) == 1
        assert bag[0].severity == BottleneckSeverity.CRITICAL

    def test_resolved_when_util_drops(self, state: OperationalState):
        state.baggage_zones["MU-A-1"] = BaggageZoneState(
            zone="MU-A-1", capacity=150, current_count=50,
            utilisation_pct=33.3,
        )
        bn = Bottleneck(
            id="bn-bag",
            type=BottleneckType.BAGGAGE_THROUGHPUT,
            severity=BottleneckSeverity.WARNING,
            zone="MU-A-1",
            root_cause="test",
            estimated_duration_minutes=15,
            affected_entity_count=5,
            detected_at=NOW,
        )
        assert check_resolved(state, bn)


# ── Connection Cluster Detector ──────────────────────────────


class TestConnectionClusterDetector:
    def test_no_bottleneck_small_cluster(self, state: OperationalState):
        state.connection_clusters = [
            {"inbound_flight": "f1", "outbound_flight": "f2", "pax_count": 3},
        ]
        bns = detect_all(state, {})
        conn = [b for b in bns if b.type == BottleneckType.CONNECTION_CLUSTER]
        assert len(conn) == 0

    def test_detects_large_cluster(self, state: OperationalState):
        state.connection_clusters = [
            {
                "inbound_flight": "inbound-1",
                "outbound_flight": "outbound-1",
                "pax_count": CONNECTION_CLUSTER_MIN_PAX + 2,
                "inbound_delay": 45,
            },
        ]
        bns = detect_all(state, {})
        conn = [b for b in bns if b.type == BottleneckType.CONNECTION_CLUSTER]
        assert len(conn) == 1
        assert conn[0].severity == BottleneckSeverity.CRITICAL

    def test_resolved_when_inbound_arrives(self, state: OperationalState):
        state.flights["inbound-1"] = FlightState(
            flight_id="inbound-1", status="arrived",
        )
        bn = Bottleneck(
            id="bn-conn",
            type=BottleneckType.CONNECTION_CLUSTER,
            severity=BottleneckSeverity.CRITICAL,
            zone="inbound-1->outbound-1",
            root_cause="test",
            estimated_duration_minutes=45,
            affected_entity_count=7,
            detected_at=NOW,
            metrics={"inbound_flight": "inbound-1"},
        )
        assert check_resolved(state, bn)


# ── Ground Vehicle Detector ──────────────────────────────────


class TestGroundVehicleDetector:
    def test_no_bottleneck_low_util(self, state: OperationalState):
        state.vehicles["fuel_truck"] = VehicleTypeState(
            vehicle_type="fuel_truck", total=10, dispatched=3, utilisation_pct=30.0,
        )
        bns = detect_all(state, {})
        gv = [b for b in bns if b.type == BottleneckType.GROUND_VEHICLE]
        assert len(gv) == 0

    def test_detects_high_util_with_demand(self, state: OperationalState):
        state.vehicles["fuel_truck"] = VehicleTypeState(
            vehicle_type="fuel_truck", total=10, dispatched=9,
            utilisation_pct=VEHICLE_UTIL_WARNING_PCT + 1,
        )
        state.flights["ta-1"] = FlightState(
            flight_id="ta-1", status="turnaround",
        )
        bns = detect_all(state, {})
        gv = [b for b in bns if b.type == BottleneckType.GROUND_VEHICLE]
        assert len(gv) == 1
        assert gv[0].zone == "fuel_truck"

    def test_resolved_when_util_drops(self, state: OperationalState):
        state.vehicles["fuel_truck"] = VehicleTypeState(
            vehicle_type="fuel_truck", total=10, dispatched=3, utilisation_pct=30.0,
        )
        bn = Bottleneck(
            id="bn-gv",
            type=BottleneckType.GROUND_VEHICLE,
            severity=BottleneckSeverity.WARNING,
            zone="fuel_truck",
            root_cause="test",
            estimated_duration_minutes=15,
            affected_entity_count=1,
            detected_at=NOW,
        )
        assert check_resolved(state, bn)


# ── Runway Capacity Detector ────────────────────────────────


class TestRunwayCapacityDetector:
    def test_no_bottleneck_good_weather(self, state: OperationalState):
        state.weather.runway_capacity_pct = 100.0
        bns = detect_all(state, {})
        rwy = [b for b in bns if b.type == BottleneckType.RUNWAY_CAPACITY]
        assert len(rwy) == 0

    def test_detects_reduced_capacity(self, state: OperationalState):
        state.weather.runway_capacity_pct = RUNWAY_CAPACITY_LOW_PCT - 5
        # Must have enough flights in queue to trigger
        for i in range(6):
            state.flights[f"rwy-{i}"] = FlightState(
                flight_id=f"rwy-{i}", status="approaching",
            )
        bns = detect_all(state, {})
        rwy = [b for b in bns if b.type == BottleneckType.RUNWAY_CAPACITY]
        assert len(rwy) == 1

    def test_resolved_when_weather_improves(self, state: OperationalState):
        state.weather.runway_capacity_pct = 80.0
        bn = Bottleneck(
            id="bn-rwy",
            type=BottleneckType.RUNWAY_CAPACITY,
            severity=BottleneckSeverity.WARNING,
            zone="airport",
            root_cause="test",
            estimated_duration_minutes=60,
            affected_entity_count=5,
            detected_at=NOW,
        )
        assert check_resolved(state, bn)


# ── detect_all integration ───────────────────────────────────


class TestDetectAll:
    def test_returns_empty_without_sim_time(self, state: OperationalState):
        state.sim_time = None
        bns = detect_all(state, {})
        assert bns == []

    def test_multi_bottleneck_detection(self, state: OperationalState):
        # Security
        state.security["Terminal A"].forecast_wait_minutes = 25.0
        state.security["Terminal A"].forecast_confidence = 0.9
        state.security["Terminal A"].queue_depth = 80
        # Runway
        state.weather.runway_capacity_pct = 50.0
        for i in range(6):
            state.flights[f"rwy-{i}"] = FlightState(
                flight_id=f"rwy-{i}", status="holding",
            )

        bns = detect_all(state, {})
        types = {b.type for b in bns}
        assert BottleneckType.SECURITY_QUEUE in types
        assert BottleneckType.RUNWAY_CAPACITY in types
