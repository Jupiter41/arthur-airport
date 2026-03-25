"""Sim-speed test harness — reusable fixture for accelerated alert validation.

Provides a deterministic clock generator that produces SimClockTick-like
payloads at configurable speed multipliers. Tests can step through simulated
time and verify that alert conditions fire at the correct sim_time regardless
of whether the simulation runs at 1x or 600x.

Usage:
    from tests.harness.sim_speed import SimClock

    clock = SimClock(start="2025-06-15T08:00:00", speed=60)
    for tick in clock.ticks(count=120):
        # tick.sim_time, tick.speed_multiplier, tick.tick_number
        pass

    # Or advance to a specific time
    clock = SimClock(start="2025-06-15T08:00:00", speed=1)
    ticks = clock.advance_to("2025-06-15T10:00:00")
    assert len(ticks) == 120  # 2 hours = 120 minutes
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterator


@dataclass(frozen=True)
class SimTick:
    """A single simulated clock tick."""
    sim_time: datetime
    speed_multiplier: int
    tick_number: int
    day_of_sim: int

    def to_payload(self) -> dict:
        """Return a dict matching the SimClockTick Kafka event payload."""
        return {
            "sim_time": self.sim_time.isoformat(),
            "speed_multiplier": self.speed_multiplier,
            "tick_number": self.tick_number,
            "day_of_sim": self.day_of_sim,
        }

    def to_event(self) -> dict:
        """Return a full SimClockTick Kafka event envelope."""
        return {
            "event_type": "SimClockTick",
            "sim_time": self.sim_time.isoformat(),
            "payload": self.to_payload(),
        }


@dataclass
class SimClock:
    """Deterministic clock for sim-speed test scenarios.

    Args:
        start: ISO timestamp for the first tick.
        speed: Speed multiplier (1 = real-time, 60 = 1 sim-min per real-second, etc.)
        step_minutes: Simulated minutes per tick (default 1).
    """
    start: str
    speed: int = 1
    step_minutes: int = 1
    _current: datetime = field(init=False)
    _tick_number: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._current = datetime.fromisoformat(self.start)

    @property
    def sim_time(self) -> datetime:
        return self._current

    @property
    def day_of_sim(self) -> int:
        start = datetime.fromisoformat(self.start)
        return (self._current - start).days + 1

    def tick(self) -> SimTick:
        """Advance one tick and return it."""
        result = SimTick(
            sim_time=self._current,
            speed_multiplier=self.speed,
            tick_number=self._tick_number,
            day_of_sim=self.day_of_sim,
        )
        self._current += timedelta(minutes=self.step_minutes)
        self._tick_number += 1
        return result

    def ticks(self, count: int) -> list[SimTick]:
        """Generate `count` ticks."""
        return [self.tick() for _ in range(count)]

    def advance_to(self, target: str) -> list[SimTick]:
        """Advance until sim_time >= target, returning all ticks produced."""
        target_dt = datetime.fromisoformat(target)
        result: list[SimTick] = []
        while self._current < target_dt:
            result.append(self.tick())
        return result

    def advance_minutes(self, minutes: int) -> list[SimTick]:
        """Advance by a given number of simulated minutes."""
        count = minutes // self.step_minutes
        return self.ticks(count)

    def iter_ticks(self, count: int) -> Iterator[SimTick]:
        """Lazily yield `count` ticks."""
        for _ in range(count):
            yield self.tick()

    def reset(self, start: str | None = None, speed: int | None = None) -> None:
        """Reset the clock, optionally with new start/speed."""
        if start is not None:
            self.start = start
        if speed is not None:
            self.speed = speed
        self._current = datetime.fromisoformat(self.start)
        self._tick_number = 0


class AlertScenario:
    """Run a callback on each tick and collect timestamps where a condition fires.

    Usage:
        def check_alert(tick: SimTick) -> bool:
            return some_condition(tick.sim_time)

        scenario = AlertScenario(
            clock=SimClock(start="2025-06-15T08:00:00", speed=1),
            check_fn=check_alert,
        )
        fired_at = scenario.run(duration_minutes=180)
        assert fired_at[0].sim_time.hour == 10
    """

    def __init__(self, clock: SimClock, check_fn):
        self.clock = clock
        self.check_fn = check_fn

    def run(self, duration_minutes: int) -> list[SimTick]:
        """Run for `duration_minutes` and return ticks where the alert fired."""
        fired: list[SimTick] = []
        for tick in self.clock.iter_ticks(duration_minutes):
            if self.check_fn(tick):
                fired.append(tick)
        return fired

    def run_at_speeds(
        self, duration_minutes: int, speeds: list[int]
    ) -> dict[int, list[SimTick]]:
        """Run the same scenario at multiple speeds, verify determinism.

        Returns a dict mapping speed → list of ticks where alert fired.
        All speeds should produce alerts at the same sim_times.
        """
        results: dict[int, list[SimTick]] = {}
        base_start = self.clock.start
        for speed in speeds:
            self.clock.reset(start=base_start, speed=speed)
            results[speed] = self.run(duration_minutes)
        return results

    @staticmethod
    def assert_deterministic(
        results: dict[int, list[SimTick]],
    ) -> None:
        """Assert that alert sim_times are identical across all speeds."""
        speed_list = list(results.keys())
        if len(speed_list) < 2:
            return
        base_times = [t.sim_time for t in results[speed_list[0]]]
        for speed in speed_list[1:]:
            other_times = [t.sim_time for t in results[speed]]
            assert base_times == other_times, (
                f"Alert times differ between speed {speed_list[0]} and {speed}:\n"
                f"  speed {speed_list[0]}: {base_times}\n"
                f"  speed {speed}: {other_times}"
            )
