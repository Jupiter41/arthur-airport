"""Owner-only, restart-safe disposition of unprovable pre-manifest baggage."""
from __future__ import annotations

from datetime import datetime
import logging

from _common import outbox
from _common.kafka_runtime import build_envelope
from db.neo4j import get_driver

logger = logging.getLogger(__name__)
MIGRATION = "rc14-identity-v1"


async def classify_batch(sim_time: datetime, batch: int = 1000) -> int:
    async def apply(tx) -> int:
        # Serialize concurrent/retried migration workers, before selecting candidates.
        await (await tx.run(
            "MERGE (m:LegacyBaggageDisposition {id: $migration}) "
            "SET m.lock = coalesce(m.lock, 0) + 1", migration=MIGRATION,
        )).consume()
        rows = await (await tx.run(
            "MATCH (b:LegacyBaggageCandidate) WITH b LIMIT $batch "
            "OPTIONAL MATCH (p)-[:CARRIES]->(b) WHERE p:Passenger OR p:PassengerArchive "
            "WITH b, collect(DISTINCT p.id) AS passenger_ids "
            "RETURN b.id AS id, passenger_ids, b:BaggageArchive AS was_archived",
            batch=batch,
        )).data()
        if not rows:
            return 0
        if any(not isinstance(r["id"], str) or not r["id"] for r in rows):
            raise RuntimeError("Legacy baggage has no stable bag ID; cannot disposition safely")
        linked = [{"id": r["id"], "passenger_id": r["passenger_ids"][0]} for r in rows if len(r["passenger_ids"]) == 1]
        quarantined = [{"id": r["id"], "original_label": "BaggageArchive" if r["was_archived"] else "Baggage",
                        "reason": "ambiguous_passenger" if len(r["passenger_ids"]) > 1 else "missing_passenger"}
                       for r in rows if len(r["passenger_ids"]) != 1]
        await (await tx.run(
            "UNWIND $rows AS row MATCH (b:LegacyBaggageCandidate {id: row.id}) "
            "SET b.passenger_id = row.passenger_id, b.identity_disposition = 'existing_link', "
            "b.identity_disposition_at = $at REMOVE b:LegacyBaggageCandidate",
            rows=linked, at=sim_time.isoformat(),
        )).consume()
        await (await tx.run(
            "UNWIND $rows AS row MATCH (b:LegacyBaggageCandidate {id: row.id}) "
            "OPTIONAL MATCH (b)-[:SCANNED_AT]->(s) WHERE s:ScanEvent OR s:ScanEventArchive "
            "WITH b, row, collect(s) AS scans "
            "SET b:LegacyBaggage, b.identity_disposition = row.reason, "
            "b.legacy_original_label = row.original_label, b.identity_disposition_at = $at "
            "REMOVE b:Baggage:BaggageArchive:UnscannedBaggage:ReviewBaggage:LegacyBaggageCandidate "
            "FOREACH (s IN scans | REMOVE s:ScanEvent:ScanEventArchive SET s:LegacyScanEvent)",
            rows=quarantined, at=sim_time.isoformat(),
        )).consume()
        document = build_envelope("BaggageIdentityDisposition", sim_time, {
            "migration": MIGRATION, "linked_ids": [r["id"] for r in linked],
            "quarantined_ids": [r["id"] for r in quarantined],
        }, "baggage-service")
        await outbox.stage_outbox(tx, "BaggageOutbox", [{"id": document["event_id"], "document": document}], 0)
        await (await tx.run(
            "MATCH (m:LegacyBaggageDisposition {id: $migration}) "
            "SET m.linked = coalesce(m.linked, 0) + $linked, "
            "m.quarantined = coalesce(m.quarantined, 0) + $quarantined, m.at = $at",
            migration=MIGRATION, linked=len(linked), quarantined=len(quarantined), at=sim_time.isoformat(),
        )).consume()
        return len(rows)

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def migrate_legacy_identity(sim_time: datetime | None) -> None:
    # Bounded auto-commit subtransactions mark candidates once; they change only
    # a derived processing index, not domain state. Disposition + facts are atomic.
    async with get_driver().session() as session:
        for label in ("Baggage", "BaggageArchive"):
            await (await session.run(
                f"MATCH (b:{label}) WHERE b.passenger_id IS NULL "
                "CALL { WITH b SET b:LegacyBaggageCandidate } IN TRANSACTIONS OF 1000 ROWS",
            )).consume()
        row = await (await session.run("MATCH (b:LegacyBaggageCandidate) RETURN count(b) AS n")).single()
    if not row["n"]:
        return
    if sim_time is None:
        raise RuntimeError("Legacy baggage disposition requires the owner's durable simulation checkpoint")
    processed = 0
    while count := await classify_batch(sim_time):
        processed += count
        logger.info("Legacy identity disposition: %d processed", processed)
