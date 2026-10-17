"""One execution path for operator, rule-based and approved actions."""

from datetime import datetime
from dataclasses import asdict

from db.neo4j import save_proposal

from _common.commands import action_command
from services import approval_queue


async def dispatch(proposal: approval_queue.Proposal, sim_time: datetime) -> dict:
    """Publish a concrete command; execution is confirmed separately by receipt."""
    from kafka.producer import emit_action_event, emit_domain_command

    intent = action_command(proposal.action_type, proposal.parameters)
    if intent is None:
        raise ValueError(
            "Action is advisory: no executable command with these parameters"
        )
    if proposal.status != approval_queue.APPROVED:
        raise ValueError("Proposal is not approved")
    approval_queue.mark_dispatched(proposal.id)
    proposal.dispatched_at = sim_time.isoformat()
    try:
        await save_proposal(asdict(proposal))
        await emit_domain_command(
            intent,
            command_id=proposal.id,
            issued_by=proposal.decided_by or proposal.proposed_by,
            issued_at=sim_time,
        )
    except Exception:
        # Keep the same command identity on retry; never claim execution.
        if proposal.status == approval_queue.DISPATCHED:
            proposal.status = approval_queue.APPROVED
            await save_proposal(asdict(proposal))
        raise
    emit_action_event("ActionDispatched", proposal.to_dict(), sim_time)
    return {
        "applied": False,
        "executed": False,
        "status": proposal.status,
        "proposal_id": proposal.id,
        "command_id": proposal.id,
        "command": intent.command_type,
    }


async def receive_result(
    event_type: str, payload: dict, sim_time: datetime, topic: str
) -> bool:
    """Accept receipts only from the command's owning domain topic."""
    from services.autonomous import record_proposal_execution

    proposal = approval_queue.get(payload.get("command_id", ""))
    if proposal is None or proposal.status != approval_queue.DISPATCHED:
        return False
    intent = action_command(proposal.action_type, proposal.parameters)
    if (
        intent is None
        or topic != intent.topic.replace(".commands", ".events")
        or payload.get("command_type") != intent.command_type
    ):
        return False
    if event_type == "CommandExecuted":
        document = asdict(proposal)
        document.update(
            status=approval_queue.EXECUTED, executed_at=sim_time.isoformat()
        )
        await save_proposal(document)
        approval_queue.mark_executed(proposal.id, sim_time)
        entry = record_proposal_execution(
            proposal.to_dict(),
            sim_time,
            decided_by=proposal.decided_by or proposal.proposed_by,
        )
        from kafka.producer import emit_autonomous_action

        emit_autonomous_action(entry, sim_time)
    elif event_type == "CommandRejected":
        reason = payload.get("reason") or "Command rejected"
        document = asdict(proposal)
        document.update(status=approval_queue.FAILED, failure_reason=reason)
        await save_proposal(document)
        approval_queue.mark_failed(proposal.id, reason)
        from kafka.producer import emit_action_event

        emit_action_event("ActionExecutionFailed", proposal.to_dict(), sim_time)
    else:
        return False
    return True
