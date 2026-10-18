"""Real proposal transactions, independent workers and acknowledged outbox recovery."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = os.getenv("ANALYSIS_SVC_URL", "http://localhost:8007")
SIM = os.getenv("SIM_SVC_URL", "http://localhost:8006")

WORKER = r'''
import asyncio, json, os, sys, time
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import uuid4
from confluent_kafka import Consumer, TopicPartition
from db import neo4j as db
from services import approval_queue, proposal_store as store, action_outbox as outbox
from kafka import producer

args = json.load(sys.stdin)
async def run():
    await db.init_neo4j()
    try:
        await store.initialize()
        clock = datetime.fromisoformat(args['clock'].replace('Z', '+00:00'))
        mode, ident = args['mode'], args['id']
        if mode == 'cleanup':
            async with db.get_driver().session() as session:
                await (await session.run("MATCH (p:ActionProposal) WHERE p.id STARTS WITH 'proposal-test-' DELETE p")).consume()
                await (await session.run("MATCH (e:AnalysisOutbox) WHERE e.document CONTAINS 'proposal-test-' DELETE e")).consume()
            return {'cleaned': True}
        if mode in ('create', 'rollback-create'):
            p = approval_queue.propose(action_type='open_security_lane', description='Synthetic proposal test',
                parameters={'terminal': 'B', 'new_lane_count': args.get('lanes', 5)}, confidence_score=0.9,
                proposed_by='operator', proposed_at=clock, requires_human=True,
                recommendation_id=args.get('recommendation', ident), bottleneck_id=args.get('target', ident))
            p.id = ident
            async def mutation():
                return await store.create(asdict(p), clock)
        elif mode in ('approve', 'retry', 'crash', 'rollback-approve'):
            async def mutation():
                return await store.dispatch(ident, clock + timedelta(minutes=5 if mode == 'retry' else 0), approve_by='operator')
        elif mode in ('reject', 'rollback-reject'):
            async def mutation():
                return await store.reject(ident, clock, 'operator', 'synthetic rejection')
        elif mode in ('receipt', 'rollback-receipt'):
            async def mutation():
                return await store.receipt('CommandExecuted', {'command_id': ident,
                    'command_type': 'OpenSecurityLane'}, clock, 'passengers.events')
        elif mode == 'confirmed-dispatch':
            async def mutation():
                from services.action_execution import dispatch
                document = next(d for d in await store.list_documents() if d['id'] == ident)
                document['status'] = 'dispatched'  # A stale snapshot in another worker.
                return await dispatch(approval_queue.Proposal(**document), clock)
        else:
            async def mutation():
                return None
        if mode.startswith('rollback-'):
            before = [d for d in await store.list_documents() if d['id'] == ident]
            async def pending():
                async with db.get_driver().session() as session:
                    return await (await session.run("MATCH (e:AnalysisOutbox) WHERE e.document CONTAINS $id "
                        "RETURN e.id AS id, e.document AS document ORDER BY e.id", id=ident)).data()
            before_outbox = await pending()
            original = store._outbox
            async def fail(*values):
                await original(*values)
                raise RuntimeError('Injected failure after outbox writes')
            store._outbox = fail
            try:
                await mutation()
                raise AssertionError('Expected rollback')
            except RuntimeError as exc:
                assert str(exc) == 'Injected failure after outbox writes'
            finally:
                store._outbox = original
            assert [d for d in await store.list_documents() if d['id'] == ident] == before
            assert await pending() == before_outbox
            return {'rolled_back': True}
        result = await mutation()
        if mode == 'crash':
            print(json.dumps(result), flush=True)
            os._exit(23)
        if mode == 'outbox':
            async with db.get_driver().session() as session:
                row = await (await session.run("MATCH (e:AnalysisOutbox) WHERE e.document CONTAINS $id "
                    "AND e.topic = 'analysis.events' RETURN e.id AS id, e.document AS document, "
                    "e.topic AS topic, e.key AS key ORDER BY e.revision, e.position LIMIT 1", id=ident)).single()
            assert row
            original = outbox.publish_confirmed
            outbox.publish_confirmed = lambda *args: (_ for _ in ()).throw(RuntimeError('Injected broker failure'))
            try:
                await outbox.publish_pending()
                raise AssertionError('Expected broker failure')
            except RuntimeError as exc:
                assert str(exc) == 'Injected broker failure'
            finally:
                outbox.publish_confirmed = original
            observer = Consumer({'bootstrap.servers': 'kafka:9092', 'group.id': str(uuid4()), 'enable.auto.commit': False})
            producer.init_kafka_producer()
            try:
                metadata = observer.list_topics('analysis.events', timeout=10)
                parts = [TopicPartition('analysis.events', n) for n in metadata.topics['analysis.events'].partitions]
                observer.assign([TopicPartition(p.topic, p.partition, observer.get_watermark_offsets(p, timeout=10)[1]) for p in parts])
                document = json.loads(row['document'])
                producer.publish_confirmed(row['topic'], row['key'], document)
                # Broker accepted the fact; simulate loss before its outbox deletion.
                await db.close_neo4j()
                await db.init_neo4j()
                await outbox.publish_pending()
                matches, deadline = 0, time.monotonic() + 20
                while matches < 2 and time.monotonic() < deadline:
                    message = observer.poll(0.2)
                    if message and not message.error() and json.loads(message.value()).get('event_id') == document['event_id']:
                        matches += 1
                assert matches == 2, matches
                async with db.get_driver().session() as session:
                    assert await (await session.run('MATCH (e:AnalysisOutbox {id: $id}) RETURN e.id', id=row['id'])).single() is None
                result = {'replayed': True}
            finally:
                observer.close()
                producer.close_kafka_producer()
        if mode == 'inspect':
            result = next(d for d in await store.list_documents() if d['id'] == ident)
            async with db.get_driver().session() as session:
                rows = await (await session.run("MATCH (e:AnalysisOutbox) WHERE e.document CONTAINS $id "
                    "AND e.topic ENDS WITH '.commands' RETURN e.document AS document", id=ident)).data()
            result['commands'] = [json.loads(row['document']) for row in rows]
        return result
    finally:
        await db.close_neo4j()
print(json.dumps(asyncio.run(run())), flush=True)
'''


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True,
                          capture_output=True, timeout=120, **kwargs)


def worker(mode, candidate, expected_code=0, **extra):
    result = compose("run", "--rm", "-T", "--no-deps", "analysis-service", "python", "-c", WORKER,
                     input=json.dumps({**candidate, **extra, "mode": mode}))
    assert result.returncode == expected_code, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def ready():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{ANALYSIS}/ready", timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    pytest.fail("Analysis service did not recover")


@pytest.fixture(scope="module", autouse=True)
def isolated_analysis_worker():
    try:
        requests.get(f"{ANALYSIS}/ready", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Analysis unavailable: {exc}")
        pytest.skip("Live stack not running")
    compose("stop", "analysis-service", check=True)
    try:
        yield
    finally:
        worker("cleanup", candidate())
        compose("up", "-d", "--no-deps", "analysis-service", check=True)
        ready()


def candidate():
    clock = requests.get(f"{SIM}/api/v1/sim/status", timeout=10).json()["sim_time"]
    flow = requests.get(f"{os.getenv('PASSENGER_SVC_URL', 'http://localhost:8002')}/api/v1/flow/summary", timeout=10).json()
    return {"id": f"proposal-test-{uuid4()}", "clock": clock, "lanes": flow["security"]["B"]["lanes_open"]}


@pytest.mark.parametrize("mutation", ["create", "approve", "reject", "receipt"])
def test_partial_proposal_transaction_rolls_back(mutation):
    item = candidate()
    if mutation != "create":
        worker("create", item)
    if mutation == "receipt":
        worker("approve", item)
    assert worker(f"rollback-{mutation}", item) == {"rolled_back": True}


def test_independent_workers_coordinate_creation_approval_and_retry():
    item = candidate()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker("create", item, id=f"proposal-test-{uuid4()}",
            target=item["id"], recommendation=item["id"]), range(2)))
    assert results[0]["id"] == results[1]["id"]
    item["id"] = results[0]["id"]
    for mode, expected in (("approve", 1), ("retry", 2)):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: worker(mode, item), range(2)))
        state = worker("inspect", item)
        assert state["dispatch_attempts"] == len(state["commands"]) == expected
        assert {c["command_id"] for c in state["commands"]} == {item["id"]}
    assert worker("reject", item) is None
    assert worker("receipt", item)["status"] == "executed"
    assert worker("approve", item) is None
    assert worker("confirmed-dispatch", item)["executed"] is True
    assert len(worker("inspect", item)["commands"]) == 2



def test_independent_approval_and_rejection_have_one_winner():
    item = candidate()
    worker("create", item)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda mode: worker(mode, item), ("approve", "reject")))
    assert sum(result is not None for result in results) == 1
    state = worker("inspect", item)
    assert state["status"] in {"dispatched", "rejected"}
    assert len(state["commands"]) == (1 if state["status"] == "dispatched" else 0)


def test_analysis_outbox_replays_same_event_after_broker_failure_and_ack_gap():
    item = candidate()
    worker("create", item)
    assert worker("outbox", item) == {"replayed": True}


def test_committed_command_survives_process_crash_and_owner_receipt():
    # Request the existing capacity so the test leaves operational settings intact.
    checkpoints = requests.get(f"{os.getenv('PASSENGER_SVC_URL', 'http://localhost:8002')}/api/v1/flow/summary", timeout=10).json()
    checkpoint = checkpoints["security"]["B"]
    item = {**candidate(), "lanes": checkpoint["lanes_open"]}
    worker("create", item)
    assert worker("crash", item, expected_code=23)["status"] == "dispatched"
    compose("up", "-d", "--no-deps", "analysis-service", check=True)
    try:
        ready()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            log = requests.get(f"{ANALYSIS}/api/v1/analysis/autonomous/log?limit=200", timeout=5).json()
            if any(action["proposal_id"] == item["id"] for action in log["actions"]):
                break
            time.sleep(1)
        else:
            pytest.fail("Committed command was not confirmed by its owner after restart")
        assert worker("inspect", item)["status"] == "executed"
    finally:
        compose("stop", "analysis-service", check=True)
