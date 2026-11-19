"""RC11 closure gate: late commit errors and bounded six-hour recovery after crash."""
from datetime import datetime, timedelta
import json
import os
import subprocess

import pytest

from tests.live_transactions.test_domain_transactions import ROOT

pytestmark = pytest.mark.skipif(os.getenv("G1_DISPOSABLE_STACK") != "1", reason="Disposable G1 infrastructure required")


def worker(owner, mode, code=0, **params):
    service = "sim-orchestrator" if owner == "sim" else owner + "-service"
    result = subprocess.run([
        "docker", "compose", "run", "--rm", "-T", "--no-deps", "-e", "G1_DISPOSABLE_STACK=1",
        "-v", f"{ROOT}/tests/live_transactions:/g1-tests:ro",
        "-v", f"{ROOT}/services/{service}:/g1-source:ro",
        service, "python", "/g1-tests/rc11_worker.py",
    ], input=json.dumps({"owner":owner,"mode":mode,**params}), text=True, capture_output=True, cwd=ROOT, timeout=180)
    assert result.returncode == code, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    if code == 0:
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "event" not in value:
                return value
    return None


@pytest.mark.parametrize("owner", ["passenger", "baggage"])
def test_six_hour_backlog_resumes_after_partial_failure_in_bounded_transactions(owner):
    worker(owner, "seed")
    worker(owner, "anchor")
    worker(owner, "fail", code=27)
    partial = worker(owner, "snapshot")
    assert partial["checkpoint"] == [{"at":"2100-01-01T12:15:00"}]
    assert len(partial["ticks"]) == 3
    worker(owner, "advance")
    after = worker(owner, "snapshot")
    assert after["checkpoint"] == [{"at":"2100-01-01T18:00:00"}]
    assert len(after["ticks"]) == 72
    previous = datetime(2100, 1, 1, 12)
    for row in after["ticks"]:
        at = datetime.fromisoformat(row["at"])
        assert timedelta(0) < at - previous <= timedelta(minutes=5)
        previous = at
    assert after["facts"][0]["n"] > 0
    expected = "departed_airport" if owner == "passenger" else "collected"
    entity = "g1-rc11-pax" if owner == "passenger" else "g1-rc11-bag"
    assert next(r["status"] for r in after["entities"] if r["id"] == entity) == expected
    worker(owner, "advance")
    assert worker(owner, "snapshot") == after


@pytest.mark.parametrize("failures,paused,controls", [(2,False,1),(3,True,0)])
def test_real_checkpoint_commit_ack_loss_retries_or_pauses_without_false_control_ack(failures, paused, controls):
    result = worker("sim", "clock", failures=failures)
    assert result["attempts"] == 3 and result["paused"] is paused
    assert result["controls"] == controls
    assert result["state"] == [{"at":"2100-01-01T12:00:00","tick":0}]


@pytest.mark.parametrize("owner", ["passenger", "baggage"])
def test_hot_recovery_query_ignores_unrelated_live_history(owner):
    result = worker(owner, "profile")
    assert result["history_entities"] == 40000 and result["hits"] < 200
    print(json.dumps({"owner": owner, **result}))


def test_real_midnight_callback_retries_after_background_and_inline_failure():
    assert worker("sim", "barrier") == {"attempts":2,"retried_consumed_task":True}
