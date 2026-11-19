"""Independent-process RC8/RC12 durability tests with real Neo4j and Kafka."""
import asyncio
from datetime import datetime, timedelta
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/g1-source")
from db import neo4j as db  # noqa: E402
from kafka import consumer, producer  # noqa: E402
from _common import kafka_runtime, outbox, seed_requests  # noqa: E402
from _common.flight_view import VIEW, bootstrap  # noqa: E402
from services import baggage_observations  # noqa: E402

ARGS = json.load(sys.stdin)
NOW = datetime(2100, 1, 1, 12)


async def query(cypher, **params):
    async with db.get_driver().session() as session:
        return await (await session.run(cypher, **params)).data()


def envelope():
    payload = {"baggage_id": "g1-rc78-bag", "passenger_id": "g1-rc78-pax",
               "flight_id": "g1-rc78-flight", "new_status": ARGS.get("status", "collected"),
               "scan_zone": "arrival-belt-3"}
    kind = "BaggageStatusChanged"
    if ARGS.get("batch"):
        kind = "BaggageStatusBatchChanged"
        payload = {"status_changes": [{"id": payload["baggage_id"], "passenger_id": payload["passenger_id"],
                    "flight_id": payload["flight_id"], "status": payload["new_status"], "zone": payload["scan_zone"]}]}
    return {"event_id": "g1-rc78-input", "event_type": kind, "sim_time": NOW.isoformat(), "payload": payload}


async def add_passenger():
    await query("MATCH(f:Flight {id:'g1-rc78-flight'}), (b:Baggage {id:'g1-rc78-bag'}) "
                "CREATE(p:Passenger {id:'g1-rc78-pax', name:'Synthetic Claimant', status:$status, "
                "location_zone:$zone, baggage_claim_at:'2100-01-01T11:59:00', deplaning_at:'2100-01-01T11:50:00', "
                "connection:false, special_assistance:false})-[:ON_FLIGHT]->(f) "
                "CREATE(p)-[:CARRIES]->(b)", status=ARGS.get("passenger_status", "baggage_claim"), zone="arrivals-hall")


async def main():
    await db.init_neo4j()
    await db.create_constraints_and_indexes()
    assert (await query("MATCH(f:Flight) WHERE NOT f.id STARTS WITH 'g1-' RETURN count(f) AS n"))[0]["n"] == 0
    mode = ARGS["mode"]
    if mode == "seed":
        await query("MATCH(n) WHERE n.id STARTS WITH 'g1-' DETACH DELETE n")
        for label in ("PassengerRuntime", "PassengerOutbox", "PassengerInbox", "PassengerBaggageObservation",
                      "BaggageOutbox", "BaggageInbox", "BaggageOutboxSeq", "SeedDay", "SeedBatch", "BaggageTagSequence"):
            await query(f"MATCH(n:{label}) DETACH DELETE n")
        await query("CREATE(f:Flight {id:'g1-rc78-flight', direction:'arrival', status:'at_gate', "
                    "flight_number:'ZZ001', flight_type:'domestic', gate_id:'B07', "
                    "scheduled_time:'2100-01-01T11:45:00', actual_time:'2100-01-01T11:45:00'}) "
                    "CREATE(:Baggage {id:'g1-rc78-bag', tag:'0000000012', status:$bag_status, "
                    "last_scan_at:'2100-01-01T12:00:00', last_scan_zone:'arrival-belt-3'})-[:LOADED_ON]->(f)",
                    bag_status=ARGS.get('bag_status', 'collected'))
        if not ARGS.get("absent"):
            await add_passenger()
    elif mode == "add-passenger":
        await add_passenger()
    elif mode == "snapshot":
        observations = await query("MATCH(o:PassengerBaggageObservation) RETURN properties(o) AS o ORDER BY o.id")
        passengers = await query("MATCH(p:Passenger {id:'g1-rc78-pax'}) RETURN properties(p) AS p")
        facts = await query("MATCH(o:PassengerOutbox) RETURN o.document AS document ORDER BY o.id")
        runtime = await query("MATCH(s:PassengerRuntime) RETURN s.last_tick_sim_time AS tick")
        print(json.dumps({"observations": observations, "passengers": passengers,
                          "facts": [json.loads(row["document"]) for row in facts], "runtime": runtime}))
    elif mode == "publish":
        from confluent_kafka import Producer
        p = Producer({"bootstrap.servers": "kafka:9092"})
        sent = []
        def ack(error, message):
            assert not error
            sent.append({"partition": message.partition(), "offset": message.offset()})
        p.produce("baggage.events", value=json.dumps(envelope()), callback=ack)
        assert p.flush(15) == 0 and sent
        print(json.dumps(sent[0]))
    elif mode in ("consume-exit", "replay"):
        from confluent_kafka import Consumer, TopicPartition
        tp = TopicPartition("baggage.events", ARGS["partition"], ARGS["offset"])
        c = Consumer({"bootstrap.servers": "kafka:9092", "group.id": ARGS["group"], "enable.auto.commit": False})
        c.assign([tp])
        running = True
        async def dispatch(doc):
            nonlocal running
            await consumer._dispatch(doc)
            running = False
        await kafka_runtime.run_consumer_loop(c, dispatch, lambda: running, manual_commit=True, timeout=0.1)
        check = Consumer({"bootstrap.servers": "kafka:9092", "group.id": ARGS["group"]})
        committed = check.committed([tp], timeout=10)[0].offset
        check.close()
        assert committed > ARGS["offset"]
        if mode == "consume-exit":
            os._exit(29)  # genuine process death after durable input ACK, before any tick
        print(json.dumps({"committed": committed}))
    elif mode == "fail-observe":
        original = outbox.stage_outbox
        async def fail(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError("RC78 injected after staging")
        outbox.stage_outbox = fail
        try:
            await consumer._dispatch(envelope())
            raise AssertionError("Expected transaction failure")
        except RuntimeError as exc:
            assert str(exc) == "RC78 injected after staging"
    elif mode == "observe":
        await consumer._dispatch(envelope())
    elif mode == "bootstrap":
        print(json.dumps({"n": await baggage_observations.bootstrap()}))
    elif mode == "advance":
        await bootstrap(VIEW, db.get_driver, None, NOW)
        producer.init_kafka_producer()
        at = NOW + timedelta(minutes=ARGS.get("minute", 1))
        await consumer._dispatch({"event_id": "g1-rc78-clock", "event_type": "SimClockTick", "sim_time": at.isoformat(),
                                  "payload": {"step_minutes": 1, "mode": "BULK" if ARGS.get("batch") else "REALTIME"}})
        producer.close_kafka_producer()
    elif mode == "purge-orphans":
        from services.retention import purge_orphan_observations
        count = await purge_orphan_observations((NOW + timedelta(hours=1)).isoformat(),
                                                NOW + timedelta(hours=169), 10)
        print(json.dumps({"n": count}))
    elif mode == "tags":
        # Two owner batches request identical provisional tags. The owner must
        # allocate unique final identities atomically, including creation facts.
        await query("MERGE(:BaggageOutboxSeq {id:'latest'})")
        for day in ("one", "two"):
            await seed_requests.store_day(db.get_driver, "g1-rc78-" + day, NOW, {"baggage": [
                {"id": "g1-rc78-" + day, "tag": "0000000012", "passenger_id": "g1-rc78-pax",
                 "flight_id": "g1-rc78-flight", "status": "in_hold"}]})
        assert await seed_requests.apply_pending("baggage", db.get_driver) == 2
        rows = await query("MATCH(b:Baggage) RETURN b.tag AS tag ORDER BY tag")
        assert len({r["tag"] for r in rows}) == 3
        print(json.dumps(rows))
    await db.close_neo4j()


assert os.getenv("G1_DISPOSABLE_STACK") == "1"
asyncio.run(main())
