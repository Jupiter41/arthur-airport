"""Unit tests for _common.kafka_runtime.run_consumer_loop.

Exercises the canonical Arthur Airport consumer pattern:
- Batch-poll → tick/other separation → dispatch others first → dispatch tick
- Stale-tick dedup (keep only latest SimClockTick per batch)
- Health marking after each non-empty batch
- Clean close on exit regardless of exit path
- Exception isolation (dispatch error must not kill the loop)
"""

import asyncio
import json
import os
import sys

import pytest

# Ensure services/ is on sys.path so _common is importable without a service context.
_SERVICES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "services")
if _SERVICES_DIR not in sys.path:
    sys.path.insert(0, _SERVICES_DIR)

from _common import kafka_runtime  # noqa: E402


class _Msg:
    """Minimal stub that mimics a confluent-kafka Message."""

    def __init__(self, payload: dict | None = None, *, bad_value: bool = False, error=None):
        self._payload = payload
        self._bad_value = bad_value
        self._error = error

    def error(self):
        return self._error

    def value(self):
        if self._bad_value:
            return b"not-json"
        return json.dumps(self._payload).encode()

    def topic(self):
        return "sim.clock" if (self._payload or {}).get("event_type") == "SimClockTick" else "test"


class _Broker:
    """Fake Consumer that returns pre-loaded batches then stops the loop."""

    def __init__(self, batches: list[list[_Msg]], running_flag: list[bool]):
        self._batches = list(batches)
        self._running_flag = running_flag
        self.closed = False

    def consume(self, batch_size=200, timeout=1.0):
        if self._batches:
            return self._batches.pop(0)
        self._running_flag[0] = False
        return []

    def close(self):
        self.closed = True


class _Health:
    def __init__(self):
        self.marks = 0

    def mark_message(self):
        self.marks += 1


def _tick(sim_time: str = "2026-01-01T10:00:00") -> dict:
    return {"event_type": "SimClockTick", "sim_time": sim_time, "payload": {"sim_time": sim_time}}


def _event(event_type: str = "SomeEvent") -> dict:
    return {"event_type": event_type, "payload": {}}


# ── Basic dispatch order ───────────────────────────────────────


class TestDispatchOrder:
    def test_domain_events_dispatched_before_tick(self):
        running = [True]
        broker = _Broker([[_Msg(_tick()), _Msg(_event("FlightStatusChanged"))]], running)
        dispatched = []

        async def dispatch(env):
            dispatched.append(env["event_type"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert dispatched == ["FlightStatusChanged", "SimClockTick"]

    def test_only_latest_tick_dispatched_from_batch(self):
        running = [True]
        t1, t2 = _tick("2026-01-01T10:00:00"), _tick("2026-01-01T10:01:00")
        broker = _Broker([[_Msg(t1), _Msg(t2)]], running)
        dispatched_times = []

        async def dispatch(env):
            if env["event_type"] == "SimClockTick":
                dispatched_times.append(env["sim_time"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert dispatched_times == ["2026-01-01T10:01:00"], "Only the latest tick should dispatch"

    def test_empty_batch_skipped(self):
        running = [True]
        broker = _Broker([[], [_Msg(_event())]], running)
        dispatched = []

        async def dispatch(env):
            dispatched.append(env)

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert len(dispatched) == 1

    def test_no_tick_only_domain_events(self):
        running = [True]
        broker = _Broker([[_Msg(_event("A")), _Msg(_event("B"))]], running)
        dispatched = []

        async def dispatch(env):
            dispatched.append(env["event_type"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert dispatched == ["A", "B"]

    def test_tick_only_no_domain_events(self):
        running = [True]
        broker = _Broker([[_Msg(_tick())]], running)
        dispatched = []

        async def dispatch(env):
            dispatched.append(env["event_type"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert dispatched == ["SimClockTick"]


# ── Error handling ─────────────────────────────────────────────


class TestErrorHandling:
    def test_dispatch_exception_does_not_stop_loop(self):
        """A crash in dispatch must not propagate — subsequent events still run."""
        running = [True]
        broker = _Broker(
            [[_Msg(_event("Bad")), _Msg(_event("Good"))]],
            running,
        )
        seen = []

        async def dispatch(env):
            if env["event_type"] == "Bad":
                raise RuntimeError("boom")
            seen.append(env["event_type"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert "Good" in seen

    def test_bad_json_message_skipped(self):
        running = [True]
        broker = _Broker([[_Msg(bad_value=True), _Msg(_event("AfterBad"))]], running)
        seen = []

        async def dispatch(env):
            seen.append(env["event_type"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert seen == ["AfterBad"]

    def test_error_message_skipped(self):
        running = [True]
        err_msg = _Msg(error="KafkaError")
        broker = _Broker([[err_msg, _Msg(_event())]], running)
        seen = []

        async def dispatch(env):
            seen.append(env["event_type"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert seen == ["SomeEvent"]

    def test_consumer_closed_after_exception_in_dispatch(self):
        running = [True]
        broker = _Broker([[_Msg(_event())]], running)

        async def dispatch(env):
            raise RuntimeError("crash")

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert broker.closed


# ── Health tracking ────────────────────────────────────────────


class TestHealthTracking:
    def test_health_marked_once_per_nonempty_batch(self):
        running = [True]
        broker = _Broker([[_Msg(_event())], [_Msg(_event())]], running)
        health = _Health()

        asyncio.run(
            kafka_runtime.run_consumer_loop(broker, AsyncDispatch(), lambda: running[0], health)
        )
        assert health.marks == 2

    def test_health_not_marked_on_empty_batch(self):
        running = [True]
        broker = _Broker([[], [_Msg(_event())]], running)
        health = _Health()

        asyncio.run(
            kafka_runtime.run_consumer_loop(broker, AsyncDispatch(), lambda: running[0], health)
        )
        assert health.marks == 1

    def test_no_health_when_none_passed(self):
        running = [True]
        broker = _Broker([[_Msg(_event())]], running)
        asyncio.run(kafka_runtime.run_consumer_loop(broker, AsyncDispatch(), lambda: running[0], None))


class AsyncDispatch:
    async def __call__(self, env):
        pass


# ── Consumer lifecycle ─────────────────────────────────────────


class TestLifecycle:
    def test_consumer_closed_on_normal_exit(self):
        running = [True]
        broker = _Broker([[_Msg(_event())]], running)

        asyncio.run(kafka_runtime.run_consumer_loop(broker, AsyncDispatch(), lambda: running[0]))
        assert broker.closed

    def test_loop_exits_when_should_run_false(self):
        """Loop terminates immediately when should_run() returns False."""
        broker = _Broker([[_Msg(_event())]], [False])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, AsyncDispatch(), lambda: False))
        assert broker.closed

    def test_multiple_batches_processed(self):
        running = [True]
        broker = _Broker(
            [[_Msg(_event("A"))], [_Msg(_event("B"))], [_Msg(_event("C"))]],
            running,
        )
        seen = []

        async def dispatch(env):
            seen.append(env["event_type"])

        asyncio.run(kafka_runtime.run_consumer_loop(broker, dispatch, lambda: running[0]))
        assert seen == ["A", "B", "C"]
