"""Simulation clock — async loop emitting SimClockTick events."""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

from kafka.producer import emit_clock_tick
from metrics import (
    sim_tick_total as m_tick_total,
    sim_tick_latency_ms as m_tick_latency,
    sim_speed_multiplier as m_speed,
    sim_day_number as m_day,
    sim_paused as m_paused,
)

logger = logging.getLogger(__name__)

SIM_START_TIME = datetime.fromisoformat(
    os.getenv("SIM_START_TIME", "2024-06-15T06:00:00")
)

# Module-level state
_running: bool = True
_paused: bool = False
_sim_time: datetime = SIM_START_TIME
_speed_multiplier: int = int(os.getenv("SIM_SPEED_MULTIPLIER", "60"))
_sim_day: int = 1
_tick_number: int = 0
_tick_latencies: list[float] = []
_events_produced: int = 0

# Callbacks
_on_hour_boundary = None
_on_day_boundary = None
_on_tick = None


def configure_callbacks(on_hour=None, on_day=None, on_tick=None) -> None:
    """Register callbacks for hour-boundary, day-boundary, and per-tick events.

    Args:
        on_hour: Async callable(sim_time) invoked every simulated hour.
        on_day: Async callable(next_day, sim_time) invoked at 23:30 to seed the next day.
        on_tick: Async callable(sim_time) invoked every simulated minute.
    """
    global _on_hour_boundary, _on_day_boundary, _on_tick
    _on_hour_boundary = on_hour
    _on_day_boundary = on_day
    _on_tick = on_tick


def get_state() -> dict:
    """Return current clock state as a JSON-serialisable dict.

    Includes: running, paused, sim_time, real_time, speed_multiplier,
    day_number, tick_number.
    """
    return {
        "running": _running,
        "paused": _paused,
        "sim_time": _sim_time.isoformat(),
        "real_time": datetime.utcnow().isoformat(),
        "speed_multiplier": _speed_multiplier,
        "mode": compute_mode(),
        "day_number": _sim_day,
        "tick_number": _tick_number,
    }


def get_sim_time() -> datetime:
    return _sim_time


def get_sim_day() -> int:
    return _sim_day


def get_tick_number() -> int:
    return _tick_number


def get_speed() -> int:
    return _speed_multiplier


def is_paused() -> bool:
    return _paused


def is_running() -> bool:
    return _running


def get_events_produced() -> int:
    return _events_produced


def get_tick_latencies() -> list[float]:
    return _tick_latencies


def set_speed(multiplier: int) -> None:
    """Change the simulation speed multiplier at runtime.

    Higher values make simulated time advance faster relative to wall-clock time.
    """
    global _speed_multiplier
    _speed_multiplier = multiplier
    logger.info("Speed set to %dx", multiplier)


def pause() -> None:
    """Pause the simulation clock — no ticks are emitted while paused."""
    global _paused
    _paused = True
    logger.info("Simulation paused at %s", _sim_time)


def resume() -> None:
    """Resume a paused simulation clock."""
    global _paused
    _paused = False
    logger.info("Simulation resumed at %s", _sim_time)


def stop() -> None:
    global _running
    _running = False
    logger.info("Simulation stopped")


def reset_to_start() -> None:
    """Reset clock state to initial values."""
    global _sim_time, _sim_day, _tick_number, _paused, _running, _events_produced, _tick_latencies
    _sim_time = SIM_START_TIME
    _sim_day = 1
    _tick_number = 0
    _paused = False
    _running = True
    _events_produced = 0
    _tick_latencies = []
    logger.info("Clock reset to %s", _sim_time)


def restore_state(
    sim_time: datetime,
    day_number: int,
    tick_number: int,
    speed_multiplier: int,
) -> None:
    """Restore clock state from a snapshot."""
    global _sim_time, _sim_day, _tick_number, _speed_multiplier, _events_produced, _tick_latencies
    _sim_time = sim_time
    _sim_day = day_number
    _tick_number = tick_number
    _speed_multiplier = speed_multiplier
    _events_produced = 0
    _tick_latencies = []
    logger.info("Clock restored to %s (day %d, tick %d)", sim_time, day_number, tick_number)


MAX_TICKS_PER_SEC = int(os.getenv("MAX_TICKS_PER_SEC", "10"))

# Speed mode thresholds — see PLAN-HIGH-SPEED.md
_FAST_THRESHOLD = 60      # above 60× → FAST mode (batched writes)
_BULK_THRESHOLD = 600     # above 600× → BULK mode (in-memory, periodic sync)


def compute_mode(speed: int | None = None) -> str:
    """Return the simulation mode for the given speed.

    * ``REALTIME`` (1×–60×)  — per-event Neo4j writes, full Kafka events
    * ``FAST``     (60×–600×) — batched Neo4j writes per tick
    * ``BULK``     (600×+)    — in-memory state, periodic Neo4j sync
    """
    s = speed if speed is not None else _speed_multiplier
    if s <= _FAST_THRESHOLD:
        return "REALTIME"
    if s <= _BULK_THRESHOLD:
        return "FAST"
    return "BULK"


def _compute_step_minutes() -> int:
    """How many sim-minutes to advance per emitted tick.

    At low speeds (≤600×) this is 1 — normal minute-by-minute ticking.
    At higher speeds the step increases so the Kafka tick rate stays
    at MAX_TICKS_PER_SEC, reducing message flood and giving consumers
    time to process each tick.
    """
    return max(1, _speed_multiplier // (60 * MAX_TICKS_PER_SEC))


async def run_clock_loop() -> None:
    """Main simulation clock loop.

    At speeds ≤600× the loop emits one tick per sim-minute (unchanged).
    At higher speeds the clock advances multiple sim-minutes per iteration
    and emits a single tick with the final sim_time, keeping the wall-clock
    tick rate capped at MAX_TICKS_PER_SEC (~10/s).  Hour- and day-boundary
    callbacks are still invoked at every intermediate sim-minute so that
    probabilistic events, next-day seeding, and day-rollover detection
    work correctly regardless of speed.
    """
    global _sim_time, _sim_day, _tick_number, _events_produced, _tick_latencies

    logger.info("Clock loop started at %s (speed: %dx)", _sim_time, _speed_multiplier)

    while _running:
        if _paused:
            m_paused.set(1)
            await asyncio.sleep(0.1)
            continue

        m_paused.set(0)
        m_speed.set(_speed_multiplier)
        m_day.set(_sim_day)
        tick_start = time.monotonic()

        step = _compute_step_minutes()

        # Advance sim_time minute-by-minute so boundary callbacks fire
        for _ in range(step):
            _sim_time += timedelta(minutes=1)

            # Hour boundary check
            if _sim_time.minute == 0 and _on_hour_boundary:
                try:
                    await _on_hour_boundary(_sim_time)
                except Exception as e:
                    logger.error("Hour boundary callback error: %s", e)

            # Day boundary: seed next day at 23:30
            if _sim_time.hour == 23 and _sim_time.minute == 30 and _on_day_boundary:
                try:
                    await _on_day_boundary(_sim_day + 1, _sim_time)
                except Exception as e:
                    logger.error("Day boundary callback error: %s", e)

            # Per-tick callback (scenario engine)
            if _on_tick:
                try:
                    await _on_tick(_sim_time)
                except Exception as e:
                    logger.error("Tick callback error: %s", e)

            # Detect day rollover
            prev = _sim_time - timedelta(minutes=1)
            if _sim_time.date() != prev.date():
                _sim_day += 1
                logger.info("Day boundary: now day %d (%s)", _sim_day, _sim_time.date())

        _tick_number += 1

        mode = compute_mode()

        # Emit one tick per outer iteration with the final sim_time
        try:
            emit_clock_tick(
                sim_time=_sim_time,
                speed_multiplier=_speed_multiplier,
                tick_number=_tick_number,
                day_of_sim=_sim_day,
                step_minutes=step,
                mode=mode,
            )
            _events_produced += 1
            m_tick_total.inc()
        except Exception as e:
            logger.error("Failed to emit SimClockTick at tick %d: %s", _tick_number, e)

        tick_elapsed = (time.monotonic() - tick_start) * 1000  # ms
        m_tick_latency.observe(tick_elapsed)
        _tick_latencies.append(tick_elapsed)
        if len(_tick_latencies) > 1000:
            _tick_latencies = _tick_latencies[-500:]

        sleep_s = step * 60.0 / _speed_multiplier
        actual_sleep = max(0, sleep_s - tick_elapsed / 1000)
        await asyncio.sleep(actual_sleep)
