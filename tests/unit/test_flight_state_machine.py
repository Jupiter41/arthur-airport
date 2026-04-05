"""Unit tests for flight-service state machine — pure logic, no I/O."""

from datetime import datetime, timedelta


from tests.conftest import import_service_module

_sm = import_service_module("flight", "services.state_machine")
VALID_TRANSITIONS = _sm.VALID_TRANSITIONS
TERMINAL_STATES = _sm.TERMINAL_STATES
PRE_DEPARTURE_STATES = _sm.PRE_DEPARTURE_STATES
can_transition = _sm.can_transition
evaluate_transition = _sm.evaluate_transition


# ── Fixtures ─────────────────────────────────────────────────────

BASE_TIME = datetime(2025, 6, 15, 10, 0, 0)


def _flight(
    status: str = "scheduled",
    direction: str = "departure",
    estimated_time: datetime | None = None,
    actual_time: datetime | None = None,
    delay_minutes: int = 0,
    gate_id: str | None = "A01",
    aircraft_type: str = "A320",
) -> dict:
    return {
        "status": status,
        "direction": direction,
        "estimated_time": (estimated_time or BASE_TIME).isoformat(),
        "actual_time": actual_time.isoformat() if actual_time else None,
        "delay_minutes": delay_minutes,
        "gate_id": gate_id,
        "aircraft_type": aircraft_type,
    }


# ── can_transition ───────────────────────────────────────────────

class TestCanTransition:
    """Verify the VALID_TRANSITIONS map is enforced."""

    def test_scheduled_to_boarding(self):
        assert can_transition("scheduled", "boarding") is True

    def test_scheduled_to_delayed(self):
        assert can_transition("scheduled", "delayed") is True

    def test_scheduled_to_cancelled(self):
        assert can_transition("scheduled", "cancelled") is True

    def test_scheduled_to_airborne_invalid(self):
        assert can_transition("scheduled", "airborne") is False

    def test_scheduled_to_landed_invalid(self):
        assert can_transition("scheduled", "landed") is False

    def test_boarding_to_departed(self):
        assert can_transition("boarding", "departed") is True

    def test_boarding_to_delayed(self):
        assert can_transition("boarding", "delayed") is True

    def test_boarding_to_cancelled(self):
        assert can_transition("boarding", "cancelled") is True

    def test_boarding_to_airborne_invalid(self):
        assert can_transition("boarding", "airborne") is False

    def test_departed_to_airborne(self):
        assert can_transition("departed", "airborne") is True

    def test_departed_to_landed_invalid(self):
        assert can_transition("departed", "landed") is False

    def test_airborne_to_approach(self):
        assert can_transition("airborne", "approach") is True

    def test_airborne_to_landed_invalid(self):
        assert can_transition("airborne", "landed") is False

    def test_approach_to_landed(self):
        assert can_transition("approach", "landed") is True

    def test_approach_to_delayed(self):
        assert can_transition("approach", "delayed") is True

    def test_landed_to_taxiing(self):
        assert can_transition("landed", "taxiing") is True

    def test_taxiing_to_at_gate(self):
        assert can_transition("taxiing", "at_gate") is True

    def test_terminal_states_have_no_outgoing(self):
        for state in TERMINAL_STATES:
            assert VALID_TRANSITIONS[state] == set()

    def test_at_gate_is_terminal(self):
        assert can_transition("at_gate", "boarding") is False
        assert can_transition("at_gate", "scheduled") is False

    def test_cancelled_is_terminal(self):
        assert can_transition("cancelled", "scheduled") is False
        assert can_transition("cancelled", "boarding") is False

    def test_unknown_state_returns_false(self):
        assert can_transition("nonexistent", "boarding") is False

    def test_all_states_have_entries(self):
        expected_states = {
            "scheduled", "boarding", "delayed", "departed",
            "airborne", "approach", "landed", "taxiing",
            "at_gate", "arrived", "cancelled", "diverted",
        }
        assert set(VALID_TRANSITIONS.keys()) == expected_states


# ── evaluate_transition — departure flow ─────────────────────────

class TestEvaluateTransitionDeparture:
    """Departure flow: scheduled → boarding → departed → airborne."""

    def test_scheduled_to_boarding_at_t_minus_60(self):
        sim_time = BASE_TIME - timedelta(minutes=60)
        flight = _flight(status="scheduled", direction="departure")
        result = evaluate_transition(flight, sim_time)
        assert result == "boarding"

    def test_scheduled_stays_before_t_minus_60(self):
        sim_time = BASE_TIME - timedelta(minutes=61)
        flight = _flight(status="scheduled", direction="departure")
        result = evaluate_transition(flight, sim_time)
        assert result is None

    def test_scheduled_to_boarding_at_t_minus_30(self):
        sim_time = BASE_TIME - timedelta(minutes=30)
        flight = _flight(status="scheduled", direction="departure")
        result = evaluate_transition(flight, sim_time)
        assert result == "boarding"

    def test_boarding_to_departed_at_eta_with_full_boarding(self):
        flight = _flight(status="boarding", direction="departure")
        result = evaluate_transition(flight, BASE_TIME, boarded_pct=0.96)
        assert result == "departed"

    def test_boarding_stays_if_low_boarding_pct(self):
        flight = _flight(status="boarding", direction="departure")
        result = evaluate_transition(flight, BASE_TIME, boarded_pct=0.80)
        assert result is None

    def test_boarding_to_delayed_with_hold(self):
        flight = _flight(status="boarding", direction="departure")
        result = evaluate_transition(flight, BASE_TIME, has_hold=True)
        assert result == "delayed"

    def test_boarding_auto_cancel_at_180_delay(self):
        flight = _flight(status="boarding", direction="departure", delay_minutes=180)
        result = evaluate_transition(flight, BASE_TIME)
        assert result == "cancelled"

    def test_departed_to_airborne_after_5_min(self):
        flight = _flight(status="departed", direction="departure")
        sim_time = BASE_TIME + timedelta(minutes=6)
        result = evaluate_transition(flight, sim_time)
        assert result == "airborne"

    def test_departed_stays_before_5_min(self):
        flight = _flight(status="departed", direction="departure")
        sim_time = BASE_TIME + timedelta(minutes=3)
        result = evaluate_transition(flight, sim_time)
        assert result is None


# ── evaluate_transition — arrival flow ───────────────────────────

class TestEvaluateTransitionArrival:
    """Arrival flow: scheduled → approach → landed → taxiing → at_gate."""

    def test_scheduled_to_approach_at_t_minus_20(self):
        sim_time = BASE_TIME - timedelta(minutes=20)
        flight = _flight(status="scheduled", direction="arrival")
        result = evaluate_transition(flight, sim_time)
        assert result == "approach"

    def test_scheduled_stays_before_t_minus_20(self):
        sim_time = BASE_TIME - timedelta(minutes=25)
        flight = _flight(status="scheduled", direction="arrival")
        result = evaluate_transition(flight, sim_time)
        assert result is None

    def test_approach_to_landed_at_eta_runway_available(self):
        flight = _flight(status="approach", direction="arrival")
        result = evaluate_transition(flight, BASE_TIME, runway_available=True)
        assert result == "landed"

    def test_approach_to_delayed_no_runway(self):
        flight = _flight(status="approach", direction="arrival")
        result = evaluate_transition(flight, BASE_TIME, runway_available=False)
        assert result == "delayed"

    def test_approach_stays_before_eta(self):
        flight = _flight(status="approach", direction="arrival")
        sim_time = BASE_TIME - timedelta(minutes=1)
        result = evaluate_transition(flight, sim_time)
        assert result is None

    def test_landed_to_taxiing_after_2_min(self):
        actual = BASE_TIME
        flight = _flight(status="landed", direction="arrival", actual_time=actual)
        sim_time = BASE_TIME + timedelta(minutes=3)
        result = evaluate_transition(flight, sim_time)
        assert result == "taxiing"

    def test_landed_stays_before_2_min(self):
        actual = BASE_TIME
        flight = _flight(status="landed", direction="arrival", actual_time=actual)
        sim_time = BASE_TIME + timedelta(minutes=1)
        result = evaluate_transition(flight, sim_time)
        assert result is None

    def test_taxiing_to_at_gate_after_8_min(self):
        actual = BASE_TIME
        flight = _flight(status="taxiing", direction="arrival", actual_time=actual)
        sim_time = BASE_TIME + timedelta(minutes=9)
        result = evaluate_transition(flight, sim_time, gate_available=True)
        assert result == "at_gate"

    def test_taxiing_stays_no_gate(self):
        actual = BASE_TIME
        flight = _flight(status="taxiing", direction="arrival", actual_time=actual)
        sim_time = BASE_TIME + timedelta(minutes=9)
        result = evaluate_transition(flight, sim_time, gate_available=False)
        assert result is None


# ── evaluate_transition — delayed state ──────────────────────────

class TestEvaluateTransitionDelayed:
    """Delayed state behavior."""

    def test_delayed_auto_cancel_at_180(self):
        flight = _flight(status="delayed", direction="departure", delay_minutes=180)
        result = evaluate_transition(flight, BASE_TIME)
        assert result == "cancelled"

    def test_delayed_departure_returns_to_boarding(self):
        flight = _flight(status="delayed", direction="departure", delay_minutes=30)
        result = evaluate_transition(flight, BASE_TIME, has_hold=False)
        assert result == "boarding"

    def test_delayed_arrival_returns_to_approach(self):
        flight = _flight(status="delayed", direction="arrival", delay_minutes=30)
        result = evaluate_transition(flight, BASE_TIME, has_hold=False, runway_available=True)
        assert result == "approach"

    def test_delayed_stays_with_hold(self):
        flight = _flight(status="delayed", direction="departure", delay_minutes=30)
        result = evaluate_transition(flight, BASE_TIME, has_hold=True)
        assert result is None


# ── Terminal states ──────────────────────────────────────────────

class TestTerminalStates:
    """Terminal states produce no transitions."""

    def test_at_gate_returns_none(self):
        flight = _flight(status="at_gate", direction="arrival")
        result = evaluate_transition(flight, BASE_TIME)
        assert result is None

    def test_cancelled_returns_none(self):
        flight = _flight(status="cancelled", direction="departure")
        result = evaluate_transition(flight, BASE_TIME)
        assert result is None


# ── Edge cases ───────────────────────────────────────────────────

class TestEdgeCases:
    """Boundary conditions and malformed input handling."""

    def test_missing_estimated_time_returns_none(self):
        flight = _flight(status="scheduled")
        flight["estimated_time"] = None
        result = evaluate_transition(flight, BASE_TIME)
        assert result is None

    def test_invalid_estimated_time_returns_none(self):
        flight = _flight(status="scheduled")
        flight["estimated_time"] = "not-a-date"
        result = evaluate_transition(flight, BASE_TIME)
        assert result is None

    def test_missing_actual_time_landed_returns_none(self):
        flight = _flight(status="landed", direction="arrival")
        flight["actual_time"] = None
        result = evaluate_transition(flight, BASE_TIME + timedelta(minutes=5))
        assert result is None

    def test_boarded_pct_exactly_095(self):
        flight = _flight(status="boarding", direction="departure")
        result = evaluate_transition(flight, BASE_TIME, boarded_pct=0.95)
        assert result == "departed"

    def test_boarded_pct_slightly_below_095(self):
        flight = _flight(status="boarding", direction="departure")
        result = evaluate_transition(flight, BASE_TIME, boarded_pct=0.949)
        assert result is None

    def test_delay_179_stays_delayed(self):
        flight = _flight(status="delayed", direction="departure", delay_minutes=179)
        result = evaluate_transition(flight, BASE_TIME, has_hold=True)
        assert result is None

    def test_delay_exactly_180_cancels(self):
        flight = _flight(status="delayed", direction="departure", delay_minutes=180)
        result = evaluate_transition(flight, BASE_TIME)
        assert result == "cancelled"

    def test_airborne_departure_stays_airborne(self):
        """Departures in airborne state are terminal — they don't approach."""
        flight = _flight(status="airborne", direction="departure")
        sim_time = BASE_TIME + timedelta(hours=5)
        result = evaluate_transition(flight, sim_time)
        assert result is None

    def test_no_gate_departure_still_boards(self):
        """Departures without a gate assignment can still transition to boarding."""
        flight = _flight(status="scheduled", direction="departure", gate_id=None)
        sim_time = BASE_TIME - timedelta(minutes=50)
        result = evaluate_transition(flight, sim_time)
        assert result == "boarding"

    def test_pre_departure_states_constant(self):
        assert PRE_DEPARTURE_STATES == {"scheduled", "boarding", "delayed"}
