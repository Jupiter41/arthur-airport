"""Tests for the sim-speed test harness itself.

Validates that SimClock, AlertScenario, and deterministic assertions
work correctly at different speed multipliers.
"""

from datetime import datetime

from tests.harness.sim_speed import SimClock, SimTick, AlertScenario


class TestSimClock:
    """SimClock produces deterministic ticks."""

    def test_basic_ticks(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        ticks = clock.ticks(3)
        assert len(ticks) == 3
        assert ticks[0].sim_time == datetime(2025, 6, 15, 8, 0)
        assert ticks[1].sim_time == datetime(2025, 6, 15, 8, 1)
        assert ticks[2].sim_time == datetime(2025, 6, 15, 8, 2)

    def test_tick_numbers_sequential(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=60)
        ticks = clock.ticks(5)
        assert [t.tick_number for t in ticks] == [0, 1, 2, 3, 4]

    def test_speed_multiplier_preserved(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=600)
        tick = clock.tick()
        assert tick.speed_multiplier == 600

    def test_advance_to(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        ticks = clock.advance_to("2025-06-15T10:00:00")
        assert len(ticks) == 120  # 2 hours = 120 minutes
        assert ticks[-1].sim_time == datetime(2025, 6, 15, 9, 59)

    def test_advance_minutes(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        ticks = clock.advance_minutes(30)
        assert len(ticks) == 30
        assert clock.sim_time == datetime(2025, 6, 15, 8, 30)

    def test_day_of_sim(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        # First day
        tick = clock.tick()
        assert tick.day_of_sim == 1
        # Advance to next day
        clock.advance_to("2025-06-16T08:00:00")
        tick = clock.tick()
        assert tick.day_of_sim == 2

    def test_to_payload(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=60)
        tick = clock.tick()
        payload = tick.to_payload()
        assert payload["sim_time"] == "2025-06-15T08:00:00"
        assert payload["speed_multiplier"] == 60
        assert payload["tick_number"] == 0

    def test_to_event(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        tick = clock.tick()
        event = tick.to_event()
        assert event["event_type"] == "SimClockTick"
        assert "payload" in event

    def test_reset(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        clock.ticks(10)
        clock.reset()
        assert clock.sim_time == datetime(2025, 6, 15, 8, 0)

    def test_reset_with_new_speed(self):
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        clock.ticks(10)
        clock.reset(speed=600)
        tick = clock.tick()
        assert tick.speed_multiplier == 600
        assert tick.sim_time == datetime(2025, 6, 15, 8, 0)


class TestAlertScenario:
    """AlertScenario fires at correct sim_times."""

    def test_alert_fires_on_condition(self):
        """Alert fires when sim_time passes 09:00."""
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        scenario = AlertScenario(
            clock=clock,
            check_fn=lambda t: t.sim_time.hour >= 9,
        )
        fired = scenario.run(duration_minutes=120)
        assert len(fired) == 60  # 09:00 through 09:59
        assert fired[0].sim_time == datetime(2025, 6, 15, 9, 0)

    def test_deterministic_across_speeds(self):
        """Same alert fires at the same sim_times regardless of speed."""

        def fires_at_10am(tick: SimTick) -> bool:
            return tick.sim_time.hour == 10 and tick.sim_time.minute == 0

        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        scenario = AlertScenario(clock=clock, check_fn=fires_at_10am)
        results = scenario.run_at_speeds(
            duration_minutes=180,
            speeds=[1, 60, 600],
        )
        # All speeds should find exactly one firing at 10:00
        for speed, fired in results.items():
            assert len(fired) == 1, f"speed={speed}: expected 1 firing, got {len(fired)}"
            assert fired[0].sim_time == datetime(2025, 6, 15, 10, 0)

        AlertScenario.assert_deterministic(results)

    def test_assert_deterministic_fails_on_mismatch(self):
        """assert_deterministic raises when results differ."""
        tick_a = SimTick(
            sim_time=datetime(2025, 6, 15, 10, 0),
            speed_multiplier=1, tick_number=0, day_of_sim=1,
        )
        tick_b = SimTick(
            sim_time=datetime(2025, 6, 15, 11, 0),
            speed_multiplier=60, tick_number=0, day_of_sim=1,
        )
        import pytest
        with pytest.raises(AssertionError, match="Alert times differ"):
            AlertScenario.assert_deterministic({1: [tick_a], 60: [tick_b]})

    def test_empty_scenario(self):
        """No alerts fire when condition is never true."""
        clock = SimClock(start="2025-06-15T08:00:00", speed=1)
        scenario = AlertScenario(
            clock=clock,
            check_fn=lambda t: False,
        )
        fired = scenario.run(duration_minutes=60)
        assert fired == []
