"""At-least-once publication of committed action facts and stable commands."""

import asyncio
import json
import logging

from db.neo4j import get_driver
from kafka.producer import publish_confirmed

logger = logging.getLogger(__name__)


async def publish_pending() -> int:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (e:AnalysisOutbox) RETURN e.id AS id, e.topic AS topic, e.key AS key, e.document AS document "
            "ORDER BY e.revision, e.position LIMIT 100",
        )
        pending = await result.data()
    for row in pending:
        await asyncio.to_thread(publish_confirmed, row["topic"], row["key"], json.loads(row["document"]))
        async with get_driver().session() as session:
            await (await session.run("MATCH (e:AnalysisOutbox {id: $id}) DELETE e", id=row["id"])).consume()
    return len(pending)


async def run(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            if await publish_pending():
                continue
        except Exception:
            logger.exception("Action outbox unavailable; committed work retained")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass
