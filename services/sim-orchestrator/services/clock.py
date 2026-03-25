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


def configure_callbacks(on_hour=None, on_day=None) -> None:
    """Register callbacks for hour-boundary and day-boundary events.

    Args:
        on_hour: Async callable(sim_time) invoked every simulated hour.
        on_day: Async callable(next_day, sim_time) invoked at 23:30 to seed the next day.
    """
    global _on_hour_boundary, _on_day_boundary
    _on_hour_boundary = on_hour
    _on_day_boundary = on_day


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


async def run_clock_loop() -> None:
    """Main simulation clock loop.

    Each iteration:
        1. Advance sim_time by 1 minute
        2. Emit SimClockTick to ``sim.clock``
        3. Call hour-boundary callback if minute == 0
        4. Call day-boundary callback at 23:30
        5. Sleep for ``60 / speed_multiplier`` real seconds
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

        _sim_time += timedelta(minutes=1)
        _tick_number += 1

        emit_clock_tick(
            sim_time=_sim_time,
            speed_multiplier=_speed_multiplier,
            tick_number=_tick_number,
            day_of_sim=_sim_day,
        )
        _events_produced += 1
        m_tick_total.inc()

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

        # Detect day rollover
        prev = _sim_time - timedelta(minutes=1)
        if _sim_time.date() != prev.date():
            _sim_day += 1
            logger.info("Day boundary: now day %d (%s)", _sim_day, _sim_time.date())

        tick_elapsed = (time.monotonic() - tick_start) * 1000  # ms
        m_tick_latency.observe(tick_elapsed)
        _tick_latencies.append(tick_elapsed)
        if len(_tick_latencies) > 1000:
            _tick_latencies = _tick_latencies[-500:]

        sleep_s = 60.0 / _speed_multiplier
        actual_sleep = max(0, sleep_s - tick_elapsed / 1000)
        await asyncio.sleep(actual_sleep)
