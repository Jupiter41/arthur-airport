"""At-least-once delivery of committed planning lifecycle/audit events."""

import asyncio
import json
import logging
import time

from confluent_kafka import Producer

from db.store import get_repository

logger = logging.getLogger(__name__)


def publish_pending(producer: Producer) -> int:
    repository = get_repository()
    delivered_count = 0
    for event in repository.pending_events():
        delivered = []
        producer.produce(
            topic="planning.events",
            key=event["payload"]["record_id"].encode(),
            value=json.dumps(event).encode(),
            callback=lambda error, message: delivered.append(error),
        )
        deadline = time.monotonic() + 10
        while not delivered and time.monotonic() < deadline:
            producer.poll(0.1)
        if not delivered or delivered[0] is not None:
            raise RuntimeError("Planning event delivery not confirmed; outbox retained")
        repository.acknowledge(event["event_id"])
        delivered_count += 1
    return delivered_count


async def run(producer: Producer, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(publish_pending, producer)
        except Exception:
            logger.exception("Planning outbox delivery failed; retrying")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass
