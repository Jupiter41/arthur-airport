"""Drive the real BULK planner, transaction and outbox through Kafka."""
import asyncio
from datetime import datetime
import json
import os
import sys
from uuid import uuid4

sys.path.insert(0, "/app")
sys.path.insert(0, "/g1-source")
from confluent_kafka import Consumer, TopicPartition  # noqa: E402
from db import neo4j as db  # noqa: E402
from kafka import consumer, producer  # noqa: E402
from _common import outbox  # noqa: E402


async def main():
    await db.init_neo4j()
    await db.create_constraints_and_indexes()
    async with db.get_driver().session() as session:
        row = await (await session.run("MATCH(f:Flight) WHERE NOT f.id STARTS WITH 'g1-' RETURN count(f) AS n")).single()
        assert row["n"] == 0
    observer = Consumer({"bootstrap.servers": "kafka:9092", "group.id": "g1-bulk-" + uuid4().hex,
                         "enable.auto.commit": False})
    metadata = observer.list_topics("baggage.events", timeout=15)
    parts = []
    for part in metadata.topics["baggage.events"].partitions:
        tp = TopicPartition("baggage.events", part)
        parts.append(TopicPartition(tp.topic, part, observer.get_watermark_offsets(tp, timeout=10)[1]))
    observer.assign(parts)
    now = datetime(2100, 1, 1, 12)
    plan = consumer._TickPlan()
    bag = consumer.BagInZone(baggage_id="g1-rc78-bag", tag="0000000012", flight_id="g1-rc78-flight",
                             passenger_id="g1-rc78-pax", terminal="B", entered_at=now.isoformat(),
                             is_dg=False, dg_class=None)
    consumer._plan_status_change(plan, bag, "on_carousel", "collected", "arrival-belt-3", now, suppress=True)
    assert await consumer._apply_tick(plan, now)
    producer.init_kafka_producer()
    await outbox.publish_pending("BaggageOutbox", db.get_driver, producer.publish_confirmed,
                                 publish_batch_confirmed=producer.publish_batch_confirmed)
    for _ in range(100):
        msg = observer.poll(0.1)
        if msg is None or msg.error():
            continue
        doc = json.loads(msg.value())
        if doc["event_type"] == "BaggageStatusChanged" and doc["payload"].get("baggage_id") == bag.baggage_id:
            assert doc["payload"]["new_status"] == "collected" and doc["payload"]["passenger_id"] == bag.passenger_id
            print(json.dumps({"partition": msg.partition(), "offset": msg.offset()}), flush=True)
            break
    else:
        raise AssertionError("The BULK planner suppressed its collection fact")
    observer.close()
    producer.close_kafka_producer()
    await db.close_neo4j()


assert os.getenv("G1_DISPOSABLE_STACK") == "1"
asyncio.run(main())
