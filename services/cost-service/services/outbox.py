"""Publish committed financial events, retaining stable IDs until broker ack."""

import asyncio
import json

import structlog

from db.neo4j import get_driver
from kafka.producer import publish_confirmed

logger = structlog.get_logger(__name__)


async def publish_pending() -> int:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (e:CostOutbox) RETURN e.id AS id, e.document AS document "
            "ORDER BY e.revision, e.position LIMIT 100"
        )
        pending = await result.data()
    count = 0
    for row in pending:
        await asyncio.to_thread(publish_confirmed, json.loads(row["document"]))
        async with get_driver().session() as session:
            result = await session.run("MATCH (e:CostOutbox {id: $id}) DELETE e", id=row["id"])
            await result.consume()
        count += 1
    return count


async def run(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            count = await publish_pending()
            if count:
                continue
        except Exception:
            logger.exception("financial outbox delivery unavailable; retaining events")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass
