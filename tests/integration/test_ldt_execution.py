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
PLANNING = os.getenv("PLANNING_SVC_URL", "http://localhost:8009")


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


def test_gdp_broker_command_holds_departures_once_and_preserves_arrivals():
    from datetime import datetime, timedelta
    from neo4j import GraphDatabase

    clock = requests.get(f"{SIM}/api/v1/sim/status", timeout=10).json()["sim_time"]
    scheduled = (datetime.fromisoformat(clock) + timedelta(hours=3)).isoformat()
    command_id = f"test-gdp-{uuid4()}"
    departure, arrival = f"{command_id}-departure", f"{command_id}-arrival"
    command = {"command_id": command_id, "command_type": "GroundDelayProgram",
               "payload": {"flight_ids": [departure, arrival, departure], "stagger_minutes": 5}}
    driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "art-digital-twin")))
    publish_and_observe = r'''
import json, sys, time
from uuid import uuid4
from confluent_kafka import Consumer, Producer, TopicPartition
command = json.load(sys.stdin)
observer = Consumer({'bootstrap.servers': 'kafka:9092', 'group.id': str(uuid4()),
                     'enable.auto.commit': False})
producer = Producer({'bootstrap.servers': 'kafka:9092', 'acks': 'all'})
try:
    metadata = observer.list_topics('flights.events', timeout=10)
    partitions = [TopicPartition('flights.events', n) for n in metadata.topics['flights.events'].partitions]
    observer.assign([TopicPartition(p.topic, p.partition, observer.get_watermark_offsets(p)[1])
                     for p in partitions])
    def send():
        producer.produce('flights.commands', key=b'gdp', value=json.dumps(command))
        assert producer.flush(10) == 0
    send()
    receipts, status_events = 0, []
    deadline = time.monotonic() + 45
    while (receipts < 2 or not status_events) and time.monotonic() < deadline:
        message = observer.poll(0.2)
        if not message or message.error():
            continue
        event = json.loads(message.value())
        if (event.get('event_type') == 'FlightStatusChanged'
                and event.get('payload', {}).get('flight_id') == command['payload']['flight_ids'][0]):
            status_events.append(event['event_id'])
        if event.get('payload', {}).get('command_id') == command['command_id']:
            assert event['event_type'] == 'CommandExecuted', event
            receipts += 1
            if receipts == 1:
                send()
    assert receipts == 2, receipts
    assert status_events
    print(json.dumps(status_events))
finally:
    observer.close()
'''
    command_sent, safe_to_delete = False, True
    try:
        with driver.session() as session:
            session.run("UNWIND $rows AS row CREATE (f:Flight) SET f = row",
                rows=[{"id": fid, "flight_number": "ZZ001", "direction": direction,
                       "status": "scheduled", "scheduled_time": scheduled, "estimated_time": scheduled,
                       "delay_minutes": 0, "pax_count": 0, "aircraft_type": "A320"}
                      for fid, direction in ((departure, "departure"), (arrival, "arrival"))]).consume()
        command_sent, safe_to_delete = True, False
        result = subprocess.run(["docker", "compose", "exec", "-T", "flight-service", "python", "-c",
                                 publish_and_observe], input=json.dumps(command), text=True,
                                capture_output=True, cwd=ROOT, timeout=65)
        assert result.returncode == 0, result.stdout + result.stderr
        with driver.session() as session:
            rows = session.run("MATCH (f:Flight) WHERE f.id IN $ids RETURN f.id AS id, "
                               "f.status AS status, f.delay_minutes AS delay", ids=[departure, arrival]).data()
        states = {row["id"]: row for row in rows}
        assert states[departure]["delay"] == 5
        assert states[arrival]["delay"] == 0 and states[arrival]["status"] == "scheduled"
        event_ids = json.loads(result.stdout.strip().splitlines()[-1])

        def financial_processed():
            with driver.session() as session:
                row = session.run("MATCH (i:CostInbox) WHERE i.id IN $ids RETURN count(i) AS n",
                                  ids=event_ids).single()
                return row["n"] == len(event_ids)

        wait_for(financial_processed)
        safe_to_delete = True
    finally:
        with driver.session() as session:
            if not command_sent or safe_to_delete:
                session.run("MATCH (f:Flight) WHERE f.id IN $ids DETACH DELETE f", ids=[departure, arrival]).consume()
            session.run("MATCH (r:CommandReceipt {id: $id}) DELETE r", id=command_id).consume()
        driver.close()


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


def test_live_what_if_projects_without_mutating_owner_capacity():
    before = requests.get(f"{PASSENGER}/api/v1/flow/summary", timeout=10).json()["security"]["B"]["lanes_open"]
    response = requests.post(f"{ANALYSIS}/api/v1/analysis/what-if", json={
        "actions": [{"action_type": "open_security_lane",
                     "parameters": {"terminal": "Terminal B", "new_lane_count": before + 1}}],
        "horizon_minutes": 15,
    }, timeout=30)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sim_time_at_request"] and body["horizon_minutes"] == 15
    assert len(body["projections"]) == 1
    assert 0 <= body["baseline"]["gate_utilisation_pct"] <= 100
    after = requests.get(f"{PASSENGER}/api/v1/flow/summary", timeout=10).json()["security"]["B"]["lanes_open"]
    assert after == before


def test_planning_runs_synthetic_scenario_and_recovers_results_after_restart():
    response = requests.post(f"{PLANNING}/api/v1/planning/scenarios", json={
        "name": "Synthetic local recovery validation", "horizon": "day",
        "monte_carlo_runs": 2, "random_seed": 42, "demand_multiplier": 1.1,
        "demand_source": "simulation", "weather_source": "simulation",
        "capex_eur": 1000, "opex_delta_eur": 10, "years_horizon": 3,
    }, timeout=30)
    assert response.status_code == 201, response.text
    scenario_id = response.json()["scenario_id"]
    endpoint = f"{PLANNING}/api/v1/planning/scenarios/{scenario_id}"

    children = []

    def completed(url=endpoint):
        result = requests.get(f"{url}/status", timeout=10)
        result.raise_for_status()
        status = result.json()
        assert status["status"] != "failed", status
        return status if status["status"] == "completed" else None

    try:
        assert wait_for(completed)["progress_pct"] == 100
        response = requests.get(f"{endpoint}/results", timeout=10)
        assert response.status_code == 200, response.text
        saved = json.loads(response.text, parse_constant=lambda value: pytest.fail(f"Nonfinite result: {value}"))
        assert saved["kpis"] and saved["baseline_kpis"] and saved["financials"]
        subprocess.run(["docker", "compose", "restart", "planning-service"], cwd=ROOT, check=True, timeout=90)

        def ready():
            try:
                return requests.get(f"{PLANNING}/ready", timeout=5).status_code == 200
            except requests.RequestException:
                return False

        wait_for(ready)
        scenario = requests.get(endpoint, timeout=10).json()
        assert scenario["random_seed"] == 42 and scenario["demand_multiplier"] == 1.1
        assert scenario["status"] == "completed"
        assert requests.get(f"{endpoint}/results", timeout=10).json() == saved
        graph = requests.get(f"{endpoint}/causal-graph", timeout=10).json()
        assert any(node["type"] == "kpi" and node["mean"] is not None for node in graph["nodes"])
        intervention = {"action": "open_security_lanes", "sim_minute": 120,
                        "duration_minutes": 60, "params": {"lanes": 2}}
        for route, payload in [
            ("replay", {"interventions": [intervention], "label": "synthetic-replay"}),
            ("counterfactual-report", {"base_interventions": [intervention], "shifts": [0]}),
        ]:
            response = requests.post(f"{endpoint}/{route}", json=payload, timeout=30)
            assert response.status_code == 202, response.text
            body = response.json()
            child_id = body["scenario_id"] if route == "replay" else body["children"][0]["scenario_id"]
            child_url = f"{PLANNING}/api/v1/planning/scenarios/{child_id}"
            children.append(child_url)
            wait_for(lambda: completed(child_url))
            child = requests.get(child_url, timeout=10).json()
            assert child["demand_multiplier"] == 1.1 and child["random_seed"] == 42
            assert child["parent_scenario_id"] == scenario_id
        replays = requests.get(f"{endpoint}/replays", timeout=10).json()["replays"]
        assert len(replays) == 2
        assert all(row["id"] and row["name"] and row["results"]["kpis"] for row in replays)
    finally:
        for child_url in children:
            response = requests.delete(child_url, timeout=10)
            assert response.status_code == 200, response.text
        response = requests.delete(endpoint, timeout=10)
        assert response.status_code == 200, response.text


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
        # Pin the observer to current broker offsets BEFORE publishing. Seeing
        # an old DB receipt alone would not prove the replay was processed.
        code = '''import json, sys, time
from uuid import uuid4
from confluent_kafka import Consumer, Producer, TopicPartition
command = json.load(sys.stdin)
c = Consumer({'bootstrap.servers': 'kafka:9092', 'group.id': str(uuid4()), 'enable.auto.commit': False})
try:
    metadata = c.list_topics('passengers.events', timeout=10)
    partitions = [TopicPartition('passengers.events', number) for number in metadata.topics['passengers.events'].partitions]
    offsets = [TopicPartition(p.topic, p.partition, c.get_watermark_offsets(p, timeout=10)[1]) for p in partitions]
    c.assign(offsets)
    producer = Producer({'bootstrap.servers': 'kafka:9092', 'acks': 'all'})
    producer.produce('passengers.commands', key='B', value=json.dumps(command))
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
            ["docker", "compose", "exec", "-T", "passenger-service", "python", "-c", code],
            input=json.dumps(command), text=True, capture_output=True, cwd=ROOT, check=True, timeout=90,
        )
        assert json.loads(result.stdout)["event_type"] == "CommandExecuted", result.stdout

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
            return (response.status_code == 200 and response.json()["sim_time"] is not None
                    and response.json()["security"]["B"]["lanes_open"] == expected)
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
