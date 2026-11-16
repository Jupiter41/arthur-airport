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
import os
import time
from typing import Any, Callable, Protocol

# RC3: one drain loop moves up to this many facts per broker round trip. A
# baggage tick stages 600-700 facts, so the old 100-row batch needed 7+ loops
# (three Neo4j round trips + an acks=all wait each) to deliver a single tick.
DEFAULT_BATCH = max(1, int(os.getenv("OUTBOX_BATCH_SIZE", "1000")))
# After a wake-up, keep re-reading briefly: a writer may notify just before
# its transaction commits, and the rows only become visible after that.
_SETTLE_S = 0.25
_SETTLE_STEP_S = 0.02

_wakeups: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}


def _wakeup(label: str) -> asyncio.Event:
    """The wake-up event for ``label`` on the running loop (one per loop)."""
    loop = asyncio.get_running_loop()
    entry = _wakeups.get(label)
    if entry is None or entry[0] is not loop:
        entry = _wakeups[label] = (loop, asyncio.Event())
    return entry[1]


def notify(outbox_label: str) -> None:
    """Wake the delivery loop of ``outbox_label`` (facts were, or are being, staged).

    Safe to call before the staging transaction commits: the loop keeps polling
    for a short settle window after each wake-up. A no-op outside an event loop.
    """
    try:
        _wakeup(outbox_label).set()
    except RuntimeError:
        pass


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
        # seen_at (wall ms) lets retention prune markers past Kafka retention (RC1).
        f"MERGE (i:{label} {{id: $id}}) SET i.sim_time = $sim_time, "
        "i.seen_at = coalesce(i.seen_at, timestamp())",
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
    notify(label)


async def publish_pending(
    outbox_label: str,
    get_driver: Callable[[], Any],
    publish_confirmed: Callable[[dict], None],
    *,
    batch: int = DEFAULT_BATCH,
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


async def _delete_and_read(
    label: str, get_driver: Callable[[], Any], acked: list[str], batch: int,
) -> list[dict]:
    """Delete the previously acked rows and read the next batch in ONE query.

    The unit subquery keeps one row even when ``acked`` is empty, and rows
    deleted earlier in the same transaction are no longer matched.
    """
    async with get_driver().session() as session:
        result = await session.run(
            f"CALL {{ UNWIND $acked AS id MATCH (d:{label} {{id: id}}) DELETE d }} "
            f"MATCH (e:{label}) RETURN e.id AS id, e.document AS document "
            f"ORDER BY e.revision, e.position LIMIT $batch",
            acked=acked, batch=batch,
        )
        return await result.data()


async def run(
    outbox_label: str,
    get_driver: Callable[[], Any],
    publish_confirmed: Callable[[dict], None],
    stop: asyncio.Event,
    *,
    logger: Any | None = None,
    poll_interval_s: float = 1.0,
    publish_batch_confirmed: Callable[[list[dict]], None] | None = None,
    batch: int = DEFAULT_BATCH,
) -> None:
    """Background loop: drain the outbox, retaining anything not yet confirmed.

    Each iteration is one Neo4j query (delete the last acked batch + read the
    next) and one broker round trip. When the outbox is empty the loop sleeps
    until :func:`notify` wakes it (every tick commit does) or ``poll_interval_s``
    elapses, whichever is first. Acked-but-undeleted rows are at worst
    redelivered with the same ``event_id`` after a crash (at-least-once).
    """
    label = _check_label(outbox_label)
    wake = _wakeup(label)
    acked: list[str] = []
    settle_until = 0.0
    while not stop.is_set():
        # Clear before reading: a notify() landing after this read is then
        # still seen by the wait below instead of being lost.
        wake.clear()
        try:
            pending = await _delete_and_read(label, get_driver, acked, batch)
            acked = []
            if pending:
                documents = [json.loads(row["document"]) for row in pending]
                if publish_batch_confirmed is not None:
                    await asyncio.to_thread(publish_batch_confirmed, documents)
                else:
                    for document in documents:
                        await asyncio.to_thread(publish_confirmed, document)
                acked = [row["id"] for row in pending]
                continue
        except Exception:
            if logger is not None:
                logger.exception(f"outbox delivery unavailable; retaining {outbox_label} events")
            settle_until = 0.0
        if time.monotonic() < settle_until:
            await asyncio.sleep(_SETTLE_STEP_S)
            continue
        stop_wait = asyncio.ensure_future(stop.wait())
        wake_wait = asyncio.ensure_future(wake.wait())
        done, _ = await asyncio.wait(
            {stop_wait, wake_wait}, timeout=poll_interval_s,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for waiter in (stop_wait, wake_wait):
            if not waiter.done():
                waiter.cancel()
        if wake_wait in done:
            settle_until = time.monotonic() + _SETTLE_S
    if acked:
        try:
            await _delete_and_read(label, get_driver, acked, 0)
        except Exception:
            if logger is not None:
                logger.exception(f"could not delete acked {outbox_label} rows; they will be redelivered")


def transition_batch_facts(
    event_type: str, sim_time: Any, producer: str, payload: dict[str, list],
    *, grouped_ids: dict[str, str] | None = None, max_items: int = 500,
) -> list[dict]:
    """Bound audit packets by entity/update count, preserving every transition.

    ``grouped_ids`` identifies cohort lists such as status_groups[].ids. Cohorts
    are split by their member IDs rather than counted as a single item. Generated
    UUIDs/zone codes therefore stay well below Kafka's default message ceiling,
    even after a long catch-up tick. Parts share an audit batch identity.
    """
    from uuid import uuid4
    from _common.kafka_runtime import build_envelope
    if max_items < 1:
        raise ValueError("max_items must be positive")
    grouped_ids = grouped_ids or {}
    parts: list[dict] = []
    current_part = {key: [] for key in payload}
    remaining = max_items

    def flush() -> None:
        nonlocal current_part, remaining
        if any(current_part.values()):
            parts.append(current_part)
        current_part = {key: [] for key in payload}
        remaining = max_items

    for key, items in payload.items():
        member_key = grouped_ids.get(key)
        for item in items:
            if member_key:
                members = item[member_key]
                offset = 0
                while offset < len(members):
                    if remaining == 0:
                        flush()
                    count = min(remaining, len(members) - offset)
                    current_part[key].append({**item, member_key: members[offset:offset + count]})
                    remaining -= count
                    offset += count
            else:
                if remaining == 0:
                    flush()
                current_part[key].append(item)
                remaining -= 1
    flush()
    batch_id = str(uuid4())
    facts = []
    for index, part in enumerate(parts):
        document = build_envelope(event_type, sim_time, {
            **part, "batch_id": batch_id, "part": index, "part_count": len(parts),
        }, producer)
        facts.append({"id": document["event_id"], "document": document})
    return facts
