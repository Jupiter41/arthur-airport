"""Fail-closed G1 tests; run only against a disposable infra-only Compose stack.

Every operation executes the real owner adapter in an independent process with
real Neo4j transactions and (delivery/replay cases) a real Kafka broker.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
OWNERS = ("flight", "passenger", "baggage")
pytestmark = pytest.mark.skipif(
    os.getenv("G1_DISPOSABLE_STACK") != "1" and os.getenv("REQUIRE_LIVE_STACK") != "1",
    reason="Requires the disposable G1 Neo4j/Kafka stack",
)


def worker(owner, mode, *, command=False, code=0, auxiliary=False, speed="REALTIME", minute=0):
    assert os.getenv("G1_DISPOSABLE_STACK") == "1", "Set G1_DISPOSABLE_STACK=1 for an isolated infra-only stack"
    result = subprocess.run([
        "docker", "compose", "run", "--rm", "-T", "--no-deps",
        "-v", f"{ROOT}/tests/live_transactions:/g1-tests:ro",
        "-v", f"{ROOT}/services/{owner}-service:/g1-source:ro",
        f"{owner}-service", "python", "/g1-tests/worker.py",
    ], cwd=ROOT, input=json.dumps({"owner": owner, "mode": mode, "command": command,
            "auxiliary": auxiliary, "speed": speed, "minute": minute}),
        text=True, capture_output=True, timeout=150)
    assert result.returncode == code, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1]) if code == 0 else None


@pytest.fixture(params=OWNERS)
def owner(request):
    worker(request.param, "seed")
    return request.param


def test_partial_tick_rolls_back_domain_checkpoint_and_outbox(owner):
    before = worker(owner, "snapshot")
    assert worker(owner, "fail") == before
    after = worker(owner, "tick")
    assert after["entities"] != before["entities"]
    assert after["facts"] and after["runtime"][0]["tick"] == "2100-01-01T12:00:00"


def test_process_exit_mid_tick_then_resume(owner):
    before = worker(owner, "snapshot")
    worker(owner, "exit-before-commit", code=27)
    assert worker(owner, "snapshot") == before
    after = worker(owner, "tick")
    assert after["facts"]
    assert worker(owner, "tick") == after


def test_process_exit_after_commit_does_not_reapply(owner):
    worker(owner, "exit-after-commit", code=28)
    committed = worker(owner, "snapshot")
    assert committed["facts"]
    assert worker(owner, "tick") == committed


def test_competing_tick_workers_commit_one_advancement(owner):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(owner, "tick"), range(2)))
    assert results[0] == results[1]
    assert results[0]["facts"]
    assert worker(owner, "tick") == results[0]


def test_receipt_and_domain_mutation_survive_competing_commands(owner):
    worker(owner, "seed", command=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: worker(owner, "command"), range(2)))
    after = worker(owner, "snapshot")
    assert after["receipts"] == [{"id": "g1-command", "kind": "CommandExecuted"}]
    docs = [json.loads(f["document"]) for f in after["facts"]]
    domain_kind = {"flight": "FlightStatusChanged", "passenger": "SecurityLanesChanged", "baggage": "BaggageStatusChanged"}[owner]
    assert sum(d["event_type"] == domain_kind for d in docs) == 1
    assert any(d["event_type"] == "CommandExecuted" for d in docs)
    worker(owner, "command")
    assert worker(owner, "snapshot")["entities"] == after["entities"]


def test_broker_failure_retains_facts_and_ack_gap_replays_stable_ids(owner):
    worker(owner, "tick")
    worker(owner, "delivery")


def test_real_kafka_input_replay_preserves_owner_checkpoint(owner):
    worker(owner, "replay")


def test_command_failure_rolls_back_mutation_receipt_and_facts(owner):
    worker(owner, "seed", command=True)
    before = worker(owner, "snapshot")
    assert worker(owner, "fail-command") == before
    after = worker(owner, "command")
    assert after["entities"] != before["entities"] or owner == "passenger"
    assert after["receipts"] == [{"id": "g1-command", "kind": "CommandExecuted"}]


@pytest.mark.parametrize("speed", ["REALTIME", "BULK"])
def test_flight_turnaround_vehicles_fuel_and_snapshots_share_tick_boundary(speed):
    worker("flight", "seed", auxiliary=True)
    before = worker("flight", "snapshot")
    assert worker("flight", "fail", auxiliary=True, speed=speed) == before
    after = worker("flight", "tick", auxiliary=True, speed=speed)
    kinds = {json.loads(row["document"])["event_type"] for row in after["facts"]}
    assert {"MinimumFuelWarning", "TurnaroundTaskStarted", "GroundVehicleDispatched"} <= kinds
    if speed == "BULK":
        assert "BulkStateSnapshot" in kinds
    after = worker("flight", "tick", auxiliary=True, speed=speed, minute=30)
    assert any(json.loads(row["document"])["event_type"] == "GroundVehicleReturned" for row in after["facts"])
    assert worker("flight", "tick", auxiliary=True, speed=speed, minute=30) == after


def test_live_passenger_ticks_and_lane_commands_do_not_invert_runtime_locks():
    worker("passenger", "seed")
    result = worker("passenger", "mixed")
    assert len(result["receipts"]) == 10
    assert all(row["kind"] == "CommandExecuted" for row in result["receipts"])
    assert result["runtime"][0]["tick"] == "2100-01-01T12:09:00"


def test_replayed_baggage_tick_retains_new_incident_and_arrival_projection():
    worker("baggage", "seed")
    worker("baggage", "replay-inputs")
