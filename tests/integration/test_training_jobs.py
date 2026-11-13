"""G7: durable training-run leases, fencing and crash recovery against real Neo4j.

Independent ``analysis-service`` worker processes exercise
``services.training_store`` directly. The long-running analysis service is
stopped for the duration so its recovery loop cannot claim synthetic runs.
No PPO training is launched by these checks.
"""

import json
import os
from pathlib import Path
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = os.getenv("ANALYSIS_SVC_URL", "http://localhost:8007")

WORKER = r'''
import asyncio, json, os, sys, time
from db import neo4j as db
from services import training_store as store

args = json.load(sys.stdin)
rid, mode = args['id'], args['mode']

async def main():
    await db.init_neo4j()
    await store.initialize()
    try:
        if mode == 'prepare':
            await store.create({'id': rid, 'model_type': 'rl', 'status': 'queued', 'total_timesteps': 1000,
                                'seed': 5, 'attempt_count': 0})
            return {'prepared': True}
        if mode == 'claim':
            claimed = await store.claim(args['token'], 30, run_id=rid)
            return {'claimed': claimed is not None}
        if mode == 'crash':
            claimed = await store.claim('crashed-owner', 2, run_id=rid)
            assert claimed and claimed['attempt_count'] == 1
            claimed['current_timesteps'] = 400
            assert await store.save(claimed, 'crashed-owner', 2)
            print(json.dumps({'attempt': 1}), flush=True)
            os._exit(23)
        if mode == 'recover':
            time.sleep(2.5)  # the crashed owner's 2 s lease has certainly expired
            claimed = await store.claim('new-owner', 30, run_id=rid)
            assert claimed and claimed['attempt_count'] == 2 and claimed['seed'] == 5
            assert claimed['current_timesteps'] == 400
            stale = dict(claimed, current_timesteps=999)
            assert not await store.save(stale, 'crashed-owner', 30), 'stale owner wrote progress'
            assert not await store.finish(dict(claimed, status='completed'), 'crashed-owner')
            assert await store.finish(dict(claimed, status='completed'), 'new-owner')
            assert await store.claim('anyone', 30, run_id=rid) is None, 'completed run reclaimed'
            return {'recovered': True}
        if mode == 'release':
            claimed = await store.claim('graceful', 30, run_id=rid)
            assert claimed
            assert await store.release(claimed, 'graceful')
            again = await store.claim('next', 30, run_id=rid)
            assert again and again['attempt_count'] == 2
            assert await store.finish(dict(again, status='stopped'), 'next')
            return {'released': True}
        if mode == 'cleanup':
            async with db.get_driver().session() as session:
                await (await session.run('MATCH (r:TrainingRun {id: $id}) DETACH DELETE r', id=rid)).consume()
            return {'deleted': True}
    finally:
        await db.close_neo4j()

print(json.dumps(asyncio.run(main())), flush=True)
'''


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True,
                          capture_output=True, timeout=180, **kwargs)


def ready():
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{ANALYSIS}/ready", timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    pytest.fail("analysis-service failed to become ready")


@pytest.fixture(scope="module", autouse=True)
def isolated_training():
    try:
        requests.get(f"{ANALYSIS}/ready", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"analysis-service unavailable: {exc}")
        pytest.skip("Live stack not running")
    compose("stop", "analysis-service", check=True)
    try:
        yield
    finally:
        compose("up", "-d", "--no-deps", "analysis-service", check=True)
        ready()


def worker(mode, rid, expected_code=0, **extra):
    result = compose("run", "--rm", "-T", "--no-deps", "analysis-service", "python", "-c", WORKER,
                     input=json.dumps({"mode": mode, "id": rid, **extra}))
    assert result.returncode == expected_code, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_independent_workers_claim_a_training_run_once():
    rid = f"train-test-{uuid4()}"
    worker("prepare", rid)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda n: worker("claim", rid, token=f"owner-{n}"), range(2)))
        assert sorted(r["claimed"] for r in results) == [False, True]
    finally:
        worker("cleanup", rid)


def test_abrupt_owner_exit_is_recovered_and_stale_owner_fenced():
    rid = f"train-test-{uuid4()}"
    worker("prepare", rid)
    try:
        assert worker("crash", rid, expected_code=23) == {"attempt": 1}
        assert worker("recover", rid) == {"recovered": True}
    finally:
        worker("cleanup", rid)


def test_graceful_release_requeues_with_next_attempt():
    rid = f"train-test-{uuid4()}"
    worker("prepare", rid)
    try:
        assert worker("release", rid) == {"released": True}
    finally:
        worker("cleanup", rid)
