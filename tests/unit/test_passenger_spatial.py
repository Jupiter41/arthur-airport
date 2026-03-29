"""Unit tests for passenger-service spatial utilities — walking times."""

from tests.conftest import import_service_module

_sp = import_service_module("passenger", "services.spatial")
euclidean_distance = _sp.euclidean_distance
walking_time_minutes = _sp.walking_time_minutes
walking_time_to_gate = _sp.walking_time_to_gate
walking_time_between_gates = _sp.walking_time_between_gates
WALKING_SPEED = _sp.WALKING_SPEED
SPECIAL_ASSIST_MULT = _sp.SPECIAL_ASSIST_MULT


WALKING_ZONES = {
    "A": {"checkin": {"x": 500, "y": 50}, "security": {"x": 500, "y": 100}, "airside": {"x": 500, "y": 130}},
    "B": {"checkin": {"x": 500, "y": 300}, "security": {"x": 500, "y": 350}, "airside": {"x": 500, "y": 380}},
    "C": {"checkin": {"x": 500, "y": 550}, "security": {"x": 500, "y": 600}, "airside": {"x": 500, "y": 630}},
}


class TestEuclideanDistance:
    def test_zero_distance(self):
        assert euclidean_distance(0, 0, 0, 0) == 0.0

    def test_horizontal(self):
        assert euclidean_distance(0, 0, 100, 0) == 100.0

    def test_vertical(self):
        assert euclidean_distance(0, 0, 0, 200) == 200.0


class TestWalkingTimeMinutes:
    def test_zero_distance(self):
        assert walking_time_minutes(0, 0, 0, 0) == 0.0

    def test_known_distance(self):
        # 84m should take 1 minute at 84 m/min
        t = walking_time_minutes(0, 0, 84, 0)
        assert abs(t - 1.0) < 0.01

    def test_special_assistance_slower(self):
        normal = walking_time_minutes(0, 0, 100, 0, special_assistance=False)
        sa = walking_time_minutes(0, 0, 100, 0, special_assistance=True)
        assert abs(sa / normal - SPECIAL_ASSIST_MULT) < 0.01


class TestWalkingTimeToGate:
    def test_same_terminal_near_gate(self):
        """Gate A01 at (160, 150), airside A at (500, 130) → short walk."""
        gate_pos = {"position_x": 160, "position_y": 150}
        t = walking_time_to_gate("A", gate_pos, WALKING_ZONES)
        assert t > 0
        assert t < 10  # should be a few minutes

    def test_same_terminal_far_gate(self):
        """Gate A14 at (940, 150), airside A at (500, 130) → longer walk."""
        gate_pos_near = {"position_x": 160, "position_y": 150}
        gate_pos_far = {"position_x": 940, "position_y": 150}
        t_near = walking_time_to_gate("A", gate_pos_near, WALKING_ZONES)
        t_far = walking_time_to_gate("A", gate_pos_far, WALKING_ZONES)
        assert t_far > t_near

    def test_cross_terminal_longer(self):
        """Walking from terminal A airside to a gate in terminal C should be longer."""
        gate_a = {"position_x": 500, "position_y": 150}
        gate_c = {"position_x": 500, "position_y": 650}
        t_same = walking_time_to_gate("A", gate_a, WALKING_ZONES)
        t_cross = walking_time_to_gate("A", gate_c, WALKING_ZONES)
        assert t_cross > t_same

    def test_special_assistance(self):
        gate_pos = {"position_x": 500, "position_y": 400}
        normal = walking_time_to_gate("B", gate_pos, WALKING_ZONES, special_assistance=False)
        sa = walking_time_to_gate("B", gate_pos, WALKING_ZONES, special_assistance=True)
        assert sa > normal

    def test_default_when_no_gate(self):
        t = walking_time_to_gate("A", None, WALKING_ZONES)
        assert t == 5.0

    def test_default_when_no_zones(self):
        gate_pos = {"position_x": 500, "position_y": 400}
        t = walking_time_to_gate("A", gate_pos, None)
        assert t == 5.0


class TestWalkingTimeBetweenGates:
    def test_same_gate(self):
        pos = {"position_x": 500, "position_y": 400}
        t = walking_time_between_gates(pos, pos)
        assert t == 0.0

    def test_adjacent_terminals(self):
        """Gate A07 to B07 — same x, different y."""
        a_pos = {"position_x": 520, "position_y": 150}
        b_pos = {"position_x": 520, "position_y": 400}
        t = walking_time_between_gates(a_pos, b_pos)
        assert t > 0
        assert t < 10  # ~250m / 84 m/min ≈ 3 min

    def test_far_terminals_longer(self):
        """A gate to C gate should take longer than A to B."""
        a_pos = {"position_x": 520, "position_y": 150}
        b_pos = {"position_x": 520, "position_y": 400}
        c_pos = {"position_x": 520, "position_y": 650}
        t_ab = walking_time_between_gates(a_pos, b_pos)
        t_ac = walking_time_between_gates(a_pos, c_pos)
        assert t_ac > t_ab

    def test_default_when_missing(self):
        t = walking_time_between_gates(None, {"position_x": 500, "position_y": 400})
        assert t == 10.0

    def test_special_assistance(self):
        a_pos = {"position_x": 500, "position_y": 150}
        c_pos = {"position_x": 500, "position_y": 650}
        normal = walking_time_between_gates(a_pos, c_pos, special_assistance=False)
        sa = walking_time_between_gates(a_pos, c_pos, special_assistance=True)
        assert abs(sa / normal - SPECIAL_ASSIST_MULT) < 0.01
