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
