"""Baggage lifecycle retention (RC1): archive finished bags, purge old archives.

Finished bags are ``collected`` (arrival), ``short_shipped`` (left behind at
departure, RC6) and ``in_hold`` on a *departure* flight (the hold left with the
aircraft). ``in_hold`` bags of an arrival flight
are still waiting for the belt — even stale ones (see DATA_FLOW_REVIEW RC8) stay
live, so they remain visible as the anomaly they are.

Archival swaps ``Baggage`` → ``BaggageArchive`` and each trail ``ScanEvent`` →
``ScanEventArchive`` (also dropping the derived ``UnscannedBaggage`` /
``ReviewBaggage`` memberships); relationships are kept. See
``_common/retention.py`` for cadence, cutoffs and the inbox rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from _common import outbox, retention
from db.neo4j import get_driver

PRODUCER = "baggage-service"

_ARCHIVE_QUERY = """
UNWIND $ids AS id
MATCH (b:Baggage {id: id})
OPTIONAL MATCH (b)-[:SCANNED_AT]->(s:ScanEvent)
WITH b, collect(s) AS scans
REMOVE b:Baggage:UnscannedBaggage:ReviewBaggage
SET b:BaggageArchive, b.archived_at = $at
FOREACH (s IN scans | REMOVE s:ScanEvent SET s:ScanEventArchive)
"""


async def _archive_tx(tx, ids: list[str], archive_before: str, sim_time: datetime) -> None:
    if not ids:
        return
    await (await tx.run(_ARCHIVE_QUERY, ids=ids, at=sim_time.isoformat())).consume()
    await outbox.stage_outbox(tx, "BaggageOutbox", [
        retention.archived_fact("Baggage", ids, archive_before, sim_time, PRODUCER),
    ], retention.FACT_REVISION)


TERMINAL_STATUSES = ("collected", "short_shipped")


async def archive_collected(
    archive_before: str, sim_time: datetime, batch: int, status: str = "collected"
) -> int:
    """Archive one batch of bags in terminal ``status`` scanned before ``archive_before``."""
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"not a terminal baggage status: {status}")

    async def apply(tx) -> int:
        rows = await (await tx.run(
            # Pinned: the plain status index would filter every live terminal bag.
            "MATCH (b:Baggage) USING INDEX b:Baggage(status, last_scan_at, id) "
            f"WHERE b.status = '{status}' AND b.last_scan_at < $before AND b.id IS NOT NULL "
            "WITH b LIMIT $batch RETURN b.id AS id",
            before=archive_before, batch=batch,
        )).data()
        ids = [row["id"] for row in rows]
        await _archive_tx(tx, ids, archive_before, sim_time)
        return len(ids)

    async with get_driver().session() as session:
        return await session.execute_write(apply)


_HOLD_RETURN = (
    "RETURN b.id AS id, b.last_scan_at AS at, "
    "EXISTS { (b)-[:LOADED_ON]->(:Flight {direction: 'departure'}) } AS departed"
)


class HoldSweep:
    """Archive departed ``in_hold`` bags, walking ``(last_scan_at, id)`` keyset order.

    Arrival ``in_hold`` bags match the index range but are not finished. The
    cursor steps past them, so each pass examines every candidate once instead
    of rescanning the same non-archivable rows in every batch.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.ts, self.id = "", ""

    async def step(self, archive_before: str, sim_time: datetime, batch: int) -> int:
        """Examine one batch; returns rows examined (< batch ⇒ pass complete)."""
        async def apply(tx) -> list[dict]:
            # Two index-ordered seeks instead of one OR predicate: the OR was
            # planned as a union + sort over every in_hold bag (5.7M db hits).
            # The full-key ORDER BY + hint lets the composite index supply order.
            rows: list[dict] = []
            if self.ts:
                rows = await (await tx.run(
                    "MATCH (b:Baggage) USING INDEX b:Baggage(status, last_scan_at, id) "
                    "WHERE b.status = 'in_hold' AND b.last_scan_at = $ts AND b.id > $id "
                    "WITH b ORDER BY b.status, b.last_scan_at, b.id LIMIT $batch "
                    + _HOLD_RETURN, ts=self.ts, id=self.id, batch=batch,
                )).data()
            if len(rows) < batch:
                rows += await (await tx.run(
                    "MATCH (b:Baggage) USING INDEX b:Baggage(status, last_scan_at, id) "
                    "WHERE b.status = 'in_hold' AND b.last_scan_at > $ts "
                    "AND b.last_scan_at < $before AND b.id IS NOT NULL "
                    "WITH b ORDER BY b.status, b.last_scan_at, b.id LIMIT $batch "
                    + _HOLD_RETURN, ts=self.ts, before=archive_before, batch=batch - len(rows),
                )).data()
            await _archive_tx(tx, [r["id"] for r in rows if r["departed"]], archive_before, sim_time)
            return rows

        async with get_driver().session() as session:
            rows = await session.execute_write(apply)
        if len(rows) < batch:
            self.reset()
        else:
            self.ts, self.id = rows[-1]["at"], rows[-1]["id"]
        return len(rows)


async def purge_archived(purge_before: str, sim_time: datetime, batch: int) -> int:
    """Delete one batch of bags (with their scan trail) archived before ``purge_before``."""
    async def apply(tx) -> int:
        row = await (await tx.run(
            "MATCH (b:BaggageArchive) WHERE b.archived_at < $before "
            "WITH b LIMIT $batch "
            "OPTIONAL MATCH (b)-[:SCANNED_AT]->(s:ScanEventArchive) "
            "WITH b, collect(s) AS scans "
            "FOREACH (s IN scans | DETACH DELETE s) "
            "DETACH DELETE b RETURN count(*) AS n",
            before=purge_before, batch=batch,
        )).single()
        count = int(row["n"]) if row else 0
        if count:
            await outbox.stage_outbox(tx, "BaggageOutbox", [
                retention.purged_fact("Baggage", count, purge_before, sim_time, PRODUCER),
            ], retention.FACT_REVISION)
        return count

    async with get_driver().session() as session:
        return await session.execute_write(apply)


def tasks(sim_time: Callable[[], datetime | None], batch: int | None = None) -> list:
    """The baggage owner's retention tasks for :func:`_common.retention.run`."""
    batch = batch or retention.BATCH
    hold = HoldSweep()

    async def baggage_archive_collected() -> int:
        now = sim_time()
        before, _ = retention.cutoffs(now)
        return await archive_collected(before, now, batch) if before else 0

    async def baggage_archive_departed_hold() -> int:
        now = sim_time()
        before, _ = retention.cutoffs(now)
        return await hold.step(before, now, batch) if before else 0

    async def baggage_purge_archive() -> int:
        now = sim_time()
        _, before = retention.cutoffs(now)
        return await purge_archived(before, now, batch) if before else 0

    async def baggage_prune_inbox() -> int:
        return await retention.prune_inbox(get_driver, "BaggageInbox", batch=batch)

    async def baggage_archive_short_shipped() -> int:
        now = sim_time()
        before, _ = retention.cutoffs(now)
        return await archive_collected(before, now, batch, "short_shipped") if before else 0

    return [baggage_archive_collected, baggage_archive_departed_hold,
            baggage_purge_archive, baggage_prune_inbox, baggage_archive_short_shipped]


async def setup() -> None:
    await retention.backfill_inbox_seen_at(get_driver, "BaggageInbox")
