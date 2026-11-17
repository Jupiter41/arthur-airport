"""Durable seed commands, applied exclusively by the entity's owner (RC7).

Kafka is the notification path. Pending commands are also discoverable after
startup/publication failure; their immutable payload is never live domain state.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from _common import outbox
from _common.kafka_runtime import build_envelope

BATCH_SIZE = 500
OWNERS = {
    "flight": ("Flight", "FlightRuntime", "FlightOutbox", "FlightsScheduled", "flights"),
    "passenger": ("Passenger", "PassengerRuntime", "PassengerOutbox", "PassengersSeeded", "passengers"),
    "baggage": ("Baggage", "BaggageOutboxSeq", "BaggageOutbox", "BaggageSeeded", "baggage"),
}


async def store_day(get_driver: Callable[[], Any], day_id: str, sim_time: datetime,
                    manifests: dict[str, list[dict]]) -> bool:
    """Commit the complete day or nothing; retries cannot generate duplicate IDs."""
    batches = [
        {"id": f"{day_id}:{owner}:{start // BATCH_SIZE}", "owner": owner,
         "document": json.dumps(rows[start:start + BATCH_SIZE])}
        for owner, rows in manifests.items() for start in range(0, len(rows), BATCH_SIZE)
    ]

    async def apply(tx: Any) -> bool:
        row = await (await tx.run(
            "MERGE (d:SeedDay {id: $id}) SET d.lock = coalesce(d.lock, 0) + 1 "
            "RETURN d.ready AS ready", id=day_id,
        )).single()
        if row["ready"]:
            return False
        await (await tx.run(
            "UNWIND $rows AS row CREATE (b:SeedBatch {id: row.id, owner: row.owner, "
            "document: row.document, sim_time: $at, pending: true})",
            rows=batches, at=sim_time.isoformat(),
        )).consume()
        await (await tx.run("MATCH (d:SeedDay {id: $id}) SET d.ready = true", id=day_id)).consume()
        return True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


def dependencies(owner: str, rows: list[dict]) -> tuple[str, dict]:
    """Only identity checks; a missing predecessor leaves the request pending."""
    if owner == "flight":
        return (
            "UNWIND $rows AS row MATCH (:Gate {id: row.gate_id}) "
            "MATCH (:Runway {id: row.runway_id}) RETURN count(*) AS count", {"rows": rows},
        )
    query = "UNWIND $rows AS row MATCH (:Flight {id: row.flight_id}) "
    if owner == "baggage":
        query += (
            "OPTIONAL MATCH (live:Passenger {id: row.passenger_id}) "
            "OPTIONAL MATCH (archived:PassengerArchive {id: row.passenger_id}) "
            "WITH row, coalesce(live, archived) AS p WHERE p IS NOT NULL "
        )
    return query + "RETURN count(*) AS count", {"rows": rows}


async def apply_pending(owner: str, get_driver: Callable[[], Any]) -> int:
    """Retry bounded owner requests, atomically accepting each with creation facts."""
    label, runtime, outbox_label, event_type, field = OWNERS[owner]
    async with get_driver().session() as session:
        pending = await (await session.run(
            "MATCH (b:SeedBatch {owner: $owner, pending: true}) "
            "RETURN b.id AS id ORDER BY b.id LIMIT 1000", owner=owner,
        )).data()
    applied = 0
    for request in pending:
        async def apply(tx: Any) -> bool:
            # Lock order matches owner ticks/commands: runtime before request.
            revision = await (await tx.run(
                f"MATCH (s:{runtime} {{id: 'latest'}}) "
                "SET s.revision = coalesce(s.revision, 0) + 1 RETURN s.revision AS revision"
            )).single()
            if revision is None:
                raise RuntimeError(f"{runtime} not initialized")
            row = await (await tx.run(
                "MATCH (b:SeedBatch {id: $id, owner: $owner}) "
                "SET b.lock = coalesce(b.lock, 0) + 1 "
                "RETURN b.pending AS pending, b.document AS document, b.sim_time AS at",
                id=request["id"], owner=owner,
            )).single()
            if not row or not row["pending"]:
                return False
            rows = json.loads(row["document"])
            query, params = dependencies(owner, rows)
            ready = await (await tx.run(query, **params)).single()
            if ready["count"] != len(rows):
                return False
            # Link references stay on the owned entity too (restart/audit).
            await (await tx.run(
                f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) "
                "ON CREATE SET n += row", rows=rows,
            )).consume()
            if owner == "flight":
                links = """
                UNWIND $rows AS row MATCH (n:Flight {id: row.id})
                MATCH (g:Gate {id: row.gate_id}) MATCH (r:Runway {id: row.runway_id})
                MERGE (n)-[:ASSIGNED_TO]->(g)
                MERGE (n)-[:USES_RUNWAY {operation: CASE WHEN row.direction = 'departure'
                    THEN 'takeoff' ELSE 'landing' END}]->(r)
                """
            elif owner == "passenger":
                links = """
                UNWIND $rows AS row MATCH (n:Passenger {id: row.id})
                MATCH (f:Flight {id: row.flight_id}) MERGE (n)-[:ON_FLIGHT]->(f)
                """
            else:
                links = """
                UNWIND $rows AS row MATCH (n:Baggage {id: row.id})
                MATCH (f:Flight {id: row.flight_id})
                OPTIONAL MATCH (live:Passenger {id: row.passenger_id})
                OPTIONAL MATCH (archived:PassengerArchive {id: row.passenger_id})
                WITH row, n, f, coalesce(live, archived) AS p
                MERGE (n)-[:LOADED_ON]->(f) MERGE (p)-[:CARRIES]->(n)
                FOREACH (_ IN CASE WHEN n.last_scan_at IS NULL THEN [1] ELSE [] END |
                    SET n:UnscannedBaggage)
                """
            await (await tx.run(links, rows=rows)).consume()
            document = build_envelope(event_type, datetime.fromisoformat(row["at"]),
                                      {field: rows, "seed_batch_id": request["id"]},
                                      f"{owner}-service")
            document["event_id"] = f"seed:{request['id']}"
            await outbox.stage_outbox(tx, outbox_label, [
                {"id": document["event_id"], "document": document},
            ], revision["revision"])
            # Drop the large command document once its owner has accepted it.
            await (await tx.run(
                "MATCH (b:SeedBatch {id: $id}) SET b.pending = false REMOVE b.document",
                id=request["id"],
            )).consume()
            return True

        async with get_driver().session() as session:
            applied += int(await session.execute_write(apply))
    return applied
