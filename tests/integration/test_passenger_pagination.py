"""Exercise real filtered pages and orphan exclusion on synthetic fixtures."""

import os
from pathlib import Path
import subprocess

import pytest
import requests

WORKER = r"""
import asyncio
from uuid import uuid4
from db.neo4j import wait_for_neo4j, get_driver, get_all_passengers, close_neo4j
async def main():
    await wait_for_neo4j(max_attempts=1)
    prefix='page-test-'+str(uuid4())
    ids=[prefix+'-'+str(n) for n in range(4)]
    try:
        async with get_driver().session() as session:
            await (await session.run('CREATE (f:Flight {id:$id,flight_number:$id})',id=prefix)).consume()
            await (await session.run('''UNWIND $ids AS id CREATE (p:Passenger {id:id,name:$name,
                status:'booked',location_zone:$zone,connection:false,special_assistance:false})
                WITH p MATCH (f:Flight {id:$fid})
                FOREACH (_ IN CASE WHEN p.id = $orphan THEN [] ELSE [1] END | CREATE (p)-[:ON_FLIGHT]->(f))''',
                ids=ids,name=prefix,zone=prefix,fid=prefix,orphan=ids[-1])).consume()
        params=dict(zone=prefix,status='booked',connection=False,special_assistance=False)
        first,total=await get_all_passengers(**params,flight_id=prefix,limit=2)
        second,again=await get_all_passengers(**params,flight_number=prefix,limit=2,offset=2)
        assert total == again == 3
        assert [p['id'] for p in first+second] == ids[:3]
        assert all(p['flight_number']==prefix for p in first+second)
        unfiltered,total=await get_all_passengers(**params)
        assert total==3 and len(unfiltered)==3
        assert await get_all_passengers(flight_id=prefix+'missing') == ([],0)
    finally:
        async with get_driver().session() as session:
            await (await session.run('UNWIND $ids AS id MATCH (p:Passenger {id:id}) DETACH DELETE p',ids=ids)).consume()
            await (await session.run('MATCH (f:Flight {id:$id}) DELETE f',id=prefix)).consume()
        await close_neo4j()
asyncio.run(main())
"""


def test_passenger_pages_preserve_filters_metadata_totals_and_exclude_orphans():
    try:
        requests.get(os.getenv("PASSENGER_SVC_URL", "http://localhost:8002") + "/ready", timeout=5).raise_for_status()
    except requests.RequestException:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail("Passenger service unavailable")
        pytest.skip("Live stack unavailable")
    result = subprocess.run(["docker", "compose", "exec", "-T", "passenger-service", "python", "-c", WORKER],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
