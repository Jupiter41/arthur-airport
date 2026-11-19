"""Real-database RC11 backlog and commit-ack fault worker; disposable G1 only."""
import asyncio
from datetime import datetime, timedelta
import json
import os
import sys

ARGS = json.load(sys.stdin)
OWNER = ARGS["owner"]
sys.path.insert(0, "/app")
sys.path.insert(0, "/g1-source")
from db import neo4j as db  # noqa: E402
from _common import outbox, transaction_scope  # noqa: E402

NOW = datetime(2100, 1, 1, 12)


async def query(cypher, **params):
    async with db.get_driver().session() as session:
        return await (await session.run(cypher, **params)).data()


async def seed():
    assert (await query("MATCH(f:Flight) WHERE NOT f.id STARTS WITH 'g1-' RETURN count(f) AS n"))[0]["n"] == 0
    await query("MATCH(n) WHERE n.id STARTS WITH 'g1-' DETACH DELETE n")
    for label in ("PassengerRuntime", "BaggageOutboxSeq", "PassengerInbox", "BaggageInbox",
                  "PassengerOutbox", "BaggageOutbox", "SeedDay", "SeedBatch", "SimState"):
        await query(f"MATCH(n:{label}) DETACH DELETE n")
    await query("CREATE(f:Flight {id:'g1-rc11-arrival', direction:'arrival', status:'at_gate', flight_number:'ZZ001', "
                "flight_type:'domestic', scheduled_time:'2100-01-01T11:45:00', actual_time:'2100-01-01T11:45:00', gate_id:'A01'}) "
                "CREATE(p:Passenger {id:'g1-rc11-pax', name:'Synthetic Recovery', status:'deplaning', "
                "deplaning_at:'2100-01-01T11:45:00', location_zone:'arrivals-hall', "
                "connection:false,special_assistance:false})-[:ON_FLIGHT]->(f) "
                "CREATE(b:Baggage {id:'g1-rc11-bag',tag:'0000000011',status:'in_hold'})-[:LOADED_ON]->(f) "
                "CREATE(p)-[:CARRIES]->(b)")


async def owner_tick():
    from kafka import consumer, producer
    from _common.flight_view import VIEW, bootstrap
    label = "PassengerRuntime" if OWNER == "passenger" else "BaggageOutboxSeq"
    await bootstrap(VIEW, db.get_driver, None, NOW)
    await transaction_scope.restore_owner_checkpoint(label, consumer._state, consumer._TICK_CODEC, db.get_driver)
    producer.init_kafka_producer()
    if ARGS["mode"] != "anchor":
        original = outbox.stage_outbox
        n = 0
        async def trace(tx, outbox_label, facts, revision):
            nonlocal n
            await original(tx, outbox_label, facts, revision)
            scope = transaction_scope.current.get()
            if scope is not None and scope.flushing:
                n += 1
                at = scope.state.last_tick_sim_time.isoformat()
                await (await tx.run("CREATE(:RC11Tick {id:$id, at:$at})", id=f"g1-rc11-{OWNER}-{at}", at=at)).consume()
                if ARGS["mode"] == "fail" and n == 4:
                    raise RuntimeError("RC11 injected fourth bounded transaction")
        outbox.stage_outbox = trace
    target = NOW if ARGS["mode"] == "anchor" else NOW + timedelta(hours=6)
    try:
        await consumer._on_clock_tick({"step_minutes": 1 if ARGS["mode"] == "anchor" else 360, "mode": "BULK"}, target)
    except RuntimeError as exc:
        assert ARGS["mode"] == "fail" and "RC11 injected" in str(exc)
        os._exit(27)
    producer.close_kafka_producer()


async def clock_fault():
    from neo4j.exceptions import ServiceUnavailable
    from services import clock, runtime_state
    from kafka import producer
    from confluent_kafka import Consumer, TopicPartition
    producer.init_kafka_producer()
    observer = Consumer({"bootstrap.servers":"kafka:9092", "group.id":"g1-rc11-clock", "enable.auto.commit":False})
    tp = TopicPartition("sim.clock", 0)
    observer.assign([TopicPartition(tp.topic, 0, observer.get_watermark_offsets(tp, timeout=10)[1])])
    clock.restore_state(NOW, 1, 0, 60)
    clock.resume()
    driver = db.get_driver()
    failures, attempts = ARGS.get("failures", 2), 0

    class Result:
        def __init__(self, result):
            self.result = result

        async def consume(self):
            nonlocal failures, attempts
            await self.result.consume()  # actual auto-commit, then model a lost ACK
            attempts += 1
            if failures:
                failures -= 1
                raise ServiceUnavailable("RC11 injected lost commit acknowledgement")

    class Session:
        def __init__(self):
            self.session = driver.session()

        async def __aenter__(self):
            await self.session.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.session.__aexit__(*args)

        async def run(self, *args, **kwargs):
            return Result(await self.session.run(*args, **kwargs))

    class Driver:
        def session(self):
            return Session()

    runtime_state.get_driver = lambda: Driver()
    runtime_state.CHECKPOINT_RETRY_DELAYS_S = (0, 0)
    try:
        await runtime_state.checkpoint(command="rc11_commit_ack")
        assert ARGS.get("failures", 2) < 3
    except ServiceUnavailable:
        assert ARGS.get("failures", 2) >= 3 and clock.is_paused()
    producer.close_kafka_producer()
    seen = []
    for _ in range(10):
        message = observer.poll(.1)
        if message and not message.error():
            doc = json.loads(message.value())
            if doc.get("payload", {}).get("command") == "rc11_commit_ack":
                seen.append(doc)
    observer.close()
    print(json.dumps({"attempts": attempts, "paused": clock.is_paused(), "controls": len(seen),
                      "state": await query("MATCH(s:SimState) RETURN s.sim_time AS at, s.tick_number AS tick")}))


async def profile_history():
    from _common.flight_view import VIEW, bootstrap
    await seed()
    await query("CREATE(old:Flight {id:'g1-rc11-old',direction:'departure',status:'arrived',scheduled_time:'2090-01-01T00:00:00'}) "
                "WITH old UNWIND range(1,20000) AS n "
                "CREATE(:Passenger {id:'g1-rc11-history-p'+toString(n),status:'departed_airport'})-[:ON_FLIGHT]->(old) "
                "CREATE(:Baggage {id:'g1-rc11-history-b'+toString(n),tag:'history-'+toString(n),status:'collected'})-[:LOADED_ON]->(old)")
    await query("CREATE(f:Flight {id:'g1-rc11-departure',direction:'departure',status:'scheduled',scheduled_time:'2100-01-01T12:30:00',estimated_time:'2100-01-01T12:30:00'}) "
                "CREATE(:Baggage {id:'g1-rc11-induct',tag:'induct',status:'dropped_off'})-[:LOADED_ON]->(f)")
    await bootstrap(VIEW, db.get_driver, None, NOW)
    driver = db.get_driver()
    results = []
    class Session:
        def __init__(self):
            self.session = driver.session()
        async def __aenter__(self):
            await self.session.__aenter__()
            return self
        async def __aexit__(self, *args):
            return await self.session.__aexit__(*args)
        async def run(self, cypher, **params):
            result = await self.session.run("PROFILE " + cypher, **params)
            results.append(result)
            return result
    class Driver:
        def session(self):
            return Session()
    db.get_driver = lambda: Driver()
    if OWNER == "passenger":
        rows = await db.get_reconciliation_candidates(NOW)
    else:
        rows = await db.get_dropped_off_baggage_for_departures(NOW + timedelta(minutes=90))
        assert len(rows) == 1
    profile = (await results[0].consume()).profile
    def stats(node):
        return {"hits":node.get("dbHits",0) + sum(stats(c)["hits"] for c in node.get("children",[])),
                "operators":[node["operatorType"], *[op for c in node.get("children",[]) for op in stats(c)["operators"]]]}
    totals = stats(profile)
    assert totals["hits"] < 200, totals
    print(json.dumps({"history_entities":40000,"rows":len(rows),**totals}))


async def barrier_failure():
    import main as app
    calls = []
    async def seed_day(sim_day):
        calls.append(sim_day)
        if len(calls) == 1:
            raise RuntimeError("RC11 injected retry failure")
        await query("MERGE(d:SeedDay {id:'g1-rc11-barrier'}) SET d.ready=true")
    async def failed_task():
        raise RuntimeError("RC11 injected background failure")
    app.seed_day = seed_day
    app._seed_task = asyncio.create_task(failed_task())
    try:
        await app._on_day_start(2, NOW)
        raise AssertionError("The failing barrier must reach the clock")
    except RuntimeError as exc:
        assert "retry failure" in str(exc)
    await app._on_day_start(2, NOW)
    assert calls == [2,2]
    assert (await query("MATCH(d:SeedDay {id:'g1-rc11-barrier'}) RETURN d.ready AS ready"))[0]["ready"]
    print(json.dumps({"attempts":len(calls),"retried_consumed_task":True}))


async def main():
    await db.init_neo4j()
    await db.create_constraints_and_indexes()
    mode = ARGS["mode"]
    assert (await query("MATCH(f:Flight) WHERE NOT f.id STARTS WITH 'g1-' RETURN count(f) AS n"))[0]["n"] == 0
    if mode == "profile":
        await profile_history()
    elif mode == "barrier":
        await barrier_failure()
    elif mode == "seed":
        await seed()
    elif mode in ("anchor", "advance", "fail"):
        await owner_tick()
    elif mode == "clock":
        await clock_fault()
    elif mode == "snapshot":
        runtime = "PassengerRuntime" if OWNER == "passenger" else "BaggageOutboxSeq"
        ticks = await query("MATCH(t:RC11Tick) RETURN t.at AS at ORDER BY at")
        checkpoint = await query(f"MATCH(s:{runtime}) RETURN s.last_tick_sim_time AS at")
        entities = await query("MATCH(n) WHERE n.id IN ['g1-rc11-pax','g1-rc11-bag'] RETURN n.id AS id,n.status AS status ORDER BY id")
        facts = await query(f"MATCH(e:{'Passenger' if OWNER == 'passenger' else 'Baggage'}Outbox) RETURN count(e) AS n")
        print(json.dumps({"ticks":ticks,"checkpoint":checkpoint,"entities":entities,"facts":facts}))
    await db.close_neo4j()


assert os.getenv("G1_DISPOSABLE_STACK") == "1"
asyncio.run(main())
