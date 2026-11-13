"""Real indexed bag ordering on an isolated, bounded synthetic graph label."""

import json
import os
from pathlib import Path
import subprocess

import pytest
import requests

WORKER = r"""
import asyncio, ast, json, sys
from datetime import datetime
from uuid import uuid4
sources=json.load(sys.stdin)
db={'__name__':'candidate_baggage_db'}
exec(compile(sources['db'],'candidate_baggage_db.py','exec'),db)
async def main():
    await db['wait_for_neo4j'](max_attempts=1)
    label='BagPageFixture'+uuid4().hex
    ids=[label+'-'+str(n) for n in range(4)]
    indexes=[label+'Id',label+'Scan',label+'UnscannedId',label+'ReviewId']
    async with db['get_driver']().session() as session:
        # Execute the production queries on a unique label. This tests actual
        # Neo4j index/null semantics without a linear deep offset through history.
        class ScopedSession:
            def __init__(self, connection=session): self.connection=connection
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def run(self, query, **params):
                query=query.replace(':BaggageIndexMigration', ':'+label+'Migration')
                query=query.replace(':UnscannedBaggage', ':'+label+'Unscanned')
                query=query.replace(':ReviewBaggage', ':'+label+'Review')
                for kind in ['Passenger','Flight','ScanEvent']:
                    query=query.replace(':'+kind, ':'+label+kind)
                return self.connection.run(query.replace(':Baggage', ':'+label), **params)
        scoped=ScopedSession()
        class ScopedDriver:
            def session(self): return scoped
        db['get_driver']=lambda:ScopedDriver()
        try:
            await (await session.run(f'CREATE INDEX {indexes[0]} FOR (b:{label}) ON (b.id)')).consume()
            await (await session.run(f'CREATE INDEX {indexes[1]} FOR (b:{label}) ON (b.last_scan_at,b.id)')).consume()
            await (await session.run(f'CREATE INDEX {indexes[2]} FOR (b:{label}Unscanned) ON (b.id)')).consume()
            await (await session.run(f'CREATE INDEX {indexes[3]} FOR (b:{label}Review) ON (b.id)')).consume()
            await (await session.run('CALL db.awaitIndexes(30)')).consume()
            await (await session.run(f'''UNWIND range(0,3) AS n
                CREATE (b:{label} {{id:$ids[n],tag:$ids[n],status:'collected'}})
                FOREACH (_ IN CASE WHEN n=3 THEN [1] ELSE [] END | SET b:{label}Unscanned)
                FOREACH (_ IN CASE WHEN n>1 THEN [1] ELSE [] END |
                    SET b.last_scan_at='2024-06-15T12:00:00')''',ids=ids)).consume()
            await db['_backfill_unscanned_index'](scoped)
            await db['_backfill_unscanned_index'](scoped)
            await (await scoped.run('MATCH(b:Baggage {id:$id}) SET b.review_status="pending"',id=ids[0])).consume()
            await (await scoped.run('MATCH(b:Baggage {id:$id}) SET b:ReviewBaggage',id=ids[3])).consume()
            await db['_backfill_review_index'](scoped)
            await db['_backfill_review_index'](scoped)
            review,total_review=await db['get_flagged_baggage']()
            assert total_review==1 and [b['id'] for b in review]==[ids[0]],review
            await (await scoped.run('MATCH(b:Baggage {id:$id}) SET b.review_status="cleared"',id=ids[0])).consume()
            first,total=await db['_unfiltered_baggage_page'](scoped,2,0)
            assert total==4 and [b['id'] for b in first]==[ids[1],ids[0]],first
            assert all(b.get('last_scan_at') is None for b in first)
            across,again=await db['_unfiltered_baggage_page'](scoped,3,1)
            assert again==4 and [b['id'] for b in across]==[ids[0],ids[3],ids[2]],across
            assert across[0].get('last_scan_at') is None
            assert await db['_unfiltered_baggage_page'](scoped,2,4)==([],4)
            now=datetime.fromisoformat('2024-06-15T13:00:00')
            await db['update_baggage_statuses']([{'id':ids[0],'status':'sorting','zone':'sorting-matrix'}],now)
            await db['update_baggage_status'](ids[1],'sorting','sorting-matrix',now)

            # Compile only the two production seed functions, using the same
            # isolated label adapter. No application service is restarted.
            tree=ast.parse(sources['seed'])
            funcs=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)
                   and n.name in ('_persist_baggage','_persist_arrival_baggage')]
            seed={'get_driver':lambda:ScopedDriver()}
            exec(compile(ast.Module(body=funcs,type_ignores=[]),'candidate_seed.py','exec'),seed)
            await (await session.run(f'CREATE (:{label}Passenger {{id:$id}}), (:{label}Flight {{id:$id}})',id=label)).consume()
            template=dict(passenger_id=label,flight_id=label,weight_kg=12.0,status='dropped_off',
                          is_dangerous_goods=False,dg_class=None,last_scan_zone=None,last_scan_at=None,carousel=None)
            await seed['_persist_baggage']([dict(template,id=label+'-4',tag=label+'-4')])
            await seed['_persist_arrival_baggage']([dict(template,id=label+'-5',tag=label+'-5')])
            count=await (await scoped.run('MATCH (b:UnscannedBaggage) RETURN count(b) AS n')).single()
            assert count['n']==2,count
            await db['flag_baggage'](label+'-4','synthetic-test','screening-unit-1',now)
            assert await db['redirect_baggage_to_flight'](label+'-5',label,now)
            count=await (await scoped.run('MATCH (b:UnscannedBaggage) RETURN count(b) AS n')).single()
            assert count['n']==0,count
            # The merged transactional owner paths must preserve the same index
            # invariant on both commit and rollback, using real Neo4j transactions.
            await seed['_persist_baggage']([dict(template,id=label+'-'+str(n),tag=label+'-'+str(n)) for n in range(6,10)])
            async with await session.begin_transaction() as tx:
                target=ScopedSession(tx)
                await db['write_baggage_statuses_tx'](target,[{'id':label+'-6','status':'sorting','zone':'sorting-matrix'}],now)
                await db['flag_baggage_tx'](target,label+'-7','synthetic-test','screening-unit-1',now)
                assert await db['redirect_baggage_to_flight_tx'](target,label+'-8',label,now)
                await tx.commit()
            async with await session.begin_transaction() as tx:
                await db['write_baggage_statuses_tx'](ScopedSession(tx),[{'id':label+'-9','status':'sorting','zone':'sorting-matrix'}],now)
                await tx.rollback()
            record=await (await scoped.run('MATCH(b:Baggage {id:$id}) RETURN b.status AS status, b.last_scan_at AS scan, b:UnscannedBaggage AS unscanned',id=label+'-9')).single()
            assert dict(record)=={'status':'dropped_off','scan':None,'unscanned':True},record
            count=await (await scoped.run('MATCH(b:UnscannedBaggage) RETURN count(b) AS n')).single()
            assert count['n']==1,count
            review,total_review=await db['get_flagged_baggage']()
            assert total_review==2 and {b['id'] for b in review}=={label+'-4',label+'-7'},review
            await (await scoped.run('MATCH(b:Baggage {id:$id}) SET b.review_status="cleared"',id=label+'-4')).consume()
            await db['update_baggage_status'](label+'-4','collected','arrival-belt-1',now)
            review,total_review=await db['get_flagged_baggage']()
            assert total_review==1 and review[0]['id']==label+'-7',review
        finally:
            for suffix in ['','Unscanned','Review','Migration','Passenger','Flight','ScanEvent']:
                await (await session.run(f'MATCH (b:{label}{suffix}) DETACH DELETE b')).consume()
            for index in indexes:
                await (await session.run(f'DROP INDEX {index} IF EXISTS')).consume()
    await db['close_neo4j']()
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
    sources = {
        "db": (root / "services/baggage-service/db/neo4j.py").read_text(encoding="utf-8"),
        "seed": (root / "services/sim-orchestrator/services/baggage.py").read_text(encoding="utf-8"),
    }
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "baggage-service", "python", "-c", WORKER],
        cwd=root, input=json.dumps(sources), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
