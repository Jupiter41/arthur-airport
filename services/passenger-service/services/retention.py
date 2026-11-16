"""Passenger lifecycle retention (RC1): archive departed passengers, purge archives.

A passenger is finished once ``departed_airport`` (both directions end there) or
``missed_flight`` (the departure left without them, RC5).
Archival swaps ``Passenger`` → ``PassengerArchive`` ``RETENTION_ARCHIVE_AFTER_H``
simulated hours after ``departed_airport_at``; relationships (``ON_FLIGHT``,
``CARRIES``) are kept so per-flight history counts still resolve. See
``_common/retention.py`` for cadence, cutoffs and the inbox rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from _common import outbox, retention
from db.neo4j import get_driver

PRODUCER = "passenger-service"


# Terminal status → the timestamp it stamps (``<status>_at``).
FINISHED = {"departed_airport": "departed_airport_at", "missed_flight": "missed_flight_at"}


async def archive_departed(
    archive_before: str, sim_time: datetime, batch: int, status: str = "departed_airport"
) -> int:
    """Archive one batch of finished passengers (``departed_airport`` / ``missed_flight``)."""
    at_field = FINISHED[status]

    async def apply(tx) -> int:
        rows = await (await tx.run(
            f"MATCH (p:Passenger) WHERE p.{at_field} < $before "
            f"AND p.status = '{status}' "
            "WITH p LIMIT $batch "
            "REMOVE p:Passenger SET p:PassengerArchive, p.archived_at = $at "
            "RETURN p.id AS id",
            before=archive_before, batch=batch, at=sim_time.isoformat(),
        )).data()
        ids = [row["id"] for row in rows]
        if ids:
            await outbox.stage_outbox(tx, "PassengerOutbox", [
                retention.archived_fact("Passenger", ids, archive_before, sim_time, PRODUCER),
            ], retention.FACT_REVISION)
        return len(ids)

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def purge_archived(purge_before: str, sim_time: datetime, batch: int) -> int:
    """Delete one batch of passengers archived before ``purge_before``."""
    async def apply(tx) -> int:
        row = await (await tx.run(
            "MATCH (p:PassengerArchive) WHERE p.archived_at < $before "
            "WITH p LIMIT $batch DETACH DELETE p RETURN count(*) AS n",
            before=purge_before, batch=batch,
        )).single()
        count = int(row["n"]) if row else 0
        if count:
            await outbox.stage_outbox(tx, "PassengerOutbox", [
                retention.purged_fact("Passenger", count, purge_before, sim_time, PRODUCER),
            ], retention.FACT_REVISION)
        return count

    async with get_driver().session() as session:
        return await session.execute_write(apply)


def tasks(sim_time: Callable[[], datetime | None], batch: int | None = None) -> list:
    """The passenger owner's retention tasks for :func:`_common.retention.run`."""
    batch = batch or retention.BATCH

    async def passenger_archive_departed() -> int:
        now = sim_time()
        before, _ = retention.cutoffs(now)
        return await archive_departed(before, now, batch) if before else 0

    async def passenger_purge_archive() -> int:
        now = sim_time()
        _, before = retention.cutoffs(now)
        return await purge_archived(before, now, batch) if before else 0

    async def passenger_prune_inbox() -> int:
        return await retention.prune_inbox(get_driver, "PassengerInbox", batch=batch)

    async def passenger_archive_missed_flight() -> int:
        now = sim_time()
        before, _ = retention.cutoffs(now)
        return await archive_departed(before, now, batch, "missed_flight") if before else 0

    return [passenger_archive_departed, passenger_purge_archive, passenger_prune_inbox,
            passenger_archive_missed_flight]


async def setup() -> None:
    await retention.backfill_inbox_seen_at(get_driver, "PassengerInbox")
