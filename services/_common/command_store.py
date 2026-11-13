"""Neo4j persistence adapter for owning-service command receipts."""

import json

from neo4j import AsyncDriver


async def load_receipt(driver: AsyncDriver, command_id: str) -> tuple[str, dict] | None:
    async with driver.session() as session:
        result = await session.run(
            "MATCH (r:CommandReceipt {id: $id}) RETURN r.event_type AS event_type, r.payload AS payload",
            id=command_id,
        )
        row = await result.single()
        return (row["event_type"], json.loads(row["payload"])) if row else None


async def save_receipt(
    driver: AsyncDriver, command_id: str, receipt: tuple[str, dict]
) -> None:
    async with driver.session() as session:
        result = await session.run(
            "MERGE (r:CommandReceipt {id: $id}) "
            "SET r.event_type = $event_type, r.payload = $payload",
            id=command_id,
            event_type=receipt[0],
            payload=json.dumps(receipt[1]),
        )
        await result.consume()


async def load_receipt_in_tx(tx, command_id: str) -> tuple[str, dict] | None:
    """Read a command receipt inside the caller's managed transaction (G1-b).

    Lets a command executor check for an existing receipt and write its domain
    state + receipt + outbox facts in one atomic unit, keyed on ``command_id``.
    """
    # Lock before checking. Concurrent deliveries must not both see "missing"
    # and apply the domain mutation twice. A placeholder exists only in this tx;
    # failures roll it back with the mutation and outbox.
    result = await tx.run(
        "MERGE (r:CommandReceipt {id: $id}) "
        "SET r.lock = coalesce(r.lock, 0) + 1 "
        "RETURN r.event_type AS event_type, r.payload AS payload",
        id=command_id,
    )
    row = await result.single()
    return (row["event_type"], json.loads(row["payload"])) if row and row["event_type"] else None



async def save_receipt_in_tx(
    tx, command_id: str, receipt: tuple[str, dict]
) -> None:
    """Persist a command receipt inside the caller's managed transaction (G1-b).

    Same write as :func:`save_receipt` but on a caller-owned ``tx`` so the
    receipt commits atomically with the domain write and staged outbox facts,
    closing the ``CommandReceipts``/``command_store`` gap named in §10 G1.
    """
    result = await tx.run(
        "MERGE (r:CommandReceipt {id: $id}) "
        "SET r.event_type = $event_type, r.payload = $payload",
        id=command_id,
        event_type=receipt[0],
        payload=json.dumps(receipt[1]),
    )
    await result.consume()
