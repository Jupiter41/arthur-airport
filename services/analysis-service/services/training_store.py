"""Durable training runs: Neo4j records, renewable leases and fenced writes (G7).

Each ``TrainingRun`` node stores the complete run document plus a lease token
and expiry. Every mutation first locks the shared ``AnalysisRuntime
{id: 'training'}`` node, so claims and fenced writes serialize across service
replicas. Lease times use Neo4j ``timestamp()`` only as scheduling metadata —
training is not simulation business logic and never reads ``sim_time``.

A run is recoverable when it is ``queued`` (created, or released by a graceful
shutdown) or ``running`` with an expired lease (its owner exited abruptly). At
most one run may hold an unexpired lease at a time.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, TypeVar

from neo4j import AsyncManagedTransaction

from db.neo4j import get_driver

T = TypeVar("T")
TERMINAL = frozenset({"completed", "failed", "stopped"})


class ActiveRunExists(ValueError):
    pass


def claimable(status: str, lease_until: int, now: int) -> bool:
    """Pure claim rule shared by the store and its unit tests."""
    return status == "queued" or (status == "running" and lease_until <= now)


async def _transaction(callback: Callable[[AsyncManagedTransaction, int], Awaitable[T]]) -> T:
    async def apply(tx: AsyncManagedTransaction) -> T:
        row = await (await tx.run(
            "MERGE (s:AnalysisRuntime {id: 'training'}) "
            "SET s.revision = coalesce(s.revision, 0) + 1 RETURN timestamp() AS now",
        )).single()
        return await callback(tx, row["now"])

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def _active_owner(tx: AsyncManagedTransaction, now: int, exclude: str | None = None) -> str | None:
    row = await (await tx.run(
        "MATCH (r:TrainingRun) WHERE r.status = 'running' AND coalesce(r.lease_until, 0) > $now "
        "AND ($exclude IS NULL OR r.id <> $exclude) RETURN r.id AS id LIMIT 1",
        now=now, exclude=exclude,
    )).single()
    return row["id"] if row else None


async def _save(tx: AsyncManagedTransaction, document: dict) -> None:
    await (await tx.run(
        "MATCH (r:TrainingRun {id: $id}) SET r.document = $document, r.status = $status",
        id=document["id"], document=json.dumps(document, allow_nan=False), status=document["status"],
    )).consume()


async def _owned(tx: AsyncManagedTransaction, run_id: str, token: str, now: int) -> dict | None:
    row = await (await tx.run(
        "MATCH (r:TrainingRun {id: $id}) RETURN r.document AS document, r.lease_token AS token, "
        "coalesce(r.lease_until, 0) AS until", id=run_id,
    )).single()
    if not row or row["token"] != token or row["until"] <= now:
        return None
    document = json.loads(row["document"])
    return document if document["status"] == "running" else None


async def initialize() -> None:
    async with get_driver().session() as session:
        for query in (
            "CREATE CONSTRAINT trainingrun_id IF NOT EXISTS FOR (r:TrainingRun) REQUIRE r.id IS UNIQUE",
            "CREATE INDEX trainingrun_status IF NOT EXISTS FOR (r:TrainingRun) ON (r.status)",
        ):
            await (await session.run(query)).consume()


async def create(document: dict) -> dict:
    """Persist a new queued run; refuses while another run holds a live lease."""
    if document.get("status") != "queued":
        raise ValueError("New training runs must be queued")

    async def apply(tx: AsyncManagedTransaction, now: int) -> dict:
        owner = await _active_owner(tx, now)
        if owner:
            raise ActiveRunExists(f"Training run {owner} is already in progress")
        stored = dict(document, created_ms=now)
        await (await tx.run(
            "CREATE (r:TrainingRun {id: $id, created_ms: $now, lease_until: 0})", id=stored["id"], now=now,
        )).consume()
        await _save(tx, stored)
        return stored

    return await _transaction(apply)


async def claim(token: str, ttl_seconds: float, run_id: str | None = None) -> dict | None:
    """Take the lease of one recoverable run (oldest first), incrementing its attempt."""
    from datetime import datetime, timezone

    # Cheap read before the serializing write transaction: the recovery loop
    # polls continuously and normally finds nothing to claim.
    async with get_driver().session() as session:
        row = await (await session.run(
            "MATCH (r:TrainingRun) WHERE ($id IS NULL OR r.id = $id) "
            "AND r.status IN ['queued', 'running'] RETURN count(r) AS candidates", id=run_id,
        )).single()
    if not row or not row["candidates"]:
        return None

    async def apply(tx: AsyncManagedTransaction, now: int) -> dict | None:
        rows = await (await tx.run(
            "MATCH (r:TrainingRun) WHERE ($id IS NULL OR r.id = $id) AND r.status IN ['queued', 'running'] "
            "RETURN r.id AS id, r.document AS document, r.lease_token AS token, "
            "coalesce(r.lease_until, 0) AS until ORDER BY r.created_ms, r.id",
            id=run_id,
        )).data()
        for row in rows:
            document = json.loads(row["document"])
            if row["token"] == token and document["status"] == "running" and row["until"] > now:
                return document  # Managed-transaction retry after an ambiguous commit.
            if not claimable(document["status"], row["until"], now):
                continue
            if await _active_owner(tx, now, exclude=row["id"]):
                return None
            document.update(status="running", error=None, completed_at=None,
                            attempt_count=int(document.get("attempt_count", 0)) + 1,
                            started_at=datetime.fromtimestamp(now / 1000, timezone.utc).isoformat())
            await _save(tx, document)
            await (await tx.run(
                "MATCH (r:TrainingRun {id: $id}) SET r.lease_token = $token, r.lease_until = $until",
                id=row["id"], token=token, until=now + int(ttl_seconds * 1000),
            )).consume()
            return document
        return None

    return await _transaction(apply)


async def save(document: dict, token: str, ttl_seconds: float) -> bool:
    """Fenced progress write that also renews the lease. False = ownership lost."""
    async def apply(tx: AsyncManagedTransaction, now: int) -> bool:
        if document.get("status") != "running" or await _owned(tx, document["id"], token, now) is None:
            return False
        await _save(tx, document)
        await (await tx.run("MATCH (r:TrainingRun {id: $id}) SET r.lease_until = $until",
                            id=document["id"], until=now + int(ttl_seconds * 1000))).consume()
        return True

    return await _transaction(apply)


async def renew(run_id: str, token: str, ttl_seconds: float) -> bool:
    async def apply(tx: AsyncManagedTransaction, now: int) -> bool:
        if await _owned(tx, run_id, token, now) is None:
            return False
        await (await tx.run("MATCH (r:TrainingRun {id: $id}) SET r.lease_until = $until",
                            id=run_id, until=now + int(ttl_seconds * 1000))).consume()
        return True

    return await _transaction(apply)


async def finish(document: dict, token: str) -> bool:
    """Fenced terminal transition (completed / failed / stopped)."""
    if document.get("status") not in TERMINAL:
        raise ValueError("Finish requires a terminal status")

    async def apply(tx: AsyncManagedTransaction, now: int) -> bool:
        if await _owned(tx, document["id"], token, now) is None:
            return False
        await _save(tx, document)
        await (await tx.run("MATCH (r:TrainingRun {id: $id}) REMOVE r.lease_token SET r.lease_until = 0",
                            id=document["id"])).consume()
        return True

    return await _transaction(apply)


async def release(document: dict, token: str) -> bool:
    """Graceful shutdown: return an owned run to the queue for the next worker."""
    async def apply(tx: AsyncManagedTransaction, now: int) -> bool:
        if await _owned(tx, document["id"], token, now) is None:
            return False
        await _save(tx, dict(document, status="queued"))
        await (await tx.run("MATCH (r:TrainingRun {id: $id}) REMOVE r.lease_token SET r.lease_until = 0",
                            id=document["id"])).consume()
        return True

    return await _transaction(apply)


async def list_recent(limit: int = 20) -> list[dict]:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (r:TrainingRun) RETURN r.document AS document ORDER BY r.created_ms DESC, r.id DESC LIMIT $limit",
            limit=limit,
        )
        return [json.loads(row["document"]) async for row in result]
