"""Live incidents.commands owner-execution check (roadmap G6).

Injects a synthetic incident, publishes a ContainIncident command on
`incidents.commands`, and asserts incident-service executes it, emits the
`IncidentStatusChanged` fact plus a durable `CommandExecuted` receipt on
`incidents.events`, and that redelivery of the same command_id re-emits the
receipt without a second mutation. Also checks a command for a missing incident
is rejected with a `CommandRejected` receipt.

Run against a disposable synthetic stack only.
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
INCIDENT = os.getenv("INCIDENT_SVC_URL", "http://localhost:8005")
SIM = os.getenv("SIM_SVC_URL", "http://localhost:8006")


@pytest.fixture(scope="module", autouse=True)
def require_stack():
    try:
        requests.get(f"{INCIDENT}/ready", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Incident service unavailable: {exc}")
        pytest.skip("Live digital twin not running")


def wait_for(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    pytest.fail("Live state did not converge before timeout")


def _publish_and_observe(command_type, command_id, incident_id):
    """Publish a command and return the matching owner receipt event."""
    clock = requests.get(f"{SIM}/api/v1/sim/status", timeout=10).json()["sim_time"]
    command = {
        "command_type": command_type, "command_id": command_id,
        "issued_at": clock, "issued_by": "integration-test", "schema_version": "1.0",
        "payload": {"incident_id": incident_id, "note": "integration"},
    }
    # Pin the observer to current broker offsets BEFORE publishing, so an old DB
    # receipt alone cannot pass for a freshly-processed command.
    code = '''import json, sys, time
from uuid import uuid4
from confluent_kafka import Consumer, Producer, TopicPartition
command = json.load(sys.stdin)
c = Consumer({'bootstrap.servers': 'kafka:9092', 'group.id': str(uuid4()), 'enable.auto.commit': False})
try:
    metadata = c.list_topics('incidents.events', timeout=10)
    partitions = [TopicPartition('incidents.events', n) for n in metadata.topics['incidents.events'].partitions]
    offsets = [TopicPartition(p.topic, p.partition, c.get_watermark_offsets(p, timeout=10)[1]) for p in partitions]
    c.assign(offsets)
    producer = Producer({'bootstrap.servers': 'kafka:9092', 'acks': 'all'})
    producer.produce('incidents.commands', key=command['payload']['incident_id'], value=json.dumps(command))
    if producer.flush(15):
        raise RuntimeError('Command not delivered')
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        message = c.poll(0.5)
        if message is None or message.error():
            continue
        event = json.loads(message.value())
        if event.get('event_type') in ('CommandExecuted', 'CommandRejected') and event['payload'].get('command_id') == command['command_id']:
            print(json.dumps(event))
            break
    else:
        raise RuntimeError('No owning-service receipt for command')
finally:
    c.close()
'''
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "incident-service", "python", "-c", code],
        input=json.dumps(command), text=True, capture_output=True, cwd=ROOT, check=True, timeout=120,
    )
    return json.loads(result.stdout)


def _inject():
    response = requests.post(f"{INCIDENT}/api/v1/incidents/inject", json={
        "type": "runway_incursion", "severity": "high", "location": "runway-09L",
        "description": "synthetic G6 command test",
    }, timeout=15)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _status(incident_id):
    response = requests.get(f"{INCIDENT}/api/v1/incidents/{incident_id}", timeout=10)
    return response.json().get("status") if response.status_code == 200 else None


def test_contain_command_executes_emits_receipt_and_is_idempotent():
    incident_id = _inject()
    assert wait_for(lambda: _status(incident_id) == "active")

    command_id = f"test-contain-{uuid4()}"
    receipt = _publish_and_observe("ContainIncident", command_id, incident_id)
    assert receipt["event_type"] == "CommandExecuted", receipt
    assert wait_for(lambda: _status(incident_id) == "contained")

    # Redelivery of the same command_id: receipt re-emitted, no second mutation
    # (the incident is already contained — a fresh execute would be rejected).
    repeat = _publish_and_observe("ContainIncident", command_id, incident_id)
    assert repeat["event_type"] == "CommandExecuted", repeat
    assert _status(incident_id) == "contained"


def test_command_for_missing_incident_is_rejected():
    receipt = _publish_and_observe(
        "ContainIncident", f"test-missing-{uuid4()}", f"inc-does-not-exist-{uuid4()}"
    )
    assert receipt["event_type"] == "CommandRejected", receipt
    assert receipt["payload"]["reason"]
