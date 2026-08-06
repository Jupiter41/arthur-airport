"""Unit tests for the flight-service pure application layer.

These cover the transition-decision functions extracted from the Kafka
consumer (the adapter). They run with no Neo4j/Kafka/state — plain values in,
decisions out — which is the whole point of the hexagonal seam.
"""

from datetime import datetime, timedelta

from tests.conftest import import_service_module

_dec = import_service_module("flight", "application.decisions")

suppress_transition_for_turnaround = _dec.suppress_transition_for_turnaround
resolve_delay_reason = _dec.resolve_delay_reason
boarding_delay_update = _dec.boarding_delay_update
NOISE_DELAY_REASONS = _dec.NOISE_DELAY_REASONS

BASE = datetime(2026, 8, 6, 12, 0, 0)


# ── suppress_transition_for_turnaround ───────────────────────────

class TestSuppressForTurnaround:
    def test_arrival_arrived_blocked_until_deplaning_done(self):
        assert suppress_transition_for_turnaround(
            "arrived", "arrival", deplaning_done=False, ready_for_boarding=True
        ) is True

    def test_arrival_arrived_allowed_when_deplaning_done(self):
        assert suppress_transition_for_turnaround(
            "arrived", "arrival", deplaning_done=True, ready_for_boarding=False
        ) is False

    def test_departure_boarding_blocked_until_ready(self):
        assert suppress_transition_for_turnaround(
            "boarding", "departure", deplaning_done=True, ready_for_boarding=False
        ) is True

    def test_departure_boarding_allowed_when_ready(self):
        assert suppress_transition_for_turnaround(
            "boarding", "departure", deplaning_done=False, ready_for_boarding=True
        ) is False

    def test_unrelated_transition_never_suppressed(self):
        # departed/landed/etc. are not turnaround-gated
        assert suppress_transition_for_turnaround(
            "departed", "departure", deplaning_done=False, ready_for_boarding=False
        ) is False

    def test_none_status_not_suppressed(self):
        assert suppress_transition_for_turnaround(
            None, "arrival", deplaning_done=False, ready_for_boarding=False
        ) is False

    def test_direction_must_match_status(self):
        # arrived only gated for arrivals; boarding only for departures
        assert suppress_transition_for_turnaround(
            "arrived", "departure", deplaning_done=False, ready_for_boarding=False
        ) is False
        assert suppress_transition_for_turnaround(
            "boarding", "arrival", deplaning_done=False, ready_for_boarding=False
        ) is False


# ── resolve_delay_reason ─────────────────────────────────────────

class TestResolveDelayReason:
    def test_hold_wins_over_everything(self):
        assert resolve_delay_reason(
            "operational", is_held=True, hold_reason="weather_hold",
            runway_incident=True, gate_incident=True,
        ) == "weather_hold"

    def test_hold_without_reason_defaults_manual_hold(self):
        assert resolve_delay_reason(
            "", is_held=True, hold_reason=None,
            runway_incident=False, gate_incident=False,
        ) == "manual_hold"

    def test_runway_incident_over_gate(self):
        assert resolve_delay_reason(
            "", is_held=False, hold_reason=None,
            runway_incident=True, gate_incident=True,
        ) == "runway_incident"

    def test_gate_incident(self):
        assert resolve_delay_reason(
            "", is_held=False, hold_reason=None,
            runway_incident=False, gate_incident=True,
        ) == "gate_incident"

    def test_existing_reason_preserved(self):
        assert resolve_delay_reason(
            "crew_readiness", is_held=False, hold_reason=None,
            runway_incident=False, gate_incident=False,
        ) == "crew_readiness"

    def test_default_operational(self):
        assert resolve_delay_reason(
            "", is_held=False, hold_reason=None,
            runway_incident=False, gate_incident=False,
        ) == "operational"

    def test_none_base_reason_defaults_operational(self):
        assert resolve_delay_reason(
            None, is_held=False, hold_reason=None,
            runway_incident=False, gate_incident=False,
        ) == "operational"


# ── boarding_delay_update ────────────────────────────────────────

class TestBoardingDelayUpdate:
    def test_none_when_not_boarding(self):
        assert boarding_delay_update(
            "scheduled", "departure", (BASE - timedelta(minutes=30)).isoformat(),
            BASE, 0.5, 0, "",
        ) is None

    def test_none_when_arrival(self):
        assert boarding_delay_update(
            "boarding", "arrival", (BASE - timedelta(minutes=30)).isoformat(),
            BASE, 0.5, 0, "",
        ) is None

    def test_none_when_scheduled_missing(self):
        assert boarding_delay_update(
            "boarding", "departure", None, BASE, 0.5, 0, "",
        ) is None

    def test_none_when_unparseable(self):
        assert boarding_delay_update(
            "boarding", "departure", "not-a-date", BASE, 0.5, 0, "",
        ) is None

    def test_none_before_scheduled_time(self):
        # sim_time earlier than schedule → not late yet
        assert boarding_delay_update(
            "boarding", "departure", (BASE + timedelta(minutes=10)).isoformat(),
            BASE, 0.5, 0, "",
        ) is None

    def test_none_when_boarding_effectively_complete(self):
        # boarded_pct >= 0.95 → no incomplete-boarding delay
        assert boarding_delay_update(
            "boarding", "departure", (BASE - timedelta(minutes=30)).isoformat(),
            BASE, 0.96, 0, "",
        ) is None

    def test_delay_computed_from_schedule(self):
        result = boarding_delay_update(
            "boarding", "departure", (BASE - timedelta(minutes=42)).isoformat(),
            BASE, 0.5, 0, "",
        )
        assert result == (42, "boarding_incomplete")

    def test_none_when_delay_not_greater_than_current(self):
        # 20 min late but flight already carries 30 min delay → no bump
        assert boarding_delay_update(
            "boarding", "departure", (BASE - timedelta(minutes=20)).isoformat(),
            BASE, 0.5, 30, "",
        ) is None

    def test_bump_when_delay_greater_than_current(self):
        result = boarding_delay_update(
            "boarding", "departure", (BASE - timedelta(minutes=50)).isoformat(),
            BASE, 0.5, 30, "",
        )
        assert result == (50, "boarding_incomplete")

    def test_preserves_noise_reason(self):
        for noise in NOISE_DELAY_REASONS:
            result = boarding_delay_update(
                "boarding", "departure", (BASE - timedelta(minutes=40)).isoformat(),
                BASE, 0.5, 0, noise,
            )
            assert result == (40, noise), noise

    def test_non_noise_reason_replaced(self):
        result = boarding_delay_update(
            "boarding", "departure", (BASE - timedelta(minutes=40)).isoformat(),
            BASE, 0.5, 0, "operational",
        )
        assert result == (40, "boarding_incomplete")

    def test_accepts_datetime_scheduled(self):
        result = boarding_delay_update(
            "boarding", "departure", BASE - timedelta(minutes=15),
            BASE, 0.5, 0, "",
        )
        assert result == (15, "boarding_incomplete")
