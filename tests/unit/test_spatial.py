"""Unit tests for spatial utility — taxi times and walking times.

Covers: same-terminal, adjacent-terminal, and far-terminal cases.
"""

import pytest
from tests.conftest import import_service_module

_sp = import_service_module("flight", "services.spatial")
euclidean_distance = _sp.euclidean_distance
taxi_time_minutes = _sp.taxi_time_minutes
taxi_time_from_positions = _sp.taxi_time_from_positions
walking_time_minutes = _sp.walking_time_minutes
walking_time_to_gate = _sp.walking_time_to_gate
TAXIWAY_SPEED = _sp.TAXIWAY_SPEED
APRON_SPEED = _sp.APRON_SPEED
APRON_RADIUS = _sp.APRON_RADIUS
WALKING_SPEED = _sp.WALKING_SPEED
SPECIAL_ASSIST_MULT = _sp.SPECIAL_ASSIST_MULT
DEFAULT_TAXI_INITIAL_MIN = _sp.DEFAULT_TAXI_INITIAL_MIN
DEFAULT_TAXI_TOTAL_MIN = _sp.DEFAULT_TAXI_TOTAL_MIN


class TestEuclideanDistance:
    def test_same_point(self):
        assert euclidean_distance(100, 200, 100, 200) == 0.0

    def test_horizontal(self):
        assert euclidean_distance(0, 0, 300, 0) == pytest.approx(300.0)

    def test_vertical(self):
        assert euclidean_distance(0, 0, 0, 400) == pytest.approx(400.0)

    def test_diagonal(self):
        assert euclidean_distance(0, 0, 300, 400) == pytest.approx(500.0)


class TestTaxiTimeMinutes:
    def test_zero_distance(self):
        """Taxi time should be zero when runway is at the gate."""
        assert taxi_time_minutes(500, 500, 500, 500) == pytest.approx(0.0)

    def test_short_distance_apron_only(self):
        """Under apron radius, only apron speed applies."""
        # 100m distance, all within apron radius of 200m
        t = taxi_time_minutes(500, 800, 500, 700)  # 100m vertical
        expected = 100.0 / APRON_SPEED
        assert t == pytest.approx(expected, rel=0.01)

    def test_terminal_a_gate_a01(self):
        """Terminal A gate A01: runway 09L threshold at (100, 800), gate at (160, 150)."""
        t = taxi_time_minutes(100, 800, 160, 150)
        # Distance: sqrt(60^2 + 650^2) ≈ 652.8m
        dist = euclidean_distance(100, 800, 160, 150)
        assert dist > APRON_RADIUS  # should have both taxiway and apron segments
        assert t > 2.0  # should take a few minutes

    def test_terminal_c_gate_c14(self):
        """Terminal C gate C14 is the farthest gate from runway 09L."""
        t_near = taxi_time_minutes(100, 800, 160, 150)  # A01 (near)
        t_far = taxi_time_minutes(100, 800, 940, 650)   # C14 (far)
        assert t_far > t_near  # far gate should take longer

    def test_same_terminal_faster_than_cross_terminal(self):
        """Terminal A (y=150) is farthest from runway 09L (y=800). B is middle, C is closest."""
        # B07 from runway 09L
        t_b07 = taxi_time_minutes(100, 800, 520, 400)
        # A01 from runway 09L (farthest terminal from runway)
        t_a01 = taxi_time_minutes(100, 800, 160, 150)
        # C01 from runway 09L (closest terminal to runway)
        t_c01 = taxi_time_minutes(100, 800, 160, 650)
        assert t_c01 < t_b07 < t_a01  # C closest, A farthest


class TestTaxiTimeFromPositions:
    def test_none_runway(self):
        """When runway position is None, fallback to defaults."""
        initial, total = taxi_time_from_positions(None, {"position_x": 500, "position_y": 150})
        assert initial == DEFAULT_TAXI_INITIAL_MIN
        assert total == DEFAULT_TAXI_TOTAL_MIN

    def test_none_gate(self):
        """When gate position is None, fallback to defaults."""
        initial, total = taxi_time_from_positions({"threshold_x": 100, "threshold_y": 800}, None)
        assert initial == DEFAULT_TAXI_INITIAL_MIN
        assert total == DEFAULT_TAXI_TOTAL_MIN

    def test_both_none(self):
        """When both are None, fallback to defaults."""
        initial, total = taxi_time_from_positions(None, None)
        assert initial == DEFAULT_TAXI_INITIAL_MIN
        assert total == DEFAULT_TAXI_TOTAL_MIN

    def test_valid_positions(self):
        """With valid positions, computes spatial taxi time."""
        runway_pos = {"threshold_x": 100, "threshold_y": 800}
        gate_pos = {"position_x": 520, "position_y": 400}
        initial, total = taxi_time_from_positions(runway_pos, gate_pos)
        assert initial == 2.0  # fixed initial phase
        assert total > initial  # total includes taxi time
        assert total > 3.0  # should be more than just initial


class TestWalkingTimeMinutes:
    def test_zero_distance(self):
        assert walking_time_minutes(100, 200, 100, 200) == 0.0

    def test_known_distance(self):
        """100m should take ~1.19 min at 84 m/min."""
        t = walking_time_minutes(0, 0, 100, 0)
        assert t == pytest.approx(100.0 / WALKING_SPEED, rel=0.01)

    def test_special_assistance(self):
        """Special assistance should multiply by 2.5."""
        normal = walking_time_minutes(0, 0, 100, 0, special_assistance=False)
        assisted = walking_time_minutes(0, 0, 100, 0, special_assistance=True)
        assert assisted == pytest.approx(normal * SPECIAL_ASSIST_MULT, rel=0.01)


class TestWalkingTimeToGate:
    WALKING_ZONES = {
        "A": {
            "checkin": {"x": 500, "y": 50},
            "security": {"x": 500, "y": 100},
            "airside": {"x": 500, "y": 130},
        },
        "B": {
            "checkin": {"x": 500, "y": 300},
            "security": {"x": 500, "y": 350},
            "airside": {"x": 500, "y": 380},
        },
        "C": {
            "checkin": {"x": 500, "y": 550},
            "security": {"x": 500, "y": 600},
            "airside": {"x": 500, "y": 630},
        },
    }

    def test_same_terminal_near_gate(self):
        """Walking from airside A to gate A07 (same terminal, nearby)."""
        gate = {"position_x": 520, "position_y": 150}
        t = walking_time_to_gate("A", gate, self.WALKING_ZONES)
        assert 0 < t < 3  # should be a short walk

    def test_same_terminal_far_gate(self):
        """Walking from airside A to gate A14 (same terminal, far end)."""
        gate_near = {"position_x": 160, "position_y": 150}
        gate_far = {"position_x": 940, "position_y": 150}
        t_near = walking_time_to_gate("A", gate_near, self.WALKING_ZONES)
        t_far = walking_time_to_gate("A", gate_far, self.WALKING_ZONES)
        assert t_far > t_near

    def test_cross_terminal(self):
        """Walking from airside A to gate C01 (cross-terminal, longest walk)."""
        gate_a = {"position_x": 520, "position_y": 150}
        gate_c = {"position_x": 160, "position_y": 650}
        t_same = walking_time_to_gate("A", gate_a, self.WALKING_ZONES)
        t_cross = walking_time_to_gate("A", gate_c, self.WALKING_ZONES)
        assert t_cross > t_same * 2  # cross-terminal much longer

    def test_none_gate(self):
        """Fallback to 5 min when gate position is None."""
        assert walking_time_to_gate("A", None, self.WALKING_ZONES) == 5.0

    def test_none_zones(self):
        """Fallback to 5 min when walking zones not available."""
        assert walking_time_to_gate("A", {"x": 500, "y": 150}, None) == 5.0
