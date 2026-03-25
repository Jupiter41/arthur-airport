"""Unit tests for weather-service FSM — pure logic, no I/O."""

import random

import pytest

from tests.conftest import import_service_module

_fsm = import_service_module("weather", "services.fsm")
SEVERITY = _fsm.SEVERITY
TRANSITION_MATRIX = _fsm.TRANSITION_MATRIX
evaluate_transition = _fsm.evaluate_transition
is_valid_transition = _fsm.is_valid_transition


class TestTransitionMatrix:
    """Verify the transition matrix is well-formed."""

    def test_all_states_have_rows(self):
        for state in SEVERITY:
            assert state in TRANSITION_MATRIX

    def test_probabilities_sum_to_1(self):
        for state, row in TRANSITION_MATRIX.items():
            total = sum(row.values())
            assert abs(total - 1.0) < 0.001, f"{state} row sums to {total}"

    def test_no_direct_lifr_to_cavok(self):
        """LIFR→CAVOK probability must be 0 (>1 step jump)."""
        assert TRANSITION_MATRIX["LIFR"]["CAVOK"] == 0.0

    def test_no_direct_cavok_to_lifr(self):
        """CAVOK→LIFR probability must be 0 (>1 step jump)."""
        assert TRANSITION_MATRIX["CAVOK"]["LIFR"] == 0.0


class TestIsValidTransition:
    """Verify single-step transition validation."""

    def test_same_state_valid(self):
        for state in SEVERITY:
            assert is_valid_transition(state, state) is True

    def test_adjacent_states_valid(self):
        assert is_valid_transition("CAVOK", "VMC") is True
        assert is_valid_transition("VMC", "CAVOK") is True
        assert is_valid_transition("VMC", "IMC") is True
        assert is_valid_transition("IMC", "VMC") is True
        assert is_valid_transition("IMC", "LIFR") is True
        assert is_valid_transition("LIFR", "IMC") is True

    def test_two_step_jump_invalid(self):
        assert is_valid_transition("CAVOK", "IMC") is False
        assert is_valid_transition("IMC", "CAVOK") is False

    def test_three_step_jump_invalid(self):
        assert is_valid_transition("CAVOK", "LIFR") is False
        assert is_valid_transition("LIFR", "CAVOK") is False


class TestEvaluateTransition:
    """Verify FSM evaluation with seeded RNG."""

    def test_deterministic_with_seed(self):
        """Same seed produces same result."""
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        r1 = evaluate_transition("CAVOK", rng1)
        r2 = evaluate_transition("CAVOK", rng2)
        assert r1 == r2

    def test_stays_in_cavok_most_often(self):
        """CAVOK has 0.85 self-transition probability — should stay most of the time."""
        random.Random(100)
        results = [evaluate_transition("CAVOK", random.Random(i)) for i in range(1000)]
        cavok_count = results.count("CAVOK")
        # Should be roughly 850/1000 — allow generous tolerance
        assert cavok_count > 700, f"CAVOK stayed only {cavok_count}/1000 times"

    def test_never_jumps_more_than_one_step(self):
        """Over many evaluations, no >1-step jumps occur."""
        for state in SEVERITY:
            for seed in range(500):
                rng = random.Random(seed)
                result = evaluate_transition(state, rng)
                current_idx = SEVERITY.index(state)
                result_idx = SEVERITY.index(result)
                assert abs(result_idx - current_idx) <= 1, (
                    f"Jump from {state} to {result} at seed {seed}"
                )

    def test_invalid_state_raises(self):
        with pytest.raises(ValueError, match="Invalid weather category"):
            evaluate_transition("TORNADO")

    def test_all_valid_outcomes_reachable(self):
        """Each state can reach itself and adjacent states over enough iterations."""
        for state in SEVERITY:
            outcomes = set()
            for seed in range(2000):
                outcomes.add(evaluate_transition(state, random.Random(seed)))
            current_idx = SEVERITY.index(state)
            # Must reach self
            assert state in outcomes
            # Must reach adjacent (if exists)
            if current_idx > 0:
                assert SEVERITY[current_idx - 1] in outcomes
            if current_idx < len(SEVERITY) - 1:
                assert SEVERITY[current_idx + 1] in outcomes

    def test_lifr_never_reaches_cavok(self):
        """LIFR can only go to IMC or stay — never to CAVOK."""
        for seed in range(2000):
            result = evaluate_transition("LIFR", random.Random(seed))
            assert result in ("LIFR", "IMC"), f"LIFR reached {result} at seed {seed}"

    def test_cavok_never_reaches_lifr(self):
        """CAVOK can only go to VMC or stay — never to LIFR."""
        for seed in range(2000):
            result = evaluate_transition("CAVOK", random.Random(seed))
            assert result in ("CAVOK", "VMC"), f"CAVOK reached {result} at seed {seed}"
