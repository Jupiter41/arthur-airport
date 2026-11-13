"""Generic transactional outbox + persistent inbox (shared A20 pattern).

Lets an owning service make *domain write + fact delivery* atomic: inside one
managed Neo4j transaction the caller writes its domain records, a persistent
inbox marker (for durable, restart-surviving idempotency) and one outbox row
per fact to publish. A background task then delivers each outbox fact to Kafka
with a stable ``event_id`` and deletes the row only after broker confirmation —
so a crash between commit and publish still delivers (at-least-once), and a
Kafka redelivery of the *input* is deduped by the persistent inbox.

This mirrors cost-service's ``services/outbox.py`` + ``services/ledger.py``
(A20) and planning-service's ``db/outbox.py`` (A21), parameterized by node
label so flight / passenger / baggage owners share one implementation instead
of hand-rolling a copy each.

Schema per owner (constraints are the owner's to create)::

    (:<Inbox>  {id, sim_time})           id UNIQUE
    (:<Outbox> {id, document, revision, position})  id UNIQUE, INDEX(revision, position)

Write side — call these *inside* ``session.execute_write(...)``::

    if await inbox_seen(tx, "FlightInbox", envelope["event_id"]):
        return  # durable dedup: already processed, do not re-apply or re-emit
    ...                                    # the caller's domain writes
    await mark_inbox(tx, "FlightInbox", envelope["event_id"], sim_time)
    await stage_outbox(tx, "FlightOutbox", facts, revision)   # facts: [{"id","document"}]

Delivery side — run one task per owner from the service's lifespan::

    stop = asyncio.Event()
    task = asyncio.create_task(run("FlightOutbox", get_driver, publish_confirmed, stop))

``publish_confirmed(document: dict) -> None`` must raise if the broker does not
acknowledge, so an unconfirmed fact is retained rather than dropped.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Protocol


class _Tx(Protocol):  # minimal structural type for an async managed transaction
    def run(self, query: str, **params: Any) -> Any: ...


def _check_label(label: str) -> str:
    """Guard against query injection: labels are hardcoded constants, never input."""
    if not label.isidentifier():
        raise ValueError(f"invalid Neo4j label: {label!r}")
    return label


async def inbox_seen(tx: _Tx, inbox_label: str, event_id: str) -> bool:
    """True if ``event_id`` was already committed by this owner (durable dedup).

    Empty ids are never considered seen (they carry no identity to dedup on).
    """
    if not event_id:
        return False
    label = _check_label(inbox_label)
    result = await tx.run(
        f"MERGE (i:{label} {{id: $id}}) "
        "SET i.lock = coalesce(i.lock, 0) + 1 "
        "WITH i WHERE i.sim_time IS NOT NULL RETURN i.id AS id", id=event_id
    )
    return (await result.single()) is not None


async def mark_inbox(tx: _Tx, inbox_label: str, event_id: str, sim_time: Any) -> None:
    """Record ``event_id`` as processed in the same transaction as the domain write."""
    if not event_id:
        return
    label = _check_label(inbox_label)
    result = await tx.run(
        f"MERGE (i:{label} {{id: $id}}) SET i.sim_time = $sim_time",
        id=event_id,
        sim_time=sim_time,
    )
    await result.consume()


async def stage_outbox(
    tx: _Tx, outbox_label: str, facts: list[dict], revision: int
) -> None:
    """Persist facts to deliver, in the caller's transaction.

    ``facts`` is a list of ``{"id": <stable event_id>, "document": <fact dict>}``.
    ``revision`` + per-fact position give a deterministic delivery order. The
    stable ``id`` is retained until broker ack, so redelivery keeps the same
    event_id (at-least-once with stable IDs, not exactly-once).
    """
    from _common.transaction_scope import current
    scope = current.get()
    if scope is not None and not scope.flushing:
        scope.facts.extend(facts)
        return
    if not facts:
        return
    label = _check_label(outbox_label)
    rows = [
        {
            "id": fact["id"],
            "document": json.dumps(fact["document"]),
            "position": position,
        }
        for position, fact in enumerate(facts)
    ]
    result = await tx.run(
        f"UNWIND $rows AS row "
        f"CREATE (e:{label} {{id: row.id, document: row.document, "
        f"revision: $revision, position: row.position}})",
        rows=rows,
        revision=revision,
    )
    await result.consume()


async def publish_pending(
    outbox_label: str,
    get_driver: Callable[[], Any],
    publish_confirmed: Callable[[dict], None],
    *,
    batch: int = 100,
    publish_batch_confirmed: Callable[[list[dict]], None] | None = None,
) -> int:
    """Deliver up to ``batch`` pending facts in order; delete each only on ack.

    ``publish_confirmed`` is a blocking producer call (run off-loop); it must
    raise on non-delivery so the row is retained. Returns the count delivered.
    """
    label = _check_label(outbox_label)
    async with get_driver().session() as session:
        result = await session.run(
            f"MATCH (e:{label}) RETURN e.id AS id, e.document AS document "
            f"ORDER BY e.revision, e.position LIMIT $batch",
            batch=batch,
        )
        pending = await result.data()
    if pending and publish_batch_confirmed is not None:
        await asyncio.to_thread(
            publish_batch_confirmed, [json.loads(row["document"]) for row in pending],
        )
        async with get_driver().session() as session:
            result = await session.run(
                f"UNWIND $ids AS id MATCH (e:{label} {{id: id}}) DELETE e",
                ids=[row["id"] for row in pending],
            )
            await result.consume()
        return len(pending)
    count = 0
    for row in pending:
        await asyncio.to_thread(publish_confirmed, json.loads(row["document"]))
        async with get_driver().session() as session:
            result = await session.run(
                f"MATCH (e:{label} {{id: $id}}) DELETE e", id=row["id"]
            )
            await result.consume()
        count += 1
    return count


async def run(
    outbox_label: str,
    get_driver: Callable[[], Any],
    publish_confirmed: Callable[[dict], None],
    stop: asyncio.Event,
    *,
    logger: Any | None = None,
    poll_interval_s: float = 1.0,
    publish_batch_confirmed: Callable[[list[dict]], None] | None = None,
) -> None:
    """Background loop: drain the outbox, retaining anything not yet confirmed."""
    while not stop.is_set():
        try:
            count = await publish_pending(
                outbox_label, get_driver, publish_confirmed,
                publish_batch_confirmed=publish_batch_confirmed,
            )
            if count:
                continue
        except Exception:
            if logger is not None:
                logger.exception(f"outbox delivery unavailable; retaining {outbox_label} events")
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_s)
        except asyncio.TimeoutError:
            pass
