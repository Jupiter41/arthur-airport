"""Independent G9 process; only for the disposable synthetic G1/G9 database."""
import asyncio
import json
import os
import sys
import time
from uuid import uuid4

sys.path.insert(0, "/app")
sys.path.insert(0, "/g1-source")

from db import neo4j as db  # noqa: E402
from services import projection_store, proposal_store, action_outbox  # noqa: E402

ARGS = json.load(sys.stdin)


async def query(statement, **params):
    async with db.get_driver().session() as session:
        return await (await session.run(statement, **params)).data()


async def snapshot():
    return {"document": await projection_store.load(), "outbox": await query(
        "MATCH(e:AnalysisOutbox) RETURN properties(e) AS fact ORDER BY e.id")}


def observer(topics, earliest=False):
    from confluent_kafka import Consumer, TopicPartition
    client = Consumer({"bootstrap.servers": "kafka:9092", "group.id": str(uuid4()),
                       "enable.auto.commit": False})
    partitions = []
    for topic in topics:
        metadata = client.list_topics(topic, timeout=10)
        for p in metadata.topics[topic].partitions:
            end = client.get_watermark_offsets(TopicPartition(topic, p), timeout=10)[1]
            partitions.append(TopicPartition(topic, p, 0 if earliest else end))
    client.assign(partitions)
    return client


async def main():
    await db.wait_for_neo4j(max_attempts=1)
    await proposal_store.initialize()
    mode = ARGS["mode"]
    if mode == "seed":
        foreign = await query("MATCH(f:Flight) WHERE NOT f.id STARTS WITH 'g1-' RETURN count(f) AS n")
        assert foreign[0]["n"] == 0, "G9 requires a disposable synthetic graph"
        for label in ("AnalysisRuntime", "AnalysisOutbox", "ActionProposal", "SecurityCheckpoint"):
            await query(f"MATCH(n:{label}) DETACH DELETE n")
        await query("CREATE (:SecurityCheckpoint {terminal:'B', queue_depth:300, lanes_open:2, "
                    "wait_minutes:50.0, sa_queue_depth:3, frozen:true, at:'2100-01-01T12:00:00'})")
        await proposal_store.save_clock({"sim_time": "2100-01-01T12:00:00"}, (0, 1))
    elif mode == "clock":
        accepted = await proposal_store.save_clock({"sim_time": ARGS["at"]}, (0, ARGS["offset"]))
        print(json.dumps({"accepted": accepted}), flush=True)
        await db.close_neo4j()
        return
    elif mode == "clear":
        for label in ("SecurityCheckpoint", "GroundVehicle", "BaggageProjection"):
            await query(f"MATCH(n:{label}) DETACH DELETE n")
    elif mode == "resolve":
        await query("MATCH(s:SecurityCheckpoint) SET s.queue_depth=0, s.wait_minutes=0, s.frozen=false")
    elif mode == "proposal":
        from datetime import datetime
        from services.approval_queue import Proposal
        document = await projection_store.load()
        rec = next(r for r in document["recommendations"] if r["executable"])
        now = datetime.fromisoformat(document["clock"]["sim_time"])
        proposal = Proposal(id="g1-projection-proposal", action_type=rec["action_type"],
            description="Synthetic recovery proposal", parameters=rec["parameters"],
            confidence_score=0.8, proposed_by="test", proposed_at=now.isoformat(),
            recommendation_id=rec["id"], bottleneck_id=rec["bottleneck_id"])
        await proposal_store.create(proposal.to_dict(), now)
        await projection_store.evaluate()
    elif mode == "reject-proposal":
        from datetime import datetime
        await proposal_store.reject("g1-projection-proposal", datetime(2100, 1, 1, 12),
                                    "test", "Synthetic rejection")
        await projection_store.evaluate()
    elif mode in ("fail", "exit-before-commit"):
        original = proposal_store._outbox
        async def fail(tx, revision, messages):
            await original(tx, revision, messages)
            if mode == "exit-before-commit":
                os._exit(27)
            raise RuntimeError("injected after discovery writes")
        proposal_store._outbox = fail
        try:
            await projection_store.evaluate()
            raise AssertionError("Expected transaction failure")
        except RuntimeError as exc:
            assert "injected" in str(exc)
    elif mode in ("evaluate", "exit-after-commit", "startup", "endpoints"):
        if mode == "startup":
            from kafka.consumer import _on_tick
            await _on_tick(await proposal_store.load_clock())
        elif mode == "endpoints":
            from routers.analysis import list_bottlenecks, list_recommendations
            print(json.dumps({"bottlenecks": await list_bottlenecks(None, None),
                              "recommendations": await list_recommendations()}), flush=True)
            await db.close_neo4j()
            return
        else:
            await projection_store.evaluate()
        if mode == "exit-after-commit":
            os._exit(28)
    elif mode == "delivery":
        before = await snapshot()
        def unavailable(*args):
            raise RuntimeError("broker unavailable")
        action_outbox.publish_confirmed = unavailable
        try:
            await action_outbox.publish_pending()
            raise AssertionError("Expected broker failure")
        except RuntimeError as exc:
            assert "broker unavailable" in str(exc)
        assert await snapshot() == before
        from kafka import producer
        producer.init_kafka_producer()
        action_outbox.publish_confirmed = producer.publish_confirmed
        client = observer(["analysis.events"])
        await action_outbox.publish_pending()
        expected = {json.loads(row["fact"]["document"])["event_id"] for row in before["outbox"]}
        observed = set()
        deadline = time.monotonic() + 20
        while expected - observed and time.monotonic() < deadline:
            message = client.poll(0.2)
            if message and not message.error():
                observed.add(json.loads(message.value())["event_id"])
        client.close()
        producer.close_kafka_producer()
        assert expected <= observed and not (await snapshot())["outbox"]
    elif mode == "owner-contract":
        from kafka.consumer import _dispatch_event, state
        client = observer(["passengers.events", "baggage.events", "ground.events"], earliest=True)
        expected = {"SecurityQueueUpdated", "BaggageZoneSnapshot", "GroundVehicleSnapshot"}
        found = {}
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            message = client.poll(0.2)
            if message is None:
                if expected <= found.keys():
                    break
                continue
            if message.error():
                continue
            doc = json.loads(message.value())
            if doc["event_type"] in expected:
                found[doc["event_type"]] = doc["payload"]
                await _dispatch_event(doc["event_type"], doc["payload"], message.topic(), doc)
        client.close()
        assert expected <= found.keys(), found.keys()
        assert {"sa_queue_depth", "frozen"} <= found["SecurityQueueUpdated"].keys()
        from services.state import OperationalState
        restored = OperationalState()
        restored.restore_graph(await db.load_operational_projection())
        assert restored.vehicles and restored.baggage_zones
        for terminal in "ABC":
            assert state.security[f"Terminal {terminal}"].queue_depth == restored.security[f"Terminal {terminal}"].queue_depth
        assert state.baggage_zones == restored.baggage_zones
        assert state.vehicles == restored.vehicles
    elif mode != "snapshot":
        raise AssertionError(mode)
    print(json.dumps(await snapshot()), flush=True)
    await db.close_neo4j()


asyncio.run(main())
