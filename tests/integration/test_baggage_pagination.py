"""Real indexed bag ordering on an isolated, bounded synthetic graph label."""

import os
from pathlib import Path
import subprocess

import pytest
import requests

WORKER = r"""
import asyncio
from uuid import uuid4
from db.neo4j import wait_for_neo4j, get_driver, _unfiltered_baggage_page, close_neo4j
async def main():
    await wait_for_neo4j(max_attempts=1)
    label='BaggagePageTest'+uuid4().hex
    ids=[label+'-'+str(n) for n in range(4)]
    indexes=[label+'Id',label+'Scan']
    async with get_driver().session() as session:
        # Execute the production queries on a unique label. This tests actual
        # Neo4j index/null semantics without a linear deep offset through history.
        class ScopedSession:
            def run(self, query, **params):
                return session.run(query.replace(':Baggage', ':'+label), **params)
        try:
            await (await session.run(f'CREATE INDEX {indexes[0]} FOR (b:{label}) ON (b.id)')).consume()
            await (await session.run(f'CREATE INDEX {indexes[1]} FOR (b:{label}) ON (b.last_scan_at,b.id)')).consume()
            await (await session.run('CALL db.awaitIndexes(30)')).consume()
            await (await session.run(f'''UNWIND range(0,3) AS n
                CREATE (b:{label} {{id:$ids[n],tag:$ids[n],status:'collected'}})
                FOREACH (_ IN CASE WHEN n>1 THEN [1] ELSE [] END |
                    SET b.last_scan_at='2024-06-15T12:00:00')''',ids=ids)).consume()
            scoped=ScopedSession()
            first,total=await _unfiltered_baggage_page(scoped,2,0)
            assert total==4 and [b['id'] for b in first]==[ids[1],ids[0]],first
            assert all(b.get('last_scan_at') is None for b in first)
            across,again=await _unfiltered_baggage_page(scoped,3,1)
            assert again==4 and [b['id'] for b in across]==[ids[0],ids[3],ids[2]],across
            assert across[0].get('last_scan_at') is None
            assert await _unfiltered_baggage_page(scoped,2,4)==([],4)
        finally:
            await (await session.run(f'MATCH (b:{label}) DELETE b')).consume()
            for index in indexes:
                await (await session.run(f'DROP INDEX {index} IF EXISTS')).consume()
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
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "baggage-service", "python", "-c", WORKER],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
