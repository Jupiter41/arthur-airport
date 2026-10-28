"""Command redelivery must not duplicate operational mutations."""

import asyncio
from datetime import datetime

import pytest

from tests.conftest import import_service_module

import_service_module("flight", "application.commands")
from _common.commands import CommandReceipts, action_command

NOW = datetime(2024, 6, 15, 12)
COMMAND = {"command_id": "cmd-1", "command_type": "HoldFlight", "payload": {}}


def test_receipt_redelivery_mutates_once_and_reemits_result():
    runtime = CommandReceipts()
    mutations, events = [], []

    async def execute(envelope):
        mutations.append(envelope)

    def emit(*args):
        events.append(args)

    asyncio.run(runtime.handle(COMMAND, NOW, execute, emit))
    asyncio.run(runtime.handle(COMMAND, NOW, execute, emit))
    assert len(mutations) == 1
    assert len(events) == 2
    assert events[0][0] == "CommandExecuted"
    assert events[0][2]["command_id"] == "cmd-1"


def test_io_error_is_retryable():
    runtime = CommandReceipts()

    async def fail(envelope):
        raise RuntimeError("Neo4j unavailable")

    with pytest.raises(RuntimeError):
        asyncio.run(runtime.handle(COMMAND, NOW, fail, lambda *a: None))
    assert runtime.results == {}


def test_rejection_emits_reason_and_no_execution():
    events = []

    async def reject(envelope):
        return "Flight not found"

    asyncio.run(
        CommandReceipts().handle(COMMAND, NOW, reject, lambda *a: events.append(a))
    )
    assert events[0][0] == "CommandRejected"
    assert events[0][2]["reason"] == "Flight not found"


def test_clock_required_before_any_mutation():
    mutations = []

    async def execute(envelope):
        mutations.append(envelope)

    with pytest.raises(RuntimeError, match="clock"):
        asyncio.run(CommandReceipts().handle(COMMAND, None, execute, lambda *a: None))
    assert mutations == []


def test_restart_reloads_receipt_without_repeating_mutation():
    documents, mutations, events = {}, [], []

    async def execute(envelope):
        mutations.append(envelope)

    async def load(key):
        return documents.get(key)

    async def save(key, receipt):
        documents[key] = receipt

    for _ in range(2):
        # New runtime represents restarting the owning service.
        asyncio.run(
            CommandReceipts().handle(
                COMMAND,
                NOW,
                execute,
                lambda *a: events.append(a),
                load,
                save,
            )
        )
    assert len(mutations) == 1
    assert len(events) == 2


@pytest.mark.parametrize(
    "parameters",
    [
        {"terminal": "A", "new_lane_count": True},
        {"terminal": "A", "new_lane_count": 0},
        {"terminal": "A", "new_lane_count": 21},
    ],
)
def test_invalid_lane_count_has_no_command(parameters):
    assert action_command("open_security_lane", parameters) is None


@pytest.mark.parametrize(
    "action_type,command_type",
    [("contain_incident", "ContainIncident"), ("resolve_incident", "ResolveIncident")],
)
def test_incident_action_maps_to_incidents_command(action_type, command_type):
    intent = action_command(action_type, {"incident_id": "inc-1", "note": "n"})
    assert intent is not None
    assert intent.topic == "incidents.commands"
    assert intent.command_type == command_type
    assert intent.entity_key == "inc-1"
    assert intent.payload == {"incident_id": "inc-1", "note": "n"}


def test_incident_action_note_optional():
    intent = action_command("resolve_incident", {"incident_id": "inc-9"})
    assert intent is not None and intent.payload == {"incident_id": "inc-9"}


def test_incident_action_without_id_has_no_command():
    assert action_command("resolve_incident", {"note": "n"}) is None
    assert action_command("contain_incident", {"incident_id": ""}) is None
