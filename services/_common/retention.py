"""Lifecycle retention for the live operational graph (RC1).

The hot path queries the live labels (``Passenger``, ``Baggage``, ``ScanEvent``)
and their status indexes. Before this module nothing ever left them, so per-tick
cost grew linearly with simulated days. Each owner now runs a background sweep,
off the tick path, in bounded transactions:

1. **Archive** finished entities once they are ``RETENTION_ARCHIVE_AFTER_H``
   simulated hours past their terminal transition: the live label is swapped for
   an archive label (``PassengerArchive``, ``BaggageArchive``,
   ``ScanEventArchive``). Properties and relationships are kept, so per-flight
   history counts still work, but the nodes leave every live index.
2. **Purge** archived entities ``RETENTION_PURGE_AFTER_H`` simulated hours after
   archival (``DETACH DELETE``), which bounds disk use. ``0`` keeps archives.
3. **Prune inbox markers** older than ``INBOX_RETENTION_H`` *wall-clock* hours.
   Kafka keeps input for 168 h (topic retention), so no redelivery can be older;
   the marker is pure transport metadata and is stamped with Neo4j's
   ``timestamp()`` when first written.

Archive and purge batches stage an ``EntitiesArchived`` / ``EntitiesPurged``
fact in the same transaction (rule 4: no silent mutation). Cutoffs derive from
the owner's simulation clock (rule 2); only the sweep cadence and the inbox
marker age use wall time.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

ARCHIVE_AFTER_H = float(os.getenv("RETENTION_ARCHIVE_AFTER_H", "24"))
PURGE_AFTER_H = float(os.getenv("RETENTION_PURGE_AFTER_H", "168"))
INBOX_RETENTION_H = float(os.getenv("INBOX_RETENTION_H", "168"))
BATCH = max(1, int(os.getenv("RETENTION_BATCH", "1000")))
INTERVAL_S = float(os.getenv("RETENTION_INTERVAL_S", "60"))
# Upper bound on batches per task per pass, so a large backlog is worked off
# over several passes instead of monopolising Neo4j.
MAX_BATCHES_PER_PASS = max(1, int(os.getenv("RETENTION_MAX_BATCHES_PER_PASS", "50")))
# Pause between two batches of the same pass (yields Neo4j to the tick path):
# at least PAUSE_S, and at least PACE x the batch's own duration, so a backlog
# drain uses at most 1/(1+PACE) of the time the sweep could take.
PAUSE_S = float(os.getenv("RETENTION_PAUSE_S", "0.05"))
PACE = float(os.getenv("RETENTION_PACE", "1.0"))
# Retention facts do not take the owner's outbox revision lock (that would
# serialise every sweep with the tick). Revision 0 sorts them ahead of pending
# tick facts; they describe entities finished hours ago, so order is moot.
FACT_REVISION = 0
ENABLED = os.getenv("RETENTION_ENABLED", "true").lower() != "false"


def _check_label(label: str) -> str:
    if not label.isidentifier():
        raise ValueError(f"invalid Neo4j label: {label!r}")
    return label


def cutoffs(sim_time: datetime | None) -> tuple[str | None, str | None]:
    """``(archive_before, purge_before)`` as naive ISO strings, or None if disabled.

    Owner timestamps are naive ISO strings, so lexical comparison is ordering.
    """
    if sim_time is None:
        return None, None
    now = sim_time.replace(tzinfo=None)
    archive_before = (now - timedelta(hours=ARCHIVE_AFTER_H)).isoformat() if ARCHIVE_AFTER_H > 0 else None
    purge_before = (now - timedelta(hours=PURGE_AFTER_H)).isoformat() if PURGE_AFTER_H > 0 else None
    return archive_before, purge_before


def archived_fact(entity: str, ids: list[str], archive_before: str, sim_time: datetime,
                  producer: str) -> dict:
    from _common.kafka_runtime import build_envelope
    document = build_envelope("EntitiesArchived", sim_time, {
        "entity": entity, "ids": ids, "count": len(ids), "archive_before": archive_before,
    }, producer)
    return {"id": document["event_id"], "document": document}


def purged_fact(entity: str, count: int, purge_before: str, sim_time: datetime,
                producer: str) -> dict:
    from _common.kafka_runtime import build_envelope
    document = build_envelope("EntitiesPurged", sim_time, {
        "entity": entity, "count": count, "purge_before": purge_before,
    }, producer)
    return {"id": document["event_id"], "document": document}


def inbox_indexes(label: str) -> list[str]:
    label = _check_label(label)
    return [f"CREATE INDEX {label.lower()}_seen_at IF NOT EXISTS FOR (i:{label}) ON (i.seen_at)"]


async def backfill_inbox_seen_at(get_driver: Callable[[], Any], label: str) -> None:
    """Stamp legacy markers (written before RC1) so they age out like new ones."""
    label = _check_label(label)
    async with get_driver().session() as session:
        await (await session.run(
            f"MATCH (i:{label}) WHERE i.seen_at IS NULL "
            "CALL { WITH i SET i.seen_at = timestamp() } IN TRANSACTIONS OF 10000 ROWS",
        )).consume()


async def prune_inbox(get_driver: Callable[[], Any], label: str, *,
                      retention_h: float | None = None, batch: int | None = None) -> int:
    """Delete one batch of inbox markers older than the Kafka retention window."""
    label = _check_label(label)
    retention_h = INBOX_RETENTION_H if retention_h is None else retention_h
    if retention_h <= 0:
        return 0
    async with get_driver().session() as session:
        row = await (await session.run(
            f"MATCH (i:{label}) WHERE i.seen_at < timestamp() - $age_ms "
            "WITH i LIMIT $batch DETACH DELETE i RETURN count(*) AS n",
            age_ms=int(retention_h * 3_600_000), batch=batch or BATCH,
        )).single()
    return int(row["n"]) if row else 0


Task = Callable[[], Awaitable[int]]


async def run_pass(tasks: list[Task], *, batch: int | None = None,
                   max_batches: int | None = None, pause_s: float | None = None,
                   logger: Any | None = None) -> dict[str, int]:
    """Run every task until it returns fewer than ``batch`` rows (or the budget ends)."""
    batch = batch or BATCH
    max_batches = max_batches or MAX_BATCHES_PER_PASS
    pause_s = PAUSE_S if pause_s is None else pause_s
    totals: dict[str, int] = {}
    for task in tasks:
        name = getattr(task, "__name__", repr(task))
        done = 0
        for _ in range(max_batches):
            started = time.monotonic()
            try:
                count = await task()
            except Exception:
                if logger is not None:
                    logger.exception(f"retention task {name} failed; retrying next pass")
                break
            done += count
            if count < batch:
                break
            await asyncio.sleep(max(pause_s, PACE * (time.monotonic() - started)))
        totals[name] = done
    return totals


async def run(stop: asyncio.Event, tasks: list[Task], *, interval_s: float | None = None,
              logger: Any | None = None, setup: Callable[[], Awaitable[None]] | None = None) -> None:
    """Background loop: one retention pass every ``interval_s`` until ``stop``."""
    if not ENABLED:
        return
    interval_s = INTERVAL_S if interval_s is None else interval_s
    if setup is not None:
        try:
            await setup()
        except Exception:
            if logger is not None:
                logger.exception("retention setup failed; continuing with sweeps")
    while not stop.is_set():
        totals = await run_pass(tasks, logger=logger)
        if logger is not None and any(totals.values()):
            logger.info(f"retention pass: {totals}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass
