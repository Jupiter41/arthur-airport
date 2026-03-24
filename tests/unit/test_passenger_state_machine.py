"""Unit tests for passenger-service state machine — pure logic, no I/O."""

from datetime import datetime, timedelta

import pytest

from tests.conftest import import_service_module

_sm = import_service_module("passenger", "services.state_machine")
DEPARTURE_STATES = _sm.DEPARTURE_STATES
ARRIVAL_STATES = _sm.ARRIVAL_STATES
CHECKIN_CUTOFF_MINUTES = _sm.CHECKIN_CUTOFF_MINUTES
GATE_OPEN_MINUTES = _sm.GATE_OPEN_MINUTES
BOARDING_CALL_MINUTES = _sm.BOARDING_CALL_MINUTES
BOARDING_RATE_PAX_PER_MIN = _sm.BOARDING_RATE_PAX_PER_MIN
DEPLANING_DELAY_MINUTES = _sm.DEPLANING_DELAY_MINUTES
BAGGAGE_CLAIM_TIMEOUT_MINUTES = _sm.BAGGAGE_CLAIM_TIMEOUT_MINUTES
sample_dwell_minutes = _sm.sample_dwell_minutes
should_move_to_security_queue = _sm.should_move_to_security_queue
should_move_to_at_gate = _sm.should_move_to_at_gate
compute_boarding_batch_size = _sm.compute_boarding_batch_size
should_start_boarding = _sm.should_start_boarding
should_move_to_baggage_claim = _sm.should_move_to_baggage_claim
should_depart_airport = _sm.should_depart_airport
get_terminal_from_gate = _sm.get_terminal_from_gate
get_terminal_for_flight = _sm.get_terminal_for_flight
zone_for_status = _sm.zone_for_status


BASE_TIME = datetime(2025, 6, 15, 10, 0, 0)


# ── Constants ────────────────────────────────────────────────────

class TestConstants:
    def test_departure_states_order(self):
        assert DEPARTURE_STATES == ["checked_in", "security_queue", "airside", "at_gate", "boarded"]

    def test_arrival_states_order(self):
        assert ARRIVAL_STATES == ["airborne", "deplaning", "baggage_claim", "departed_airport"]

    def test_cutoff_is_45(self):
        assert CHECKIN_CUTOFF_MINUTES == 45

    def test_gate_open_is_30(self):
        assert GATE_OPEN_MINUTES == 30

    def test_boarding_rate(self):
        assert BOARDING_RATE_PAX_PER_MIN == 10


# ── Security queue trigger ───────────────────────────────────────

class TestShouldMoveToSecurityQueue:
    def test_moves_at_cutoff(self):
        scheduled = BASE_TIME
        sim_time = BASE_TIME - timedelta(minutes=CHECKIN_CUTOFF_MINUTES)
        assert should_move_to_security_queue(sim_time, scheduled) is True

    def test_moves_after_cutoff(self):
        scheduled = BASE_TIME
        sim_time = BASE_TIME - timedelta(minutes=30)
        assert should_move_to_security_queue(sim_time, scheduled) is True

    def test_stays_before_cutoff(self):
        scheduled = BASE_TIME
        sim_time = BASE_TIME - timedelta(minutes=50)
        assert should_move_to_security_queue(sim_time, scheduled) is False

    def test_accepts_string_scheduled_time(self):
        sim_time = BASE_TIME - timedelta(minutes=40)
        assert should_move_to_security_queue(sim_time, BASE_TIME.isoformat()) is True


# ── Gate movement ────────────────────────────────────────────────

class TestShouldMoveToAtGate:
    def test_moves_when_gate_open_and_dwell_elapsed(self):
        estimated = BASE_TIME
        sim_time = BASE_TIME - timedelta(minutes=10)
        airside_at = BASE_TIME - timedelta(minutes=45)
        assert should_move_to_at_gate(sim_time, estimated, 30, airside_at) is True

    def test_stays_before_gate_open(self):
        estimated = BASE_TIME
        sim_time = BASE_TIME - timedelta(minutes=35)
        airside_at = BASE_TIME - timedelta(minutes=45)
        assert should_move_to_at_gate(sim_time, estimated, 5, airside_at) is False

    def test_stays_if_dwell_not_elapsed(self):
        estimated = BASE_TIME
        sim_time = BASE_TIME - timedelta(minutes=25)
        airside_at = BASE_TIME - timedelta(minutes=30)
        assert should_move_to_at_gate(sim_time, estimated, 60, airside_at) is False

    def test_moves_immediately_no_dwell_info(self):
        estimated = BASE_TIME
        sim_time = BASE_TIME - timedelta(minutes=20)
        assert should_move_to_at_gate(sim_time, estimated, None, None) is True


# ── Boarding ─────────────────────────────────────────────────────

class TestBoarding:
    def test_batch_size_1_minute(self):
        assert compute_boarding_batch_size(1) == BOARDING_RATE_PAX_PER_MIN

    def test_batch_size_5_minutes(self):
        assert compute_boarding_batch_size(5) == BOARDING_RATE_PAX_PER_MIN * 5

    def test_should_start_boarding_at_t_minus_20(self):
        sim_time = BASE_TIME - timedelta(minutes=BOARDING_CALL_MINUTES)
        assert should_start_boarding(sim_time, BASE_TIME, "boarding") is True

    def test_should_not_start_boarding_early(self):
        sim_time = BASE_TIME - timedelta(minutes=BOARDING_CALL_MINUTES + 5)
        assert should_start_boarding(sim_time, BASE_TIME, "boarding") is False

    def test_should_not_board_if_departed(self):
        sim_time = BASE_TIME - timedelta(minutes=10)
        assert should_start_boarding(sim_time, BASE_TIME, "departed") is False


# ── Arrival flow ─────────────────────────────────────────────────

class TestArrivalFlow:
    def test_move_to_baggage_claim_after_delay(self):
        deplaning_at = BASE_TIME
        sim_time = BASE_TIME + timedelta(minutes=DEPLANING_DELAY_MINUTES + 1)
        assert should_move_to_baggage_claim(sim_time, deplaning_at) is True

    def test_stays_deplaning_before_delay(self):
        deplaning_at = BASE_TIME
        sim_time = BASE_TIME + timedelta(minutes=DEPLANING_DELAY_MINUTES - 1)
        assert should_move_to_baggage_claim(sim_time, deplaning_at) is False

    def test_no_deplaning_time_stays(self):
        assert should_move_to_baggage_claim(BASE_TIME, None) is False

    def test_depart_when_baggage_collected(self):
        assert should_depart_airport(BASE_TIME, None, baggage_collected=True) is True

    def test_depart_on_timeout(self):
        bc_at = BASE_TIME
        sim_time = BASE_TIME + timedelta(minutes=BAGGAGE_CLAIM_TIMEOUT_MINUTES + 1)
        assert should_depart_airport(sim_time, bc_at) is True

    def test_stays_before_timeout(self):
        bc_at = BASE_TIME
        sim_time = BASE_TIME + timedelta(minutes=BAGGAGE_CLAIM_TIMEOUT_MINUTES - 1)
        assert should_depart_airport(sim_time, bc_at) is False


# ── Terminal helpers ─────────────────────────────────────────────

class TestTerminalHelpers:
    def test_gate_a01(self):
        assert get_terminal_from_gate("A01", None) == "A"

    def test_gate_b12(self):
        assert get_terminal_from_gate("B12", None) == "B"

    def test_gate_c05(self):
        assert get_terminal_from_gate("C05", None) == "C"

    def test_fallback_to_terminal_id(self):
        assert get_terminal_from_gate(None, "T-B") == "B"

    def test_default_fallback(self):
        assert get_terminal_from_gate(None, None) == "A"

    def test_get_terminal_for_flight_hash_distribution(self):
        """Without gate, uses hash-based distribution."""
        terminals = set()
        for i in range(30):
            t = get_terminal_for_flight(None, None, f"flight-{i}")
            terminals.add(t)
        # Should distribute across all 3 terminals
        assert len(terminals) == 3


# ── Zone mapping ─────────────────────────────────────────────────

class TestZoneForStatus:
    def test_checked_in(self):
        assert zone_for_status("checked_in", "A") == "check-in-A"

    def test_security_queue(self):
        assert zone_for_status("security_queue", "B") == "security-B"

    def test_airside(self):
        assert zone_for_status("airside", "C") == "airside-C"

    def test_at_gate_with_gate(self):
        assert zone_for_status("at_gate", "A", gate_id="A05") == "gate-A05"

    def test_at_gate_without_gate(self):
        assert zone_for_status("at_gate", "A") == "airside-A"

    def test_baggage_claim(self):
        assert zone_for_status("baggage_claim", "A") == "baggage-claim"

    def test_departed_airport(self):
        assert zone_for_status("departed_airport", "A") == "arrivals-hall"


# ── Dwell sampling ───────────────────────────────────────────────

class TestDwellSampling:
    def test_dwell_in_range(self):
        for _ in range(100):
            d = sample_dwell_minutes()
            assert 5 <= d <= 90

    def test_dwell_is_integer(self):
        assert isinstance(sample_dwell_minutes(), int)
