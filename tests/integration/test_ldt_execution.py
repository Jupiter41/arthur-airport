"""Live prediction, owner command confirmation, restart and replay checks.

Only run against a disposable synthetic stack: this test changes lane capacity
and restarts passenger-service, then restores the original capacity.
"""

import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
PASSENGER = os.getenv("PASSENGER_SVC_URL", "http://localhost:8002")
ANALYSIS = os.getenv("ANALYSIS_SVC_URL", "http://localhost:8007")
SIM = os.getenv("SIM_SVC_URL", "http://localhost:8006")


@pytest.fixture(scope="module", autouse=True)
def require_stack():
    try:
        response = requests.get(f"{ANALYSIS}/ready", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Analysis service unavailable: {exc}")
        pytest.skip("Live digital twin not running")


def wait_for(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    pytest.fail("Live state did not converge before timeout")


def test_forecast_points_identify_real_source_and_clock():
    response = requests.get(f"{PASSENGER}/api/v1/flow/forecast?terminal=B&window=30", timeout=15)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sim_time"]
    assert len(body["forecast"]) == 6
    assert body["congestion_risk"]["confidence_calibrated"] is False
    assert body["congestion_risk"]["confidence"] is None
    assert all(point["source"] in {"lightgbm", "schedule_ratio"} for point in body["forecast"])
    assert all(point["predicted_queue_depth"] >= 0 for point in body["forecast"])


def test_approved_proposal_executes_and_receipt_survives_restart_and_replay():
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "art-digital-twin")),
    )
    original = requests.get(f"{PASSENGER}/api/v1/flow/summary", timeout=10).json()["security"]["B"]["lanes_open"]
    changed = 6 if original != 6 else 5

    def publish(command_id, lanes):
        clock = requests.get(f"{SIM}/api/v1/sim/status", timeout=10).json()["sim_time"]
        command = {"command_type": "OpenSecurityLane", "command_id": command_id,
                   "issued_at": clock, "issued_by": "integration-test", "schema_version": "1.0",
                   "payload": {"terminal": "B", "lanes_open": lanes}}
        code = (
            "import json,sys; from confluent_kafka import Producer; "
            "p=Producer({'bootstrap.servers':'kafka:9092','acks':'all'}); "
            "p.produce('passengers.commands',key='B',value=sys.stdin.buffer.read()); "
            "remaining=p.flush(15); sys.exit(1 if remaining else 0)"
        )
        subprocess.run(
            ["docker", "compose", "exec", "-T", "passenger-service", "python", "-c", code],
            input=json.dumps(command), text=True, cwd=ROOT, check=True, timeout=30,
        )

    def receipt(command_id):
        with driver.session() as session:
            row = session.run(
                "MATCH (r:CommandReceipt {id: $id}) RETURN r.event_type AS event_type, r.payload AS payload",
                id=command_id,
            ).single()
            return dict(row) if row else None

    def lanes_are(expected):
        try:
            response = requests.get(f"{PASSENGER}/api/v1/flow/summary", timeout=5)
            return response.status_code == 200 and response.json()["security"]["B"]["lanes_open"] == expected
        except requests.RequestException:
            return False

    command_id = f"test-{uuid4()}"
    try:
        clock = requests.get(f"{SIM}/api/v1/sim/status", timeout=10).json()["sim_time"]
        # Synthetic fixture at the approval boundary. Analysis must recover it,
        # dispatch the real Kafka command and accept the owner's durable receipt.
        proposal = {
            "id": command_id, "action_type": "open_security_lane",
            "description": "Synthetic integration proposal",
            "parameters": {"terminal": "Terminal B", "new_lane_count": changed},
            "confidence_score": 0.85, "proposed_by": "integration-test",
            "proposed_at": clock, "status": "approved", "requires_human": False,
            "emitted": True,
        }
        with driver.session() as session:
            session.run(
                "CREATE (p:ActionProposal {id: $id, document: $document})",
                id=command_id, document=json.dumps(proposal),
            ).consume()
        subprocess.run(["docker", "compose", "restart", "analysis-service"], cwd=ROOT, check=True, timeout=90)
        saved = wait_for(lambda: receipt(command_id))
        assert saved["event_type"] == "CommandExecuted"
        wait_for(lambda: lanes_are(changed))

        def confirmed():
            response = requests.get(f"{ANALYSIS}/api/v1/analysis/approvals?all=true", timeout=10)
            response.raise_for_status()
            return next((p for p in response.json()["approvals"]
                         if p["id"] == command_id and p["status"] == "executed"), None)

        assert wait_for(confirmed)["executed_at"]
        subprocess.run(["docker", "compose", "restart", "passenger-service"], cwd=ROOT, check=True, timeout=90)
        wait_for(lambda: lanes_are(changed))
        # A changed body with the SAME identity must return the saved result,
        # never apply a second mutation after the receipt cache was lost.
        publish(command_id, original)
        time.sleep(3)
        assert receipt(command_id) == saved
        assert lanes_are(changed)
    finally:
        try:
            restore_id = f"restore-{uuid4()}"
            publish(restore_id, original)
            wait_for(lambda: receipt(restore_id))
            wait_for(lambda: lanes_are(original))
        finally:
            driver.close()
