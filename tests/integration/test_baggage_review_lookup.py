"""Real indexed review lookup retains both predicates without duplicate bags."""

import os
from pathlib import Path
import subprocess

import pytest
import requests


WORKER = r"""
import asyncio
from uuid import uuid4
from db.neo4j import wait_for_neo4j, get_driver, get_flagged_baggage, close_neo4j
async def main():
    await wait_for_neo4j(max_attempts=1)
    prefix='!review-test-'+str(uuid4())
    ids=[prefix+'-'+str(n) for n in range(4)]
    try:
        async with get_driver().session() as session:
            await (await session.run('''
                CREATE (p:Passenger {id:$prefix,name:$prefix})
                CREATE (f:Flight {id:$prefix,flight_number:$prefix})
                WITH p,f UNWIND range(0,3) AS n
                CREATE (b:Baggage:UnscannedBaggage {id:$ids[n],tag:$ids[n],
                    status:CASE WHEN n IN [0,2] THEN 'flagged' ELSE 'collected' END,
                    review_status:CASE WHEN n IN [1,2] THEN 'pending' ELSE 'cleared' END})
                CREATE (p)-[:CARRIES]->(b) CREATE (b)-[:LOADED_ON]->(f)
                CREATE (p)-[:CARRIES]->(b) CREATE (b)-[:LOADED_ON]->(f)
            ''',prefix=prefix,ids=ids)).consume()
        first,total=await get_flagged_baggage(limit=2)
        second,again=await get_flagged_baggage(limit=2,offset=2)
        assert total==again and total>=3
        assert [r['id'] for r in first]==ids[:2],first
        own=[r for r in first+second if r['id'] in ids]
        assert sorted(r['id'] for r in own)==ids[:3], own
        assert all(r['passenger_name']==prefix and r['flight_number']==prefix for r in own)
        assert await get_flagged_baggage(offset=total)==([],total)
    finally:
        async with get_driver().session() as session:
            await (await session.run('UNWIND $ids AS id MATCH (b:Baggage {id:id}) DETACH DELETE b',ids=ids)).consume()
            await (await session.run('MATCH (p:Passenger {id:$id}) DETACH DELETE p',id=prefix)).consume()
            await (await session.run('MATCH (f:Flight {id:$id}) DELETE f',id=prefix)).consume()
        await close_neo4j()
asyncio.run(main())
"""


def test_review_lookup_includes_both_predicates_once_with_metadata():
    try:
        requests.get(os.getenv("BAGGAGE_SVC_URL", "http://localhost:8003") + "/ready", timeout=5).raise_for_status()
    except requests.RequestException:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail("Baggage service unavailable")
        pytest.skip("Live stack unavailable")
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "baggage-service", "python", "-c", WORKER],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
