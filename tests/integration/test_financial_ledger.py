"""Real Neo4j rollback/concurrency and Kafka outbox replay on a disposable stack."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
COST = os.getenv("COST_SVC_URL", "http://localhost:8008")
SIM = os.getenv("SIM_SVC_URL", "http://localhost:8006")

# Each invocation is an independent worker with its own driver/cache. The normal
# cost container is stopped for this module so its outbox cannot consume the
# injected-failure fixtures before they are inspected.
WORKER = r'''
import asyncio, json, os, sys, time
from pathlib import Path
from uuid import uuid4
from confluent_kafka import Consumer, TopicPartition
from db import neo4j as db
from kafka import consumer, producer
from services import ledger, outbox

args = json.load(sys.stdin)

async def counts(tx, source):
    row = await (await tx.run(
        "OPTIONAL MATCH (c:CostRecord {source_event_id: $id}) "
        "WITH count(c) AS costs OPTIONAL MATCH (c:CarbonRecord {source_event_id: $id}) "
        "WITH costs, count(c) AS carbon OPTIONAL MATCH (i:CostInbox {id: $id}) "
        "RETURN costs, carbon, count(i) AS inbox", id=source)).single()
    return dict(row)

async def main():
    await db._init_driver()
    consumer.set_rates(json.loads(Path('fixtures/cost_rates.json').read_text()))
    consumer.set_carbon_factors(json.loads(Path('fixtures/carbon_factors.json').read_text()))
    await ledger.initialize()
    event = args['event']
    fid = event['payload']['flight_id']
    async with db.get_driver().session() as session:
        result = await session.run(
            "MERGE (f:Flight {id: $id}) ON CREATE SET f.direction = 'departure', "
            "f.flight_number = 'ZZ001', f.aircraft_type = 'A320', f.pax_count = 100, "
            "f.distance_km = 1200, f.status = 'departed', f.scheduled_time = '2100-01-01T12:00:00'",
            id=fid)
        await result.consume()
    mode = args['mode']
    if mode == 'prepare':
        return {'prepared': True}
    if mode.startswith('fail-'):
        original = ledger._write_records if mode == 'fail-records' else ledger._write_effects
        async def fail(*values):
            await original(*values)
            # Prove writes exist in the uncommitted transaction before failure.
            assert (await counts(values[0], event['event_id']))['costs'] > 0
            raise RuntimeError('Injected crash before commit')
        target = '_write_records' if mode == 'fail-records' else '_write_effects'
        setattr(ledger, target, fail)
        try:
            await consumer.process_envelope(event)
            raise AssertionError('Expected transaction failure')
        except RuntimeError as exc:
            assert str(exc) == 'Injected crash before commit'
        finally:
            setattr(ledger, target, original)
        async with db.get_driver().session() as session:
            assert await counts(session, event['event_id']) == {'costs': 0, 'carbon': 0, 'inbox': 0}
            pending = await (await session.run(
                "MATCH (e:CostOutbox) WHERE e.document CONTAINS $id RETURN count(e) AS n",
                id=event['event_id'])).single()
            assert pending['n'] == 0
    applied = await consumer.process_envelope(event)
    async with db.get_driver().session() as session:
        saved = await counts(session, event['event_id'])
        links = await (await session.run(
            "MATCH (c:CostRecord {source_event_id: $id})-[:FOR_FLIGHT]->(:Flight {id: $fid}) "
            "RETURN count(c) AS n", id=event['event_id'], fid=fid)).single()
    assert saved['inbox'] == 1
    assert links['n'] == saved['costs']
    if mode == 'crash-after-commit':
        print(json.dumps({'applied': applied, **saved}), flush=True)
        os._exit(23)  # No graceful shutdown or offset acknowledgement.
    if mode == 'kafka-replay':
        producer.init_kafka_producer()
        positions = []
        observed = Consumer({'bootstrap.servers': 'kafka:9092', 'group.id': 'cost-service',
                             'enable.auto.commit': False})
        try:
            def delivered(error, message):
                assert error is None, error
                positions.append(TopicPartition(message.topic(), message.partition(), message.offset() + 1))
            for _ in range(2):
                producer._producer.produce('flights.events', key=fid, value=json.dumps(event), callback=delivered)
            assert producer._producer.flush(15) == 0 and len(positions) == 2
            target = positions[-1]
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                committed = observed.committed([target], timeout=5)[0].offset
                if committed >= target.offset:
                    break
                await asyncio.sleep(0.2)
            else:
                raise AssertionError('Owning consumer never acknowledged the fresh Kafka replay')
            async with db.get_driver().session() as session:
                assert await counts(session, event['event_id']) == saved
        finally:
            observed.close()
            producer.close_kafka_producer()
    if mode == 'outbox':
        async with db.get_driver().session() as session:
            row = await (await session.run(
                "MATCH (e:CostOutbox) WHERE e.document CONTAINS $id "
                "RETURN e.id AS id, e.document AS document", id=event['event_id'])).single()
        assert row
        original = outbox.publish_confirmed
        def unavailable(event):
            raise RuntimeError('Injected broker failure')
        outbox.publish_confirmed = unavailable
        try:
            await outbox.publish_pending()
            raise AssertionError('Expected broker failure')
        except RuntimeError as exc:
            assert str(exc) == 'Injected broker failure'
        finally:
            outbox.publish_confirmed = original
        observer = Consumer({'bootstrap.servers': 'kafka:9092', 'group.id': str(uuid4()),
                             'enable.auto.commit': False})
        try:
            metadata = observer.list_topics('cost.events', timeout=10)
            parts = [TopicPartition('cost.events', n) for n in metadata.topics['cost.events'].partitions]
            observer.assign([TopicPartition(p.topic, p.partition,
                observer.get_watermark_offsets(p, timeout=10)[1]) for p in parts])
            producer.init_kafka_producer()
            document = json.loads(row['document'])
            producer.publish_confirmed(document)
            # Delivery happened, but simulate a crash before deleting its outbox
            # entry. Reopen storage, then use the actual outbox worker to retry.
            await db.close_neo4j()
            await db._init_driver()
            await outbox.publish_pending()
            matches = 0
            deadline = time.monotonic() + 20
            while matches < 2 and time.monotonic() < deadline:
                message = observer.poll(0.2)
                if message and not message.error():
                    received = json.loads(message.value())
                    if received['event_id'] == document['event_id']:
                        matches += 1
            assert matches == 2, matches
            async with db.get_driver().session() as session:
                exists = await (await session.run(
                    "MATCH (e:CostOutbox {id: $id}) RETURN e.id AS id", id=row['id'])).single()
                assert exists is None
        finally:
            observer.close()
            producer.close_kafka_producer()
    return {'applied': applied, **saved}

async def run():
    try:
        print(json.dumps(await main()), flush=True)
    finally:
        await db.close_neo4j()

asyncio.run(run())
'''


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True,
                          capture_output=True, timeout=120, **kwargs)


@pytest.fixture(scope="module", autouse=True)
def isolated_financial_worker():
    try:
        requests.get(f"{COST}/ready", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Financial service unavailable: {exc}")
        pytest.skip("Live stack not running")
    compose("stop", "cost-service", check=True)
    try:
        yield
    finally:
        compose("up", "-d", "--no-deps", "cost-service", check=True)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if requests.get(f"{COST}/ready", timeout=3).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            pytest.fail("Financial service did not recover after ledger validation")


def event():
    clock = requests.get(f"{SIM}/api/v1/sim/status", timeout=10).json()
    return {"event_id": f"financial-test-{uuid4()}", "event_type": "FlightStatusChanged",
            "sim_time": clock["sim_time"],
            "payload": {"flight_id": f"synthetic-{uuid4()}", "new_status": "departed",
                        "day_of_sim": clock.get("day_of_sim", clock.get("sim_day", 1))}}


def worker(mode, input_event, expected_code=0):
    result = compose("run", "--rm", "-T", "--no-deps", "cost-service", "python", "-c", WORKER,
                     input=json.dumps({"mode": mode, "event": input_event}))
    assert result.returncode == expected_code, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("mode", ["fail-records", "fail-outbox"])
def test_partial_financial_transaction_rolls_back_and_retries(mode):
    result = worker(mode, event())
    assert result == {"applied": True, "costs": 3, "carbon": 3, "inbox": 1}


def test_independent_workers_cannot_double_charge_same_event():
    candidate = event()
    worker("prepare", candidate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker("apply", candidate), range(2)))
    assert sorted(result["applied"] for result in results) == [False, True]
    assert all(result["costs"] == result["carbon"] == 3 and result["inbox"] == 1 for result in results)


def test_committed_gate_window_survives_process_crash_and_duplicate_replay():
    candidate = event()
    boarding = json.loads(json.dumps(candidate))
    boarding["event_id"] += "-boarding"
    boarding["payload"]["new_status"] = "boarding"
    boarding["sim_time"] = (datetime.fromisoformat(candidate["sim_time"].replace("Z", "+00:00"))
                            - timedelta(hours=1)).isoformat()
    assert worker("crash-after-commit", boarding, expected_code=23)["inbox"] == 1
    first = worker("apply", candidate)
    assert first == {"applied": True, "costs": 5, "carbon": 3, "inbox": 1}
    assert worker("apply", candidate) == {**first, "applied": False}


def test_outbox_survives_broker_failure_and_replays_same_id_after_ack_gap():
    assert worker("outbox", event()) == {"applied": True, "costs": 3, "carbon": 3, "inbox": 1}


def test_kafka_redelivery_is_acknowledged_after_service_restart_without_recharging():
    candidate = event()
    assert worker("apply", candidate)["applied"] is True
    compose("up", "-d", "--no-deps", "cost-service", check=True)
    compose("restart", "cost-service", check=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{COST}/ready", timeout=3).status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        pytest.fail("Financial consumer did not recover")
    assert worker("kafka-replay", candidate) == {"applied": False, "costs": 3, "carbon": 3, "inbox": 1}
