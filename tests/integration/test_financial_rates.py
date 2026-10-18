"""Effective rate persistence, replica updates and frozen planning recovery."""

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
COST = os.getenv("COST_SVC_URL", "http://localhost:8008")
PLANNING = os.getenv("PLANNING_SVC_URL", "http://localhost:8009")

COST_WORKER = r'''
import asyncio, json, sys
from db import neo4j as db
from services import ledger, rates
from _common.financial_rates import rates_version
args = json.load(sys.stdin)
async def run():
    await db._init_driver()
    try:
        await ledger.initialize()
        if args.get('validate_summary'):
            from uuid import uuid4
            from math import isclose
            from services import cost_engine, carbon_tracker
            async def no_effects(event):
                pass
            # Select a distant day, then return to day one without inventing
            # new financial effects. Both are durable ledger transactions.
            for day in (1000, 1):
                await ledger.process({'event_id': str(uuid4()), 'event_type': 'SimClockTick',
                    'sim_time': '2026-01-01T12:00:00Z', 'payload': {'day_of_sim': day}}, no_effects)
            async with db.get_driver().session() as session:
                row = await (await session.run(
                    "MATCH (c:CostRecord) WHERE c.sim_day = 1 "
                    "RETURN sum(CASE WHEN c.is_revenue THEN 0 ELSE c.amount_eur END) AS cost, "
                    "sum(CASE WHEN c.is_revenue THEN c.amount_eur ELSE 0 END) AS revenue")).single()
                totals = cost_engine.get_running_totals()
                assert row['cost'] > 0
                assert isclose(totals['total_cost_eur'], row['cost'], abs_tol=0.01)
                assert isclose(totals['total_revenue_eur'], row['revenue'], abs_tol=0.01)
                carbon = await (await session.run(
                    "MATCH (c:CarbonRecord) WHERE c.sim_day = 1 RETURN sum(c.co2_kg) AS kg")).single()
                assert isclose(carbon_tracker.get_carbon_totals()['total_kg'], carbon['kg'], abs_tol=0.01)
        if args.get('patch') is not None:
            committed = await rates.update(args['patch'])
            async with db.get_driver().session() as session:
                row = await (await session.run(
                    "MATCH (e:CostOutbox) WHERE e.document CONTAINS $version "
                    "RETURN e.document AS document LIMIT 1", version=rates_version(committed))).single()
                assert row and json.loads(row['document'])['event_type'] == 'CostRatesUpdated'
                from kafka import producer
                producer.init_kafka_producer()
                try:
                    producer.publish_confirmed(json.loads(row['document']))
                finally:
                    producer.close_kafka_producer()
        print(json.dumps(await rates.read()), flush=True)
    finally:
        await db.close_neo4j()
asyncio.run(run())
'''

PLANNING_WORKER = r'''
import json, sys
from db import store
from scenarios import jobs, model
from engine.infrastructure import InfrastructureConfig
args = json.load(sys.stdin)
store.initialize()
try:
    sid = args['id']
    if args['mode'] == 'claim':
        model.store_scenario(model.PlanningScenario(id=sid, random_seed=0,
            name='Synthetic rate snapshot test', infrastructure=InfrastructureConfig(daily_flight_target=20)))
    else:
        with store.get_repository().driver.session() as session:
            session.run('MATCH (s:PlanningScenario {id: $id}) SET s.lease_until = 0', id=sid).consume()
    lease, document = jobs.claim(sid)
    print(json.dumps(document), flush=True)
    if args['mode'] == 'recover':
        lease.release()
finally:
    store.close()
'''


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True,
                          capture_output=True, timeout=120, **kwargs)


def worker(service, source, payload):
    result = compose("run", "--rm", "-T", "--no-deps", service, "python", "-c", source,
                     input=json.dumps(payload))
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def ready(url):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{url}/ready", timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    pytest.fail(f"Service did not become ready: {url}")


@pytest.fixture(scope="module")
def isolated_rates():
    try:
        original = requests.get(f"{COST}/api/v1/costs/rates", timeout=5)
        original.raise_for_status()
        requests.get(f"{PLANNING}/ready", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Live services unavailable: {exc}")
        pytest.skip("Live stack not running")
    compose("stop", "cost-service", "planning-service", check=True)
    try:
        yield original.json()
    finally:
        # Restore only the leaves changed by these tests. Other configuration,
        # operational nodes and other Compose projects are never reset.
        compose("stop", "cost-service", "planning-service", check=True)
        worker("cost-service", COST_WORKER, {"patch": {
            "airport_fees": {"passenger_departure_fee_eur": original.json()["airport_fees"]["passenger_departure_fee_eur"]},
            "staffing": {"security_officer_per_hour_eur": original.json()["staffing"]["security_officer_per_hour_eur"]},
        }})
        compose("up", "-d", "--no-deps", "cost-service", "planning-service", check=True)
        ready(COST)
        ready(PLANNING)


def test_competing_rate_updates_and_frozen_planning_recovery(isolated_rates):
    original = isolated_rates
    sid = f"synthetic-rates-{uuid4()}"
    fee = original["airport_fees"]["passenger_departure_fee_eur"] + 7
    wage = original["staffing"]["security_officer_per_hour_eur"] + 3
    patches = [{"airport_fees": {"passenger_departure_fee_eur": fee}},
               {"staffing": {"security_officer_per_hour_eur": wage}}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda patch: worker("cost-service", COST_WORKER, {"patch": patch}), patches))
    committed = worker("cost-service", COST_WORKER, {})
    assert committed["airport_fees"]["passenger_departure_fee_eur"] == fee
    assert committed["staffing"]["security_officer_per_hour_eur"] == wage
    first = worker("planning-service", PLANNING_WORKER, {"id": sid, "mode": "claim"})
    assert first["financial_rates"] == committed
    worker("cost-service", COST_WORKER, {"patch": {
        "airport_fees": {"passenger_departure_fee_eur": fee + 11},
    }})
    recovered = worker("planning-service", PLANNING_WORKER, {"id": sid, "mode": "recover"})
    assert recovered["attempt_count"] == 2
    assert recovered["financial_rates"] == first["financial_rates"]
    assert recovered["financial_rates_version"] == first["financial_rates_version"]
    compose("up", "-d", "--no-deps", "cost-service", "planning-service", check=True)
    ready(COST)
    ready(PLANNING)
    try:
        after_restart = requests.get(f"{COST}/api/v1/costs/rates", timeout=5).json()
        assert after_restart["airport_fees"]["passenger_departure_fee_eur"] == fee + 11
        before = after_restart
        bad = requests.patch(f"{COST}/api/v1/costs/rates", json={"airport_fees": {
            "passenger_departure_fee_eur": fee + 99, "landing_rate_per_tonne_eur": False,
        }}, timeout=10)
        assert bad.status_code == 400
        assert requests.get(f"{COST}/api/v1/costs/rates", timeout=5).json() == before
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            scenario = requests.get(f"{PLANNING}/api/v1/planning/scenarios/{sid}", timeout=5).json()
            assert scenario["status"] != "failed", scenario
            if scenario["status"] == "completed":
                break
            time.sleep(0.2)
        else:
            pytest.fail("Recovered scenario never completed")
        assert scenario["financial_rates"] == committed
        results = requests.get(f"{PLANNING}/api/v1/planning/scenarios/{sid}/results", timeout=5).json()
        assert results["financial_rates_version"] == first["financial_rates_version"]
    finally:
        response = requests.delete(f"{PLANNING}/api/v1/planning/scenarios/{sid}", timeout=10)
        assert response.status_code in (200, 204), response.text


def test_summary_rebuilds_evicted_day_from_authoritative_ledger(isolated_rates):
    compose("stop", "cost-service", check=True)
    try:
        worker("cost-service", COST_WORKER, {"validate_summary": True})
    finally:
        compose("up", "-d", "--no-deps", "cost-service", check=True)
        ready(COST)
