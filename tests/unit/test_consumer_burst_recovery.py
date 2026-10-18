"""Exercise real consumer loops during command-before-clock restart recovery."""

import asyncio
import importlib
import json
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import import_service_module


class Message:
    def __init__(self, event):
        self.event = event

    def error(self):
        return None

    def value(self):
        return json.dumps(self.event).encode()

    def topic(self):
        return "sim.clock" if self.event.get("event_type") == "SimClockTick" else "passengers.events"


def context(service, monkeypatch):
    import_service_module(service, "application.commands" if service != "analysis" else "services.state")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    return importlib.import_module("kafka.consumer")


@pytest.mark.parametrize("service", ["passenger", "baggage"])
def test_command_received_before_clock_is_retained_until_valid_tick(service, monkeypatch):
    consumer = context(service, monkeypatch)
    consumer._state.sim_time = None
    command = {"command_type": "OpenSecurityLane", "command_id": "synthetic-command"}
    tick = {"event_type": "SimClockTick", "sim_time": "2026-01-01T10:00:00",
            "payload": {"sim_time": "2026-01-01T10:00:00"}}
    batches = [[Message(command)], [Message(tick)]]
    observed = []

    class Broker:
        def subscribe(self, topics):
            pass

        def consume(self, *args, **kwargs):
            if batches:
                return batches.pop(0)
            consumer.stop_consumer()
            return []

        def close(self):
            pass

    monkeypatch.setattr(consumer, "_make_consumer", Broker)
    if service == "passenger":
        monkeypatch.setattr(consumer, "_run_command_consumer", AsyncMock())

    async def dispatch(envelope):
        if envelope.get("command_type"):
            assert consumer._state.sim_time == datetime(2026, 1, 1, 10)
        observed.append(envelope)

    monkeypatch.setattr(consumer, "_dispatch", dispatch)
    asyncio.run(consumer.run_consumer())
    assert observed == [command, tick]


def test_analysis_preserves_facts_and_receipts_but_evaluates_latest_tick(monkeypatch):
    consumer = context("analysis", monkeypatch)
    first = {"event_type": "SimClockTick", "payload": {"sim_time": "2026-01-01T10:00:00"}}
    latest = {"event_type": "SimClockTick", "payload": {"sim_time": "2026-01-01T10:01:00"}}
    fact = {"event_type": "SecurityQueueUpdated", "payload": {"terminal": "B"}}
    receipt = {"event_type": "CommandExecuted", "payload": {"command_id": "synthetic-command"}}
    batches = [[Message(event) for event in [first, fact, latest, receipt]]]

    class Broker:
        def __init__(self, config):
            pass

        def subscribe(self, topics):
            pass

        def consume(self, *args, **kwargs):
            if batches:
                return batches.pop(0)
            consumer.stop_consumer()
            return []

        def close(self):
            pass

    monkeypatch.setattr(consumer, "Consumer", Broker)
    dispatch = AsyncMock()
    evaluate = AsyncMock()
    monkeypatch.setattr(consumer, "_dispatch_event", dispatch)
    monkeypatch.setattr(consumer, "_on_tick", evaluate)
    asyncio.run(consumer.run_consumer())
    assert [call.args[0] for call in dispatch.await_args_list] == [
        "SimClockTick", "SecurityQueueUpdated", "SimClockTick", "CommandExecuted"]
    evaluate.assert_awaited_once_with(latest["payload"])


def test_passenger_command_executes_while_fact_tick_is_waiting(monkeypatch):
    consumer = context("passenger", monkeypatch)
    consumer._state.sim_time = datetime(2026, 1, 1, 10)
    tick = {"event_type": "SimClockTick"}
    command = {"command_type": "OpenSecurityLane", "command_id": "under-load"}
    closed = []

    async def exercise():
        tick_started = asyncio.Event()
        command_done = asyncio.Event()

        class Facts:
            def subscribe(self, topics):
                assert "passengers.commands" not in topics

            def consume(self, *args, **kwargs):
                return [Message(tick)]

            def close(self):
                closed.append("facts")

        class Commands:
            sent = False

            def subscribe(self, topics):
                assert topics == ["passengers.commands"]

            def poll(self, timeout):
                if tick_started.is_set() and not self.sent:
                    self.sent = True
                    return Message(command)

            def commit(self, message, asynchronous):
                assert command_done.is_set()
                assert asynchronous is False

            def close(self):
                closed.append("commands")

        async def slow_tick(envelope):
            tick_started.set()
            await asyncio.wait_for(command_done.wait(), timeout=2)
            consumer.stop_consumer()

        async def handle(envelope):
            assert envelope == command
            assert tick_started.is_set()
            command_done.set()

        monkeypatch.setattr(consumer, "_make_consumer", Facts)
        monkeypatch.setattr(consumer, "_make_command_consumer", Commands)
        monkeypatch.setattr(consumer, "_dispatch", slow_tick)
        monkeypatch.setattr(consumer, "_handle_command", handle)
        await asyncio.wait_for(consumer.run_consumer(), timeout=3)

    asyncio.run(exercise())
    assert closed == ["commands", "facts"]


def test_passenger_command_waits_for_clock_and_retries_before_offset_commit(monkeypatch):
    consumer = context("passenger", monkeypatch)
    consumer._state.sim_time = None
    consumer._consumer_running = True
    command = {"command_type": "OpenSecurityLane", "command_id": "retry-command"}
    calls = []

    class Commands:
        def subscribe(self, topics):
            pass

        def poll(self, timeout):
            return Message(command)

        def commit(self, message, asynchronous):
            calls.append("commit")
            consumer.stop_consumer()

        def close(self):
            calls.append("close")

    async def handle(envelope):
        assert consumer._state.sim_time is not None
        calls.append("execute")
        if calls.count("execute") == 1:
            raise RuntimeError("Transient database failure")

    async def exercise():
        task = asyncio.create_task(consumer._run_command_consumer())
        await asyncio.sleep(0.15)
        assert calls == []  # No receipt or commit before a real simulation clock.
        consumer._state.sim_time = datetime(2026, 1, 1, 10)
        await asyncio.wait_for(task, timeout=2)

    monkeypatch.setattr(consumer, "_make_command_consumer", Commands)
    monkeypatch.setattr(consumer, "_handle_command", handle)
    asyncio.run(exercise())
    assert calls == ["execute", "execute", "commit", "close"]
