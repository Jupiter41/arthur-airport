"""Daily ranking retains exact compensation attribution with duplicate edges."""

import os
from pathlib import Path
import subprocess

import pytest
import requests

WORKER = r"""
import asyncio
from uuid import uuid4
from db.neo4j import wait_for_neo4j, get_driver, close_neo4j
from db.queries import most_expensive_incidents

async def main():
    await wait_for_neo4j(max_attempts=1)
    prefix = 'ranking-test-' + str(uuid4())
    day = 2000000 + uuid4().int % 1000000000
    try:
        async with get_driver().session() as session:
            await (await session.run('''
                CREATE (a:Incident {id:$a}), (b:Incident {id:$b}), (f:Flight {id:$f})
                CREATE (c:CostRecord {id:$c, sim_day:$day, amount_eur:10})-[:CAUSED_BY]->(a)
                CREATE (d:CostRecord {id:$d, sim_day:$day, amount_eur:20})-[:CAUSED_BY]->(b)
                CREATE (a)-[:AFFECTS]->(f), (a)-[:AFFECTS]->(f)
                CREATE (e:CostRecord {id:$e, sim_day:$day, category:'eu261_compensation', amount_eur:100})
                CREATE (e)-[:FOR_FLIGHT]->(f), (e)-[:FOR_FLIGHT]->(f)
                CREATE (:CostRecord {id:$old, sim_day:1, category:'eu261_compensation', amount_eur:999})-[:FOR_FLIGHT]->(f)
            ''', **{k:prefix+'-'+k for k in ['a','b','c','d','e','f','old']}, day=day)).consume()
        rows = await most_expensive_incidents(get_driver(), day)
        assert [(r['id'], r['direct_cost'], r['eu261_cost']) for r in rows] == [
            (prefix+'-a', 10, 100), (prefix+'-b', 20, 0)], rows
    finally:
        async with get_driver().session() as session:
            for label, keys in [('CostRecord',['c','d','e','old']), ('Incident',['a','b']), ('Flight',['f'])]:
                await (await session.run(f'UNWIND $ids AS id MATCH (n:{label} {{id:id}}) DETACH DELETE n',
                    ids=[prefix+'-'+key for key in keys])).consume()
        await close_neo4j()
asyncio.run(main())
"""


def test_daily_incident_ranking_deduplicates_records_and_excludes_other_days():
    try:
        requests.get(os.getenv("COST_SVC_URL", "http://localhost:8008") + "/ready", timeout=5).raise_for_status()
    except requests.RequestException:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail("Cost service unavailable")
        pytest.skip("Live stack unavailable")
    result = subprocess.run(["docker", "compose", "exec", "-T", "cost-service", "python", "-c", WORKER],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
