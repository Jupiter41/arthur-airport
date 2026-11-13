"""Independent owner process used only by the disposable G1 live-stack suite."""
import asyncio
from datetime import datetime
import json
import os
import sys
import time
from uuid import uuid4

sys.path.insert(0, "/app")
sys.path.insert(0, "/g1-source")

from db import neo4j as db  # noqa: E402
from kafka import consumer, producer  # noqa: E402
from _common import kafka_runtime, outbox, transaction_scope  # noqa: E402

ARGS = json.load(sys.stdin)
OWNER = ARGS["owner"]
LABEL = OWNER.capitalize()
RUNTIME = "BaggageOutboxSeq" if OWNER == "baggage" else f"{LABEL}Runtime"
CLOCK = datetime(2100, 1, 1, 12)


async def query(cypher, **params):
    async with db.get_driver().session() as session:
        return await (await session.run(cypher, **params)).data()


async def snapshot():
    entities = await query(
        "MATCH (n) WHERE (n.id STARTS WITH 'g1-' OR n:SecurityCheckpoint) AND NOT n:CommandReceipt "
        "RETURN labels(n) AS labels, properties(n) AS p ORDER BY n.id, n.terminal"
    )
    facts = await query(f"MATCH (e:{LABEL}Outbox) RETURN e.id AS id, e.document AS document ORDER BY e.revision, e.position")
    runtime = await query(f"MATCH (s:{RUNTIME} {{id:'latest'}}) RETURN s.last_tick_sim_time AS tick, s.document AS document")
    receipts = await query("MATCH (r:CommandReceipt) RETURN r.id AS id, r.event_type AS kind ORDER BY r.id")
    return {"entities": entities, "facts": facts, "runtime": runtime, "receipts": receipts}


async def seed():
    # This suite owns an infra-only, disposable Compose project. Refuse an
    # operational database before clearing any test/runtime records.
    foreign = await query("MATCH (f:Flight) WHERE NOT f.id STARTS WITH 'g1-' RETURN count(f) AS n")
    assert foreign[0]["n"] == 0, "G1 tests require an empty disposable database"
    await query("MATCH (t:Terminal {id:'T-A'}) DETACH DELETE t")
    await query("MATCH (n) WHERE n.id STARTS WITH 'g1-' DETACH DELETE n")
    for label in ("FlightRuntime", "PassengerRuntime", "BaggageOutboxSeq", "FlightInbox", "PassengerInbox",
                  "BaggageInbox", "FlightOutbox", "PassengerOutbox", "BaggageOutbox", "SecurityCheckpoint",
                  "BaggageProjection"):
        await query(f"MATCH (n:{label}) DETACH DELETE n")
    await query("MATCH (s:ScanEvent) DETACH DELETE s")
    for fid in ("g1-flight", "g1-second", "g1-target"):
        await query(
            "CREATE (f:Flight {id:$id, flight_number:'ZZ001', status:'scheduled', direction:'departure', "
            "aircraft_type:'A320', scheduled_time:'2100-01-01T12:45:00', estimated_time:'2100-01-01T12:45:00', "
            "pax_count:1, delay_minutes:0, flight_type:'domestic'})", id=fid)
    await query("CREATE (t:Terminal {id:'g1-terminal'})-[:HAS_GATE]->(:Gate {id:'g1-gate', status:'available', terminal_id:'g1-terminal'})")
    # Gate resolver expects the configured terminal identity.
    await query("MATCH (t:Terminal {id:'g1-terminal'}) SET t.id='T-A'")
    await query("MERGE (:Runway {id:'g1-runway', status:'open', ils:true})")
    await query(
        "MATCH (f:Flight {id:'g1-flight'}) CREATE (p:Passenger {id:'g1-pax', name:'Synthetic Passenger', "
        "status:'checked_in', location_zone:'check-in-A', flight_id:f.id, terminal_id:'T-A', "
        "special_assistance:false, connection:false})-[:ON_FLIGHT]->(f) "
        "CREATE (b:Baggage {id:'g1-bag', tag:'0000000001', status:'dropped_off', "
        "is_dangerous_goods:false, terminal_id:'T-A'})-[:LOADED_ON]->(f) CREATE (p)-[:CARRIES]->(b)"
    )
    # Commands exercise a definite domain mutation rather than a rejection.
    if ARGS.get("command"):
        await query("MATCH (f:Flight {id:'g1-flight'}) SET f.status='boarding'")
    if ARGS.get("auxiliary"):
        await query("MATCH (f:Flight {id:'g1-flight'}) SET f.status='taxiing', f.direction='arrival', "
                    "f.aircraft_registration='G1-REG', f.gate_id='g1-gate', f.actual_time='2100-01-01T11:50:00'")
        await query("MATCH (f:Flight {id:'g1-second'}) SET f.status='approach', f.direction='arrival'")
        await query("MATCH (f:Flight {id:'g1-target'}) SET f.aircraft_registration='G1-REG'")
        await query("MATCH (r:Runway) SET r.status='closed'")


async def command():
    if consumer._state.sim_time is None:
        consumer._state.sim_time = CLOCK
    envelope = {"command_id": "g1-command", "command_type": {
        "flight": "HoldFlight", "passenger": "OpenSecurityLane", "baggage": "RedirectBaggage",
    }[OWNER], "payload": {
        "flight": {"flight_id": "g1-flight", "reason": "synthetic test", "duration_min": 10},
        "passenger": {"terminal": "A", "lanes_open": 7},
        "baggage": {"bag_id": "g1-bag", "target_flight_id": "g1-target"},
    }[OWNER]}
    await consumer._handle_command(envelope)


async def tick():
    if ARGS.get("auxiliary"):
        consumer._state.vehicle_pool.initialize_fleet()
        consumer._state.holding_minutes["g1-second"] = 29
        consumer._state.noise_settings.update(diversion_rate=0, equipment_failure_rate=0)
    from datetime import timedelta
    clock = CLOCK + timedelta(minutes=ARGS.get("minute", 0))
    await consumer._dispatch({"event_id": "g1-tick", "event_type": "SimClockTick",
        "sim_time": clock.isoformat(), "payload": {"step_minutes": 1, "mode": ARGS.get("speed", "REALTIME")}})


async def delivery():
    before = await snapshot()
    assert before["facts"], "No committed domain facts to deliver"
    def unavailable(document):
        raise RuntimeError("injected broker failure")
    try:
        await outbox.publish_pending(f"{LABEL}Outbox", db.get_driver, unavailable)
        raise AssertionError("Expected delivery failure")
    except RuntimeError as exc:
        assert str(exc) == "injected broker failure"
    assert (await snapshot())["facts"] == before["facts"]
    from confluent_kafka import Consumer, TopicPartition
    topics = [f"{'passengers' if OWNER == 'passenger' else 'flights' if OWNER == 'flight' else 'baggage'}.events"]
    if OWNER == "flight":
        topics.append("ground.events")
    observer = Consumer({"bootstrap.servers": "kafka:9092", "group.id": str(uuid4()), "enable.auto.commit": False})
    parts = []
    for topic in topics:
        metadata = observer.list_topics(topic, timeout=15)
        assert metadata.topics[topic].error is None
        for partition in metadata.topics[topic].partitions:
            tp = TopicPartition(topic, partition)
            parts.append(TopicPartition(topic, partition, observer.get_watermark_offsets(tp, timeout=10)[1]))
    observer.assign(parts)
    producer.init_kafka_producer()
    first = json.loads(before["facts"][0]["document"])
    producer.publish_confirmed(first)
    # Process exit after broker ack but before deleting the outbox row.
    await db.close_neo4j()
    await db.init_neo4j()
    await outbox.publish_pending(
        f"{LABEL}Outbox", db.get_driver, producer.publish_confirmed, batch=10000,
        publish_batch_confirmed=producer.publish_batch_confirmed,
    )
    observed = []
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        message = observer.poll(0.2)
        if message and not message.error():
            observed.append(json.loads(message.value())["event_id"])
        if all(observed.count(row["id"]) >= (2 if row["id"] == first["event_id"] else 1) for row in before["facts"]):
            break
    observer.close()
    producer.close_kafka_producer()
    assert all(observed.count(row["id"]) >= 1 for row in before["facts"])
    assert observed.count(first["event_id"]) == 2
    assert (await snapshot())["facts"] == []


async def replay():
    from confluent_kafka import Consumer, TopicPartition
    group = f"g1-{OWNER}-{uuid4()}"
    c = Consumer({"bootstrap.servers": "kafka:9092", "group.id": group, "enable.auto.commit": False})
    tp = TopicPartition("sim.clock", 0)
    start = c.get_watermark_offsets(tp, timeout=15)[1]
    producer.init_kafka_producer()
    doc = {"event_id": f"g1-input-{uuid4()}", "event_type": "SimClockTick", "sim_time": CLOCK.isoformat(),
           "payload": {"step_minutes": 1}}
    producer._producer.produce("sim.clock", value=json.dumps(doc))
    assert producer._producer.flush(15) == 0
    producer.close_kafka_producer()
    states = []
    for _ in range(2):
        c.assign([TopicPartition("sim.clock", 0, start)])
        running = True
        async def dispatch(envelope):
            nonlocal running
            await consumer._dispatch(envelope)
            running = False
        # Real Kafka polling + the actual owning-service dispatch + durable ack.
        # Clear process-local dedup to model a new worker on redelivery.
        consumer._state._idempotency.clear()
        await kafka_runtime.run_consumer_loop(c, dispatch, lambda: running, manual_commit=True, timeout=0.1)
        c = Consumer({"bootstrap.servers": "kafka:9092", "group.id": group, "enable.auto.commit": False})
        assert c.committed([tp], timeout=10)[0].offset >= start + 1
        states.append(await snapshot())
    c.close()
    assert states[0] == states[1], "Kafka replay re-applied an already committed tick"


async def main():
    await db.init_neo4j()
    await db.create_constraints_and_indexes()
    mode = ARGS["mode"]
    if mode == "seed":
        await seed()
    elif mode == "snapshot":
        pass
    elif mode in ("fail", "fail-command", "exit-before-commit"):
        original = outbox.stage_outbox
        async def fail(tx, label, facts, revision):
            await original(tx, label, facts, revision)
            scope = transaction_scope.current.get()
            if scope is None or scope.flushing:
                rows = await (await tx.run(f"MATCH (e:{LABEL}Outbox) RETURN count(e) AS n")).single()
                assert rows["n"] > 0, "Failure must follow real domain/outbox writes"
                if mode == "exit-before-commit":
                    os._exit(27)
                raise RuntimeError("injected before commit")
        outbox.stage_outbox = fail
        # Flight uses its own imported alias for the shared outbox module too.
        try:
            await (command() if mode == "fail-command" else tick())
            raise AssertionError("Expected rollback")
        except RuntimeError as exc:
            assert str(exc) == "injected before commit"
    elif mode in ("tick", "exit-after-commit"):
        await tick()
        if mode == "exit-after-commit":
            os._exit(28)
    elif mode == "replay-inputs":
        await tick()
        await query("MATCH (f:Flight {id:'g1-target'}) "
                    "CREATE (:Baggage {id:'g1-arrived', tag:'0000000002', status:'arrived', "
                    "last_scan_zone:'arrival-belt-1', last_scan_at:'2100-01-01T12:00:00'})-[:LOADED_ON]->(f)")
        await consumer._on_incident_created({
            "incident_id": "g1-power", "type": "system_failure", "location": "power-A",
        }, CLOCK)
        await consumer._on_clock_tick({"step_minutes": 1}, CLOCK)
        assert consumer._state.conveyor.get_zone("induction-A").status == "offline"
        assert any(b.baggage_id == "g1-arrived" for b in
                   consumer._state.conveyor.get_zone("arrival-belt-1").queue)
    elif mode == "mixed":
        from datetime import timedelta
        consumer._state.sim_time = CLOCK
        async def ticks():
            for minute in range(10):
                await consumer._on_clock_tick({"step_minutes": 1}, CLOCK + timedelta(minutes=minute))
        async def commands():
            for number in range(10):
                await consumer._handle_command({
                    "command_id": f"g1-mixed-{number}", "command_type": "OpenSecurityLane",
                    "payload": {"terminal": "B", "lanes_open": 7},
                })
        await asyncio.wait_for(asyncio.gather(ticks(), commands()), timeout=45)
    elif mode == "command":
        await command()
    elif mode == "delivery":
        await delivery()
    elif mode == "replay":
        await replay()
    else:
        raise AssertionError(mode)
    print(json.dumps(await snapshot()), flush=True)
    await db.close_neo4j()


asyncio.run(main())
