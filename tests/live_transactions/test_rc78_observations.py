"""Required RC8/RC12 ACK/crash/replay and expired-offset recovery evidence."""
import json
import os
import subprocess
from uuid import uuid4

import pytest

from tests.live_transactions.test_domain_transactions import ROOT

pytestmark = pytest.mark.skipif(os.getenv("G1_DISPOSABLE_STACK") != "1", reason="Disposable G1 stack required")


def worker(mode, code=0, **params):
    result = subprocess.run([
        "docker", "compose", "run", "--rm", "-T", "--no-deps", "-e", "G1_DISPOSABLE_STACK=1",
        "-v", f"{ROOT}/tests/live_transactions:/g1-tests:ro",
        "-v", f"{ROOT}/services/passenger-service:/g1-source:ro",
        "passenger-service", "python", "/g1-tests/rc78_worker.py",
    ], input=json.dumps({"mode": mode, **params}), text=True, capture_output=True, cwd=ROOT, timeout=120)
    assert result.returncode == code, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    return json.loads(lines[-1]) if code == 0 and lines else None


@pytest.mark.parametrize("batch", [False, True], ids=["per-bag", "bulk-batch"])
def test_collection_survives_ack_then_process_death_before_a_tick(batch):
    worker("seed")
    source = worker("publish", batch=batch)
    group = "g1-rc78-" + uuid4().hex
    worker("consume-exit", code=29, batch=batch, group=group, **source)
    before = worker("snapshot")
    assert before["observations"][0]["o"]["collected_at"] == "2100-01-01T12:00:00"
    assert all(r["tick"] is None for r in before["runtime"])
    worker("replay", batch=batch, group=group, **source)
    assert worker("snapshot") == before
    worker("advance", batch=batch)
    after = worker("snapshot")
    assert after["passengers"][0]["p"]["status"] == "departed_airport"
    assert after["passengers"][0]["p"]["departed_airport_at"] == "2100-01-01T12:01:00"


def test_rollback_and_bag_before_passenger_then_claim_exit():
    worker("seed", absent=True)
    before = worker("snapshot")
    worker("fail-observe")
    rolled_back = worker("snapshot")
    assert rolled_back["observations"] == before["observations"] == []
    assert rolled_back["facts"] == before["facts"] == []
    worker("observe")
    assert worker("snapshot")["observations"]
    worker("add-passenger")
    worker("advance")
    assert worker("snapshot")["passengers"][0]["p"]["status"] == "departed_airport"


def test_expired_offset_bootstrap_rebuilds_collection_without_replaying_input():
    worker("seed")
    assert not worker("snapshot")["observations"]
    assert worker("bootstrap")["n"] == 1
    before = worker("snapshot")
    assert worker("bootstrap")["n"] == 1
    assert worker("snapshot") == before
    worker("advance")
    assert worker("snapshot")["passengers"][0]["p"]["status"] == "departed_airport"


def test_early_carousel_stays_deplaning_until_claim_and_survives_restart():
    worker("seed", passenger_status="deplaning")
    worker("observe", status="on_carousel")
    before = worker("snapshot")
    assert before["passengers"][0]["p"]["location_zone"] == "arrivals-hall"
    worker("advance", minute=1)
    assert worker("snapshot")["passengers"][0]["p"]["status"] == "deplaning"
    worker("advance", minute=6)
    after = worker("snapshot")["passengers"][0]["p"]
    assert after["status"] == "baggage_claim" and after["location_zone"] == "carousel-3"


def test_owner_allocates_unique_tags_for_colliding_provisional_manifests():
    worker("seed")
    assert len(worker("tags")) == 3


@pytest.mark.parametrize("absent", [True, False], ids=["orphan", "active"])
def test_observation_retention_expires_only_orphans(absent):
    worker("seed", absent=absent)
    worker("observe")
    assert worker("purge-orphans")["n"] == int(absent)
    after = worker("snapshot")
    assert bool(after["observations"]) is not absent
    if absent:
        assert any(f["event_type"] == "PassengerBaggageObservationsPurged" for f in after["facts"])


def test_actual_bulk_planner_fact_reaches_claimant_after_ack_and_restart():
    worker("seed", bag_status="on_carousel")
    result = subprocess.run([
        "docker", "compose", "run", "--rm", "-T", "--no-deps", "-e", "G1_DISPOSABLE_STACK=1",
        "-v", f"{ROOT}/tests/live_transactions:/g1-tests:ro",
        "-v", f"{ROOT}/services/baggage-service:/g1-source:ro",
        "baggage-service", "python", "/g1-tests/rc78_baggage_worker.py",
    ], text=True, capture_output=True, cwd=ROOT, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    source = json.loads(result.stdout.strip().splitlines()[-1])
    worker("consume-exit", code=29, group="g1-rc78-" + uuid4().hex, **source)
    worker("advance", batch=True)
    assert worker("snapshot")["passengers"][0]["p"]["status"] == "departed_airport"
