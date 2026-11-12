"""Boarding reads retain catch-up states while excluding ineligible history."""

import os
from pathlib import Path
import subprocess

import pytest
import requests

WORKER = r"""
import asyncio
from uuid import uuid4
from db.neo4j import wait_for_neo4j,get_driver,get_passengers_by_status,close_neo4j
async def main():
    await wait_for_neo4j(max_attempts=1)
    prefix='boarding-query-'+uuid4().hex
    eligible=['boarding','scheduled','delayed','airborne','departed','taxiing']
    states=eligible+['arrived','diverted','cancelled',None,'scheduled']
    ids=[prefix+'-'+str(n) for n in range(len(states))]
    try:
        async with get_driver().session() as s:
            await (await s.run('''UNWIND range(0,size($states)-1) AS n
                CREATE (f:Flight {id:$ids[n],flight_number:$ids[n],status:$states[n],
                    direction:'synthetic-query-fixture',scheduled_time:
                    CASE WHEN n=10 THEN '1900-02-01T12:00:00' ELSE '1900-01-01T12:00:00' END})
                CREATE (p:Passenger {id:$ids[n],name:$prefix,status:$prefix})-[:ON_FLIGHT]->(f)
            ''',states=states,ids=ids,prefix=prefix)).consume()
        before='1900-01-01T13:00:00'
        filtered=await get_passengers_by_status(prefix,scheduled_before=before,flight_statuses=eligible)
        assert {r['id'] for r in filtered}==set(ids[:6]),filtered
        assert all(r['flight_number']==r['id'] and r['flight_status'] in eligible for r in filtered)
        assert await get_passengers_by_status(prefix,scheduled_before=before,flight_statuses=[])==[]
        unfiltered=await get_passengers_by_status(prefix,scheduled_before=before)
        assert {r['id'] for r in unfiltered}==set(ids[:10]),unfiltered
    finally:
        async with get_driver().session() as s:
            for label in ['Passenger','Flight']:
                await (await s.run(f'UNWIND $ids AS id MATCH(n:{label} {{id:id}}) DETACH DELETE n',ids=ids)).consume()
        await close_neo4j()
asyncio.run(main())
"""


def test_boarding_query_keeps_eligible_states_cutoff_and_metadata():
    try:
        requests.get(os.getenv("PASSENGER_SVC_URL", "http://localhost:8002") + "/ready", timeout=5).raise_for_status()
    except requests.RequestException:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail("Passenger service unavailable")
        pytest.skip("Live stack unavailable")
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "passenger-service", "python", "-c", WORKER],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
