"""RC1 closure: actual owner transactions across independent worker restarts.

Run on an isolated Neo4j-only Compose project; Kafka is unnecessary because the
atomic outbox rows are inspected directly. No application workarounds are used.
"""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.getenv("G1_DISPOSABLE_STACK") != "1",
                                reason="Requires isolated RC1 Neo4j")


def worker(owner, mode, **params):
    result = subprocess.run([
        "docker", "compose", "run", "--rm", "-T", "--no-deps",
        "-e", "G1_DISPOSABLE_STACK=1",
        "-v", f"{ROOT}/tests/live_transactions:/g1-tests:ro",
        "-v", f"{ROOT}/services/{owner}-service:/g1-source:ro",
        f"{owner}-service", "python", "/g1-tests/rc1_worker.py",
    ], input=json.dumps({"owner": owner, "mode": mode, **params}),
        cwd=ROOT, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    return json.loads(lines[-1]) if lines else None


def test_missed_connection_archive_rollback_restart_and_purge():
    owner = "passenger"
    worker(owner, "seed")
    before = worker(owner, "snapshot")
    worker(owner, "rollback-archive")
    assert worker(owner, "snapshot") == before
    assert worker(owner, "archive")["count"] == 1
    after = worker(owner, "snapshot")
    nodes = {n["id"]: n for n in after["nodes"]}
    assert "PassengerArchive" in nodes["g1-rc1-old"]["labels"]
    for name in ("edge", "young", "active"):
        assert "Passenger" in nodes["g1-rc1-" + name]["labels"]
    assert after["links"] == before["links"]
    facts = [f for f in after["facts"] if f["event_type"] == "EntitiesArchived"]
    assert any(f["payload"]["ids"] == ["g1-rc1-old"] for f in facts)
    assert worker(owner, "archive")["count"] == 0  # independent process replay
    assert worker(owner, "purge", hours=168)["count"] == 0  # strict cutoff
    assert worker(owner, "purge", hours=169)["count"] == 1
    final = worker(owner, "snapshot")
    assert len(final["nodes"]) == 3
    assert any(f["event_type"] == "EntitiesPurged" and f["payload"]["count"] == 1 for f in final["facts"])


def test_old_diverted_holds_recover_archive_and_purge_across_restarts():
    owner = "baggage"
    worker(owner, "seed")
    before = worker(owner, "snapshot")
    worker(owner, "rollback-recovery")
    assert worker(owner, "snapshot") == before
    worker(owner, "recover")
    after = worker(owner, "snapshot")
    nodes = {n["id"]: n for n in after["nodes"]}
    assert nodes["g1-rc1-held"]["p"]["status"] == "diverted"
    assert nodes["g1-rc1-held"]["p"]["last_scan_at"] == "2100-01-10T12:00:00"
    assert nodes["g1-rc1-active"]["p"]["status"] == "in_hold"
    facts = [f for f in after["facts"] if f["event_type"] == "BaggageStatusChanged"]
    assert any(f["payload"].get("passenger_id") == "g1-rc1-pax" and
               f["payload"]["new_status"] == "diverted" for f in facts)
    assert len(after["scans"]) == 2
    worker(owner, "recover")
    assert worker(owner, "snapshot") == after
    assert worker(owner, "archive", hours=24)["count"] == 0
    worker(owner, "rollback-archive", hours=25)
    assert worker(owner, "snapshot") == after
    assert worker(owner, "archive", hours=25)["count"] == 1
    archived = worker(owner, "snapshot")
    assert archived["links"] == after["links"]
    assert all(s["labels"] == ["ScanEventArchive"] for s in archived["scans"])
    assert worker(owner, "purge", hours=193)["count"] == 0
    assert worker(owner, "purge", hours=194)["count"] == 1
    final = worker(owner, "snapshot")
    assert [n["id"] for n in final["nodes"]] == ["g1-rc1-active"]
    assert not final["scans"]
    assert final["archive_scans"] == archived["archive_scans"] - 2
    assert any(f["event_type"] == "EntitiesArchived" and f["payload"]["ids"] == ["g1-rc1-held"] for f in final["facts"])
    assert any(f["event_type"] == "EntitiesPurged" and f["payload"]["count"] == 1 for f in final["facts"])
