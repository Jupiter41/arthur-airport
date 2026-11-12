"""Index ordering retains unscanned bags and pages across the null boundary."""

import os
from pathlib import Path
import subprocess

import pytest
import requests

WORKER = r"""
import asyncio
from uuid import uuid4
from db.neo4j import wait_for_neo4j, get_driver, get_all_baggage, close_neo4j
async def main():
    await wait_for_neo4j(max_attempts=1)
    prefix='zz-pagination-'+str(uuid4())
    ids=[prefix+'-'+str(n) for n in range(4)]
    try:
        async with get_driver().session() as session:
            await (await session.run('''UNWIND range(0,3) AS n
                CREATE (b:Baggage {id:$ids[n],tag:$ids[n],status:'collected'})
                FOREACH (_ IN CASE WHEN n>1 THEN [1] ELSE [] END |
                    SET b.last_scan_at='9999-01-01T12:00:00')''',ids=ids)).consume()
            nulls=(await (await session.run('MATCH (b:Baggage) WHERE b.last_scan_at IS NULL RETURN count(b) AS n')).single())['n']
        first,total=await get_all_baggage(limit=2)
        assert [b['id'] for b in first]==[ids[1],ids[0]], first
        assert all(b.get('last_scan_at') is None for b in first)
        across,again=await get_all_baggage(limit=3,offset=nulls-1)
        assert again==total and len(across)==3
        assert across[0].get('last_scan_at') is None, (nulls, across)
        assert [b['id'] for b in across[1:]]==[ids[3],ids[2]], across
        assert await get_all_baggage(limit=2,offset=total)==([],total)
    finally:
        async with get_driver().session() as session:
            await (await session.run('UNWIND $ids AS id MATCH (b:Baggage {id:id}) DELETE b',ids=ids)).consume()
        await close_neo4j()
asyncio.run(main())
"""


def test_unfiltered_baggage_retains_nulls_and_crosses_to_scanned_index():
    try:
        requests.get(os.getenv("BAGGAGE_SVC_URL", "http://localhost:8003") + "/ready", timeout=5).raise_for_status()
    except requests.RequestException:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail("Baggage service unavailable")
        pytest.skip("Live stack unavailable")
    root = Path(__file__).resolve().parents[2]
    sim = os.getenv("SIM_SVC_URL", "http://localhost:8006")
    paused = requests.get(sim + "/api/v1/sim/status", timeout=10).json()["paused"]
    requests.post(sim + "/api/v1/sim/pause", timeout=10).raise_for_status()
    try:
        subprocess.run(["docker", "compose", "stop", "baggage-service"], cwd=root,
                       capture_output=True, check=True, timeout=40)
        result = subprocess.run(["docker", "compose", "run", "--rm", "-T", "--no-deps",
                                 "baggage-service", "python", "-c", WORKER],
            cwd=root, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        subprocess.run(["docker", "compose", "up", "-d", "--no-deps", "baggage-service"],
                       cwd=root, capture_output=True, check=True, timeout=40)
        if not paused:
            requests.post(sim + "/api/v1/sim/resume", timeout=10).raise_for_status()
