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
