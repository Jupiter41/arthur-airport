"""Owner routing and durable execution adapter behavior."""

import asyncio
from datetime import timedelta

import pytest

from tests.unit.test_proposal_store import context, create, commands, NOW


def test_dispatch_targets_passenger_owner_without_claiming_application(context):
    _, execution, _, driver = context
    proposal = asyncio.run(create(context, human=False))
    result = asyncio.run(execution.dispatch(proposal, NOW))
    assert result["executed"] is result["applied"] is False
    assert proposal.status == "dispatched"
    command = commands(driver)[0]
    assert command["payload"] == {"terminal": "B", "lanes_open": 5}
    assert command["command_id"] == proposal.id
    assert any(row["topic"] == "passengers.commands" for row in driver.db["outbox"].values())


def test_only_owner_receipt_marks_execution_and_duplicate_is_ignored(context):
    _, execution, _, _ = context
    proposal = asyncio.run(create(context, human=False))
    asyncio.run(execution.dispatch(proposal, NOW))
    payload = {"command_id": proposal.id, "command_type": "OpenSecurityLane"}
    assert not asyncio.run(execution.receive_result("CommandExecuted", payload, NOW, "flights.events"))
    assert proposal.status == "dispatched"
    assert asyncio.run(execution.receive_result("CommandExecuted", payload, NOW, "passengers.events"))
    assert proposal.status == "executed"
    assert not asyncio.run(execution.receive_result("CommandExecuted", payload, NOW, "passengers.events"))
    assert len(asyncio.run(execution.confirmed_log())) == 1


def test_rejected_command_does_not_appear_in_applied_log(context):
    _, execution, _, _ = context
    proposal = asyncio.run(create(context, human=False))
    asyncio.run(execution.dispatch(proposal, NOW))
    assert asyncio.run(execution.receive_result("CommandRejected", {
        "command_id": proposal.id, "command_type": "OpenSecurityLane", "reason": "No checkpoint"
    }, NOW, "passengers.events"))
    assert proposal.status == "failed" and proposal.failure_reason == "No checkpoint"
    assert asyncio.run(execution.confirmed_log()) == []


def test_broker_failure_retains_retryable_proposal_and_stable_identity(context, monkeypatch):
    _, execution, worker, driver = context
    proposal = asyncio.run(create(context, human=False))
    asyncio.run(execution.dispatch(proposal, NOW))
    monkeypatch.setattr(worker, "publish_confirmed", lambda *args: (_ for _ in ()).throw(RuntimeError("broker")))
    with pytest.raises(RuntimeError, match="broker"):
        asyncio.run(worker.publish_pending())
    assert proposal.status == "dispatched"
    asyncio.run(execution.dispatch(proposal, NOW + timedelta(minutes=5)))
    assert len(commands(driver)) == 2
    assert {command["command_id"] for command in commands(driver)} == {proposal.id}


def test_unsupported_action_emits_no_command(context):
    _, execution, _, driver = context
    proposal = execution.approval_queue.propose(action_type="ground_delay_program", description="Advisory",
        parameters={}, confidence_score=0.9, proposed_by="operator", proposed_at=NOW, requires_human=False)
    proposal = asyncio.run(execution.persist(proposal, NOW))
    with pytest.raises(ValueError, match="advisory"):
        asyncio.run(execution.dispatch(proposal, NOW))
    assert proposal.status == "approved" and commands(driver) == []


def test_baggage_action_uses_baggage_command_topic(context):
    _, execution, _, driver = context
    proposal = execution.approval_queue.propose(action_type="redirect_baggage", description="Synthetic redirect",
        parameters={"bag_id": "bag-1", "target_flight_id": "f2"}, confidence_score=0.9,
        proposed_by="operator", proposed_at=NOW, requires_human=False)
    proposal = asyncio.run(execution.persist(proposal, NOW))
    asyncio.run(execution.dispatch(proposal, NOW))
    assert any(row["topic"] == "baggage.commands" for row in driver.db["outbox"].values())


def test_execution_log_survives_local_cache_loss(context):
    _, execution, _, _ = context
    proposal = asyncio.run(create(context, human=False))
    asyncio.run(execution.dispatch(proposal, NOW))
    asyncio.run(execution.receive_result("CommandExecuted", {
        "command_id": proposal.id, "command_type": "OpenSecurityLane"
    }, NOW, "passengers.events"))
    execution.approval_queue.clear()
    assert asyncio.run(execution.confirmed_log())[0]["proposal_id"] == proposal.id


def test_receipt_committed_before_dispatch_returns_confirmed_status(context):
    store, execution, _, driver = context
    proposal = asyncio.run(create(context, human=False))
    asyncio.run(execution.dispatch(proposal, NOW))
    # Another replica receives the owner result; this caller's cache is stale.
    asyncio.run(store.receipt("CommandExecuted", {
        "command_id": proposal.id, "command_type": "OpenSecurityLane"
    }, NOW, "passengers.events"))
    assert proposal.status == "dispatched"
    result = asyncio.run(execution.dispatch(proposal, NOW))
    assert result["executed"] is result["applied"] is True
    assert result["status"] == "executed"
    assert len(commands(driver)) == 1
