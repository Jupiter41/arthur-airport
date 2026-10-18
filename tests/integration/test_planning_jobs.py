"""Durable planning worker ownership and crash recovery against real Neo4j."""

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
PLANNING = os.getenv("PLANNING_SVC_URL", "http://localhost:8009")

WORKER = r'''
import json, os, sys, time
from db import store
from engine.infrastructure import InfrastructureConfig
from scenarios import jobs, model

args = json.load(sys.stdin)
store.initialize()
repository = store.get_repository()
sid, mode = args['id'], args['mode']
try:
    if mode in ('prepare', 'crash'):
        scenario = model.PlanningScenario(id=sid, name='Synthetic durable-job validation', random_seed=0,
            infrastructure=InfrastructureConfig(daily_flight_target=20))
        model.store_scenario(scenario)
        if mode == 'prepare':
            print(json.dumps({'prepared': True}))
            sys.exit(0)
    if mode == 'cleanup':
        assert repository.delete('PlanningScenario', sid)
        print(json.dumps({'deleted': True}))
        sys.exit(0)
    claimed = jobs.claim(sid, seconds=2 if mode in ('crash', 'heartbeat') else 30)
    if mode == 'claim':
        print(json.dumps({'claimed': claimed is not None,
            'seed': claimed[1]['random_seed'] if claimed else None}))
        sys.exit(0)
    assert claimed
    lease, document = claimed
    if mode == 'crash':
        document.update(progress_pct=50, runs_completed=1)
        lease.save(document)
        print(json.dumps({'seed': document['random_seed'], 'attempt': document['attempt_count']}), flush=True)
        os._exit(23)
    if mode == 'heartbeat':
        lease.start()
        try:
            time.sleep(3)
            assert jobs.claim(sid) is None, 'An active heartbeat did not protect ownership'
            lease.save(document)
        finally:
            lease.close()
        lease.release()
    if mode == 'fence':
        old = lease
        with repository.driver.session() as session:
            session.run('MATCH (s:PlanningScenario {id: $id}) SET s.lease_until = 0', id=sid).consume()
        lease, replacement = jobs.claim(sid)
        assert replacement['random_seed'] == document['random_seed']
        assert replacement['attempt_count'] == 2
        completed = dict(replacement, status='completed', progress_pct=100)
        results = {'scenario_id': sid, 'kpis': {'synthetic': {'mean': 1}}}
        for action in (lambda: old.save(document), lambda: old.finish(completed, results)):
            try:
                action()
                raise AssertionError('Stale owner was allowed to publish')
            except jobs.LeaseLost:
                pass
        lease.finish(completed, results)
        assert model.get_results(sid) == results
    if mode == 'atomic':
        completed = dict(document, status='completed', progress_pct=100)
        results = {'scenario_id': sid, 'kpis': {'synthetic': {'mean': 1}}}
        original = repository.write_outbox
        def fail(tx, event):
            original(tx, event)
            raise RuntimeError('Injected completion failure')
        repository.write_outbox = fail
        try:
            lease.finish(completed, results)
            raise AssertionError('Expected failure')
        except RuntimeError as exc:
            assert str(exc) == 'Injected completion failure'
        finally:
            repository.write_outbox = original
        assert model.get_results(sid) is None
        assert model.get_scenario(sid).status == 'running'
        lease.finish(completed, results)
        assert model.get_scenario(sid).status == 'completed'
        assert model.get_results(sid) == results
    assert repository.delete('PlanningScenario', sid)
    print(json.dumps({'validated': mode}), flush=True)
finally:
    store.close()
'''


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True,
                          capture_output=True, timeout=120, **kwargs)


def ready():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{PLANNING}/ready", timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    pytest.fail("Planning worker failed to become ready")


@pytest.fixture(scope="module", autouse=True)
def isolated_queue():
    try:
        requests.get(f"{PLANNING}/ready", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Planning service unavailable: {exc}")
        pytest.skip("Live stack not running")
    compose("stop", "planning-service", check=True)
    try:
        yield
    finally:
        compose("up", "-d", "--no-deps", "planning-service", check=True)
        ready()


def worker(mode, sid, expected_code=0):
    result = compose("run", "--rm", "-T", "--no-deps", "planning-service", "python", "-c", WORKER,
                     input=json.dumps({"mode": mode, "id": sid}))
    assert result.returncode == expected_code, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("mode", ["fence", "atomic", "heartbeat"])
def test_real_job_lease_fencing_atomicity_and_heartbeat(mode):
    sid = f"job-test-{uuid4()}"
    worker("prepare", sid)
    assert worker(mode, sid) == {"validated": mode}


def test_independent_workers_only_claim_once():
    sid = f"job-test-{uuid4()}"
    worker("prepare", sid)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker("claim", sid), range(2)))
        assert sorted(result["claimed"] for result in results) == [False, True]
        assert next(result["seed"] for result in results if result["claimed"]) == 0
    finally:
        worker("cleanup", sid)


def test_service_automatically_recovers_an_expired_job_after_worker_process_exit():
    sid = f"job-test-{uuid4()}"
    crashed = worker("crash", sid, expected_code=23)
    assert crashed == {"seed": 0, "attempt": 1}
    compose("up", "-d", "--no-deps", "planning-service", check=True)
    ready()
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        scenario = requests.get(f"{PLANNING}/api/v1/planning/scenarios/{sid}", timeout=10).json()
        if scenario["status"] == "completed":
            break
        assert scenario["status"] != "failed", scenario
        time.sleep(1)
    else:
        pytest.fail("Interrupted planning job was not automatically recovered")
    assert scenario["random_seed"] == 0 and scenario["attempt_count"] == 2
    assert scenario["progress_pct"] == 100
    assert scenario["infrastructure"]["daily_flight_target"] == 20
    result = requests.get(f"{PLANNING}/api/v1/planning/scenarios/{sid}/results", timeout=10)
    assert result.status_code == 200 and result.json()["kpis"]
    deleted = requests.delete(f"{PLANNING}/api/v1/planning/scenarios/{sid}", timeout=10)
    assert deleted.status_code == 200
