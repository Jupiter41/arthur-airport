"""Transactional proposal decisions, dispatch attempts, clock and event outbox."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Awaitable, Callable, TypeVar
from uuid import uuid4

from neo4j import AsyncManagedTransaction
from pydantic import BaseModel, Field, TypeAdapter

from _common.commands import action_command
from _common.events import EventEnvelope
from db.neo4j import get_driver
from services.approval_queue import Proposal

ACTIVE = {"pending", "approved", "dispatched"}
T = TypeVar("T")


class ActionClock(BaseModel):
    sim_time: datetime
    speed_multiplier: float = Field(1, gt=0)
    tick_number: int = Field(0, ge=0)
    day_of_sim: int = Field(1, ge=1)
    step_minutes: int = Field(1, gt=0)
    mode: str = "REALTIME"


def _key(document: dict) -> str:
    target = [document.get("bottleneck_id"), document["action_type"], document["parameters"]]
    return sha256(json.dumps(target, sort_keys=True, allow_nan=False).encode()).hexdigest()


async def _lock(tx: AsyncManagedTransaction) -> int:
    row = await (await tx.run(
        "MERGE (s:AnalysisRuntime {id: 'actions'}) "
        "SET s.revision = coalesce(s.revision, 0) + 1 RETURN s.revision AS revision",
    )).single()
    return row["revision"]


async def _transaction(callback: Callable[[AsyncManagedTransaction, int], Awaitable[T]]) -> T:
    async def apply(tx: AsyncManagedTransaction) -> T:
        return await callback(tx, await _lock(tx))

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def _get(tx: AsyncManagedTransaction, proposal_id: str) -> dict | None:
    row = await (await tx.run(
        "MATCH (p:ActionProposal {id: $id}) RETURN p.document AS document", id=proposal_id,
    )).single()
    return json.loads(row["document"]) if row else None


async def _save(tx: AsyncManagedTransaction, document: dict) -> None:
    await (await tx.run(
        "MERGE (p:ActionProposal {id: $id}) SET p.document = $document, p.status = $status, "
        "p.target_key = $key, p.recommendation_id = $recommendation_id",
        id=document["id"], document=json.dumps(document, allow_nan=False), status=document["status"],
        key=_key(document), recommendation_id=document.get("recommendation_id"),
    )).consume()


def _fact(kind: str, document: dict, clock: datetime) -> dict:
    payload = deepcopy(document)
    payload.pop("emitted", None)
    return {"topic": "analysis.events", "key": document["id"],
            "envelope": EventEnvelope.build(kind, clock, "analysis-service", payload).model_dump(mode="json")}


async def _outbox(tx: AsyncManagedTransaction, revision: int, messages: list[dict]) -> None:
    await (await tx.run(
        "UNWIND $rows AS row CREATE (e:AnalysisOutbox) SET e = row",
        rows=[{"id": str(uuid4()), "revision": revision, "position": n, "topic": row["topic"],
               "key": row["key"], "document": json.dumps(row["envelope"], allow_nan=False)}
              for n, row in enumerate(messages)],
    )).consume()


async def initialize() -> None:
    async with get_driver().session() as session:
        for query in (
            "CREATE CONSTRAINT actionproposal_id IF NOT EXISTS FOR (p:ActionProposal) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT analysis_runtime_id IF NOT EXISTS FOR (s:AnalysisRuntime) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT analysis_outbox_id IF NOT EXISTS FOR (e:AnalysisOutbox) REQUIRE e.id IS UNIQUE",
            "CREATE INDEX analysis_outbox_order IF NOT EXISTS FOR (e:AnalysisOutbox) ON (e.revision, e.position)",
        ):
            await (await session.run(query)).consume()

    async def migrate(tx: AsyncManagedTransaction, revision: int) -> None:
        result = await tx.run("MATCH (p:ActionProposal) RETURN p.document AS document")
        for row in await result.data():
            await _save(tx, asdict(TypeAdapter(Proposal).validate_python(json.loads(row["document"]))))

    await _transaction(migrate)


async def list_documents() -> list[dict]:
    async with get_driver().session() as session:
        result = await session.run("MATCH (p:ActionProposal) RETURN p.document AS document")
        return [json.loads(row["document"]) async for row in result]


async def get_document(proposal_id: str) -> dict | None:
    async with get_driver().session() as session:
        return await _get(session, proposal_id)


async def create(document: dict, clock: datetime) -> dict:
    document = asdict(TypeAdapter(Proposal).validate_python(deepcopy(document)))
    if document["status"] not in {"pending", "approved"}:
        raise ValueError("New proposals must be pending or approved")
    document["emitted"] = True

    async def apply(tx: AsyncManagedTransaction, revision: int) -> dict:
        existing = await _get(tx, document["id"])
        if existing:
            if not existing.get("emitted"):
                existing.update(emitted=True, revision=revision)
                await _save(tx, existing)
                await _outbox(tx, revision, [_fact("ActionProposed", existing, clock)])
            return existing
        duplicate = await (await tx.run(
            "MATCH (p:ActionProposal) WHERE (p.target_key = $key AND p.status IN $active) "
            "OR ($recommendation_id IS NOT NULL AND p.recommendation_id = $recommendation_id "
            "AND NOT p.status IN ['failed', 'rejected']) RETURN p.document AS document LIMIT 1",
            key=_key(document), active=sorted(ACTIVE), recommendation_id=document.get("recommendation_id"),
        )).single()
        if duplicate:
            return json.loads(duplicate["document"])
        document["revision"] = revision
        await _save(tx, document)
        await _outbox(tx, revision, [_fact("ActionProposed", document, clock)])
        return document

    return await _transaction(apply)


def _due(document: dict, clock: datetime) -> bool:
    raw = document.get("dispatched_at")
    if not raw:
        return True
    previous = datetime.fromisoformat(raw)
    current = clock.replace(tzinfo=clock.tzinfo or timezone.utc)
    previous = previous.replace(tzinfo=previous.tzinfo or timezone.utc)
    return (current - previous).total_seconds() >= 300


async def dispatch(proposal_id: str, clock: datetime, *, approve_by: str | None = None) -> dict | None:
    async def apply(tx: AsyncManagedTransaction, revision: int) -> dict | None:
        document = await _get(tx, proposal_id)
        if document is None or document["status"] not in ACTIVE:
            return None
        document["revision"] = revision
        messages = []
        intent = action_command(document["action_type"], document["parameters"])
        if intent is None:
            raise ValueError("Action is advisory: no executable command with these parameters")
        if document["status"] == "pending":
            if approve_by is None:
                return None
            document.update(status="approved", decided_by=approve_by, decided_at=clock.isoformat())
            messages.append(_fact("ActionApproved", document, clock))
        elif document["status"] == "dispatched" and not _due(document, clock):
            return document
        document.update(status="dispatched", command_id=document["id"], dispatched_at=clock.isoformat(),
                        dispatch_attempts=document.get("dispatch_attempts", 0) + 1)
        messages.extend([{"topic": intent.topic, "key": intent.entity_key, "envelope": {
            "command_type": intent.command_type, "command_id": document["id"], "schema_version": "1.0",
            "issued_by": document.get("decided_by") or document["proposed_by"],
            "issued_at": clock.isoformat(), "producer": "analysis-service", "payload": intent.payload,
        }}, _fact("ActionDispatched", document, clock)])
        document["revision"] = revision
        await _save(tx, document)
        await _outbox(tx, revision, messages)
        return document

    return await _transaction(apply)


async def reject(proposal_id: str, clock: datetime, decided_by: str, reason: str) -> dict | None:
    async def apply(tx: AsyncManagedTransaction, revision: int) -> dict | None:
        document = await _get(tx, proposal_id)
        if not document or document["status"] != "pending":
            return None
        document.update(status="rejected", decided_by=decided_by, decided_at=clock.isoformat(), reject_reason=reason)
        document["revision"] = revision
        await _save(tx, document)
        await _outbox(tx, revision, [_fact("ActionRejected", document, clock)])
        return document

    return await _transaction(apply)


async def fail(proposal_id: str, clock: datetime, reason: str) -> dict | None:
    async def apply(tx: AsyncManagedTransaction, revision: int) -> dict | None:
        document = await _get(tx, proposal_id)
        if not document or document["status"] != "approved":
            return None
        document.update(status="failed", failure_reason=reason)
        document["revision"] = revision
        await _save(tx, document)
        await _outbox(tx, revision, [_fact("ActionExecutionFailed", document, clock)])
        return document

    return await _transaction(apply)


async def receipt(kind: str, payload: dict, clock: datetime, topic: str) -> dict | None:
    async def apply(tx: AsyncManagedTransaction, revision: int) -> dict | None:
        document = await _get(tx, payload.get("command_id", ""))
        if not document or document["status"] != "dispatched":
            return None
        intent = action_command(document["action_type"], document["parameters"])
        if (intent is None or topic != intent.topic.replace(".commands", ".events")
                or payload.get("command_type") != intent.command_type):
            return None
        document["revision"] = revision
        if kind == "CommandExecuted":
            from services.autonomous import execution_entry

            document.update(status="executed", executed_at=clock.isoformat())
            fact = _fact("AutonomousActionApplied", execution_entry(document, clock), clock)
        elif kind == "CommandRejected":
            document.update(status="failed", failure_reason=payload.get("reason") or "Command rejected")
            fact = _fact("ActionExecutionFailed", document, clock)
        else:
            return None
        document["revision"] = revision
        await _save(tx, document)
        await _outbox(tx, revision, [fact])
        return document

    return await _transaction(apply)


async def save_clock(payload: dict, position: tuple[int, int]) -> bool:
    if position[0] != 0 or position[1] < 0:
        raise ValueError("sim.clock requires partition zero and a valid broker offset")
    tick = ActionClock.model_validate(payload).model_dump(mode="json")

    async def apply(tx: AsyncManagedTransaction, revision: int) -> bool:
        row = await (await tx.run(
            "MATCH (s:AnalysisRuntime {id: 'actions'}) RETURN s.clock_offset AS offset",
        )).single()
        if row and row["offset"] is not None and position[1] <= row["offset"]:
            return False
        await (await tx.run(
            "MATCH (s:AnalysisRuntime {id: 'actions'}) SET s.clock = $clock, "
            "s.clock_partition = $partition, s.clock_offset = $offset",
            clock=json.dumps(tick, allow_nan=False), partition=position[0], offset=position[1],
        )).consume()
        return True

    return await _transaction(apply)


async def load_clock() -> dict | None:
    async with get_driver().session() as session:
        row = await (await session.run("MATCH (s:AnalysisRuntime {id: 'actions'}) RETURN s.clock AS clock")).single()
    return json.loads(row["clock"]) if row and row["clock"] else None
