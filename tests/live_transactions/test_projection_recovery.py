"""G9 recovery under independent process exits, replicas and real Kafka."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess

import pytest

from tests.live_transactions.test_domain_transactions import ROOT, worker, pytestmark  # noqa: F401


def projection(mode, code=0, **args):
    result = subprocess.run([
        "docker", "compose", "run", "--rm", "-T", "--no-deps",
        "-v", f"{ROOT}/tests/live_transactions:/g1-tests:ro",
        "-v", f"{ROOT}/services/analysis-service:/g1-source:ro",
        "analysis-service", "python", "/g1-tests/projection_worker.py",
    ], cwd=ROOT, input=json.dumps({"mode": mode, **args}), text=True,
        capture_output=True, timeout=150)
    assert result.returncode == code, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1]) if code == 0 else None


@pytest.fixture
def discovery():
    worker("passenger", "seed")
    projection("seed")


def test_discovery_rollback_abrupt_exit_and_accepted_clock_startup(discovery):
    before = projection("snapshot")
    assert projection("fail") == before
    projection("exit-before-commit", code=27)
    assert projection("snapshot") == before
    recovered = projection("startup")
    assert recovered["document"]["bottlenecks"] and recovered["outbox"]
    assert projection("evaluate") == recovered
    projection("delivery")


def test_committed_exit_replay_competing_evaluators_and_replica_endpoints(discovery):
    projection("exit-after-commit", code=28)
    committed = projection("snapshot")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: projection("evaluate"), range(2)))
    assert results == [committed, committed]
    endpoints = projection("endpoints")
    assert endpoints["bottlenecks"]["bottlenecks"] == committed["document"]["bottlenecks"]
    assert endpoints["recommendations"]["recommendations"] == committed["document"]["recommendations"]
    projection("resolve")
    resolved = projection("evaluate")
    assert not resolved["document"]["bottlenecks"]
    assert resolved["document"]["clock_offset"] == committed["document"]["clock_offset"]


def test_new_offset_rewind_empty_reconciliation_and_old_clock_fencing(discovery):
    first = projection("evaluate")
    assert projection("clock", at="2100-01-01T11:00:00", offset=2)["accepted"]
    rewound = projection("evaluate")
    assert rewound["document"]["clock"]["sim_time"].startswith("2100-01-01T11:")
    assert not projection("clock", at="2100-01-01T12:00:00", offset=1)["accepted"]
    projection("clear")
    cleared = projection("evaluate")
    assert not cleared["document"]["bottlenecks"]
    assert not cleared["document"]["recommendations"]
    assert cleared["document"]["input_digest"] != first["document"]["input_digest"]


@pytest.mark.parametrize("speed", ["REALTIME", "BULK"])
def test_actual_owner_snapshots_reach_analysis_without_sampled_drift(speed):
    worker("flight", "seed", auxiliary=True)
    worker("flight", "tick", auxiliary=True, speed=speed)
    worker("flight", "delivery")
    worker("passenger", "tick", speed=speed)
    worker("passenger", "delivery")
    worker("baggage", "tick", speed=speed)
    worker("baggage", "delivery")
    projection("owner-contract")


@pytest.mark.parametrize("owner", ["flight", "passenger", "baggage"])
def test_owner_checkpoint_is_available_before_first_new_tick(owner):
    worker(owner, "seed", auxiliary=owner == "flight")
    committed = worker(owner, "tick", auxiliary=owner in {"flight", "baggage"})
    startup = worker(owner, "startup")
    assert startup["checkpoint"] == json.loads(committed["runtime"][0]["document"])
    assert startup["sim_time"] == committed["runtime"][0]["tick"]
