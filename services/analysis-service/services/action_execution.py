"""Cache adapters over the authoritative transactional proposal store."""

from dataclasses import asdict
from datetime import datetime

from _common.commands import action_command
from services import approval_queue, proposal_store


async def refresh() -> list[approval_queue.Proposal]:
    return [approval_queue.cache(document) for document in await proposal_store.list_documents()]


async def persist(proposal: approval_queue.Proposal, clock: datetime) -> approval_queue.Proposal:
    document = await proposal_store.create(asdict(proposal), clock)
    if document["id"] != proposal.id:
        approval_queue.discard(proposal.id)
    return approval_queue.cache(document)


async def dispatch(proposal: approval_queue.Proposal, sim_time: datetime, *, approve_by: str | None = None) -> dict:
    document = await proposal_store.dispatch(proposal.id, sim_time, approve_by=approve_by)
    if document is None:
        # A receipt may commit between the caller's snapshot and dispatch.
        # Report that committed result without authorizing another command.
        document = await proposal_store.get_document(proposal.id)
        if document is None or document["status"] != approval_queue.EXECUTED:
            raise ValueError("Proposal is not approved or retryable")
    confirmed = approval_queue.cache(document)
    intent = action_command(confirmed.action_type, confirmed.parameters)
    return {"applied": confirmed.status == approval_queue.EXECUTED,
            "executed": confirmed.status == approval_queue.EXECUTED, "status": confirmed.status,
            "proposal_id": confirmed.id, "command_id": confirmed.id, "command": intent.command_type}


async def receive_result(event_type: str, payload: dict, sim_time: datetime, topic: str) -> bool:
    from services.autonomous import record_proposal_execution

    document = await proposal_store.receipt(event_type, payload, sim_time, topic)
    if document is None:
        return False
    proposal = approval_queue.cache(document)
    if event_type == "CommandExecuted":
        record_proposal_execution(proposal.to_dict(), sim_time, decided_by=proposal.decided_by or proposal.proposed_by)
    return True


async def confirmed_log() -> list[dict]:
    from services.autonomous import execution_entry

    return [execution_entry(document, datetime.fromisoformat(document["executed_at"]))
            for document in await proposal_store.list_documents()
            if document["status"] == "executed" and document.get("executed_at")]


async def clock() -> datetime | None:
    payload = await proposal_store.load_clock()
    return datetime.fromisoformat(payload["sim_time"]) if payload else None
