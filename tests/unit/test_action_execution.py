"""Exercise dispatch and receipt behavior, including the negative paths."""

import asyncio
import importlib
from datetime import datetime

import pytest

from tests.conftest import import_service_module

NOW = datetime(2024, 6, 15, 12)


@pytest.fixture
def context(monkeypatch):
    execution = import_service_module("analysis", "services.action_execution")
    producer = importlib.import_module("kafka.producer")
    auto = importlib.import_module("services.autonomous")
    sent = []
    events = []

    async def send(intent, **kwargs):
        sent.append((intent, kwargs))

    async def save(document):
        pass

    monkeypatch.setattr(execution, "save_proposal", save)
    monkeypatch.setattr(producer, "emit_autonomous_action", lambda *args: None)
    monkeypatch.setattr(producer, "emit_domain_command", send)
    monkeypatch.setattr(
        producer, "emit_action_event", lambda *args: events.append(args)
    )
    queue = execution.approval_queue
    queue.clear()
    return execution, queue, producer, auto, sent, events


def proposal(queue, action="open_security_lane", parameters=None):
    return queue.propose(
        action_type=action,
        description="Relieve security congestion",
        parameters=parameters
        if parameters is not None
        else {
            "terminal": "Terminal B",
            "new_lane_count": 5,
        },
        confidence_score=0.9,
        proposed_by="operator",
        proposed_at=NOW,
        requires_human=False,
    )


def test_dispatch_targets_passenger_owner_without_claiming_application(context):
    execution, queue, _, auto, sent, events = context
    p = proposal(queue)
    result = asyncio.run(execution.dispatch(p, NOW))
    assert result["executed"] is False
    assert result["applied"] is False
    assert p.status == queue.DISPATCHED
    intent, metadata = sent[0]
    assert intent.topic == "passengers.commands"
    assert intent.payload == {"terminal": "B", "lanes_open": 5}
    assert metadata["command_id"] == p.id
    assert auto.get_action_log() == []
    assert events[0][0] == "ActionDispatched"


def test_only_owner_receipt_marks_execution_and_duplicate_is_ignored(context):
    execution, queue, _, auto, _, _ = context
    p = proposal(queue)
    asyncio.run(execution.dispatch(p, NOW))
    payload = {"command_id": p.id, "command_type": "OpenSecurityLane"}
    assert not asyncio.run(
        execution.receive_result("CommandExecuted", payload, NOW, "flights.events")
    )
    assert p.status == queue.DISPATCHED
    assert asyncio.run(
        execution.receive_result("CommandExecuted", payload, NOW, "passengers.events")
    )
    assert p.status == queue.EXECUTED
    assert not asyncio.run(
        execution.receive_result("CommandExecuted", payload, NOW, "passengers.events")
    )
    assert len(auto.get_action_log()) == 1


def test_rejected_command_does_not_appear_in_applied_log(context):
    execution, queue, _, auto, _, _ = context
    p = proposal(queue)
    asyncio.run(execution.dispatch(p, NOW))
    assert asyncio.run(
        execution.receive_result(
            "CommandRejected",
            {
                "command_id": p.id,
                "command_type": "OpenSecurityLane",
                "reason": "No checkpoint",
            },
            NOW,
            "passengers.events",
        )
    )
    assert p.status == queue.FAILED
    assert p.failure_reason == "No checkpoint"
    assert auto.get_action_log() == []


def test_broker_failure_retains_retryable_proposal_and_stable_identity(
    context, monkeypatch
):
    execution, queue, producer, _, sent, _ = context
    p = proposal(queue)
    original_send = producer.emit_domain_command

    async def fail(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(producer, "emit_domain_command", fail)
    with pytest.raises(RuntimeError, match="broker unavailable"):
        asyncio.run(execution.dispatch(p, NOW))
    assert p.status == queue.APPROVED
    monkeypatch.setattr(producer, "emit_domain_command", original_send)
    asyncio.run(execution.dispatch(p, NOW))
    assert sent[0][1]["command_id"] == p.id


def test_unsupported_action_emits_nothing(context):
    execution, queue, _, _, sent, events = context
    p = proposal(queue, "ground_delay_program", {})
    with pytest.raises(ValueError, match="advisory"):
        asyncio.run(execution.dispatch(p, NOW))
    assert p.status == queue.APPROVED
    assert sent == events == []


def test_baggage_action_uses_baggage_command_topic(context):
    execution, queue, _, _, sent, _ = context
    p = proposal(
        queue, "redirect_baggage", {"bag_id": "bag-1", "target_flight_id": "f2"}
    )
    asyncio.run(execution.dispatch(p, NOW))
    assert sent[0][0].topic == "baggage.commands"


def test_receipt_before_publisher_returns_is_not_overwritten(context, monkeypatch):
    execution, queue, producer, _, _, _ = context
    p = proposal(queue)

    async def send(intent, **kwargs):
        await execution.receive_result(
            "CommandExecuted",
            {
                "command_id": p.id,
                "command_type": intent.command_type,
            },
            NOW,
            "passengers.events",
        )

    monkeypatch.setattr(producer, "emit_domain_command", send)
    asyncio.run(execution.dispatch(p, NOW))
    assert p.status == queue.EXECUTED
